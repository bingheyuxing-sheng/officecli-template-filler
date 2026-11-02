"""
Complex Cell Structure Guard & Donor-Aware Table Engine (v3.0 — Fixes P1-5).

Key v3.0 enhancements over v2.9:
1. Classifies every cell (`classify_cell_structure(cell)`) into:
   - `plain_text`
   - `mixed_format`
   - `image_cell`
   - `hyperlink_cell`
   - `nested_table`
   - `sdt_control`
   - `field_code`
   - `unknown_complex`
2. Prevents destructive wiping of `cell.paragraphs[1:]` and `p0.runs` when the cell
   contains nested tables, hyperlinks, SDT content controls, field codes, drawings,
   or multi-run mixed formatting—routing each to its dedicated non-destructive handler.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, List, Optional, Tuple
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

from .ooxml_utils import (
    LogicalParagraphView,
    W14_PARA_ID,
    W14_TEXT_ID,
    ensure_xml_space_preserve_on_run,
    ensure_xml_space_preserve_on_t,
    regenerate_unique_ooxml_ids,
)
from .style_engine import (
    fill_paragraph_strict_style,
    is_red_run,
    normalize_rPr_fonts_and_strip_red,
    resolve_run_effective_font,
    resolve_run_effective_sz,
    resolve_style_sz_and_font,
)


TBLPR_ORDER = (
    "tblStyle", "tblpPr", "tblOverlap", "bidiVisual", "tblStyleRowBandSize",
    "tblStyleColBandSize", "tblW", "jc", "tblCellSpacing", "tblInd", "tblBorders",
    "shd", "tblLayout", "tblCellMar", "tblLook", "tblCaption", "tblDescription",
)

TBLPR_SYNC_TAGS = (
    "tblStyle", "tblStyleRowBandSize", "tblStyleColBandSize", "tblW", "jc",
    "tblCellSpacing", "tblInd", "tblBorders", "tblLayout", "tblCellMar", "tblLook",
)

TCPR_ORDER = (
    "cnfStyle", "tcW", "gridSpan", "hMerge", "vMerge", "tcBorders", "shd", "noWrap",
    "tcMar", "textDirection", "tcFitText", "vAlign", "hideMark", "headers",
    "cellIns", "cellDel", "cellMerge", "tcPrChange",
)


def _cell_shading(cell):
    """Shading tuple for one cell, or None when the cell declares no `w:shd`."""
    tcPr = cell._tc.tcPr
    if tcPr is None:
        return None
    shd = tcPr.find(qn("w:shd"))
    if shd is None:
        return None
    return (shd.get(qn("w:val")), shd.get(qn("w:fill")) or shd.get(qn("w:color")))


def _cell_valign(cell):
    tcPr = cell._tc.tcPr
    if tcPr is None:
        return None
    v_align = tcPr.find(qn("w:vAlign"))
    return v_align.get(qn("w:val")) if v_align is not None else None


def _row_height(row):
    trPr = row._tr.find(qn("w:trPr"))
    if trPr is None:
        return None
    height = trPr.find(qn("w:trHeight"))
    return height.get(qn("w:val")) if height is not None else None


def _row_height_detail(row) -> Dict[str, Any]:
    """`w:trHeight` value plus its rule — `atLeast 380` and `exact 380` are not the same."""
    trPr = row._tr.find(qn("w:trPr"))
    height = trPr.find(qn("w:trHeight")) if trPr is not None else None
    if height is None:
        return {"val": None, "hRule": None}
    raw_val = height.get(qn("w:val"))
    try:
        val: Optional[int] = int(raw_val) if raw_val is not None else None
    except ValueError:
        val = None
    return {"val": val, "hRule": height.get(qn("w:hRule"))}


def _height_value(entry) -> Any:
    """Read a row height as an int from either the v3.5 dict form or a pre-v3.5 raw string."""
    value = entry.get("val") if isinstance(entry, dict) else entry
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _insert_tcpr_child(tcPr, node, tag_name: str) -> None:
    """Insert a `w:tcPr` child at its schema position."""
    order_index = TCPR_ORDER.index(tag_name)
    for child in list(tcPr):
        name = child.tag.rsplit("}", 1)[-1]
        if name in TCPR_ORDER and TCPR_ORDER.index(name) > order_index:
            tcPr.insert(tcPr.index(child), node)
            return
    tcPr.append(node)


def extract_table_style_profile(tbl) -> Dict[str, Any]:
    """Return a JSON-serializable table style profile suitable for independent storage."""
    return table_style_signature(tbl)


def save_table_style_profile(tbl, profile_path: str) -> str:
    import json
    with open(profile_path, "w", encoding="utf-8") as handle:
        json.dump(extract_table_style_profile(tbl), handle, ensure_ascii=False, indent=2)
    return profile_path


def load_table_style_profile(profile_path: str) -> Dict[str, Any]:
    import json
    with open(profile_path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def table_style_signature(tbl) -> Dict[str, Any]:
    """Structural fingerprint of a table: grid widths, layout, alignment, margins and borders."""
    tbl_el = tbl._tbl
    tblPr = tbl_el.find(qn("w:tblPr"))

    grid_el = tbl_el.find(qn("w:tblGrid"))
    col_widths = []
    if grid_el is not None:
        for col in grid_el.findall(qn("w:gridCol")):
            raw = col.get(qn("w:w")) or ""
            if raw.isdigit():
                col_widths.append(int(raw))

    signature: Dict[str, Any] = {
        "row_count": len(tbl.rows),
        "column_count": len(col_widths),
        "total_width": sum(col_widths),
        "col_widths": col_widths,
        "layout": None,
        "jc": None,
        "cell_margins": {},
        "borders": {},
        "header_row_height": None,
        "tbl_style": None,
        "tbl_look": None,
        "row_band_size": None,
        "col_band_size": None,
        "tbl_ind": None,
        "tbl_cell_spacing": None,
        "header_shading": [],
        "valign_distribution": {},
        "row_heights": [],
        "cell_text_styles": [],
        "cells": [],
    }

    if tblPr is not None:
        style_el = tblPr.find(qn("w:tblStyle"))
        if style_el is not None:
            signature["tbl_style"] = style_el.get(qn("w:val"))
        layout_el = tblPr.find(qn("w:tblLayout"))
        if layout_el is not None:
            signature["layout"] = layout_el.get(qn("w:type"))
        jc_el = tblPr.find(qn("w:jc"))
        if jc_el is not None:
            signature["jc"] = jc_el.get(qn("w:val"))
        look_el = tblPr.find(qn("w:tblLook"))
        if look_el is not None:
            signature["tbl_look"] = {
                key.rsplit("}", 1)[-1]: value for key, value in look_el.attrib.items()
            }
        row_band = tblPr.find(qn("w:tblStyleRowBandSize"))
        if row_band is not None:
            signature["row_band_size"] = row_band.get(qn("w:val"))
        col_band = tblPr.find(qn("w:tblStyleColBandSize"))
        if col_band is not None:
            signature["col_band_size"] = col_band.get(qn("w:val"))
        ind_el = tblPr.find(qn("w:tblInd"))
        if ind_el is not None:
            signature["tbl_ind"] = ind_el.get(qn("w:w"))
        spacing_el = tblPr.find(qn("w:tblCellSpacing"))
        if spacing_el is not None:
            signature["tbl_cell_spacing"] = spacing_el.get(qn("w:w"))
        margins_el = tblPr.find(qn("w:tblCellMar"))
        if margins_el is not None:
            for side in ("top", "left", "bottom", "right"):
                node = margins_el.find(qn(f"w:{side}"))
                if node is not None:
                    signature["cell_margins"][side] = node.get(qn("w:w"))
        borders_el = tblPr.find(qn("w:tblBorders"))
        if borders_el is not None:
            for side in ("top", "left", "bottom", "right", "insideH", "insideV"):
                node = borders_el.find(qn(f"w:{side}"))
                if node is not None:
                    signature["borders"][side] = (
                        node.get(qn("w:val")),
                        node.get(qn("w:sz")),
                        node.get(qn("w:color")),
                    )

    if tbl.rows:
        signature["header_shading"] = [_cell_shading(cell) for cell in get_unique_row_cells(tbl.rows[0])]
        signature["header_row_height"] = _row_height(tbl.rows[0])
        signature["row_heights"] = [_row_height_detail(row) for row in tbl.rows]

    valign_counts: Dict[str, int] = {}
    for row in tbl.rows:
        for cell in get_unique_row_cells(row):
            value = _cell_valign(cell) or "none"
            valign_counts[value] = valign_counts.get(value, 0) + 1
    signature["valign_distribution"] = valign_counts

    for row_index, row in enumerate(tbl.rows):
        for col_index, cell in enumerate(get_unique_row_cells(row)):
            tcPr = cell._tc.tcPr
            cell_signature = {"row": row_index, "cell": col_index, "tcW": None, "gridSpan": None, "hMerge": None, "vMerge": None, "tcMar": {}}
            if tcPr is not None:
                for tag_name in ("tcW", "gridSpan", "hMerge", "vMerge"):
                    node = tcPr.find(qn(f"w:{tag_name}"))
                    if node is not None:
                        cell_signature[tag_name] = tuple(sorted((key.rsplit("}", 1)[-1], value) for key, value in node.attrib.items()))
                margins = tcPr.find(qn("w:tcMar"))
                if margins is not None:
                    for side in ("top", "left", "bottom", "right", "start", "end"):
                        node = margins.find(qn(f"w:{side}"))
                        if node is not None:
                            cell_signature["tcMar"][side] = (node.get(qn("w:w")), node.get(qn("w:type")))
            signature["cells"].append(cell_signature)
            paragraph_styles = []
            for paragraph in cell.paragraphs:
                runs = [run for run in paragraph.runs if (run.text or "").strip()]
                if not runs:
                    font = resolve_style_sz_and_font(paragraph, fallback_font=None, fallback_sz=None)
                    paragraph_styles.append((font[0], font[1], None, None))
                    continue
                for run in runs:
                    ascii_font, east_asia = resolve_run_effective_font(run, paragraph)
                    size = resolve_run_effective_sz(run, paragraph)
                    paragraph_styles.append((ascii_font, east_asia, size, bool(run.bold)))
            signature["cell_text_styles"].append((row_index, col_index, tuple(paragraph_styles)))

    return signature


def compare_table_style(out_sig: Dict[str, Any], ref_sig: Dict[str, Any], table_index: int) -> List[Tuple[Any, ...]]:
    """Report structural table drift that text-level QA cannot see."""
    issues: List[Tuple[Any, ...]] = []

    if out_sig["column_count"] != ref_sig["column_count"]:
        issues.append(("table_column_count", table_index, out_sig["column_count"], ref_sig["column_count"]))
        return issues

    out_rows = out_sig.get("row_count")
    ref_rows = ref_sig.get("row_count")
    if out_rows is not None and ref_rows is not None and out_rows != ref_rows:
        # Reported only: adding/removing rows changes business content and is never
        # applied by `restore_table_style_from_reference`.
        issues.append(("table_row_count", table_index, out_rows, ref_rows))

    if ref_sig["total_width"] and out_sig["total_width"]:
        drift = abs(out_sig["total_width"] - ref_sig["total_width"]) / float(ref_sig["total_width"])
        if drift > 0.08:
            issues.append(("table_total_width", table_index, out_sig["total_width"], ref_sig["total_width"]))

    if ref_sig["col_widths"] and out_sig["col_widths"]:
        ref_total = float(ref_sig["total_width"] or 1)
        out_total = float(out_sig["total_width"] or 1)
        for col_index, (out_w, ref_w) in enumerate(zip(out_sig["col_widths"], ref_sig["col_widths"])):
            if abs(out_w / out_total - ref_w / ref_total) > 0.05:
                issues.append(("table_column_ratio", table_index, col_index, round(out_w / out_total, 3), round(ref_w / ref_total, 3)))
                break

    if ref_sig["layout"] and out_sig["layout"] and ref_sig["layout"] != out_sig["layout"]:
        issues.append(("table_layout", table_index, out_sig["layout"], ref_sig["layout"]))

    if ref_sig["jc"] and out_sig["jc"] and ref_sig["jc"] != out_sig["jc"]:
        issues.append(("table_alignment", table_index, out_sig["jc"], ref_sig["jc"]))

    for side, ref_value in ref_sig["cell_margins"].items():
        out_value = out_sig["cell_margins"].get(side)
        if out_value is not None and ref_value is not None and out_value != ref_value:
            issues.append(("table_cell_margin", table_index, side, out_value, ref_value))

    for side, ref_value in ref_sig["borders"].items():
        if not ref_value or ref_value[0] in (None, "nil", "none"):
            continue
        out_value = out_sig["borders"].get(side)
        if not out_value or out_value[0] in (None, "nil", "none"):
            issues.append(("table_border_missing", table_index, side, out_value, ref_value))
        elif len(ref_value) >= 3 and len(out_value) >= 3:
            if ref_value[1] != out_value[1] or ref_value[2] != out_value[2]:
                issues.append(("table_border_style", table_index, side, out_value, ref_value))

    if ref_sig.get("tbl_style") and out_sig.get("tbl_style") and ref_sig["tbl_style"] != out_sig["tbl_style"]:
        issues.append(("table_style_id", table_index, out_sig["tbl_style"], ref_sig["tbl_style"]))

    reference_shading = [item for item in ref_sig.get("header_shading") or [] if item]
    output_shading = [item for item in out_sig.get("header_shading") or [] if item]
    if reference_shading:
        if not output_shading:
            issues.append(("table_header_shading_missing", table_index, None, reference_shading[:2]))
        else:
            reference_fills = {fill for _val, fill in reference_shading}
            output_fills = {fill for _val, fill in output_shading}
            if reference_fills != output_fills:
                issues.append(("table_header_shading", table_index, sorted(output_fills), sorted(reference_fills)))

    reference_valign = ref_sig.get("valign_distribution") or {}
    output_valign = out_sig.get("valign_distribution") or {}
    if reference_valign:
        ref_dominant = max(sorted(reference_valign.items()), key=lambda kv: kv[1])[0]
        out_dominant = max(sorted(output_valign.items()), key=lambda kv: kv[1])[0] if output_valign else "none"
        if ref_dominant != "none" and out_dominant != ref_dominant:
            issues.append(("table_cell_valign", table_index, out_dominant, ref_dominant))

    reference_look = ref_sig.get("tbl_look") or {}
    if reference_look and reference_look != (out_sig.get("tbl_look") or {}):
        issues.append(("table_tbl_look", table_index, out_sig.get("tbl_look"), reference_look))

    for band_key in ("row_band_size", "col_band_size"):
        ref_band = ref_sig.get(band_key)
        if ref_band and ref_band != out_sig.get(band_key):
            issues.append(("table_band_size", table_index, out_sig.get(band_key), ref_band))

    for row_index, (out_entry, ref_entry) in enumerate(
        zip(out_sig.get("row_heights") or [], ref_sig.get("row_heights") or [])
    ):
        out_height = _height_value(out_entry)
        ref_height = _height_value(ref_entry)
        if not ref_height:
            continue
        if not out_height:
            issues.append(("table_row_height", table_index, row_index, out_height, ref_height))
            continue
        drift = abs(out_height - ref_height) / float(ref_height)
        if drift > 0.15:
            issues.append(("table_row_height", table_index, row_index, out_height, ref_height))
            continue
        ref_rule = (ref_entry.get("hRule") or "auto") if isinstance(ref_entry, dict) else "auto"
        out_rule = (out_entry.get("hRule") or "auto") if isinstance(out_entry, dict) else "auto"
        if ref_rule != out_rule:
            issues.append(("table_row_height_rule", table_index, row_index, out_rule, ref_rule))

    if ref_sig["header_row_height"] and out_sig["header_row_height"]:
        try:
            ref_h = float(ref_sig["header_row_height"])
            out_h = float(out_sig["header_row_height"])
            if ref_h and abs(out_h - ref_h) / ref_h > 0.15:
                issues.append(("table_header_height", table_index, out_h, ref_h))
        except (TypeError, ValueError):
            pass

    ref_cells = {(item["row"], item["cell"]): item for item in ref_sig.get("cells", [])}
    out_cells = {(item["row"], item["cell"]): item for item in out_sig.get("cells", [])}
    for position, ref_cell in ref_cells.items():
        out_cell = out_cells.get(position)
        if out_cell is None:
            continue
        for property_name in ("tcW", "gridSpan", "hMerge", "vMerge", "tcMar"):
            if out_cell.get(property_name) != ref_cell.get(property_name):
                issues.append(("table_cell_property", table_index, position[0], position[1], property_name, out_cell.get(property_name), ref_cell.get(property_name)))

    output_cells = {(row, col): styles for row, col, styles in out_sig.get("cell_text_styles", [])}
    for row, col, ref_styles in ref_sig.get("cell_text_styles", []):
        out_styles = output_cells.get((row, col))
        if out_styles is None:
            continue
        if out_styles != ref_styles:
            issues.append(("table_cell_font_or_size", table_index, row, col, out_styles, ref_styles))

    return issues


def _insert_tblpr_child(tblPr, node, tag_name: str) -> None:
    """Insert a `w:tblPr` child at its schema position, not at the end."""
    order_index = TBLPR_ORDER.index(tag_name)
    for child in list(tblPr):
        name = child.tag.rsplit("}", 1)[-1]
        if name in TBLPR_ORDER and TBLPR_ORDER.index(name) > order_index:
            tblPr.insert(tblPr.index(child), node)
            return
    tblPr.append(node)


TRPR_ORDER = (
    "cnfStyle", "divId", "gridBefore", "gridAfter", "wBefore", "wAfter", "cantSplit",
    "trHeight", "tblHeader", "tblCellSpacing", "jc", "hidden", "ins", "del", "trPrChange",
)


def _get_or_add_trPr(tr_el):
    trPr = tr_el.find(qn("w:trPr"))
    if trPr is None:
        trPr = OxmlElement("w:trPr")
        tr_el.insert(0, trPr)
    return trPr


def _insert_trpr_child(trPr, node, tag_name: str) -> None:
    order_index = TRPR_ORDER.index(tag_name)
    for child in list(trPr):
        name = child.tag.rsplit("}", 1)[-1]
        if name in TRPR_ORDER and TRPR_ORDER.index(name) > order_index:
            trPr.insert(trPr.index(child), node)
            return
    trPr.append(node)


class TableRestoreResult(dict):
    """Restore report. Truthiness keeps the pre-v3.5 `bool` contract (topology ok)."""

    def __bool__(self) -> bool:
        return bool(self.get("topology_ok", True))


def _tcpr_props(cell) -> Dict[str, Any]:
    """Merge topology properties of one cell (`gridSpan` / `hMerge` / `vMerge`)."""
    tcPr = cell._tc.tcPr
    if tcPr is None:
        return {}
    props: Dict[str, Any] = {}
    for tag_name in ("gridSpan", "hMerge", "vMerge"):
        node = tcPr.find(qn(f"w:{tag_name}"))
        if node is not None:
            props[tag_name] = {
                key.rsplit("}", 1)[-1]: value for key, value in node.attrib.items()
            }
    return props


def _cell_text(cell) -> str:
    return "".join(paragraph.text for paragraph in cell.paragraphs).strip()


def _grid_span_of(cell) -> int:
    span = _tcpr_props(cell).get("gridSpan") or {}
    try:
        return max(int(span.get("val", 1)), 1)
    except (TypeError, ValueError):
        return 1


def _set_tcpr_prop(cell, tag_name: str, attributes: Dict[str, Any]) -> None:
    tcPr = cell._tc.get_or_add_tcPr()
    existing = tcPr.find(qn(f"w:{tag_name}"))
    if existing is not None:
        tcPr.remove(existing)
    node = OxmlElement(f"w:{tag_name}")
    for key, value in attributes.items():
        node.set(qn(f"w:{key}"), str(value))
    _insert_tcpr_child(tcPr, node, tag_name)


def _vertical_merge_chain(table, row_index: int, cell_index: int):
    chain = [table.rows[row_index].cells[cell_index]]
    row = row_index
    while row + 1 < len(table.rows):
        next_cells = table.rows[row + 1].cells
        if cell_index >= len(next_cells):
            break
        v_merge = _tcpr_props(next_cells[cell_index]).get("vMerge") or {}
        if v_merge.get("val") != "continue":
            break
        row += 1
        chain.append(next_cells[cell_index])
    return chain


def _restore_merges(target_tbl, reference_tbl, result: TableRestoreResult) -> None:
    """Write merge topology only when it is provably safe; otherwise report it for a human."""
    if len(target_tbl.rows) != len(reference_tbl.rows):
        result["manual_required"].append({"property": "merge", "reason": "row_count_mismatch"})
        return

    for row_index, (target_row, reference_row) in enumerate(zip(target_tbl.rows, reference_tbl.rows)):
        # `row.cells` yields one entry per grid column, repeating merged cells, so the
        # column count of a merged and an unmerged row stays comparable.
        target_cells = list(target_row.cells)
        reference_cells = list(reference_row.cells)
        if len(target_cells) != len(reference_cells):
            result["manual_required"].append({
                "row": row_index, "property": "merge", "reason": "cell_count_mismatch",
            })
            continue

        seen_reference_cells: List[int] = []
        removed_cells = 0
        for cell_index in range(len(reference_cells)):
            reference_cell = reference_cells[cell_index]
            reference_id = id(reference_cell._tc)
            if reference_id in seen_reference_cells:
                continue
            seen_reference_cells.append(reference_id)

            target_cells = list(target_row.cells)
            physical_index = cell_index - removed_cells
            if physical_index >= len(target_cells):
                break
            target_cell = target_cells[physical_index]
            desired = _tcpr_props(reference_cell)
            current = _tcpr_props(target_cell)
            if desired == current:
                continue

            if not desired:
                # Clearing a merge the template does not have changes layout destructively.
                result["manual_required"].append({
                    "row": row_index, "cell": cell_index, "property": "merge",
                    "reason": "target_has_merge_reference_does_not",
                })
                continue

            span = _grid_span_of(reference_cell)
            participants = target_cells[physical_index:physical_index + span]
            if len(participants) != span:
                result["manual_required"].append({
                    "row": row_index, "cell": cell_index, "property": "merge",
                    "reason": "merge_span_out_of_bounds",
                })
                continue
            texts = {_cell_text(cell) for cell in participants if _cell_text(cell)}
            if len(texts) > 1:
                result["manual_required"].append({
                    "row": row_index, "cell": cell_index, "property": "merge",
                    "reason": "merged_cells_have_different_text",
                })
                continue
            if any(_has_structural_anchors(cell._tc) for cell in participants):
                result["manual_required"].append({
                    "row": row_index, "cell": cell_index, "property": "merge",
                    "reason": "merged_cells_contain_revisions_or_comments",
                })
                continue

            chain_resource: List[Any] = []
            if "vMerge" in desired:
                reference_chain = _vertical_merge_chain(reference_tbl, row_index, cell_index)
                target_chain = _vertical_merge_chain(target_tbl, row_index, cell_index)
                if len(reference_chain) > 1:
                    if len(target_chain) != len(reference_chain):
                        result["manual_required"].append({
                            "row": row_index, "cell": cell_index, "property": "vMerge",
                            "reason": "vertical_merge_chain_mismatch",
                        })
                        continue
                    chain_texts = {_cell_text(cell) for cell in target_chain if _cell_text(cell)}
                    if len(chain_texts) > 1 or any(
                        _has_structural_anchors(cell._tc) for cell in target_chain
                    ):
                        result["manual_required"].append({
                            "row": row_index, "cell": cell_index, "property": "vMerge",
                            "reason": "vertical_merge_content_unsafe",
                        })
                        continue
                    chain_resource = target_chain

            written: List[str] = []
            for tag_name in ("gridSpan", "hMerge"):
                if tag_name in desired:
                    _set_tcpr_prop(target_cell, tag_name, desired[tag_name])
                    written.append(tag_name)
            if span > 1 and "gridSpan" in desired and len(participants) > 1:
                # A merged row physically holds one `w:tc`; the covered cells must go.
                for extra_cell in participants[1:]:
                    parent = extra_cell._tc.getparent()
                    if parent is not None:
                        parent.remove(extra_cell._tc)
                removed_cells += len(participants) - 1
            if "vMerge" in desired:
                _set_tcpr_prop(target_cell, "vMerge", desired["vMerge"])
                written.append("vMerge")
                if desired["vMerge"].get("val") == "restart" and chain_resource:
                    for chain_cell in chain_resource[1:]:
                        _set_tcpr_prop(chain_cell, "vMerge", {"val": "continue"})
                        written.append("vMerge")

            location = f"r{row_index}.c{cell_index}"
            result["restored"].extend(f"{location}.{tag}" for tag in written)


def restore_table_style_from_reference(target_tbl, reference_tbl) -> TableRestoreResult:
    """
    Copy grid column widths, table-level properties, row heights and merge topology.

    Merge writes are gated: identical topology, merged cells carrying at most one non-empty
    text, and no revision/comment anchors inside the region. Anything else lands in
    `manual_required` instead of being rewritten. Truthiness of the result matches the
    pre-v3.5 boolean (False only when the column topology cannot be restored).
    """
    result = TableRestoreResult(
        topology_ok=True,
        restored=[],
        skipped=[],
        manual_required=[],
    )
    target_el = target_tbl._tbl
    reference_el = reference_tbl._tbl

    target_grid = target_el.find(qn("w:tblGrid"))
    reference_grid = reference_el.find(qn("w:tblGrid"))
    if reference_grid is None:
        result["topology_ok"] = False
        result["manual_required"].append({"property": "grid", "reason": "reference_grid_missing"})
        return result

    reference_cols = reference_grid.findall(qn("w:gridCol"))
    target_cols = target_grid.findall(qn("w:gridCol")) if target_grid is not None else []
    if len(reference_cols) != len(target_cols):
        result["topology_ok"] = False
        result["manual_required"].append({
            "property": "column_count",
            "reason": f"reference={len(reference_cols)} target={len(target_cols)}",
        })
        return result

    for target_col, reference_col in zip(target_cols, reference_cols):
        width = reference_col.get(qn("w:w"))
        if width:
            target_col.set(qn("w:w"), width)
    result["restored"].append("grid")

    reference_pr = reference_el.find(qn("w:tblPr"))
    target_pr = target_el.find(qn("w:tblPr"))
    if reference_pr is None or target_pr is None:
        return result

    for tag_name in TBLPR_SYNC_TAGS:
        reference_node = reference_pr.find(qn(f"w:{tag_name}"))
        if reference_node is None:
            continue
        existing = target_pr.find(qn(f"w:{tag_name}"))
        if existing is not None:
            target_pr.remove(existing)
        _insert_tblpr_child(target_pr, deepcopy(reference_node), tag_name)
        result["restored"].append(f"tblPr.{tag_name}")

    if _restore_header_shading(target_tbl, reference_tbl):
        result["restored"].append("header_shading")
    if _restore_cell_valign(target_tbl, reference_tbl):
        result["restored"].append("vAlign")
    if _restore_row_heights(target_tbl, reference_tbl):
        result["restored"].append("row_heights")
    if _restore_cell_text_styles(target_tbl, reference_tbl):
        result["restored"].append("cell_text_styles")
    if _restore_cell_tcw_and_margins(target_tbl, reference_tbl):
        result["restored"].append("cell_widths")
    _restore_merges(target_tbl, reference_tbl, result)
    return result


def _restore_cell_tcw_and_margins(target_tbl, reference_tbl) -> int:
    """Copy per-cell `w:tcW` and `w:tcMar` so column widths and padding match the template."""
    restored = 0
    for row_index, reference_row in enumerate(reference_tbl.rows):
        if row_index >= len(target_tbl.rows):
            break
        for target_cell, reference_cell in zip(
            get_unique_row_cells(target_tbl.rows[row_index]),
            get_unique_row_cells(reference_row),
        ):
            for tag_name in ("tcW", "tcMar"):
                if _sync_tcpr_child(target_cell, reference_cell, tag_name):
                    restored += 1
    return restored


def _restore_cell_text_styles(target_tbl, reference_tbl) -> int:
    """Copy template paragraph/run formatting while preserving target cell text."""
    restored = 0
    for row_index, reference_row in enumerate(reference_tbl.rows):
        if row_index >= len(target_tbl.rows):
            break
        target_cells = get_unique_row_cells(target_tbl.rows[row_index])
        reference_cells = get_unique_row_cells(reference_row)
        for target_cell, reference_cell in zip(target_cells, reference_cells):
            if classify_cell_structure(target_cell) in ("nested_table", "image_cell", "sdt_control", "field_code", "unknown_complex"):
                continue
            for target_p, reference_p in zip(target_cell.paragraphs, reference_cell.paragraphs):
                reference_pPr = reference_p._p.pPr
                if reference_pPr is not None:
                    target_pPr = target_p._p.get_or_add_pPr()
                    for child in list(target_pPr):
                        if child.tag.rsplit("}", 1)[-1] == "rPr":
                            target_pPr.remove(child)
                    reference_mark = reference_pPr.find(qn("w:rPr"))
                    if reference_mark is not None:
                        target_pPr.append(deepcopy(reference_mark))
                reference_runs = [run for run in reference_p.runs if (run.text or "").strip()]
                target_runs = [run for run in target_p.runs if (run.text or "").strip()]
                if not reference_runs:
                    continue
                for run_index, target_run in enumerate(target_runs):
                    donor_run = reference_runs[min(run_index, len(reference_runs) - 1)]
                    donor_rPr = donor_run._r.rPr
                    if donor_rPr is None:
                        continue
                    target_rPr = target_run._r.get_or_add_rPr()
                    for child in list(target_rPr):
                        target_rPr.remove(child)
                    target_rPr.extend(deepcopy(child) for child in donor_rPr)
                    restored += 1
    return restored


def _sync_tcpr_child(cell, reference_cell, tag_name: str) -> bool:
    """Copy one `w:tcPr` child from the reference cell, preserving schema order."""
    reference_tcPr = reference_cell._tc.tcPr
    if reference_tcPr is None:
        return False
    reference_node = reference_tcPr.find(qn(f"w:{tag_name}"))
    if reference_node is None:
        return False
    target_tcPr = cell._tc.get_or_add_tcPr()
    existing = target_tcPr.find(qn(f"w:{tag_name}"))
    if existing is not None:
        target_tcPr.remove(existing)
    _insert_tcpr_child(target_tcPr, deepcopy(reference_node), tag_name)
    return True


def _restore_header_shading(target_tbl, reference_tbl) -> int:
    """Copy header-row `w:shd` (the blue/white table-header band seen in templates)."""
    if not target_tbl.rows or not reference_tbl.rows:
        return 0
    restored = 0
    for target_cell, reference_cell in zip(
        get_unique_row_cells(target_tbl.rows[0]),
        get_unique_row_cells(reference_tbl.rows[0]),
    ):
        if _sync_tcpr_child(target_cell, reference_cell, "shd"):
            restored += 1
    return restored


def _restore_cell_valign(target_tbl, reference_tbl) -> int:
    """Copy `w:vAlign` for every matching cell so vertical centering matches the template."""
    restored = 0
    for row_index, reference_row in enumerate(reference_tbl.rows):
        if row_index >= len(target_tbl.rows):
            break
        for target_cell, reference_cell in zip(
            get_unique_row_cells(target_tbl.rows[row_index]),
            get_unique_row_cells(reference_row),
        ):
            if _sync_tcpr_child(target_cell, reference_cell, "vAlign"):
                restored += 1
    return restored


def _restore_row_heights(target_tbl, reference_tbl) -> int:
    """Match template row heights: fill missing rows, fix >15% drift and `hRule` drift."""
    restored = 0
    for row_index, reference_row in enumerate(reference_tbl.rows):
        if row_index >= len(target_tbl.rows):
            break
        reference_height = reference_row._tr.find(qn("w:trPr"))
        reference_height = (
            reference_height.find(qn("w:trHeight")) if reference_height is not None else None
        )
        if reference_height is None:
            continue

        reference_detail = _row_height_detail(reference_row)
        if reference_detail["val"] is None:
            continue

        target_row = target_tbl.rows[row_index]
        target_detail = _row_height_detail(target_row)
        if target_detail["val"] is not None:
            drift = abs(target_detail["val"] - reference_detail["val"]) / float(reference_detail["val"])
            same_rule = (reference_detail["hRule"] or "auto") == (target_detail["hRule"] or "auto")
            if drift <= 0.15 and same_rule:
                continue

        target_trPr = _get_or_add_trPr(target_row._tr)
        existing = target_trPr.find(qn("w:trHeight"))
        if existing is not None:
            target_trPr.remove(existing)
        _insert_trpr_child(target_trPr, deepcopy(reference_height), "trHeight")
        restored += 1
    return restored


def get_unique_row_cells(row):
    """Return distinct Word Cell objects in visual left-to-right order (skips merged duplicates)."""
    seen_tcs = set()
    unique_cells = []
    for cell in row.cells:
        tc_id = id(cell._tc)
        if tc_id not in seen_tcs:
            seen_tcs.add(tc_id)
            unique_cells.append(cell)
    return unique_cells


# Bookmark/comment anchors and tracked-change wrappers must survive any cell fill:
# removing the nodes they wrap silently breaks cross-references, comments, and revisions.
_STRUCTURAL_ANCHOR_LOCAL_NAMES = {
    "bookmarkStart",
    "bookmarkEnd",
    "commentRangeStart",
    "commentRangeEnd",
    "commentReference",
    "ins",
    "del",
    "moveFrom",
    "moveTo",
    "moveFromRangeStart",
    "moveFromRangeEnd",
    "moveToRangeStart",
    "moveToRangeEnd",
}


def _has_structural_anchors(el) -> bool:
    """True when `el` contains bookmark, comment, or tracked-change anchor nodes."""
    for node in el.iter():
        local = node.tag.split("}")[-1] if "}" in node.tag else node.tag
        if local in _STRUCTURAL_ANCHOR_LOCAL_NAMES:
            return True
    return False


class CellStructureStr(str):
    """
    Hybrid string returned by `classify_cell_structure(cell)`.
    Behaves as a plain `str` (e.g. `classify_cell_structure(cell) == "plain_text"`)
    AND supports dict-style `c_info["cell_type"]` lookup for callers expecting a dict.
    """

    def __getitem__(self, key):
        if isinstance(key, str):
            if key == "cell_type":
                return str(self)
            raise KeyError(key)
        return super().__getitem__(key)

    def get(self, key: str, default=None):
        if key == "cell_type":
            return str(self)
        return default


def classify_cell_structure(cell) -> CellStructureStr:
    """
    Classify the structural type of a Word table cell before attempting any mutation (P1-5 fix):
    - `nested_table`: contains `<w:tbl>` inside `<w:tc>`
    - `image_cell`: contains `<a:blip>` or `<w:drawing>` or `<w:pict>`
    - `sdt_control`: contains `<w:sdt>` content control
    - `hyperlink_cell`: contains `<w:hyperlink>`
    - `field_code`: contains `<w:fldSimple>`, `<w:fldChar>`, or `<w:instrText>`
    - `anchored_text`: contains bookmarks, comment ranges, or tracked-change wrappers (`w:ins`/`w:del`)
      that must be preserved; filled by surgical text replacement only, never by removing nodes
    - `unknown_complex`: contains OLE objects (`w:object`), SmartArt (`dgm:relIds`), charts (`c:chart`), or math (`m:oMath`)
    - `mixed_format`: contains multiple populated runs with distinct formatting (e.g., bold label + value, or red placeholder run + black label)
    - `plain_text`: simple single-style text or blank cell safe for direct style-cloned fill
    """
    tc = cell._tc
    if tc.findall(qn("w:tbl")):
        return CellStructureStr("nested_table")
    for elem in tc.iter():
        local = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
        if local in ("object", "OLEObject", "relIds", "chart", "oMath", "oMathPara"):
            return CellStructureStr("unknown_complex")
    if tc.xpath(".//a:blip | .//w:drawing | .//w:pict"):
        return CellStructureStr("image_cell")
    if tc.xpath(".//w:sdt"):
        return CellStructureStr("sdt_control")
    if tc.xpath(".//w:hyperlink"):
        return CellStructureStr("hyperlink_cell")
    if tc.xpath(".//w:fldSimple | .//w:fldChar | .//w:instrText"):
        return CellStructureStr("field_code")
    if _has_structural_anchors(tc):
        return CellStructureStr("anchored_text")

    # Check if cell has multiple runs with different non-empty formatting (mixed_format)
    populated_runs = []
    for p in cell.paragraphs:
        for r in p.runs:
            if r.text.strip():
                populated_runs.append(r)
    if len(populated_runs) > 1:
        sigs = set()
        for r in populated_runs:
            rPr = r._r.rPr
            b = rPr.find(qn("w:b")) is not None if rPr is not None else False
            c = rPr.find(qn("w:color")).get(qn("w:val")) if (rPr is not None and rPr.find(qn("w:color")) is not None) else ""
            sz = rPr.find(qn("w:sz")).get(qn("w:val")) if (rPr is not None and rPr.find(qn("w:sz")) is not None) else ""
            sigs.add((b, c.upper(), sz))
        if len(sigs) > 1:
            return CellStructureStr("mixed_format")

    return CellStructureStr("plain_text")


def _extract_run_rPr_only(p, strip_bold: bool = False, preferred_font: Optional[str] = None):
    inh_font, inh_sz = resolve_style_sz_and_font(p, fallback_font=None, fallback_sz=None)
    for run in p.runs:
        if run.text.strip() and run._r.rPr is not None:
            return normalize_rPr_fonts_and_strip_red(
                run._r.rPr,
                strip_bold=strip_bold,
                default_font=preferred_font or inh_font,
                default_sz=inh_sz,
            )
    return None


def _extract_mark_rPr_only(p, strip_bold: bool = False, preferred_font: Optional[str] = None):
    inh_font, inh_sz = resolve_style_sz_and_font(p, fallback_font=None, fallback_sz=None)
    if p._p.pPr is not None:
        mark_rPr = p._p.pPr.find(qn("w:rPr"))
        if mark_rPr is not None:
            return normalize_rPr_fonts_and_strip_red(
                mark_rPr,
                strip_bold=strip_bold,
                default_font=preferred_font or inh_font,
                default_sz=inh_sz,
            )
    return None


def _find_row_or_table_populated_font(table, target_row_idx: int) -> Optional[str]:
    row_order = [target_row_idx] + [r for r in range(len(table.rows)) if r != target_row_idx]
    for r_i in row_order:
        if 0 <= r_i < len(table.rows):
            for cell in get_unique_row_cells(table.rows[r_i]):
                for p in cell.paragraphs:
                    for run in p.runs:
                        if run.text.strip() and run._r.rPr is not None:
                            rf = run._r.rPr.find(qn("w:rFonts"))
                            if rf is not None:
                                ea = rf.get(qn("w:eastAsia")) or rf.get(qn("w:ascii"))
                                if ea:
                                    return ea
    return None


def extract_donor_style_from_table(table, target_row_idx: int, target_col_idx: int) -> Tuple[Any, Any]:
    """
    Two-Pass Priority Chain to extract exact `(pPr, rPr)` for a cell:
    - PASS 1: populated runs in target cell, then same-column/row structurally equivalent cells.
    - PASS 2: paragraph-mark properties `<w:pPr><w:rPr>` on target cell and blank donors,
      inheriting missing font family from populated runs in the same row/table.
    """
    target_pPr = None
    for r_i in [target_row_idx] + [r for r in range(1, len(table.rows)) if r != target_row_idx]:
        if r_i < len(table.rows):
            u_cells = get_unique_row_cells(table.rows[r_i])
            if target_col_idx < len(u_cells):
                for p in u_cells[target_col_idx].paragraphs:
                    if p._p.pPr is not None:
                        target_pPr = deepcopy(p._p.pPr)
                        break
                if target_pPr is not None:
                    break

    row_populated_font = _find_row_or_table_populated_font(table, target_row_idx)

    run_candidates = [(target_row_idx, target_col_idx, False)]
    for r in range(1, len(table.rows)):
        if r != target_row_idx:
            run_candidates.append((r, target_col_idx, False))
    if target_col_idx >= 1:
        for r in range(1, len(table.rows)):
            for c in range(1, len(table.columns)):
                run_candidates.append((r, c, False))

    for r_i, c_i, is_header in run_candidates:
        if r_i < len(table.rows):
            u_cells = get_unique_row_cells(table.rows[r_i])
            if c_i < len(u_cells):
                for p in u_cells[c_i].paragraphs:
                    rPr = _extract_run_rPr_only(p, strip_bold=is_header, preferred_font=row_populated_font)
                    if rPr is not None:
                        return target_pPr, rPr

    mark_candidates = [(target_row_idx, target_col_idx, False)]
    for r in range(1, len(table.rows)):
        if r != target_row_idx:
            mark_candidates.append((r, target_col_idx, False))
    for c in range(len(table.columns)):
        if c != target_col_idx:
            mark_candidates.append((target_row_idx, c, False))
    for r in range(1, len(table.rows)):
        for c in range(len(table.columns)):
            mark_candidates.append((r, c, False))
    mark_candidates.append((0, target_col_idx, True))
    mark_candidates.append((0, 0, True))

    for r_i, c_i, is_header in mark_candidates:
        if r_i < len(table.rows):
            u_cells = get_unique_row_cells(table.rows[r_i])
            if c_i < len(u_cells):
                for p in u_cells[c_i].paragraphs:
                    rPr = (
                        _extract_run_rPr_only(p, strip_bold=is_header, preferred_font=row_populated_font)
                        or _extract_mark_rPr_only(p, strip_bold=is_header, preferred_font=row_populated_font)
                    )
                    if rPr is not None:
                        return target_pPr, rPr

    return target_pPr, normalize_rPr_fonts_and_strip_red(
        None, default_font=row_populated_font, default_sz=None
    )


def _fill_sdt_control_cell(cell, text: str, donor_rPr) -> None:
    """Update `<w:sdtContent>` text inside an SDT content control without deleting `<w:sdt>`."""
    for sdt_content in cell._tc.xpath(".//w:sdtContent"):
        t_nodes = sdt_content.xpath(".//w:t")
        if t_nodes:
            t_nodes[0].text = str(text)
            ensure_xml_space_preserve_on_t(t_nodes[0])
            for extra_t in t_nodes[1:]:
                extra_t.text = ""
            return
    # Fallback if sdtContent has no w:t yet
    for p in cell.paragraphs:
        fill_paragraph_strict_style(p, str(text))
        return


def _fill_hyperlink_cell(cell, text: str, placeholder_token: Optional[str] = None) -> None:
    """Update text inside `<w:hyperlink>` while preserving `<w:hyperlink r:id="...">` relationship."""
    if placeholder_token:
        for p in cell.paragraphs:
            view = LogicalParagraphView(p._p)
            if placeholder_token in view.logical_text:
                view.replace_all_tokens({placeholder_token: str(text)})
                return
    for hl in cell._tc.xpath(".//w:hyperlink"):
        t_nodes = hl.xpath(".//w:t")
        if t_nodes:
            t_nodes[0].text = str(text)
            ensure_xml_space_preserve_on_t(t_nodes[0])
            for extra_t in t_nodes[1:]:
                extra_t.text = ""
            return


def _fill_anchored_text_cell(cell, text: str) -> Dict[str, Any]:
    """
    Replace cell text without removing any paragraph, run, bookmark, comment, or revision node.

    Only the character content of `<w:t>` is rewritten; anchor nodes wrapped around runs are siblings
    of those `<w:t>` elements, so they survive untouched.
    """
    paragraphs = list(cell.paragraphs)
    if not paragraphs:
        cell.add_paragraph()
        paragraphs = list(cell.paragraphs)

    written = False
    for p in paragraphs:
        view = LogicalParagraphView(p._p)
        if not view.logical_text.strip():
            continue
        if not written:
            view.replace_span(0, len(view.logical_text), text, strip_red_color=True)
            written = True
        else:
            view.replace_span(0, len(view.logical_text), "", strip_red_color=True)

    if not written:
        fill_paragraph_strict_style(paragraphs[0], text)
    return {"status": "updated_anchored_text", "cell_type": "anchored_text"}


def fill_cell_strict_style(
    table_or_cell,
    row_idx_or_text: Any = None,
    unique_col_idx: Optional[int] = None,
    text: Optional[str] = None,
    align_override: Optional[str] = None,
    placeholder_token: Optional[str] = None,
    allow_complex_overwrite: bool = False,
) -> Dict[str, Any]:
    """
    Structure-aware Word table cell filler (fixes P1-5).
    Supports BOTH calling conventions:
      - `fill_cell_strict_style(table, row_idx, unique_col_idx, text, ...)`
      - `fill_cell_strict_style(cell, text, ...)`
    """
    if hasattr(table_or_cell, "_tc") and unique_col_idx is None and text is None:
        cell = table_or_cell
        text = "" if row_idx_or_text is None else str(row_idx_or_text)
        row_idx = 0
        unique_col_idx = 0
        cell_type = str(classify_cell_structure(cell))
        donor_pPr, donor_rPr = None, None
    else:
        table = table_or_cell
        row_idx = int(row_idx_or_text)
        unique_col_idx = int(unique_col_idx or 0)
        text = "" if text is None else str(text)
        u_cells = get_unique_row_cells(table.rows[row_idx])
        cell = u_cells[unique_col_idx]
        cell_type = str(classify_cell_structure(cell))
        donor_pPr, donor_rPr = extract_donor_style_from_table(table, row_idx, unique_col_idx)

    # 1. Surgical token replacement works safely across ANY cell type (even cells with images/fields)
    if placeholder_token:
        replaced_count = 0
        for p in cell.paragraphs:
            view = LogicalParagraphView(p._p)
            replaced_count += view.replace_all_tokens({placeholder_token: str(text)})
        if replaced_count > 0:
            return {"status": "replaced_by_token", "cell_type": cell_type, "count": replaced_count}

    # 2. Dispatch by detected cell structure (P1-5 table)
    if cell_type in ("nested_table", "image_cell", "unknown_complex", "field_code") and not allow_complex_overwrite:
        # If there is a red placeholder run in one of the direct paragraphs (outside drawings/fields), replace only that run
        for p in cell.paragraphs:
            red_runs = [r for r in p.runs if is_red_run(r) and r.text.strip()]
            if red_runs:
                fill_paragraph_strict_style(p, str(text), placeholder_run=red_runs[0])
                return {"status": "replaced_red_run_in_complex_cell", "cell_type": cell_type}
        raise ValueError(
            f"Refusing to destructively overwrite complex cell at row={row_idx}, col={unique_col_idx} "
            f"(detected structure='{cell_type}'). Pass `placeholder_token` for surgical replacement, "
            f"use the dedicated image/nested-table handler, or set `allow_complex_overwrite=True`."
        )

    if cell_type == "sdt_control":
        _fill_sdt_control_cell(cell, str(text), donor_rPr)
        return {"status": "updated_sdt_control", "cell_type": cell_type}

    if cell_type == "hyperlink_cell":
        _fill_hyperlink_cell(cell, str(text), placeholder_token=placeholder_token)
        return {"status": "updated_hyperlink", "cell_type": cell_type}

    if cell_type == "anchored_text" and not allow_complex_overwrite:
        return _fill_anchored_text_cell(cell, str(text))

    if cell_type == "mixed_format" and not allow_complex_overwrite:
        p0 = cell.paragraphs[0]
        fill_paragraph_strict_style(p0, str(text))
        return {"status": "updated_mixed_format", "cell_type": cell_type}

    # 3. Standard `plain_text` cell fill
    if not cell.paragraphs:
        cell.add_paragraph()
    p0 = cell.paragraphs[0]

    if p0._p.pPr is None and donor_pPr is not None:
        p0._p.insert(0, deepcopy(donor_pPr))

    pPr = p0._p.get_or_add_pPr()
    if donor_pPr is None or pPr.find(qn("w:jc")) is None:
        if donor_pPr is not None:
            donor_jc = donor_pPr.find(qn("w:jc"))
            if donor_jc is not None and pPr.find(qn("w:jc")) is None:
                pPr.append(deepcopy(donor_jc))
    old_mark_rPr = pPr.find(qn("w:rPr"))
    if old_mark_rPr is not None:
        pPr.remove(old_mark_rPr)
    if donor_rPr is not None:
        pPr.append(deepcopy(donor_rPr))

    if align_override is not None:
        jc = pPr.find(qn("w:jc"))
        if jc is None:
            jc = OxmlElement("w:jc")
            pPr.append(jc)
        jc.set(qn("w:val"), align_override)

    for p in cell.paragraphs[1:]:
        if not _has_structural_anchors(p._p):
            p._element.getparent().remove(p._element)
    for r in list(p0.runs):
        r._r.getparent().remove(r._r)

    lines = str(text).split("\n")
    for idx, line in enumerate(lines):
        if idx > 0:
            p0.add_run().add_break()
        run = p0.add_run(line)
        if donor_rPr is not None:
            run._r.insert(0, deepcopy(donor_rPr))
        ensure_xml_space_preserve_on_run(run)

    return {"status": "filled_plain_text", "cell_type": cell_type}


def lock_table_layout_fixed(table, ensure_cant_split: bool = True, ensure_header_repeat: bool = True) -> None:
    """Set `w:tblLayout` to `'fixed'`, `<w:cantSplit/>` on rows, and `<w:tblHeader/>` on row 0."""
    tblPr = table._tbl.tblPr
    if tblPr is not None:
        tblLayout = tblPr.find(qn("w:tblLayout"))
        if tblLayout is None:
            tblLayout = OxmlElement("w:tblLayout")
            tblPr.append(tblLayout)
        tblLayout.set(qn("w:type"), "fixed")

    for r_idx, row in enumerate(table.rows):
        trPr = row._tr.get_or_add_trPr()
        if ensure_cant_split and trPr.find(qn("w:cantSplit")) is None:
            trPr.append(OxmlElement("w:cantSplit"))
        if ensure_header_repeat and r_idx == 0 and len(table.rows) > 1 and trPr.find(qn("w:tblHeader")) is None:
            trPr.append(OxmlElement("w:tblHeader"))


def clone_append_table_row(table, template_row_idx: int = -1, ensure_cant_split: bool = True):
    """
    Clone an existing data row (preserving `trPr`, `tcPr`, borders, widths, `pPr`, `rPr`),
    regenerate unique OOXML `paraId`/`docPr` IDs, ensure `<w:cantSplit/>`, and append to table.
    """
    existing_ids = set()
    tbl_root = table._tbl.getroottree().getroot() if hasattr(table._tbl, "getroottree") else table._tbl
    for node in tbl_root.iter():
        for attr in (W14_PARA_ID, W14_TEXT_ID, "id"):
            if attr in node.attrib:
                existing_ids.add(node.attrib[attr].upper())
    source_tr = table.rows[template_row_idx]._tr
    new_tr = deepcopy(source_tr)
    regenerate_unique_ooxml_ids(new_tr, existing_ids=existing_ids)
    trPr = new_tr.get_or_add_trPr()
    tbl_header = trPr.find(qn("w:tblHeader"))
    if tbl_header is not None:
        trPr.remove(tbl_header)
    if ensure_cant_split and trPr.find(qn("w:cantSplit")) is None:
        trPr.append(OxmlElement("w:cantSplit"))
    table._tbl.append(new_tr)
    new_row = table.rows[-1]
    for cell in get_unique_row_cells(new_row):
        if classify_cell_structure(cell) == "plain_text":
            for p in cell.paragraphs:
                for r in list(p.runs):
                    r._r.getparent().remove(r._r)
    return new_row


# Alias for v3.0 package export
clone_row_preserving_format = clone_append_table_row
