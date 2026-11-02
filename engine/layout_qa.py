# -*- coding: utf-8 -*-
"""
v3.5 M6 — Layout fingerprint QA.

Whole-page pixel comparison flags every text replacement as a layout defect, which made
the old visual QA unusable for generated documents. This module compares *layout*
instead of pixels: page setup, paragraph geometry, table widths and image aspect ratios.

Rules:
- text content changes with identical geometry and fonts -> no issue
- same geometry but different font / size -> LAYOUT_FONT_DRIFT
- alignment / indent / spacing drift -> LAYOUT_POSITION_DRIFT
- table column-ratio drift > 5% -> LAYOUT_TABLE_DRIFT
- image aspect-ratio drift > 5% -> LAYOUT_IMAGE_DRIFT
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

import docx
from docx.oxml.ns import qn

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


def _run_fingerprint(run, paragraph) -> Dict[str, Any]:
    ascii_font, east_asia = resolve_run_effective_font(run, paragraph)
    return {
        "font": east_asia or ascii_font,
        "size": str(resolve_run_effective_sz(run, paragraph)),
        "bold": bool(run.bold),
    }


def _paragraph_fingerprint(index: int, paragraph) -> Dict[str, Any]:
    fmt = paragraph.paragraph_format
    runs = [_run_fingerprint(run, paragraph) for run in paragraph.runs if (run.text or "").strip()]
    return {
        "index": index,
        "alignment": str(fmt.alignment) if fmt.alignment is not None else None,
        "first_line_indent": _length_twips(fmt.first_line_indent),
        "left_indent": _length_twips(fmt.left_indent),
        "line_spacing": fmt.line_spacing if isinstance(fmt.line_spacing, float) else None,
        "space_before": _length_twips(fmt.space_before),
        "space_after": _length_twips(fmt.space_after),
        "style": getattr(getattr(paragraph, "style", None), "name", None),
        "runs": runs,
    }


def _table_fingerprint(index: int, table) -> Dict[str, Any]:
    grid = table._tbl.find(qn("w:tblGrid"))
    column_widths = []
    if grid is not None:
        for column in grid.findall(qn("w:gridCol")):
            raw = column.get(qn("w:w")) or ""
            if raw.isdigit():
                column_widths.append(int(raw))
    return {
        "index": index,
        "row_count": len(table.rows),
        "column_widths": column_widths,
        "total_width": sum(column_widths),
    }


def fingerprint_docx(docx_path: str) -> Dict[str, Any]:
    """Extract the layout-only fingerprint of a document (text content is excluded)."""
    document = docx.Document(docx_path)
    images = []
    for shape in document.inline_shapes:
        width, height = int(shape.width), int(shape.height)
        images.append({
            "width": width,
            "height": height,
            "aspect": round(width / float(height), 4) if height else None,
        })
    return {
        "docx_path": os.path.abspath(docx_path),
        "sections": [_section_fingerprint(section) for section in document.sections],
        "paragraphs": [
            _paragraph_fingerprint(index, paragraph)
            for index, paragraph in enumerate(document.paragraphs)
        ],
        "tables": [
            _table_fingerprint(index, table)
            for index, table in enumerate(document.tables)
        ],
        "images": images,
    }


def compare_layout_fingerprints(output_docx: str, reference_docx: str) -> Dict[str, Any]:
    """Compare two documents by layout; content changes alone never raise an issue."""
    issues: List[Dict[str, Any]] = []
    out_fp = fingerprint_docx(output_docx)
    ref_fp = fingerprint_docx(reference_docx)

    for index, (out_sec, ref_sec) in enumerate(zip(out_fp["sections"], ref_fp["sections"])):
        for key in ("page_width", "page_height", "orientation"):
            if out_sec[key] != ref_sec[key]:
                issues.append(_issue(
                    "LAYOUT_PAGE_DRIFT",
                    f"section[{index}].{key}",
                    f"output={out_sec[key]} reference={ref_sec[key]}",
                ))
        for side in ("top", "bottom", "left", "right"):
            if out_sec["margins"].get(side) != ref_sec["margins"].get(side):
                issues.append(_issue(
                    "LAYOUT_PAGE_DRIFT",
                    f"section[{index}].margin.{side}",
                    f"output={out_sec['margins'].get(side)} reference={ref_sec['margins'].get(side)}",
                ))

    if len(out_fp["paragraphs"]) != len(ref_fp["paragraphs"]):
        issues.append(_issue(
            "LAYOUT_PARAGRAPH_COUNT",
            "body",
            f"output={len(out_fp['paragraphs'])} reference={len(ref_fp['paragraphs'])}",
        ))

    for out_p, ref_p in zip(out_fp["paragraphs"], ref_fp["paragraphs"]):
        location = f"body.p[{ref_p['index']}]"
        for key in ("alignment", "line_spacing"):
            if out_p[key] != ref_p[key]:
                issues.append(_issue(
                    "LAYOUT_POSITION_DRIFT",
                    f"{location}.{key}",
                    f"output={out_p[key]} reference={ref_p[key]}",
                ))
        for key in ("first_line_indent", "left_indent", "space_before", "space_after"):
            if out_p[key] != ref_p[key]:
                issues.append(_issue(
                    "LAYOUT_POSITION_DRIFT",
                    f"{location}.{key}",
                    f"output={out_p[key]} reference={ref_p[key]}",
                ))
        if not out_p["runs"] or not ref_p["runs"]:
            continue
        out_run, ref_run = out_p["runs"][0], ref_p["runs"][0]
        if out_run["font"] != ref_run["font"] or out_run["size"] != ref_run["size"]:
            issues.append(_issue(
                "LAYOUT_FONT_DRIFT",
                f"{location}.r[0]",
                f"output={out_run['font']}/{out_run['size']} "
                f"reference={ref_run['font']}/{ref_run['size']}",
            ))
        if out_run["bold"] != ref_run["bold"]:
            issues.append(_issue(
                "LAYOUT_FONT_DRIFT",
                f"{location}.r[0].bold",
                f"output={out_run['bold']} reference={ref_run['bold']}",
            ))

    for out_t, ref_t in zip(out_fp["tables"], ref_fp["tables"]):
        location = f"body.tbl[{ref_t['index']}]"
        if out_t["row_count"] != ref_t["row_count"]:
            issues.append(_issue(
                "LAYOUT_TABLE_ROW_COUNT",
                location,
                f"output={out_t['row_count']} reference={ref_t['row_count']}",
            ))
        if ref_t["total_width"] and out_t["total_width"]:
            drift = abs(out_t["total_width"] - ref_t["total_width"]) / float(ref_t["total_width"])
            if drift > _WIDTH_DRIFT:
                issues.append(_issue(
                    "LAYOUT_TABLE_DRIFT",
                    location,
                    f"total width {out_t['total_width']} vs {ref_t['total_width']}",
                ))
        if ref_t["column_widths"] and out_t["column_widths"]:
            ref_total = float(ref_t["total_width"] or 1)
            out_total = float(out_t["total_width"] or 1)
            for column_index, (out_w, ref_w) in enumerate(
                zip(out_t["column_widths"], ref_t["column_widths"])
            ):
                if abs(out_w / out_total - ref_w / ref_total) > _WIDTH_DRIFT:
                    issues.append(_issue(
                        "LAYOUT_TABLE_DRIFT",
                        f"{location}.col[{column_index}]",
                        f"ratio {out_w / out_total:.3f} vs {ref_w / ref_total:.3f}",
                    ))
                    break

    for index, (out_img, ref_img) in enumerate(zip(out_fp["images"], ref_fp["images"])):
        if out_img["aspect"] is None or ref_img["aspect"] is None:
            continue
        if abs(out_img["aspect"] - ref_img["aspect"]) / ref_img["aspect"] > _ASPECT_DRIFT:
            issues.append(_issue(
                "LAYOUT_IMAGE_DRIFT",
                f"image[{index}]",
                f"aspect {out_img['aspect']} vs {ref_img['aspect']}",
            ))

    return {
        "passed": not issues,
        "issues": issues,
        "structured_issues": issues,
        "coverage_gaps": [],
        "unverified_count": 0,
        "compared": {
            "sections": min(len(out_fp["sections"]), len(ref_fp["sections"])),
            "paragraphs": min(len(out_fp["paragraphs"]), len(ref_fp["paragraphs"])),
            "tables": min(len(out_fp["tables"]), len(ref_fp["tables"])),
            "images": min(len(out_fp["images"]), len(ref_fp["images"])),
        },
    }
