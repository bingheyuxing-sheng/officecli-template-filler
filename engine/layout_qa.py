# -*- coding: utf-8 -*-
"""Content-independent DOCX layout fingerprint comparison."""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Tuple

import docx
from docx.oxml.ns import qn
from docx.text.run import Run

from .ooxml_utils import (
    iter_all_document_paragraphs_with_Wait_context,
    iter_all_document_tables_with_context,
)
from .style_engine import resolve_run_effective_font, resolve_run_effective_sz

_WIDTH_DRIFT = 0.05
_ASPECT_DRIFT = 0.05


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
    for r_el in paragraph._p.iter(qn("w:r")):
        parent = r_el.getparent()
        while parent is not None and parent.tag != qn("w:p"):
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
        "runs": [_run_fingerprint(run, paragraph) for run in _own_runs(paragraph)],
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
    paragraphs = [
        _paragraph_fingerprint(ctx["location_id"], ctx["paragraph"])
        for ctx in iter_all_document_paragraphs_with_Wait_context(document)
    ]
    tables = [
        _table_fingerprint(ctx["table_id"], ctx["table"])
        for ctx in iter_all_document_tables_with_context(document)
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


def compare_layout_fingerprints(output_docx: str, reference_docx: str) -> Dict[str, Any]:
    """Compare layout and formatting without comparing text content."""
    issues: List[Dict[str, Any]] = []
    out_fp = fingerprint_docx(output_docx)
    ref_fp = fingerprint_docx(reference_docx)

    _count_issue(issues, "LAYOUT_SECTION_COUNT", "sections", out_fp["sections"], ref_fp["sections"])
    _count_issue(issues, "LAYOUT_PARAGRAPH_COUNT", "paragraphs", out_fp["paragraphs"], ref_fp["paragraphs"])
    _count_issue(issues, "LAYOUT_TABLE_COUNT", "tables", out_fp["tables"], ref_fp["tables"])
    _count_issue(issues, "LAYOUT_IMAGE_COUNT", "images", out_fp["images"], ref_fp["images"])

    for index, (out_sec, ref_sec) in enumerate(zip(out_fp["sections"], ref_fp["sections"])):
        for key in ("page_width", "page_height", "orientation"):
            if out_sec[key] != ref_sec[key]:
                issues.append(_issue("LAYOUT_PAGE_DRIFT", f"section[{index}].{key}", f"output={out_sec[key]} reference={ref_sec[key]}"))
        for side in ("top", "bottom", "left", "right"):
            if out_sec["margins"].get(side) != ref_sec["margins"].get(side):
                issues.append(_issue("LAYOUT_PAGE_DRIFT", f"section[{index}].margin.{side}", f"output={out_sec['margins'].get(side)} reference={ref_sec['margins'].get(side)}"))

    for out_p, ref_p in zip(out_fp["paragraphs"], ref_fp["paragraphs"]):
        location = ref_p["location"]
        for key in ("alignment", "line_spacing", "first_line_indent", "left_indent", "space_before", "space_after"):
            if out_p[key] != ref_p[key]:
                issues.append(_issue("LAYOUT_POSITION_DRIFT", f"{location}.{key}", f"output={out_p[key]} reference={ref_p[key]}"))
        if len(out_p["runs"]) != len(ref_p["runs"]):
            issues.append(_issue("LAYOUT_RUN_COUNT", location, f"output={len(out_p['runs'])} reference={len(ref_p['runs'])}"))
        for run_index, (out_run, ref_run) in enumerate(zip(out_p["runs"], ref_p["runs"])):
            for key in ("font", "size"):
                out_value, ref_value = out_run[key], ref_run[key]
                if out_value not in (None, "None") and ref_value not in (None, "None") and out_value != ref_value:
                    issues.append(_issue("LAYOUT_FONT_DRIFT", f"{location}.r[{run_index}].{key}", f"output={out_value} reference={ref_value}"))
            if out_run["bold"] != ref_run["bold"]:
                issues.append(_issue("LAYOUT_FONT_DRIFT", f"{location}.r[{run_index}].bold", f"output={out_run['bold']} reference={ref_run['bold']}"))

    for out_t, ref_t in zip(out_fp["tables"], ref_fp["tables"]):
        location = ref_t["location"]
        if out_t["row_count"] != ref_t["row_count"]:
            issues.append(_issue("LAYOUT_TABLE_ROW_COUNT", location, f"output={out_t['row_count']} reference={ref_t['row_count']}"))
        if out_t["column_count"] != ref_t["column_count"]:
            issues.append(_issue("LAYOUT_TABLE_COLUMN_COUNT", location, f"output={out_t['column_count']} reference={ref_t['column_count']}"))
        if ref_t["total_width"] and out_t["total_width"]:
            drift = abs(out_t["total_width"] - ref_t["total_width"]) / float(ref_t["total_width"])
            if drift > _WIDTH_DRIFT:
                issues.append(_issue("LAYOUT_TABLE_DRIFT", location, f"total width {out_t['total_width']} vs {ref_t['total_width']}"))
        if ref_t["column_widths"] and out_t["column_widths"]:
            ref_total = float(ref_t["total_width"] or 1)
            out_total = float(out_t["total_width"] or 1)
            for column_index, (out_w, ref_w) in enumerate(zip(out_t["column_widths"], ref_t["column_widths"])):
                if abs(out_w / out_total - ref_w / ref_total) > _WIDTH_DRIFT:
                    issues.append(_issue("LAYOUT_TABLE_DRIFT", f"{location}.col[{column_index}]", f"ratio {out_w / out_total:.3f} vs {ref_w / ref_total:.3f}"))

    for out_img, ref_img in zip(out_fp["images"], ref_fp["images"]):
        location = ref_img["location"]
        if (out_img["width"], out_img["height"]) != (ref_img["width"], ref_img["height"]):
            issues.append(_issue("LAYOUT_IMAGE_SIZE_DRIFT", location, f"output={out_img['width']}x{out_img['height']} reference={ref_img['width']}x{ref_img['height']}"))
        if out_img["aspect"] is not None and ref_img["aspect"] is not None and ref_img["aspect"]:
            if abs(out_img["aspect"] - ref_img["aspect"]) / ref_img["aspect"] > _ASPECT_DRIFT:
                issues.append(_issue("LAYOUT_IMAGE_DRIFT", location, f"aspect {out_img['aspect']} vs {ref_img['aspect']}"))

    coverage_gaps = list(dict.fromkeys(out_fp["coverage_gaps"] + ref_fp["coverage_gaps"]))
    return {
        "passed": not issues,
        "issues": issues,
        "structured_issues": issues,
        "coverage_gaps": coverage_gaps,
        "unverified_count": len(coverage_gaps),
        "compared": {key: min(len(out_fp[key]), len(ref_fp[key])) for key in ("sections", "paragraphs", "tables", "images")},
    }
