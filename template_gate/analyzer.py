# -*- coding: utf-8 -*-
"""Template evidence collection.

The analyzer is an adapter, not a second DOCX parser: it consumes the frozen
DocumentSpec 4.0 plus the existing engine probes (style resolution, table
signature, story iteration) and records one evidence item per property.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import docx
from docx.oxml.ns import qn

from engine import __version__ as ENGINE_VERSION
from engine.ooxml_utils import (
    iter_all_document_paragraphs_with_Wait_context,
    iter_all_document_tables_with_context,
)
from engine.style_engine import resolve_style_sz_and_font
from engine.table_engine import table_style_signature
from template_intelligence import build_document_spec_from_path

from .evidence import EvidenceRegistry
from .models import (
    ANALYSIS_VERSION,
    SCHEMA_VERSION,
    EvidenceRecord,
    EvidenceStatus,
    EvidenceType,
    canonical_json,
    sha256_text,
    stable_evidence_id,
)

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "config" / "template-gate-policy.json"

ANALYSIS_CACHE_VERSION = "1"

_HEADING_RE = re.compile(r"^(?:heading|标题)\s*([1-9])$", re.IGNORECASE)
_PRESERVABLE_OBJECT_TYPES = frozenset({"chart", "smartart", "ole_object"})
_PARAGRAPH_TASK_TYPES = frozenset({"REPAIR", "REFORMAT", "REVIEW"})


def load_policy(path: Optional[str] = None) -> Dict[str, Any]:
    policy_path = Path(path) if path else POLICY_PATH
    with open(policy_path, "r", encoding="utf-8") as handle:
        policy = json.load(handle)
    if not isinstance(policy, dict) or not isinstance(policy.get("task_types"), dict):
        raise ValueError("invalid template-gate policy: %s" % policy_path)
    return policy


def _required_properties(policy: Dict[str, Any], task_type: str) -> set:
    entry = policy["task_types"].get(task_type) or {}
    return set(entry.get("required_properties") or [])


def _spec_digest(spec: Dict[str, Any]) -> str:
    payload = copy.deepcopy(spec)
    fingerprint = payload.get("fingerprint_ref")
    if isinstance(fingerprint, dict):
        fingerprint.pop("baseline_path", None)
    return sha256_text(canonical_json(payload))


def _file_sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _template_sha(template_path: str, spec: Dict[str, Any]) -> str:
    declared = (spec.get("template") or {}).get("template_sha256")
    if isinstance(declared, str) and len(declared) == 64:
        return declared
    return _file_sha256(template_path)


def _paragraph_style(paragraph) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    name = None
    if paragraph is not None:
        try:
            name = getattr(getattr(paragraph, "style", None), "name", None)
        except Exception:
            name = None
    font = None
    size = None
    if paragraph is not None:
        try:
            font, size = resolve_style_sz_and_font(paragraph)
        except Exception:
            font, size = None, None
    return name, size, font


def _length_value(value: Any) -> Any:
    if value is None:
        return None
    twips = getattr(value, "twips", None)
    if twips is not None:
        return int(twips)
    if isinstance(value, (int, float)):
        return float(value)
    return str(value)


def _heading_level(paragraph, p_el) -> Optional[int]:
    style_name, _size, _font = _paragraph_style(paragraph)
    if style_name:
        match = _HEADING_RE.match(str(style_name).strip())
        if match:
            return int(match.group(1))
    p_pr = p_el.find(qn("w:pPr")) if p_el is not None else None
    if p_pr is not None:
        outline = p_pr.find(qn("w:outlineLvl"))
        if outline is not None:
            raw = outline.get(qn("w:val")) or ""
            if raw.isdigit():
                return int(raw) + 1
    return None


def _numbering(p_el) -> Optional[Dict[str, Any]]:
    if p_el is None:
        return None
    p_pr = p_el.find(qn("w:pPr"))
    if p_pr is None:
        return None
    num_pr = p_pr.find(qn("w:numPr"))
    if num_pr is None:
        return None
    values: Dict[str, Any] = {}
    num_id = num_pr.find(qn("w:numId"))
    ilvl = num_pr.find(qn("w:ilvl"))
    if num_id is not None:
        values["num_id"] = num_id.get(qn("w:val"))
    if ilvl is not None:
        values["level"] = ilvl.get(qn("w:val"))
    return values or None


def _field_codes(p_el) -> List[str]:
    if p_el is None:
        return []
    codes: List[str] = []
    for node in p_el.xpath(".//w:instrText"):
        text = (node.text or "").strip()
        if text:
            codes.append(text)
    for node in p_el.xpath(".//w:fldSimple"):
        instr = (node.get(qn("w:instr")) or "").strip()
        if instr:
            codes.append(instr)
    return list(dict.fromkeys(codes))


def _run_fonts(paragraph) -> List[Tuple[Optional[str], Optional[Any]]]:
    values: List[Tuple[Optional[str], Optional[Any]]] = []
    if paragraph is None:
        return values
    for run in paragraph.runs:
        if not (run.text or "").strip():
            continue
        font_name = None
        try:
            font_name = run.font.name
        except Exception:
            font_name = None
        r_pr = run._element.find(qn("w:rPr"))
        if r_pr is not None:
            r_fonts = r_pr.find(qn("w:rFonts"))
            if r_fonts is not None:
                font_name = r_fonts.get(qn("w:eastAsia")) or font_name
        size_pt = None
        try:
            if run.font.size is not None:
                size_pt = round(float(run.font.size.pt), 2)
        except Exception:
            size_pt = None
        values.append((font_name, size_pt))
    return values


def _table_cell_texts(table) -> List[str]:
    texts: List[str] = []
    try:
        for row in table.rows:
            for cell in row.cells:
                texts.append((cell.text or "").strip())
    except Exception:
        return texts
    return texts


def _table_has_slots(table_id: str, slot_locations: Sequence[str]) -> bool:
    return any(str(location).startswith(table_id + ".") for location in slot_locations)


def _table_purpose(table, table_id: str, slot_locations: Sequence[str]) -> Tuple[str, str]:
    has_slots = _table_has_slots(table_id, slot_locations)
    if has_slots:
        return "fillable_form", EvidenceStatus.VERIFIED.value
    texts = _table_cell_texts(table)
    headers: List[str] = []
    try:
        if table.rows:
            headers = [(cell.text or "").strip() for cell in table.rows[0].cells]
    except Exception:
        headers = []
    if any(headers):
        return "fixed_or_reference", EvidenceStatus.VERIFIED.value
    non_empty = [text for text in texts if text]
    if not non_empty:
        return "layout", EvidenceStatus.VERIFIED.value
    if len(texts) > 1:
        return "unclear", EvidenceStatus.AMBIGUOUS.value
    return "layout", EvidenceStatus.VERIFIED.value


def _add(
    registry: EvidenceRegistry,
    *,
    object_id: str,
    location: str,
    prop: str,
    value: Any,
    source: str,
    evidence_type: str,
    status: str,
    task_relevant: bool,
    detail: str = "",
    required_materials: Optional[Sequence[str]] = None,
    occurrence: int = 1,
) -> EvidenceRecord:
    record = EvidenceRecord(
        evidence_id=stable_evidence_id(object_id, prop, source, occurrence),
        object_id=object_id,
        location=location,
        property=prop,
        value=value,
        source=source,
        evidence_type=evidence_type,
        verification_status=status,
        task_relevant=task_relevant,
        blocking=False,
        detail=detail,
        required_materials=list(required_materials or []),
    )
    registry.add(record)
    return record


def _collect_spec_evidence(
    registry: EvidenceRegistry,
    spec: Dict[str, Any],
    task_type: str,
    required: set,
    slot_locations: Sequence[str],
) -> None:
    document = spec.get("document") if isinstance(spec.get("document"), dict) else {}
    sections = document.get("sections") or []
    _add(
        registry,
        object_id="template",
        location="document",
        prop="page.setup",
        value={
            "page_size": document.get("page_size"),
            "orientation": document.get("orientation"),
            "sections": sections,
        },
        source="document_spec",
        evidence_type=EvidenceType.COMPUTED_PROPERTY.value,
        status=EvidenceStatus.VERIFIED.value if sections else EvidenceStatus.UNVERIFIED.value,
        task_relevant="page.setup" in required,
        detail="page size, orientation, margins and section distances",
    )

    for region in spec.get("protected_regions") or []:
        if not isinstance(region, dict):
            continue
        location = str(region.get("location_id") or "document")
        _add(
            registry,
            object_id=str(region.get("region_id") or location),
            location=location,
            prop="protected.region",
            value=region,
            source="document_spec",
            evidence_type=EvidenceType.PARSER_RULE.value,
            status=EvidenceStatus.VERIFIED.value,
            task_relevant=False,
            detail="protected region: %s" % region.get("kind"),
        )

    for slot in spec.get("slots") or []:
        if not isinstance(slot, dict):
            continue
        location = str(slot.get("location_id") or "")
        slot_id = str(slot.get("slot_id") or location)
        protection = str(slot.get("protection_status") or "UNKNOWN")
        fillable = protection != "PROTECTED"
        relevant = fillable and task_type in {"GENERATE", "REVIEW"}
        _add(
            registry,
            object_id=slot_id,
            location=location,
            prop="slot.fillability",
            value=protection,
            source="document_spec",
            evidence_type=EvidenceType.PARSER_RULE.value,
            status=EvidenceStatus.VERIFIED.value,
            task_relevant=relevant,
            detail="candidate_type=%s confirmation_tier=%s"
            % (slot.get("candidate_type"), slot.get("confirmation_tier")),
            occurrence=int(slot.get("occurrence") or 1),
        )
        _add(
            registry,
            object_id=slot_id,
            location=location,
            prop="slot.location",
            value=location,
            source="document_spec",
            evidence_type=EvidenceType.PARSER_RULE.value,
            status=EvidenceStatus.VERIFIED.value,
            task_relevant=relevant,
            occurrence=int(slot.get("occurrence") or 1),
        )
        style = slot.get("style_reference")
        _add(
            registry,
            object_id=slot_id,
            location=location,
            prop="slot.style",
            value=style,
            source="document_spec",
            evidence_type=EvidenceType.STYLE_DEFINITION.value,
            status=EvidenceStatus.VERIFIED.value if style else EvidenceStatus.UNVERIFIED.value,
            task_relevant=relevant,
            detail="slot style reference",
            occurrence=int(slot.get("occurrence") or 1),
        )
        if not fillable or slot.get("candidate_type") == "control_or_field":
            _add(
                registry,
                object_id=slot_id,
                location=location,
                prop="sdt.editability",
                value="PROTECTED",
                source="document_spec",
                evidence_type=EvidenceType.PARSER_RULE.value,
                status=EvidenceStatus.VERIFIED.value,
                task_relevant=False,
                detail="SDT/control content is protected; sdt_edit=false",
                occurrence=int(slot.get("occurrence") or 1),
            )
        if slot.get("candidate_type") == "red_run_clue":
            red_relevant = task_type == "GENERATE"
            _add(
                registry,
                object_id=slot_id,
                location=location,
                prop="red_text.semantic",
                value=slot.get("matched_text"),
                source="parser_rule",
                evidence_type=EvidenceType.PARSER_RULE.value,
                status=EvidenceStatus.AMBIGUOUS.value,
                task_relevant=red_relevant,
                detail="red text may be a placeholder, instruction or emphasis",
                required_materials=[
                    "一份已填写完成的同类文档",
                    "该红色文字的填写说明",
                    "明确说明保留原样",
                ],
                occurrence=int(slot.get("occurrence") or 1),
            )


def _collect_paragraph_evidence(
    registry: EvidenceRegistry,
    doc,
    task_type: str,
    required: set,
    slot_locations: Sequence[str],
) -> None:
    slot_set = set(slot_locations)
    for ctx in iter_all_document_paragraphs_with_Wait_context(doc):
        location = str(ctx.get("location_id") or "")
        paragraph = ctx.get("paragraph")
        p_el = ctx.get("p_el")
        scope = str(ctx.get("scope") or "")
        style_name, size, font = _paragraph_style(paragraph)
        paragraph_relevant = task_type in _PARAGRAPH_TASK_TYPES
        is_slot_paragraph = location in slot_set

        _add(
            registry,
            object_id=location,
            location=location,
            prop="paragraph.style",
            value={
                "style_name": style_name,
                "effective_sz_half_pt": size,
                "font_east_asia": font,
            },
            source="docx_styles_xml",
            evidence_type=EvidenceType.STYLE_DEFINITION.value,
            status=EvidenceStatus.VERIFIED.value
            if any(value is not None for value in (style_name, size, font))
            else EvidenceStatus.UNVERIFIED.value,
            task_relevant=paragraph_relevant or (is_slot_paragraph and task_type == "GENERATE"),
            detail="paragraph style, size and East Asian font",
        )

        fmt = getattr(paragraph, "paragraph_format", None) if paragraph is not None else None
        if fmt is not None:
            _add(
                registry,
                object_id=location,
                location=location,
                prop="paragraph.spacing",
                value={
                    "space_before": _length_value(fmt.space_before),
                    "space_after": _length_value(fmt.space_after),
                    "line_spacing": _length_value(fmt.line_spacing),
                    "first_line_indent": _length_value(fmt.first_line_indent),
                    "left_indent": _length_value(fmt.left_indent),
                    "alignment": str(fmt.alignment) if fmt.alignment is not None else None,
                },
                source="docx_paragraph_properties",
                evidence_type=EvidenceType.XML_NODE.value,
                status=EvidenceStatus.VERIFIED.value,
                task_relevant=paragraph_relevant,
                detail="spacing and indentation from paragraph properties",
            )
        else:
            _add(
                registry,
                object_id=location,
                location=location,
                prop="paragraph.spacing",
                value=None,
                source="docx_paragraph_properties",
                evidence_type=EvidenceType.XML_NODE.value,
                status=EvidenceStatus.UNVERIFIED.value,
                task_relevant=paragraph_relevant,
                detail="paragraph properties could not be read",
            )

        heading = _heading_level(paragraph, p_el)
        _add(
            registry,
            object_id=location,
            location=location,
            prop="heading.level",
            value=heading,
            source="docx_styles_xml",
            evidence_type=EvidenceType.STYLE_DEFINITION.value,
            status=EvidenceStatus.VERIFIED.value,
            task_relevant=False,
            detail="heading level derived from style name or w:outlineLvl",
        )
        _add(
            registry,
            object_id=location,
            location=location,
            prop="numbering.level",
            value=_numbering(p_el),
            source="docx_paragraph_properties",
            evidence_type=EvidenceType.XML_NODE.value,
            status=EvidenceStatus.VERIFIED.value,
            task_relevant=False,
            detail="numbering properties; absence is a fact",
        )

        if is_slot_paragraph:
            run_values = _run_fonts(paragraph)
            font_names = sorted({str(item[0]) for item in run_values if item[0]})
            sizes = sorted({str(item[1]) for item in run_values if item[1] is not None})
            if len(font_names) > 1:
                _add(
                    registry,
                    object_id=location,
                    location=location,
                    prop="font_family",
                    value=font_names,
                    source="docx_styles_xml",
                    evidence_type=EvidenceType.XML_NODE.value,
                    status=EvidenceStatus.CONFLICT.value,
                    task_relevant=True,
                    detail="slot paragraph mixes multiple font families",
                )
            elif font_names:
                _add(
                    registry,
                    object_id=location,
                    location=location,
                    prop="font_family",
                    value=font_names[0],
                    source="docx_styles_xml",
                    evidence_type=EvidenceType.XML_NODE.value,
                    status=EvidenceStatus.VERIFIED.value,
                    task_relevant=True,
                )
            if len(sizes) > 1:
                _add(
                    registry,
                    object_id=location,
                    location=location,
                    prop="font_size",
                    value=sizes,
                    source="docx_styles_xml",
                    evidence_type=EvidenceType.XML_NODE.value,
                    status=EvidenceStatus.CONFLICT.value,
                    task_relevant=True,
                    detail="slot paragraph mixes multiple font sizes",
                )
            elif sizes:
                _add(
                    registry,
                    object_id=location,
                    location=location,
                    prop="font_size",
                    value=sizes[0],
                    source="docx_styles_xml",
                    evidence_type=EvidenceType.XML_NODE.value,
                    status=EvidenceStatus.VERIFIED.value,
                    task_relevant=True,
                )

        if scope == "textbox" or "txbx" in location or (p_el is not None and bool(p_el.xpath("ancestor::w:txbxContent"))):
            _add(
                registry,
                object_id=location,
                location=location,
                prop="textbox.position",
                value=None,
                source="docx_paragraph_properties",
                evidence_type=EvidenceType.XML_NODE.value,
                status=EvidenceStatus.UNVERIFIED.value,
                task_relevant=task_type in _PARAGRAPH_TASK_TYPES,
                detail="textbox geometry/anchor cannot be resolved deterministically",
                required_materials=["该文本框的定位说明或已填写完成的同类文档"],
            )

        codes = _field_codes(p_el)
        if codes:
            _add(
                registry,
                object_id=location,
                location=location,
                prop="field.code",
                value=codes,
                source="docx_fields",
                evidence_type=EvidenceType.XML_NODE.value,
                status=EvidenceStatus.VERIFIED.value,
                task_relevant=False,
                detail="field codes are preserved, not edited",
            )
            if any("PAGE" in code.upper() for code in codes):
                _add(
                    registry,
                    object_id=location,
                    location=location,
                    prop="page.number",
                    value=codes,
                    source="docx_fields",
                    evidence_type=EvidenceType.XML_NODE.value,
                    status=EvidenceStatus.VERIFIED.value,
                    task_relevant=False,
                    detail="page numbering field detected",
                )

        if p_el is not None and bool(p_el.xpath(".//wp:anchor")):
            _add(
                registry,
                object_id=location,
                location=location,
                prop="image.layout",
                value="anchored",
                source="docx_drawing",
                evidence_type=EvidenceType.XML_NODE.value,
                status=EvidenceStatus.UNVERIFIED.value,
                task_relevant=False,
                detail="floating anchor geometry is not verified; object is preserved",
            )


def _collect_table_evidence(
    registry: EvidenceRegistry,
    spec: Dict[str, Any],
    doc,
    task_type: str,
    slot_locations: Sequence[str],
) -> None:
    tables_by_id: Dict[str, Any] = {}
    for ctx in iter_all_document_tables_with_context(doc):
        table_id = str(ctx.get("table_id") or "")
        if table_id:
            tables_by_id[table_id] = ctx.get("table")

    capacity_locations = {
        str(item.get("location_id"))
        for item in spec.get("capacity_profiles") or []
        if isinstance(item, dict)
    }

    for table in spec.get("structure", {}).get("tables") or []:
        if not isinstance(table, dict):
            continue
        table_id = str(table.get("table_id") or "")
        actual = tables_by_id.get(table_id)
        has_slots = _table_has_slots(table_id, slot_locations)
        _add(
            registry,
            object_id=table_id,
            location=table_id,
            prop="table.structure",
            value={
                "rows": table.get("rows"),
                "cols": table.get("cols"),
                "headers": table.get("headers"),
                "cell_type_counts": table.get("cell_type_counts"),
            },
            source="document_spec",
            evidence_type=EvidenceType.PARSER_RULE.value,
            status=EvidenceStatus.VERIFIED.value,
            task_relevant=task_type in _PARAGRAPH_TASK_TYPES or (task_type == "GENERATE" and has_slots),
            detail="table structure inventory",
        )

        if actual is None:
            for prop in ("table.border", "table.shading", "table.merge", "table.column_width"):
                _add(
                    registry,
                    object_id=table_id,
                    location=table_id,
                    prop=prop,
                    value=None,
                    source="docx_table_properties",
                    evidence_type=EvidenceType.XML_NODE.value,
                    status=EvidenceStatus.UNVERIFIED.value,
                    task_relevant=task_type in _PARAGRAPH_TASK_TYPES,
                    detail="table object could not be resolved",
                )
            continue

        try:
            signature = table_style_signature(actual)
        except Exception as exc:
            signature = {}
            detail = "table signature unavailable: %s" % type(exc).__name__
        else:
            detail = "table style signature"

        if signature:
            _add(
                registry,
                object_id=table_id,
                location=table_id,
                prop="table.border",
                value=signature.get("borders") or {},
                source="docx_table_properties",
                evidence_type=EvidenceType.XML_NODE.value,
                status=EvidenceStatus.VERIFIED.value,
                task_relevant=task_type in _PARAGRAPH_TASK_TYPES,
                detail=detail,
            )
            _add(
                registry,
                object_id=table_id,
                location=table_id,
                prop="table.shading",
                value=signature.get("header_shading") or [],
                source="docx_table_properties",
                evidence_type=EvidenceType.XML_NODE.value,
                status=EvidenceStatus.VERIFIED.value,
                task_relevant=task_type in _PARAGRAPH_TASK_TYPES,
                detail=detail,
            )
            _add(
                registry,
                object_id=table_id,
                location=table_id,
                prop="table.merge",
                value=[
                    {
                        "row": cell.get("row"),
                        "cell": cell.get("cell"),
                        "gridSpan": cell.get("gridSpan"),
                        "hMerge": cell.get("hMerge"),
                        "vMerge": cell.get("vMerge"),
                    }
                    for cell in signature.get("cells") or []
                    if cell.get("gridSpan") or cell.get("hMerge") or cell.get("vMerge")
                ],
                source="docx_table_properties",
                evidence_type=EvidenceType.XML_NODE.value,
                status=EvidenceStatus.VERIFIED.value,
                task_relevant=task_type in _PARAGRAPH_TASK_TYPES,
                detail=detail,
            )
            _add(
                registry,
                object_id=table_id,
                location=table_id,
                prop="table.column_width",
                value=signature.get("col_widths") or [],
                source="docx_table_properties",
                evidence_type=EvidenceType.XML_NODE.value,
                status=EvidenceStatus.VERIFIED.value,
                task_relevant=task_type in _PARAGRAPH_TASK_TYPES,
                detail=detail,
            )
        else:
            for prop in ("table.border", "table.shading", "table.merge", "table.column_width"):
                _add(
                    registry,
                    object_id=table_id,
                    location=table_id,
                    prop=prop,
                    value=None,
                    source="docx_table_properties",
                    evidence_type=EvidenceType.XML_NODE.value,
                    status=EvidenceStatus.UNVERIFIED.value,
                    task_relevant=task_type in _PARAGRAPH_TASK_TYPES,
                    detail=detail,
                )

        matching_capacity = sorted(
            location for location in capacity_locations if location.startswith(table_id + ".")
        )
        _add(
            registry,
            object_id=table_id,
            location=table_id,
            prop="table.capacity",
            value=matching_capacity or None,
            source="document_spec",
            evidence_type=EvidenceType.COMPUTED_PROPERTY.value,
            status=EvidenceStatus.VERIFIED.value if matching_capacity else EvidenceStatus.UNVERIFIED.value,
            task_relevant=task_type == "GENERATE" and has_slots,
            detail="capacity profiles for fillable cells; estimates never authorize shrinking",
        )

        purpose, status = _table_purpose(actual, table_id, slot_locations)
        _add(
            registry,
            object_id=table_id,
            location=table_id,
            prop="table.purpose",
            value=purpose,
            source="docx_table_properties",
            evidence_type=EvidenceType.COMPUTED_PROPERTY.value,
            status=status,
            task_relevant=True,
            detail="table purpose: fillable form, fixed/reference table, layout table or unclear",
            required_materials=[
                "一份已填写完成的同类文档",
                "该表格的填写说明",
                "明确说明该表格保留原样",
            ],
        )


def _collect_image_evidence(
    registry: EvidenceRegistry,
    spec: Dict[str, Any],
    task_type: str,
) -> None:
    for image in spec.get("structure", {}).get("images") or []:
        if not isinstance(image, dict):
            continue
        location = str(image.get("location_id") or "")
        object_type = str(image.get("object_type") or "")
        object_id = "%s:%s" % (location, object_type)
        _add(
            registry,
            object_id=object_id,
            location=location,
            prop="image.layout",
            value={
                "object_type": object_type,
                "width_cm": image.get("width_cm"),
                "height_cm": image.get("height_cm"),
                "ref_count": image.get("ref_count"),
            },
            source="docx_drawing",
            evidence_type=EvidenceType.XML_NODE.value,
            status=EvidenceStatus.VERIFIED.value
            if object_type in {"inline_blip", "anchored_blip", "vml", "svg"}
            else EvidenceStatus.UNVERIFIED.value,
            task_relevant=False,
            detail="image inventory; vector and floating objects remain unverified",
        )
        _add(
            registry,
            object_id=object_id,
            location=location,
            prop="image.role",
            value=None,
            source="parser_rule",
            evidence_type=EvidenceType.PARSER_RULE.value,
            status=EvidenceStatus.UNVERIFIED.value,
            task_relevant=False,
            detail="image role (logo/stamp/qr/illustration) is not required for this task",
        )
        if object_type in _PRESERVABLE_OBJECT_TYPES:
            _add(
                registry,
                object_id=object_id,
                location=location,
                prop="object.preservable",
                value={"object_type": object_type, "mode": "preserve"},
                source="document_spec",
                evidence_type=EvidenceType.PARSER_RULE.value,
                status=EvidenceStatus.VERIFIED.value,
                task_relevant=False,
                detail="L4 object is preserved read-only",
            )


def _apply_policy(
    registry: EvidenceRegistry,
    task_type: str,
    policy: Dict[str, Any],
) -> None:
    blocking_statuses = set(policy.get("blocking_statuses") or [])
    for record in registry.records():
        if not record.task_relevant:
            record.blocking = False
        elif record.verification_status in blocking_statuses:
            record.blocking = True
        else:
            record.blocking = False
        if record.blocking:
            record.severity = "blocking"
        elif record.task_relevant or record.verification_status != EvidenceStatus.VERIFIED.value:
            record.severity = "warning"
        else:
            record.severity = "info"


def _add_conflict_records(registry: EvidenceRegistry, required: set) -> None:
    for conflict in registry.detect_conflicts():
        object_id = str(conflict.get("object_id") or "")
        prop = str(conflict.get("property") or "")
        relevant = prop in required
        blocking = relevant
        record = EvidenceRecord(
            evidence_id=stable_evidence_id(object_id, prop, "conflict_detector"),
            object_id=object_id,
            location=object_id,
            property=prop,
            value=conflict.get("values"),
            source="conflict_detector",
            evidence_type=EvidenceType.COMPUTED_PROPERTY.value,
            verification_status=EvidenceStatus.CONFLICT.value,
            task_relevant=relevant,
            blocking=blocking,
            severity="blocking" if blocking else "warning",
            detail="two or more VERIFIED sources disagree",
            required_materials=["确认该属性应采用的唯一值或参考文档"],
        )
        registry.add(record)


def build_analysis(
    template_path: str,
    task_type: str,
    *,
    spec: Optional[Dict[str, Any]] = None,
    supplements: Optional[Sequence[Any]] = None,
    previous: Optional[Dict[str, Any]] = None,
    policy: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build a deterministic evidence analysis for one template and task type."""
    task = str(task_type or "").strip().upper()
    policy = policy or load_policy()
    if task not in policy["task_types"]:
        raise ValueError("unsupported task type: %r" % (task_type,))
    task_policy = policy["task_types"][task]
    if not task_policy.get("gate"):
        raise ValueError("task type does not require a template gate: %s" % task)

    spec = spec or build_document_spec_from_path(template_path)
    template_sha = _template_sha(template_path, spec)
    spec_digest = _spec_digest(spec)
    policy_digest = sha256_text(canonical_json(policy))
    cache_key = None
    if not supplements and not previous and os.path.isfile(template_path):
        from engine.analysis_cache import key_from_parts, read_json

        cache_key = key_from_parts(
            "analysis",
            template_sha,
            os.path.basename(str(template_path)),
            task,
            spec_digest,
            ANALYSIS_VERSION,
            ENGINE_VERSION,
            policy_digest,
            ANALYSIS_CACHE_VERSION,
        )
        cached = read_json("analysis", cache_key)
        if (
            cached is not None
            and cached.get("analysis_id")
            and cached.get("evidence_digest")
            and str(cached.get("template_sha256")) == template_sha
            and str(cached.get("task_type")) == task
            and str(cached.get("spec_digest")) == spec_digest
            and str(cached.get("analysis_version")) == ANALYSIS_VERSION
            and str(cached.get("policy_version")) == str(policy.get("version") or "1.0")
        ):
            return copy.deepcopy(cached)

    doc = docx.Document(template_path)
    required = _required_properties(policy, task)
    slot_locations = [
        str(slot.get("location_id"))
        for slot in spec.get("slots") or []
        if isinstance(slot, dict) and slot.get("location_id")
    ]

    registry = EvidenceRegistry()
    _collect_spec_evidence(registry, spec, task, required, slot_locations)
    _collect_paragraph_evidence(registry, doc, task, required, slot_locations)
    _collect_table_evidence(registry, spec, doc, task, slot_locations)
    _collect_image_evidence(registry, spec, task)

    # Supplements are layered later (W4-4); the hook exists so callers cannot
    # silently lose material they supplied.
    supplement_meta: List[Dict[str, Any]] = []
    if supplements:
        from .supplements import apply_supplements, supplement_metadata  # local import avoids a cycle

        apply_supplements(registry, spec, template_path, supplements)
        supplement_meta = supplement_metadata(supplements)

    _add_conflict_records(registry, required)
    _apply_policy(registry, task, policy)

    summary = registry.summary()
    evidence_digest = registry.digest()
    analysis_id = "analysis_" + sha256_text(
        "%s|%s|%s|%s"
        % (evidence_digest, template_sha, task, ANALYSIS_VERSION)
    )[:12]

    analysis = {
        "schema_version": SCHEMA_VERSION,
        "analysis_id": analysis_id,
        "template_sha256": template_sha,
        "template_name": os.path.basename(str(template_path)),
        "spec_schema_version": str((spec.get("schema_version") or "4.0")),
        "spec_digest": spec_digest,
        "fingerprint_ref": dict(spec.get("fingerprint_ref") or {}),
        "analysis_version": ANALYSIS_VERSION,
        "parser_version": ENGINE_VERSION,
        "policy_version": str(policy.get("version") or "1.0"),
        "task_type": task,
        "evidence": registry.to_list(),
        "summary": summary,
        "evidence_digest": evidence_digest,
        "supplements": supplement_meta,
    }
    if cache_key is not None:
        from engine.analysis_cache import write_json

        try:
            write_json("analysis", cache_key, analysis)
        except OSError:
            pass
    return analysis


__all__ = [
    "build_analysis",
    "load_policy",
]
