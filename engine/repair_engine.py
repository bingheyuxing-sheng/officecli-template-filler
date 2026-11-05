# -*- coding: utf-8 -*-
"""
Document Repair Planner & Execution Engine (v3.0 — Dual-Document REPAIR Mode).

Core capabilities:
1. Dual-Document Structural & Style Comparison (`build_repair_plan`):
   - Compares a Reference/Template Document (`reference_docx`) and a Broken/Target Document (`broken_docx`).
   - Preserves all business text and table cell values in `broken_docx` while diagnosing formatting deviations against `reference_docx`:
     * Section page setup (page size, margins, orientation, header/footer distances)
     * Paragraph style & formatting (line spacing, indentation, alignment, keep_with_next, font family/size, unexpected red text)
     * Table structure & hygiene (`w:cantSplit`, `w:tblHeader`, cell vertical alignment, borders, cell margins, paragraph styles inside cells)
     * OOXML hygiene (missing `xml:space="preserve"`, duplicate `w14:paraId` / `wp:docPr` IDs)
   - Outputs a structured, reviewable `repair_plan.json` before modifying any file.
2. Safe Non-Destructive Repair Execution (`execute_repair_plan`):
   - Applies approved actions from `repair_plan` onto `broken_docx` and saves to `output_docx`.
   - Protects complex cells (nested tables, images, SDT controls, fields) from destructive overwrites.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional
import docx
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

from .ooxml_utils import sanitize_ooxml_whitespace_and_pagination, is_red_run
from .style_engine import resolve_style_sz_and_font
from .table_engine import classify_cell_structure, restore_table_style_from_reference


def _extract_section_signature(sec) -> Dict[str, Optional[int]]:
    return {
        "page_width": int(sec.page_width) if sec.page_width is not None else None,
        "page_height": int(sec.page_height) if sec.page_height is not None else None,
        "orientation": int(sec.orientation) if sec.orientation is not None else 0,
        "top_margin": int(sec.top_margin) if sec.top_margin is not None else None,
        "bottom_margin": int(sec.bottom_margin) if sec.bottom_margin is not None else None,
        "left_margin": int(sec.left_margin) if sec.left_margin is not None else None,
        "right_margin": int(sec.right_margin) if sec.right_margin is not None else None,
        "header_distance": int(sec.header_distance) if sec.header_distance is not None else None,
        "footer_distance": int(sec.footer_distance) if sec.footer_distance is not None else None,
    }


def _classify_paragraph_role(p, idx: int) -> str:
    """Classify a paragraph into a structural role for cross-document style matching."""
    style_name = (getattr(getattr(p, "style", None), "name", "") or "").lower()
    txt = (p.text or "").strip()
    if "heading 1" in style_name or "标题 1" in style_name or idx == 0 and len(txt) <= 40:
        return "title_or_h1"
    if "heading 2" in style_name or "标题 2" in style_name:
        return "h2"
    if "heading 3" in style_name or "标题 3" in style_name:
        return "h3"
    if txt.startswith(("一、", "二、", "三、", "四、", "五、", "六、", "七、", "八、", "九、", "十、")):
        return "section_heading_cn"
    if txt.startswith(("（一）", "（二）", "（三）", "（四）", "（五）", "(一)", "(二)")):
        return "subsection_heading_cn"
    return "body"


def _extract_paragraph_format_profile(p) -> Dict[str, Any]:
    pPr = p._p.pPr
    spacing_before = None
    spacing_after = None
    spacing_line = None
    spacing_lineRule = None
    first_line_indent = None
    left_indent = None
    jc_val = None

    if pPr is not None:
        sp = pPr.find(qn("w:spacing"))
        if sp is not None:
            spacing_before = sp.get(qn("w:before"))
            spacing_after = sp.get(qn("w:after"))
            spacing_line = sp.get(qn("w:line"))
            spacing_lineRule = sp.get(qn("w:lineRule"))
        ind = pPr.find(qn("w:ind"))
        if ind is not None:
            first_line_indent = ind.get(qn("w:firstLine")) or ind.get(qn("w:firstLineChars"))
            left_indent = ind.get(qn("w:left"))
        jc = pPr.find(qn("w:jc"))
        if jc is not None:
            jc_val = jc.get(qn("w:val"))

    font_ea, sz_val = resolve_style_sz_and_font(p, fallback_font=None, fallback_sz=None)
    font_ascii = None
    # Explicit run formatting overrides the paragraph style (that is how Word resolves it);
    # letting the style win wrote 11pt into documents whose template run is 12pt.
    for r in p.runs:
        if r.text.strip() and r._r.rPr is not None:
            rPr = r._r.rPr
            sz_el = rPr.find(qn("w:sz"))
            if sz_el is not None and sz_el.get(qn("w:val")):
                sz_val = sz_el.get(qn("w:val"))
            rFonts = rPr.find(qn("w:rFonts"))
            if rFonts is not None:
                font_ea = rFonts.get(qn("w:eastAsia")) or font_ea
                font_ascii = rFonts.get(qn("w:ascii")) or font_ascii
            break

    return {
        "style_name": getattr(getattr(p, "style", None), "name", None),
        "jc": jc_val,
        "spacing_before": spacing_before,
        "spacing_after": spacing_after,
        "spacing_line": spacing_line,
        "spacing_lineRule": spacing_lineRule,
        "first_line_indent": first_line_indent,
        "left_indent": left_indent,
        "sz_val": sz_val,
        "font_east_asia": font_ea,
        "font_ascii": font_ascii,
    }


def build_repair_plan(
    reference_docx_path: str,
    broken_docx_path: str,
    strip_residual_red: bool = True,
) -> Dict[str, Any]:
    """
    Compare `reference_docx_path` (template / style standard) and `broken_docx_path`
    (target document whose content must be preserved but formatting repaired) and
    generate a structured `repair_plan` dictionary.
    """
    ref_doc = docx.Document(reference_docx_path)
    brk_doc = docx.Document(broken_docx_path)

    actions: List[Dict[str, Any]] = []

    # 1. Section & Page Setup Comparison
    if ref_doc.sections and brk_doc.sections:
        for s_idx, brk_sec in enumerate(brk_doc.sections):
            ref_sec = ref_doc.sections[min(s_idx, len(ref_doc.sections) - 1)]
            ref_sig = _extract_section_signature(ref_sec)
            brk_sig = _extract_section_signature(brk_sec)
            diffs = {
                k: {"reference": ref_sig[k], "broken": brk_sig[k]}
                for k in ref_sig
                if ref_sig[k] is not None and ref_sig[k] != brk_sig[k]
            }
            if diffs:
                actions.append({
                    "action_id": f"sec_repair_{s_idx}",
                    "action_type": "SYNC_SECTION_PAGE_SETUP",
                    "target": f"section[{s_idx}]",
                    "reference_section_index": min(s_idx, len(ref_doc.sections) - 1),
                    "diffs": diffs,
                    "risk_level": "LOW",
                })

    # 2. Build role-based reference paragraph style catalog
    role_catalog: Dict[str, Dict[str, Any]] = {}
    for idx, p in enumerate(ref_doc.paragraphs):
        if not (p.text or "").strip():
            continue
        role = _classify_paragraph_role(p, idx)
        if role not in role_catalog:
            role_catalog[role] = _extract_paragraph_format_profile(p)

    # Compare broken paragraphs against reference role catalog or positional counterpart
    for p_idx, brk_p in enumerate(brk_doc.paragraphs):
        if not (brk_p.text or "").strip():
            continue
        role = _classify_paragraph_role(brk_p, p_idx)
        ref_prof = None
        if p_idx < len(ref_doc.paragraphs) and (ref_doc.paragraphs[p_idx].text or "").strip():
            ref_role = _classify_paragraph_role(ref_doc.paragraphs[p_idx], p_idx)
            if ref_role == role:
                ref_prof = _extract_paragraph_format_profile(ref_doc.paragraphs[p_idx])
        if ref_prof is None:
            ref_prof = role_catalog.get(role) or role_catalog.get("body")

        if ref_prof is not None:
            brk_prof = _extract_paragraph_format_profile(brk_p)
            p_diffs = {}
            for key in ("jc", "spacing_line", "spacing_lineRule", "first_line_indent", "sz_val", "font_east_asia", "font_ascii"):
                if ref_prof.get(key) is not None and ref_prof.get(key) != brk_prof.get(key):
                    p_diffs[key] = {"reference": ref_prof.get(key), "broken": brk_prof.get(key)}
            has_red = strip_residual_red and any(is_red_run(r) for r in brk_p.runs)
            if p_diffs or has_red:
                actions.append({
                    "action_id": f"body_p_repair_{p_idx}",
                    "action_type": "SYNC_PARAGRAPH_FORMAT",
                    "target": f"body.p[{p_idx}]",
                    "paragraph_index": p_idx,
                    "role": role,
                    "target_profile": ref_prof,
                    "strip_red": has_red,
                    "diffs": p_diffs,
                    "risk_level": "LOW",
                })

    # 3. Table Structure, Pagination Hygiene & Cell Style Comparison
    for t_idx, brk_tbl in enumerate(brk_doc.tables):
        ref_tbl = ref_doc.tables[t_idx] if t_idx < len(ref_doc.tables) else (ref_doc.tables[0] if ref_doc.tables else None)
        missing_cant_split = 0
        for row in brk_tbl.rows:
            trPr = row._tr.find(qn("w:trPr"))
            if trPr is None or trPr.find(qn("w:cantSplit")) is None:
                missing_cant_split += 1
        header_missing = False
        if brk_tbl.rows:
            tr0_pr = brk_tbl.rows[0]._tr.find(qn("w:trPr"))
            if tr0_pr is None or tr0_pr.find(qn("w:tblHeader")) is None:
                header_missing = True

        if missing_cant_split > 0 or header_missing or ref_tbl is not None:
            actions.append({
                "action_id": f"tbl_repair_{t_idx}",
                "action_type": "REPAIR_TABLE_FORMAT_AND_PAGINATION",
                "target": f"body.tbl[{t_idx}]",
                "table_index": t_idx,
                "reference_table_index": t_idx if (ref_tbl is not None and t_idx < len(ref_doc.tables)) else (0 if ref_tbl is not None else None),
                "missing_cant_split_rows": missing_cant_split,
                "header_missing_tblHeader": header_missing,
                "strip_red": strip_residual_red,
                "risk_level": "LOW",
            })

    # 4. Global OOXML Hygiene Action
    actions.append({
        "action_id": "ooxml_hygiene_pass",
        "action_type": "SANITIZE_OOXML_WHITESPACE_AND_IDS",
        "target": "document_package",
        "risk_level": "LOW",
    })

    return {
        "schema_version": "3.0",
        "task_mode": "REPAIR",
        "reference_docx": reference_docx_path,
        "broken_docx": broken_docx_path,
        "total_actions": len(actions),
        "actions": actions,
    }


TRPR_ORDER = (
    "cnfStyle", "divId", "gridBefore", "gridAfter", "wBefore", "wAfter", "cantSplit",
    "trHeight", "tblHeader", "tblCellSpacing", "jc", "hidden", "ins", "del", "trPrChange",
)


def _get_or_add_trPr(tr_el):
    """`w:trPr` must be the first child of `w:tr`."""
    trPr = tr_el.find(qn("w:trPr"))
    if trPr is None:
        trPr = OxmlElement("w:trPr")
        tr_el.insert(0, trPr)
    return trPr


def _insert_trpr_child(trPr, node, tag_name: str) -> None:
    """Insert a `w:trPr` child at its schema position instead of appending blindly."""
    order_index = TRPR_ORDER.index(tag_name)
    for child in list(trPr):
        name = child.tag.rsplit("}", 1)[-1]
        if name in TRPR_ORDER and TRPR_ORDER.index(name) > order_index:
            trPr.insert(trPr.index(child), node)
            return
    trPr.append(node)


def _row_is_bold(row) -> bool:
    runs = [
        run for cell in row.cells
        for paragraph in cell.paragraphs
        for run in paragraph.runs
        if (run.text or "").strip()
    ]
    if not runs:
        return False
    return all(bool(run.bold) for run in runs)


def _is_probable_header_row(tbl, reference_tbl=None) -> bool:
    """
    Decide whether row 0 is a real header before writing `<w:tblHeader/>`.

    Blindly marking row 0 as a repeating header would duplicate ordinary data rows across
    pages, so require evidence: the reference table marks it as a header, or the whole first
    row is bold while the following row is not.
    """
    if reference_tbl is not None and reference_tbl.rows:
        reference_trPr = reference_tbl.rows[0]._tr.find(qn("w:trPr"))
        if reference_trPr is not None and reference_trPr.find(qn("w:tblHeader")) is not None:
            return True
    if len(tbl.rows) < 2:
        return False
    return _row_is_bold(tbl.rows[0]) and not _row_is_bold(tbl.rows[1])


def _apply_paragraph_profile(p, profile: Dict[str, Any], strip_red: bool = True) -> None:
    """Apply a reference paragraph profile to `p` without altering its text or complex runs."""
    p_el = p._p
    pPr = p_el.get_or_add_pPr()

    if profile.get("jc"):
        jc = pPr.find(qn("w:jc"))
        if jc is None:
            jc = OxmlElement("w:jc")
            pPr.append(jc)
        jc.set(qn("w:val"), str(profile["jc"]))

    if any(profile.get(k) is not None for k in ("spacing_before", "spacing_after", "spacing_line", "spacing_lineRule")):
        sp = pPr.find(qn("w:spacing"))
        if sp is None:
            sp = OxmlElement("w:spacing")
            pPr.append(sp)
        if profile.get("spacing_before") is not None:
            sp.set(qn("w:before"), str(profile["spacing_before"]))
        if profile.get("spacing_after") is not None:
            sp.set(qn("w:after"), str(profile["spacing_after"]))
        if profile.get("spacing_line") is not None:
            sp.set(qn("w:line"), str(profile["spacing_line"]))
        if profile.get("spacing_lineRule") is not None:
            sp.set(qn("w:lineRule"), str(profile["spacing_lineRule"]))

    if profile.get("first_line_indent") is not None or profile.get("left_indent") is not None:
        ind = pPr.find(qn("w:ind"))
        if ind is None:
            ind = OxmlElement("w:ind")
            pPr.append(ind)
        if profile.get("first_line_indent") is not None:
            ind.set(qn("w:firstLine"), str(profile["first_line_indent"]))
        if profile.get("left_indent") is not None:
            ind.set(qn("w:left"), str(profile["left_indent"]))

    sz_val = profile.get("sz_val")
    font_ea = profile.get("font_east_asia") or "宋体"
    font_ascii = profile.get("font_ascii") or "Times New Roman"

    for r in p.runs:
        rPr = r._r.get_or_add_rPr()
        if strip_red:
            color = rPr.find(qn("w:color"))
            if color is not None and is_red_run(r):
                rPr.remove(color)
        rFonts = rPr.find(qn("w:rFonts"))
        if rFonts is None:
            rFonts = OxmlElement("w:rFonts")
            rPr.insert(0, rFonts)
        for attr in ("w:hint", "w:eastAsiaTheme", "w:asciiTheme", "w:hAnsiTheme", "w:cstheme"):
            if qn(attr) in rFonts.attrib:
                del rFonts.attrib[qn(attr)]
        rFonts.set(qn("w:eastAsia"), font_ea)
        rFonts.set(qn("w:ascii"), font_ascii)
        rFonts.set(qn("w:hAnsi"), font_ascii)
        if sz_val is not None:
            for tag_name in ("w:sz", "w:szCs"):
                sz_el = rPr.find(qn(tag_name))
                if sz_el is None:
                    sz_el = OxmlElement(tag_name)
                    rPr.append(sz_el)
                sz_el.set(qn("w:val"), str(sz_val))


def execute_repair_plan(
    repair_plan: Dict[str, Any],
    output_docx_path: str,
) -> Dict[str, Any]:
    """
    Execute a `repair_plan` generated by `build_repair_plan()`, preserving all content in
    `broken_docx` while restoring formatting from `reference_docx`, and save to `output_docx_path`.
    """
    ref_doc = docx.Document(repair_plan["reference_docx"])
    brk_doc = docx.Document(repair_plan["broken_docx"])

    applied_count = 0
    protected_cells_skipped = 0
    fixed_cant_split_rows = 0
    fixed_tbl_header_rows = 0
    skipped_header_candidates = 0

    for action in repair_plan.get("actions", []):
        atype = action.get("action_type")
        if atype == "SYNC_SECTION_PAGE_SETUP":
            t_idx = int(action["target"].split("[")[1].rstrip("]"))
            r_idx = int(action.get("reference_section_index", 0))
            if t_idx < len(brk_doc.sections) and r_idx < len(ref_doc.sections):
                ref_sec = ref_doc.sections[r_idx]
                brk_sec = brk_doc.sections[t_idx]
                brk_sec.orientation = ref_sec.orientation
                brk_sec.page_width = ref_sec.page_width
                brk_sec.page_height = ref_sec.page_height
                brk_sec.top_margin = ref_sec.top_margin
                brk_sec.bottom_margin = ref_sec.bottom_margin
                brk_sec.left_margin = ref_sec.left_margin
                brk_sec.right_margin = ref_sec.right_margin
                brk_sec.header_distance = ref_sec.header_distance
                brk_sec.footer_distance = ref_sec.footer_distance
                applied_count += 1

        elif atype == "SYNC_PARAGRAPH_FORMAT":
            p_idx = action.get("paragraph_index")
            if p_idx is not None and p_idx < len(brk_doc.paragraphs):
                _apply_paragraph_profile(
                    brk_doc.paragraphs[p_idx],
                    action.get("target_profile", {}),
                    strip_red=bool(action.get("strip_red", True)),
                )
                applied_count += 1

        elif atype == "REPAIR_TABLE_FORMAT_AND_PAGINATION":
            t_idx = action.get("table_index")
            ref_t_idx = action.get("reference_table_index")
            if t_idx is not None and t_idx < len(brk_doc.tables):
                brk_tbl = brk_doc.tables[t_idx]
                ref_tbl = (
                    ref_doc.tables[ref_t_idx]
                    if (ref_t_idx is not None and ref_t_idx < len(ref_doc.tables))
                    else None
                )
                # Table-level style: borders, margins, grid widths, tblStyle, header shading,
                # cell vertical alignment and row heights, all via the shared REVIEW restore path.
                if ref_tbl is not None:
                    restore_table_style_from_reference(brk_tbl, ref_tbl)

                # Sync cell paragraph styles safely (skipping complex non-plain cells if destructive)
                seen_tc = set()
                for r_idx, row in enumerate(brk_tbl.rows):
                    for c_idx, cell in enumerate(row.cells):
                        if id(cell._tc) in seen_tc:
                            continue
                        seen_tc.add(id(cell._tc))
                        c_info = classify_cell_structure(cell)
                        if c_info["cell_type"] in ("nested_table", "image_cell", "sdt_control", "field_code", "unknown_complex"):
                            protected_cells_skipped += 1
                            continue
                        # Find reference donor cell profile
                        donor_prof = None
                        if ref_tbl is not None and ref_tbl.rows:
                            ref_r = min(r_idx, len(ref_tbl.rows) - 1)
                            ref_c = min(c_idx, len(ref_tbl.rows[ref_r].cells) - 1)
                            ref_cell = ref_tbl.rows[ref_r].cells[ref_c]
                            if ref_cell.paragraphs:
                                donor_prof = _extract_paragraph_format_profile(ref_cell.paragraphs[0])
                        if donor_prof:
                            for p in cell.paragraphs:
                                _apply_paragraph_profile(
                                    p,
                                    donor_prof,
                                    strip_red=bool(action.get("strip_red", True)),
                                )
                # Row-level pagination attributes: the plan detected them, so apply them here.
                if action.get("missing_cant_split_rows"):
                    for row in brk_tbl.rows:
                        trPr = _get_or_add_trPr(row._tr)
                        if trPr.find(qn("w:cantSplit")) is None:
                            _insert_trpr_child(trPr, OxmlElement("w:cantSplit"), "cantSplit")
                            fixed_cant_split_rows += 1

                if action.get("header_missing_tblHeader"):
                    if _is_probable_header_row(brk_tbl, ref_tbl):
                        trPr = _get_or_add_trPr(brk_tbl.rows[0]._tr)
                        if trPr.find(qn("w:tblHeader")) is None:
                            _insert_trpr_child(trPr, OxmlElement("w:tblHeader"), "tblHeader")
                            fixed_tbl_header_rows += 1
                    else:
                        # Row 0 is not provably a header; never duplicate a data row across pages.
                        skipped_header_candidates += 1

                applied_count += 1

        elif atype == "SANITIZE_OOXML_WHITESPACE_AND_IDS":
            sanitize_ooxml_whitespace_and_pagination(brk_doc)
            applied_count += 1

    os.makedirs(os.path.dirname(os.path.abspath(output_docx_path)), exist_ok=True)
    brk_doc.save(output_docx_path)

    return {
        "output_docx": output_docx_path,
        "applied_actions": applied_count,
        "protected_cells_skipped": protected_cells_skipped,
        "fixed_cant_split_rows": fixed_cant_split_rows,
        "fixed_tbl_header_rows": fixed_tbl_header_rows,
        "skipped_header_candidates": skipped_header_candidates,
    }
