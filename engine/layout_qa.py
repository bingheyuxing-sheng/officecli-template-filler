# -*- coding: utf-8 -*-
"""Content-independent DOCX layout fingerprint comparison."""

from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional, Tuple

import docx
from docx.oxml.ns import qn
from docx.text.run import Run

from .alignment import align_paragraphs, align_tables
from .ooxml_utils import (
    iter_all_document_paragraphs_with_Wait_context,
    iter_all_document_tables_with_context,
)
from .qa_policy import resolve_comparison_profile, split_issues
from .style_engine import resolve_run_effective_font, resolve_run_effective_sz

_WIDTH_DRIFT = 0.05
_ASPECT_DRIFT = 0.05
_BODY_PARAGRAPH_RE = re.compile(r"body\.p\[(\d+)\]$")
_TABLE_LOCATION_RE = re.compile(r"body\.tbl\[(\d+)\]$")


def _issue(code: str, location: str, detail: str, severity: str = "medium") -> Dict[str, Any]:
    return {"code": code, "location": location, "detail": detail, "severity": severity}


def _length_twips(value) -> Optional[int]:
    try:
        return int(value.twips) if value is not None else None
    except Exception:
        return None


def _section_fingerprint(section) -> Dict[str, Any]:
    return {
        "page_width": _length_twips(section.page_width),
        "page_height": _length_twips(section.page_height),
        "orientation": str(section.orientation) if section.orientation is not None else None,
        "margins": {
            "top": _length_twips(section.top_margin),
            "bottom": _length_twips(section.bottom_margin),
            "left": _length_twips(section.left_margin),
            "right": _length_twips(section.right_margin),
        },
    }


def _own_runs(paragraph):
    """Accepted-view runs: tracked insertions count, deletions/moves/comment anchors do not."""
    for r_el in paragraph._p.iter(qn("w:r")):
        if r_el.find(qn("w:commentReference")) is not None:
            continue
        parent = r_el.getparent()
        while parent is not None and parent.tag != qn("w:p"):
            if parent.tag in (qn("w:del"), qn("w:moveFrom")):
                parent = None
                break
            parent = parent.getparent()
        if parent is paragraph._p:
            yield Run(r_el, paragraph)


def _run_fingerprint(run, paragraph) -> Dict[str, Any]:
    ascii_font, east_asia = resolve_run_effective_font(run, paragraph)
    return {
        "font": east_asia or ascii_font,
        "size": str(resolve_run_effective_sz(run, paragraph)),
        "bold": bool(run.bold),
    }


def _effective_run_fingerprints(paragraph) -> List[Dict[str, Any]]:
    """Coalesce adjacent runs with identical formatting: tracked edits split runs, layout does not."""
    result: List[Dict[str, Any]] = []
    previous_key = None
    for run in _own_runs(paragraph):
        fingerprint = _run_fingerprint(run, paragraph)
        key = (fingerprint["font"], fingerprint["size"], fingerprint["bold"])
        if key == previous_key:
            continue
        result.append(fingerprint)
        previous_key = key
    return result


def _paragraph_fingerprint(location: str, paragraph) -> Dict[str, Any]:
    fmt = paragraph.paragraph_format
    return {
        "location": location,
        "alignment": str(fmt.alignment) if fmt.alignment is not None else None,
        "first_line_indent": _length_twips(fmt.first_line_indent),
        "left_indent": _length_twips(fmt.left_indent),
        "line_spacing": fmt.line_spacing if isinstance(fmt.line_spacing, float) else None,
        "space_before": _length_twips(fmt.space_before),
        "space_after": _length_twips(fmt.space_after),
        "style": getattr(getattr(paragraph, "style", None), "name", None),
        "runs": _effective_run_fingerprints(paragraph),
    }


def _table_fingerprint(location: str, table) -> Dict[str, Any]:
    grid = table._tbl.find(qn("w:tblGrid"))
    column_widths = []
    if grid is not None:
        for column in grid.findall(qn("w:gridCol")):
            raw = column.get(qn("w:w")) or ""
            if raw.isdigit():
                column_widths.append(int(raw))
    return {
        "location": location,
        "row_count": len(table.rows),
        "column_count": len(column_widths) or (len(table.columns) if table.rows else 0),
        "column_widths": column_widths,
        "total_width": sum(column_widths),
    }


def _images_and_gaps(document) -> Tuple[List[Dict[str, Any]], List[str]]:
    images: List[Dict[str, Any]] = []
    gaps: List[str] = []
    for ctx in iter_all_document_paragraphs_with_Wait_context(document):
        p_el = ctx["p_el"]
        if p_el.xpath(".//wp:anchor"):
            gaps.append("FLOATING_IMAGE_LAYOUT_UNSUPPORTED")
        for index, inline in enumerate(p_el.xpath(".//wp:inline")):
            extents = inline.xpath("./wp:extent") or inline.xpath(".//wp:extent")
            if not extents:
                continue
            width = int(extents[0].get("cx") or 0)
            height = int(extents[0].get("cy") or 0)
            images.append({
                "location": f"{ctx['location_id']}.image[{index}]",
                "width": width,
                "height": height,
                "aspect": round(width / float(height), 4) if height else None,
            })
    for rel in document.part.rels.values():
        if rel.is_external:
            continue
        reltype = (rel.reltype or "").lower()
        if any(kind in reltype for kind in ("footnotes", "endnotes", "comments")):
            element = getattr(rel.target_part, "element", None)
            if element is not None and element.findall(".//" + qn("w:tbl")):
                gaps.append("STORY_TABLE_LAYOUT_UNSUPPORTED")
    return images, list(dict.fromkeys(gaps))


def fingerprint_docx(docx_path: str) -> Dict[str, Any]:
    """Extract layout-only data across all supported document stories."""
    document = docx.Document(docx_path)
    # Comments are annotations, not rendered page content: their story must not
    # change the paragraph/table counts of the layout fingerprint.
    paragraphs = [
        _paragraph_fingerprint(ctx["location_id"], ctx["paragraph"])
        for ctx in iter_all_document_paragraphs_with_Wait_context(document)
        if not ctx["location_id"].startswith(("comments.", "comments["))
    ]
    tables = [
        _table_fingerprint(ctx["table_id"], ctx["table"])
        for ctx in iter_all_document_tables_with_context(document)
        if not str(ctx["table_id"]).startswith(("comments.", "comments["))
    ]
    images, coverage_gaps = _images_and_gaps(document)
    return {
        "docx_path": os.path.abspath(docx_path),
        "sections": [_section_fingerprint(section) for section in document.sections],
        "paragraphs": paragraphs,
        "tables": tables,
        "images": images,
        "coverage_gaps": coverage_gaps,
    }


def _count_issue(issues, code: str, kind: str, output_items, reference_items) -> None:
    if len(output_items) != len(reference_items):
        issues.append(_issue(code, kind, f"output={len(output_items)} reference={len(reference_items)}"))


def _story_prefix(location: str) -> str:
    """`sec[0].header.p[2]` -> `sec[0].header`; table-cell paragraphs are excluded."""
    index = location.rfind(".p[")
    return location[:index] if index > 0 else location


def _is_table_cell_paragraph(location: str) -> bool:
    return ".tbl[" in location or re.search(r"\.r\[\d+\]\.c\[\d+\]", location) is not None


def _compare_paragraph_pair(
    out_p: Dict[str, Any],
    ref_p: Dict[str, Any],
    location: str,
    profile: str,
    issues: List[Dict[str, Any]],
) -> None:
    for key in ("alignment", "line_spacing", "first_line_indent", "left_indent", "space_before", "space_after"):
        if out_p[key] != ref_p[key]:
            issues.append(_issue(
                "LAYOUT_POSITION_DRIFT",
                f"{location}.{key}",
                f"output={out_p[key]} reference={ref_p[key]} (reference {ref_p['location']})",
            ))
    if profile == "REPLICA" and len(out_p["runs"]) != len(ref_p["runs"]):
        issues.append(_issue(
            "LAYOUT_RUN_COUNT",
            location,
            f"output={len(out_p['runs'])} reference={len(ref_p['runs'])}",
            severity="low",
        ))
    for run_index, (out_run, ref_run) in enumerate(zip(out_p["runs"], ref_p["runs"])):
        for key in ("font", "size"):
            out_value, ref_value = out_run[key], ref_run[key]
            if out_value not in (None, "None") and ref_value not in (None, "None") and out_value != ref_value:
                issues.append(_issue(
                    "LAYOUT_FONT_DRIFT",
                    f"{location}.r[{run_index}].{key}",
                    f"output={out_value} reference={ref_value}",
                    severity="high" if profile == "REPLICA" else "medium",
                ))
        if out_run["bold"] != ref_run["bold"]:
            issues.append(_issue(
                "LAYOUT_FONT_DRIFT",
                f"{location}.r[{run_index}].bold",
                f"output={out_run['bold']} reference={ref_run['bold']}",
                severity="high" if profile == "REPLICA" else "medium",
            ))


def _compare_table_pair(
    out_t: Dict[str, Any],
    ref_t: Dict[str, Any],
    location: str,
    issues: List[Dict[str, Any]],
) -> None:
    if out_t["row_count"] != ref_t["row_count"]:
        issues.append(_issue(
            "LAYOUT_TABLE_ROW_COUNT", location,
            f"output={out_t['row_count']} reference={ref_t['row_count']}",
            severity="medium",
        ))
    if out_t["column_count"] != ref_t["column_count"]:
        issues.append(_issue(
            "LAYOUT_TABLE_COLUMN_COUNT", location,
            f"output={out_t['column_count']} reference={ref_t['column_count']}",
            severity="high",
        ))
    if ref_t["total_width"] and out_t["total_width"]:
        drift = abs(out_t["total_width"] - ref_t["total_width"]) / float(ref_t["total_width"])
        if drift > _WIDTH_DRIFT:
            issues.append(_issue(
                "LAYOUT_TABLE_DRIFT", location,
                f"total width {out_t['total_width']} vs {ref_t['total_width']}",
                severity="high",
            ))
    if ref_t["column_widths"] and out_t["column_widths"]:
        ref_total = float(ref_t["total_width"] or 1)
        out_total = float(out_t["total_width"] or 1)
        for column_index, (out_w, ref_w) in enumerate(zip(out_t["column_widths"], ref_t["column_widths"])):
            if abs(out_w / out_total - ref_w / ref_total) > _WIDTH_DRIFT:
                issues.append(_issue(
                    "LAYOUT_TABLE_DRIFT", f"{location}.col[{column_index}]",
                    f"ratio {out_w / out_total:.3f} vs {ref_w / ref_total:.3f}",
                    severity="high",
                ))


def compare_layout_fingerprints(
    output_docx: str,
    reference_docx: str,
    comparison_profile: str = "REPLICA",
) -> Dict[str, Any]:
    """Compare layout and formatting without comparing text content."""
    profile = resolve_comparison_profile(comparison_profile, reference_provided=True)
    issues: List[Dict[str, Any]] = []
    informational: List[Dict[str, Any]] = []
    out_fp = fingerprint_docx(output_docx)
    ref_fp = fingerprint_docx(reference_docx)

    if profile == "REPLICA":
        _count_issue(issues, "LAYOUT_SECTION_COUNT", "sections", out_fp["sections"], ref_fp["sections"])
        _count_issue(issues, "LAYOUT_PARAGRAPH_COUNT", "paragraphs", out_fp["paragraphs"], ref_fp["paragraphs"])
        _count_issue(issues, "LAYOUT_TABLE_COUNT", "tables", out_fp["tables"], ref_fp["tables"])
        _count_issue(issues, "LAYOUT_IMAGE_COUNT", "images", out_fp["images"], ref_fp["images"])

    for index, (out_sec, ref_sec) in enumerate(zip(out_fp["sections"], ref_fp["sections"])):
        for key in ("page_width", "page_height", "orientation"):
            if out_sec[key] != ref_sec[key]:
                issues.append(_issue(
                    "LAYOUT_PAGE_DRIFT", f"section[{index}].{key}",
                    f"output={out_sec[key]} reference={ref_sec[key]}",
                    severity="high",
                ))
        for side in ("top", "bottom", "left", "right"):
            if out_sec["margins"].get(side) != ref_sec["margins"].get(side):
                issues.append(_issue(
                    "LAYOUT_PAGE_DRIFT", f"section[{index}].margin.{side}",
                    f"output={out_sec['margins'].get(side)} reference={ref_sec['margins'].get(side)}",
                    severity="high",
                ))

    out_doc = docx.Document(output_docx)
    ref_doc = docx.Document(reference_docx)
    paragraph_alignment = align_paragraphs(out_doc.paragraphs, ref_doc.paragraphs)
    table_alignment = align_tables(out_doc.tables, ref_doc.tables)

    out_body = {
        int(match.group(1)): item
        for item in out_fp["paragraphs"]
        if (match := _BODY_PARAGRAPH_RE.match(item["location"]))
    }
    ref_body = {
        int(match.group(1)): item
        for item in ref_fp["paragraphs"]
        if (match := _BODY_PARAGRAPH_RE.match(item["location"]))
    }
    for out_index, ref_index in paragraph_alignment["matches"].items():
        out_p = out_body.get(out_index)
        ref_p = ref_body.get(ref_index)
        if out_p is None or ref_p is None:
            continue
        _compare_paragraph_pair(out_p, ref_p, out_p["location"], profile, issues)
    for out_index in paragraph_alignment["unmatched_output"]:
        out_p = out_body.get(out_index)
        if out_p is not None:
            informational.append(_issue(
                "LAYOUT_NEW_PARAGRAPH", out_p["location"],
                "output paragraph has no template counterpart",
                severity="low",
            ))
    for ref_index in paragraph_alignment["unmatched_reference"]:
        ref_p = ref_body.get(ref_index)
        if ref_p is not None:
            informational.append(_issue(
                "LAYOUT_REMOVED_PARAGRAPH", ref_p["location"],
                "template paragraph has no output counterpart",
                severity="low",
            ))

    # Header/footer/other story paragraphs: compare within each story by index. Table-cell
    # paragraphs are skipped here because table structure and cell styles are checked below.
    out_stories: Dict[str, List[Dict[str, Any]]] = {}
    ref_stories: Dict[str, List[Dict[str, Any]]] = {}
    for item in out_fp["paragraphs"]:
        if _BODY_PARAGRAPH_RE.match(item["location"]) or _is_table_cell_paragraph(item["location"]):
            continue
        out_stories.setdefault(_story_prefix(item["location"]), []).append(item)
    for item in ref_fp["paragraphs"]:
        if _BODY_PARAGRAPH_RE.match(item["location"]) or _is_table_cell_paragraph(item["location"]):
            continue
        ref_stories.setdefault(_story_prefix(item["location"]), []).append(item)
    for story, out_items in out_stories.items():
        for out_p, ref_p in zip(out_items, ref_stories.get(story, [])):
            _compare_paragraph_pair(out_p, ref_p, out_p["location"], profile, issues)

    out_tables = {
        int(match.group(1)): item
        for item in out_fp["tables"]
        if (match := _TABLE_LOCATION_RE.match(item["location"]))
    }
    ref_tables = {
        int(match.group(1)): item
        for item in ref_fp["tables"]
        if (match := _TABLE_LOCATION_RE.match(item["location"]))
    }
    for out_index, ref_index in table_alignment["matches"].items():
        out_t = out_tables.get(out_index)
        ref_t = ref_tables.get(ref_index)
        if out_t is None or ref_t is None:
            continue
        _compare_table_pair(out_t, ref_t, out_t["location"], issues)
    for out_index in table_alignment["unmatched_output"]:
        out_t = out_tables.get(out_index)
        if out_t is not None:
            informational.append(_issue(
                "LAYOUT_NEW_TABLE", out_t["location"],
                "output table has no template counterpart",
                severity="low",
            ))
    for ref_index in table_alignment["unmatched_reference"]:
        ref_t = ref_tables.get(ref_index)
        if ref_t is not None:
            informational.append(_issue(
                "LAYOUT_REMOVED_TABLE", ref_t["location"],
                "template table has no output counterpart",
                severity="low",
            ))

    for out_img, ref_img in zip(out_fp["images"], ref_fp["images"]):
        location = ref_img["location"]
        if (out_img["width"], out_img["height"]) != (ref_img["width"], ref_img["height"]):
            issues.append(_issue(
                "LAYOUT_IMAGE_SIZE_DRIFT", location,
                f"output={out_img['width']}x{out_img['height']} reference={ref_img['width']}x{ref_img['height']}",
                severity="medium",
            ))
        if out_img["aspect"] is not None and ref_img["aspect"] is not None and ref_img["aspect"]:
            if abs(out_img["aspect"] - ref_img["aspect"]) / ref_img["aspect"] > _ASPECT_DRIFT:
                issues.append(_issue(
                    "LAYOUT_IMAGE_DRIFT", location,
                    f"aspect {out_img['aspect']} vs {ref_img['aspect']}",
                    severity="medium",
                ))

    blocking, warnings, _pending = split_issues(issues)
    coverage_gaps = list(dict.fromkeys(out_fp["coverage_gaps"] + ref_fp["coverage_gaps"]))
    return {
        "passed": not blocking,
        "issues": issues,
        "structured_issues": issues,
        "warnings": warnings,
        "warning_count": len(warnings),
        "informational": informational,
        "comparison_profile": profile,
        "coverage_gaps": coverage_gaps,
        "unverified_count": len(coverage_gaps),
        "compared": {
            "sections": min(len(out_fp["sections"]), len(ref_fp["sections"])),
            "paragraphs": len(paragraph_alignment["matches"]),
            "tables": len(table_alignment["matches"]),
            "images": min(len(out_fp["images"]), len(ref_fp["images"])),
        },
        "alignment": {
            "matched_paragraphs": len(paragraph_alignment["matches"]),
            "new_paragraphs": paragraph_alignment["unmatched_output"],
            "removed_paragraphs": paragraph_alignment["unmatched_reference"],
            "matched_tables": len(table_alignment["matches"]),
            "new_tables": table_alignment["unmatched_output"],
            "removed_tables": table_alignment["unmatched_reference"],
        },
    }
