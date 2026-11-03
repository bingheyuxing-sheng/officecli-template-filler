# -*- coding: utf-8 -*-
"""
DOCX Parser, Task Router, Template Compatibility Classifier (L1-L4) & DocumentSpec Extractor (v3.0).

Core capabilities:
1. Task Router: Classifies user tasks into GENERATE, POLISH, REPAIR, MERGE, REFORMAT, or EXCEL_GENERATE.
2. Template Compatibility Assessment (L1 - L4):
   - L1: Plain paragraphs, simple tables, inline pictures (Full automatic fill/repair)
   - L2: Headers/footers, merged cells, nested tables, hyperlinks, formulas (Automatic fill + key item confirmation)
   - L3: Content controls (w:sdt), field codes, cross-references, footnotes/endnotes, comments, textboxes (Semi-automatic + manual confirmation)
   - L4: Charts (c:chart), SmartArt (dgm:relIds), OLE objects, macro-enabled .docm, complex floating shapes (Read-only protection / risk warning)
3. Document Understanding -> DocumentSpec JSON extraction:
   - Covers body, tables (including nested), headers/footers, textboxes, footnotes/endnotes, comments.
   - Uses non-destructive LogicalParagraphView so <w:proofErr> and split runs are never destructively stripped during scanning.
"""

from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional, Tuple
import docx
from docx.oxml.ns import qn

from .ooxml_utils import (
    LogicalParagraphView,
    RED_HEX_SET,
    TOKEN_PATTERN,
    is_red_run,
    iter_all_document_paragraphs_with_Wait_context,
    iter_all_document_tables_with_context,
)
from .style_engine import resolve_style_sz_and_font
from .table_engine import classify_cell_structure
from .image_engine import count_image_part_references
from .capabilities import SUPPORTED_INPUT_EXTENSIONS, get_capability, unsupported_inputs


TASK_MODES = (
    "GENERATE",
    "POLISH",
    "REPAIR",
    "REVIEW",
    "MERGE",
    "REFORMAT",
    "EXCEL_GENERATE",
    "PROOFREAD",
)


def route_document_task(
    input_files: List[str],
    user_intent: str = "",
) -> Dict[str, Any]:
    """
    Route an incoming Office document request into one of the v3.5 task modes:
    - GENERATE: Single .docx template -> filled output .docx
    - EXCEL_GENERATE: Single .xlsx template -> filled output .xlsx
    - POLISH: Single draft .docx -> formatted/polished .docx (no external reference doc)
    - REPAIR: Reference/template .docx + broken/target .docx -> repaired .docx
    - REVIEW: Reference/template .docx + draft .docx -> revision-marked .docx for human accept/reject
    - MERGE: Multiple .docx/.xlsx inputs -> consolidated output
    - REFORMAT: Source document + target specification/template -> restyled document
    - PROOFREAD: Single .docx -> tracked-changes corrected .docx (no template restore)
    - UNSUPPORTED_INPUT: at least one input is not .docx/.docm/.xlsx/.xlsm

    Every result carries `capability` (`{enabled, handler, reason}`) from
    `engine/capabilities.py`, so an unimplemented mode can never be run by accident.

    Also determines whether external web search should be enabled by default:
    - REPAIR / REVIEW / POLISH / REFORMAT / PROOFREAD: web_search_policy = "DISABLED_BY_DEFAULT"
    - GENERATE / EXCEL_GENERATE: web_search_policy = "ON_DEMAND_PUBLIC_STANDARDS_ONLY"
    """
    norm_files = [str(f).strip() for f in (input_files or []) if str(f).strip()]
    intent_lower = (user_intent or "").lower()

    rejected = unsupported_inputs(norm_files)
    if rejected:
        # A PDF/.doc/.wps input cannot be read by any handler: say so instead of
        # routing it into GENERATE and producing a document from nothing.
        return {
            "task_mode": "UNSUPPORTED_INPUT",
            "input_files": norm_files,
            "docx_files": [],
            "xlsx_files": [],
            "unsupported_files": rejected,
            "supported_formats": list(SUPPORTED_INPUT_EXTENSIONS),
            "web_search_policy": "DISABLED_BY_DEFAULT",
            "capability": {
                "task_mode": "UNSUPPORTED_INPUT",
                "enabled": False,
                "handler": None,
                "reason": "UNSUPPORTED_INPUT",
            },
        }

    xlsx_files = [f for f in norm_files if f.lower().endswith((".xlsx", ".xlsm"))]
    docx_files = [f for f in norm_files if f.lower().endswith((".docx", ".docm"))]

    review_keywords = ("审核", "审阅", "修订", "留痕", "review", "track changes", "tracked changes", "按模板修正")
    merge_keywords = ("合并", "汇总", "整合", "拼接", "merge", "combine", "consolidate")
    create_keywords = (
        "生成", "编制", "编写", "起草", "新建", "制作", "创建", "写一份", "写个",
        "produce", "create", "draft", "generate",
    )
    modify_keywords = (
        "修改", "调整", "对齐", "统一", "套用", "改格式", "格式修改", "重新排版",
        "排版规范", "格式统一", "转换版式", "reformat", "convert style",
        "restyle", "normalize formatting",
    )
    # "按模板" alone is ambiguous: "按模板生成" is GENERATE, "按模板修改格式" is REFORMAT.
    # A template phrase only becomes a REFORMAT signal when no create verb is present.
    template_phrases = ("按模板", "根据模板", "照模板", "套模板", "模板格式", "模板样式")
    reformat_keywords = (
        "转换", "重构版式", "重新排版", "统一字体", "统一字号", "排版规范",
        "格式统一", "reformat", "convert style", "restyle", "normalize formatting",
    )
    polish_keywords = ("美化", "润色", "排版优化", "polish", "beautify", "format cleanup")
    repair_keywords = ("修复", "repair", "fix format")
    proofread_keywords = (
        "错别字", "错字", "校对", "数据错误", "逻辑问题", "proofread", "typo",
    )

    is_review = any(k in intent_lower for k in review_keywords)
    is_merge = any(k in intent_lower for k in merge_keywords)
    is_create = any(k in intent_lower for k in create_keywords)
    has_modify = any(k in intent_lower for k in modify_keywords)
    has_template_phrase = any(k in intent_lower for k in template_phrases)
    is_reformat = any(k in intent_lower for k in reformat_keywords)
    is_polish = any(k in intent_lower for k in polish_keywords)
    is_repair = any(k in intent_lower for k in repair_keywords)
    is_proofread = any(k in intent_lower for k in proofread_keywords)
    is_reformat = (
        is_reformat
        or has_modify
        or (has_template_phrase and not is_create and not is_repair and not is_proofread and not is_polish)
    )

    input_roles = []
    data_sources = []
    secondary_actions = []

    # Role-aware routing: an .xlsx accompanying a .docx template is usually a data source,
    # not a second document to merge. Only an explicit merge request keeps MERGE.
    if is_review and len(docx_files) >= 2:
        task_mode = "REVIEW"
    elif is_merge:
        task_mode = "MERGE"
    elif docx_files and xlsx_files:
        intent_known = (
            is_create or is_reformat or is_proofread or is_polish or is_repair or has_template_phrase
        )
        if not intent_known:
            # No intent signal at all: keep the legacy safe default for multi-source input.
            task_mode = "MERGE"
        else:
            data_sources = list(xlsx_files)
            if is_reformat and not is_create:
                task_mode = "REFORMAT"
            else:
                task_mode = "GENERATE"
            if is_reformat and is_create:
                secondary_actions.append("REFORMAT")
    elif len(xlsx_files) >= 2:
        task_mode = "EXCEL_GENERATE"
        data_sources = list(xlsx_files[1:])
    elif len(docx_files) >= 2:
        task_mode = "REFORMAT" if is_reformat else "REPAIR"
    elif len(docx_files) == 1:
        if is_proofread:
            # Single-document proofreading is not a restyle: route it to PROOFREAD so it
            # does not fall into REFORMAT and rewrite formatting.
            task_mode = "PROOFREAD"
        elif is_reformat:
            task_mode = "REFORMAT"
        elif is_repair:
            # A single document has no reference template, so "fix format" means restyle against
            # the standard rules. Dual-document REPAIR requires two .docx inputs.
            task_mode = "REFORMAT"
        elif is_polish:
            task_mode = "POLISH"
        else:
            task_mode = "GENERATE"
    elif len(xlsx_files) == 1:
        task_mode = "EXCEL_GENERATE"
    else:
        task_mode = "GENERATE"

    for path in docx_files:
        role = "merge_source" if task_mode == "MERGE" else "template"
        input_roles.append({"path": path, "role": role})
    for path in xlsx_files:
        if path in data_sources:
            role = "data_source"
        elif task_mode == "MERGE":
            role = "merge_source"
        else:
            role = "template"
        input_roles.append({"path": path, "role": role})

    if task_mode in ("REPAIR", "REVIEW", "POLISH", "REFORMAT", "MERGE", "PROOFREAD"):
        web_search_policy = "DISABLED_BY_DEFAULT"
    else:
        web_search_policy = "ON_DEMAND_PUBLIC_STANDARDS_ONLY"

    capability = get_capability(task_mode)
    secondary_capabilities = [
        {"task_mode": mode, "capability": get_capability(mode)}
        for mode in secondary_actions
    ]

    return {
        "task_mode": task_mode,
        "primary_mode": task_mode,
        "secondary_actions": secondary_actions,
        "secondary_capabilities": secondary_capabilities,
        "input_files": norm_files,
        "docx_files": docx_files,
        "xlsx_files": xlsx_files,
        "data_sources": data_sources,
        "input_roles": input_roles,
        "intent_features": {
            "create": is_create,
            "modify": has_modify,
            "template_phrase": has_template_phrase,
            "merge": is_merge,
            "review": is_review,
            "reformat": is_reformat,
        },
        "web_search_policy": web_search_policy,
        "capability": capability,
    }


def _local_name(el) -> str:
    return el.tag.split("}")[-1] if "}" in el.tag else el.tag


def _has_ole_object(p_el) -> bool:
    """
    Detect embedded OLE objects without relying on an `o:` XPath prefix.

    python-docx's `nsmap` does not register the `o:` (urn:schemas-microsoft-com:office:office)
    prefix, so an `o:OLEObject` XPath raises `Undefined namespace prefix` at runtime.
    """
    if p_el.xpath(".//w:object"):
        return True
    return any(_local_name(node) == "OLEObject" for node in p_el.iter())


def assess_template_compatibility_level(doc, file_path: str = "") -> Dict[str, Any]:
    """
    Evaluate a Word document against the v3.0 L1-L4 Template Compatibility Matrix.
    """
    l2_features: List[str] = []
    l3_features: List[str] = []
    l4_features: List[str] = []

    if file_path and file_path.lower().endswith(".docm"):
        l4_features.append("macro_enabled_docm")

    # Check sections for headers/footers
    for s_idx, sec in enumerate(doc.sections):
        for hdr_name, hdr in (
            ("header", sec.header),
            ("first_page_header", sec.first_page_header),
            ("even_page_header", sec.even_page_header),
            ("footer", sec.footer),
            ("first_page_footer", sec.first_page_footer),
            ("even_page_footer", sec.even_page_footer),
        ):
            try:
                if hdr is not None and not hdr.is_linked_to_previous:
                    text_joined = "".join(p.text for p in hdr.paragraphs).strip()
                    if text_joined or hdr.tables:
                        l2_features.append(f"section[{s_idx}].{hdr_name}")
            except Exception:
                pass

    # Check all paragraphs across all scopes
    for ctx in iter_all_document_paragraphs_with_Wait_context(doc):
        scope = ctx["scope"]
        p_el = ctx["p_el"]
        if scope in ("textbox", "footnote", "endnote", "comment"):
            l3_features.append(f"scope:{scope}@{ctx['location_id']}")
        if p_el.xpath(".//w:hyperlink"):
            l2_features.append(f"hyperlink@{ctx['location_id']}")
        if p_el.xpath(".//w:sdt"):
            l3_features.append(f"sdt_control@{ctx['location_id']}")
        if p_el.xpath(".//w:fldSimple | .//w:instrText"):
            l3_features.append(f"field_code@{ctx['location_id']}")
        if p_el.xpath(".//c:chart"):
            l4_features.append(f"chart@{ctx['location_id']}")
        if p_el.xpath(".//dgm:relIds"):
            l4_features.append(f"smartart@{ctx['location_id']}")
        if _has_ole_object(p_el):
            l4_features.append(f"ole_object@{ctx['location_id']}")
        if p_el.xpath(".//wp:anchor"):
            l4_features.append(f"floating_anchor_drawing@{ctx['location_id']}")

    # Check tables for merged cells & nested tables
    for t_ctx in iter_all_document_tables_with_context(doc):
        tbl = t_ctx["table"]
        if t_ctx["depth"] > 0:
            l2_features.append(f"nested_table@{t_ctx['table_id']}")
        for row in tbl.rows:
            for cell in row.cells:
                tcPr = cell._tc.tcPr
                if tcPr is not None:
                    if tcPr.find(qn("w:gridSpan")) is not None or tcPr.find(qn("w:vMerge")) is not None:
                        l2_features.append(f"merged_cell@{t_ctx['table_id']}")
                        break

    if l4_features:
        level = "L4"
        strategy = "READ_ONLY_PROTECTION_AND_RISK_WARNING"
    elif l3_features:
        level = "L3"
        strategy = "SEMI_AUTOMATIC_WITH_USER_CONFIRMATION"
    elif l2_features:
        level = "L2"
        strategy = "AUTOMATIC_FILL_WITH_KEY_ITEM_VERIFICATION"
    else:
        level = "L1"
        strategy = "FULL_AUTOMATIC_FILL_AND_REPAIR"

    return {
        "compatibility_level": level,
        "recommended_strategy": strategy,
        "l2_features": sorted(set(l2_features))[:30],
        "l3_features": sorted(set(l3_features))[:30],
        "l4_features": sorted(set(l4_features))[:30],
    }


def extract_document_spec(doc, file_path: str = "") -> Dict[str, Any]:
    """
    Document Understanding Module:
    Parse a Word document into a structured `DocumentSpec` dictionary covering:
    - compatibility assessment (L1-L4)
    - sections & page setup (margins, orientation, page size, header/footer distances)
    - style hierarchy summary
    - logical paragraphs across all scopes (non-destructive LogicalParagraphView)
    - candidate placeholders / instruction runs (with 4-tier confirmation classification)
    - table structure & cell classifications
    - embedded media & non-text object profiles (including reference counts & MIME types)
    """
    compatibility = assess_template_compatibility_level(doc, file_path=file_path)
    img_ref_info = count_image_part_references(doc)
    # `count_image_part_references` keys entries by `owner_part:rId`; index them by bare rId for lookups.
    img_ref_by_rid: Dict[str, Dict[str, Any]] = {}
    for info in img_ref_info.values():
        rid = info.get("rId")
        if rid and rid not in img_ref_by_rid:
            img_ref_by_rid[rid] = info

    sections_spec: List[Dict[str, Any]] = []
    for idx, sec in enumerate(doc.sections):
        sections_spec.append({
            "section_index": idx,
            "page_width_twips": int(sec.page_width.twips) if sec.page_width else None,
            "page_height_twips": int(sec.page_height.twips) if sec.page_height else None,
            "orientation": int(sec.orientation) if sec.orientation is not None else 0,
            "top_margin_twips": int(sec.top_margin.twips) if sec.top_margin else None,
            "bottom_margin_twips": int(sec.bottom_margin.twips) if sec.bottom_margin else None,
            "left_margin_twips": int(sec.left_margin.twips) if sec.left_margin else None,
            "right_margin_twips": int(sec.right_margin.twips) if sec.right_margin else None,
            "header_distance_twips": int(sec.header_distance.twips) if sec.header_distance else None,
            "footer_distance_twips": int(sec.footer_distance.twips) if sec.footer_distance else None,
        })

    candidate_hits: List[Dict[str, Any]] = []
    image_profiles: List[Dict[str, Any]] = []
    paragraphs_spec: List[Dict[str, Any]] = []

    for ctx in iter_all_document_paragraphs_with_Wait_context(doc):
        p = ctx["paragraph"]
        p_el = ctx["p_el"]
        loc_id = ctx["location_id"]
        scope = ctx["scope"]

        view = LogicalParagraphView(p_el)
        logical_text = view.logical_text

        style_east_asia, style_sz = (
            resolve_style_sz_and_font(p) if p is not None else (None, None)
        )
        style_ascii = "Times New Roman" if style_east_asia else None

        # Check explicit placeholder tokens via LogicalParagraphView (works across split runs!)
        token_spans = view.find_regex_spans(TOKEN_PATTERN)
        for start, end, matched_token in token_spans:
            candidate_hits.append({
                "location_id": loc_id,
                "scope": scope,
                "candidate_type": "explicit_token",
                "matched_text": matched_token,
                "span": [start, end],
                "confirmation_tier": "AUTO_DERIVE_OR_BIND",
            })

        # Check red runs (clue only)
        if p is not None:
            red_runs = [r.text for r in p.runs if is_red_run(r) and r.text.strip()]
            if red_runs:
                candidate_hits.append({
                    "location_id": loc_id,
                    "scope": scope,
                    "candidate_type": "red_run_clue",
                    "matched_text": "".join(red_runs)[:120],
                    "confirmation_tier": "DEFAULT_FILL_WITH_NOTICE",
                })

        if p_el.xpath(".//w:sdt | .//w:fldSimple | .//w:instrText"):
            candidate_hits.append({
                "location_id": loc_id,
                "scope": scope,
                "candidate_type": "control_or_field",
                "matched_text": logical_text.strip()[:120],
                "confirmation_tier": "PROTECTED_DO_NOT_TOUCH",
            })

        # Check inline/anchored drawings & non-text objects
        blips = p_el.xpath(".//a:blip")
        if blips:
            extents = p_el.xpath(".//wp:extent")
            cx_cm = int(extents[0].get("cx")) / 360000.0 if extents else 0.0
            cy_cm = int(extents[0].get("cy")) / 360000.0 if extents else 0.0
            rId = blips[0].get(qn("r:embed"))
            ref_entry = img_ref_by_rid.get(rId, {})
            image_profiles.append({
                "location_id": loc_id,
                "scope": scope,
                "object_type": "inline_blip",
                "rId": rId,
                "width_cm": round(cx_cm, 2),
                "height_cm": round(cy_cm, 2),
                "partname": ref_entry.get("partname", ""),
                "content_type": ref_entry.get("content_type", ""),
                "ref_count": ref_entry.get("ref_count", 1),
            })

        for unsupported_check, obj_type in (
            (lambda el: bool(el.xpath(".//c:chart")), "chart"),
            (lambda el: bool(el.xpath(".//dgm:relIds")), "smartart"),
            (_has_ole_object, "ole_object"),
        ):
            if unsupported_check(p_el):
                image_profiles.append({
                    "location_id": loc_id,
                    "scope": scope,
                    "object_type": obj_type,
                    "rId": None,
                    "width_cm": 0.0,
                    "height_cm": 0.0,
                    "partname": "",
                    "content_type": "",
                    "ref_count": 0,
                })

        paragraphs_spec.append({
            "location_id": loc_id,
            "scope": scope,
            "text_preview": logical_text[:120],
            "style_name": getattr(getattr(p, "style", None), "name", None) if p is not None else None,
            "resolved_sz_half_pt": style_sz,
            "resolved_font_east_asia": style_east_asia,
            "resolved_font_ascii": style_ascii,
            "has_proof_err": len(p_el.findall(qn("w:proofErr"))) > 0,
        })

    table_profiles: List[Dict[str, Any]] = []
    for t_ctx in iter_all_document_tables_with_context(doc):
        tbl = t_ctx["table"]
        t_id = t_ctx["table_id"]
        max_chars_per_col: Dict[int, int] = {}
        cell_classifications: Dict[str, int] = {}
        seen_tc = set()
        for r_idx, row in enumerate(tbl.rows):
            for c_idx, cell in enumerate(row.cells):
                tc_id = id(cell._tc)
                txt = cell.text.strip()
                if r_idx > 0:
                    max_chars_per_col[c_idx] = max(max_chars_per_col.get(c_idx, 0), len(txt))
                if tc_id not in seen_tc:
                    seen_tc.add(tc_id)
                    c_info = classify_cell_structure(cell)
                    ct = c_info["cell_type"]
                    cell_classifications[ct] = cell_classifications.get(ct, 0) + 1

        headers = [c.text.strip().replace("\n", "") for c in tbl.rows[0].cells] if tbl.rows else []
        table_profiles.append({
            "table_id": t_id,
            "scope": t_ctx["scope"],
            "depth": t_ctx["depth"],
            "rows": len(tbl.rows),
            "cols": len(tbl.columns),
            "headers": headers,
            "max_sample_chars_per_col": max_chars_per_col,
            "cell_type_counts": cell_classifications,
        })

    return {
        "schema_version": "3.0",
        "file_path": file_path,
        "compatibility": compatibility,
        "sections": sections_spec,
        "paragraphs_count": len(paragraphs_spec),
        "paragraphs": paragraphs_spec,
        "candidate_hits": candidate_hits,
        "table_profiles": table_profiles,
        "image_profiles": image_profiles,
    }


def scan_red_runs_and_cell_capacities(doc):
    """
    Backwards-compatible v3.0 wrapper returning (candidate_hits, table_profiles, image_profiles)
    using non-destructive LogicalParagraphView (never strips <w:proofErr> or collapses runs).
    """
    spec = extract_document_spec(doc)
    return spec["candidate_hits"], spec["table_profiles"], spec["image_profiles"]
