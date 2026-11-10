# -*- coding: utf-8 -*-
"""Supplement material processing and incremental re-analysis (W4-4).

A supplement never clears every unknown by itself.  Each claim is attached to a
specific evidence address and must either match an existing value or create a
conflict that keeps the gate blocked.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import docx

from engine.ooxml_utils import iter_all_document_paragraphs_with_Wait_context
from engine.table_engine import table_style_signature

from .evidence import EvidenceRegistry
from .models import (
    EvidenceRecord,
    EvidenceStatus,
    EvidenceType,
    ResolutionType,
    canonical_json,
    sha256_text,
    stable_evidence_id,
)

_CLAIM_ID_RE = re.compile(r"(ev_[0-9a-f]{12})\s*[:=]\s*(.+)")
_CLAIM_LOCATION_RE = re.compile(r"([A-Za-z0-9_.\[\]#:-]+)\s*\|\s*([A-Za-z0-9_.]+)\s*=\s*(.+)")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_semantic_supplement(path: str) -> Optional[Dict[str, Any]]:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    if payload.get("kind") != "TemplateSemanticSupplement":
        return None
    return payload


def _supplement_record(
    registry: EvidenceRegistry,
    *,
    evidence_id: Any = None,
    object_id: Any = None,
    location: Any = None,
    prop: Any = None,
) -> EvidenceRecord:
    if isinstance(evidence_id, str) and evidence_id:
        record = registry.get(evidence_id)
        if record is None:
            raise ValueError("supplement references unknown evidence_id: %s" % evidence_id)
        return record
    property_name = str(prop or "").strip()
    if object_id:
        candidates = registry.query(
            object_id=str(object_id),
            property=property_name or None,
        )
    else:
        if not isinstance(location, str) or not location:
            raise ValueError("supplement entry requires evidence_id, object id or location")
        candidates = [
            record
            for record in registry.query(property=property_name or None)
            if record.location == location
        ]
    if not candidates:
        raise ValueError(
            "supplement target does not exist: location=%s property=%s"
            % (location, property_name or "*")
        )
    if len(candidates) > 1:
        raise ValueError(
            "supplement target is ambiguous: location=%s property=%s matches %d records"
            % (location, property_name or "*", len(candidates))
        )
    return candidates[0]


def _resolve_supplement_record(
    record: EvidenceRecord,
    value: Any,
    *,
    source: str,
    user_statement: str,
    detail: str,
) -> None:
    record.value = value
    record.source = source
    record.evidence_type = EvidenceType.USER_STATEMENT.value
    record.verification_status = EvidenceStatus.VERIFIED.value
    record.blocking = False
    record.resolved_at = _now()
    record.detail = detail
    record.resolutions.append(
        {
            "resolution_id": "res_"
            + sha256_text(
                "%s|%s|%s" % (record.evidence_id, source, canonical_json(value))
            )[:12],
            "resolution_type": ResolutionType.PROVIDE_VALUE.value,
            "value": value,
            "source": source,
            "user_statement": user_statement,
            "resolved_at": _now(),
        }
    )


def apply_semantic_supplement(
    registry: EvidenceRegistry,
    template_path: str,
    supplement: Dict[str, Any],
    *,
    supplement_path: str,
) -> None:
    """Apply one TemplateSemanticSupplement 1.0 file to the evidence registry.

    Every declaration must resolve one existing evidence record. Duplicate or
    ambiguous declarations are rejected rather than applied in file order.
    """
    actual_sha = _sha256_file(template_path)
    declared_sha = str(supplement.get("template_sha256") or "")
    if declared_sha != actual_sha:
        raise ValueError(
            "semantic supplement template_sha256 mismatch: declared %s, actual %s"
            % (declared_sha or "<missing>", actual_sha)
        )
    source = "semantic_supplement:%s" % _sha256_file(supplement_path)
    try:
        from jsonschema import Draft202012Validator
        from jsonschema.exceptions import ValidationError

        schema_path = (
            os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            + os.sep
            + "schemas"
            + os.sep
            + "template_semantic_supplement-1.0.schema.json"
        )
        with open(schema_path, "r", encoding="utf-8") as handle:
            schema = json.load(handle)
        Draft202012Validator(schema).validate(supplement)
    except (OSError, ValueError, TypeError, ValidationError) as exc:
        raise ValueError("invalid TemplateSemanticSupplement: %s" % exc) from exc
    seen: set[Tuple[str, str]] = set()

    def claim_key(
        evidence_id: Any, location: Any, prop: Any, object_id: Any = None
    ) -> Tuple[str, str]:
        if isinstance(evidence_id, str) and evidence_id:
            key = ("evidence_id", evidence_id)
        else:
            key = (
                "location",
                "%s|%s|%s" % (object_id or "", location or "", prop or ""),
            )
        if key in seen:
            raise ValueError("duplicate semantic supplement declaration: %s" % (key,))
        seen.add(key)
        return key

    red_entries = supplement.get("red_text") or []
    for entry in red_entries:
        if not isinstance(entry, dict):
            raise ValueError("red_text supplement entries must be objects")
        claim_key(
            entry.get("evidence_id"),
            entry.get("location"),
            entry.get("property") or "red_text.semantic",
        )
        record = _supplement_record(
            registry,
            evidence_id=entry.get("evidence_id"),
            location=entry.get("location"),
            prop=entry.get("property") or "red_text.semantic",
        )
        current = record.value if isinstance(record.value, dict) else {}
        value = dict(current)
        for key in (
            "semantic",
            "action",
            "deletion_reason",
            "requires_confirmation",
        ):
            if key in entry:
                value[key] = entry[key]
        value["requires_confirmation"] = False
        value.setdefault("original_text", entry.get("original_text"))
        value.setdefault("run_ranges", [])
        _resolve_supplement_record(
            record,
            value,
            source=source,
            user_statement=str(entry.get("user_statement") or ""),
            detail="red-text semantics confirmed by semantic supplement",
        )

    font_entries = supplement.get("font_rules") or []
    for entry in font_entries:
        if not isinstance(entry, dict):
            raise ValueError("font_rules supplement entries must be objects")
        claim_key(
            entry.get("evidence_id"),
            entry.get("location"),
            entry.get("property") or "font_rule",
        )
        record = _supplement_record(
            registry,
            evidence_id=entry.get("evidence_id"),
            location=entry.get("location"),
            prop=entry.get("property") or "font_rule",
        )
        current = record.value if isinstance(record.value, dict) else {}
        value = dict(current)
        for key in (
            "label_size_pt",
            "slot_size_pt",
            "label_font",
            "slot_font",
            "intentional",
        ):
            if key in entry:
                value[key] = entry[key]
        value.setdefault("structure", "label_then_slot")
        value["requires_confirmation"] = False
        _resolve_supplement_record(
            record,
            value,
            source=source,
            user_statement=str(entry.get("user_statement") or ""),
            detail="mixed label/slot font rule confirmed by semantic supplement",
        )

    for section_name, property_name, id_key in (
        ("fields", "field", "field_id"),
        ("sdts", "sdt", "sdt_id"),
    ):
        for entry in supplement.get(section_name) or []:
            if not isinstance(entry, dict):
                raise ValueError("%s supplement entries must be objects" % section_name)
            object_id = entry.get(id_key)
            claim_key(
                entry.get("evidence_id"),
                entry.get("location"),
                entry.get("property") or property_name,
                object_id=object_id,
            )
            record = _supplement_record(
                registry,
                evidence_id=entry.get("evidence_id"),
                object_id=object_id,
                location=entry.get("location"),
                prop=entry.get("property") or property_name,
            )
            values = entry.get("values") if isinstance(entry.get("values"), dict) else {}
            current = record.value if isinstance(record.value, dict) else {}
            merged = dict(current)
            merged.update(values)
            _resolve_supplement_record(
                record,
                merged,
                source=source,
                user_statement=str(entry.get("user_statement") or ""),
                detail="%s inventory confirmed by semantic supplement" % property_name,
            )

    for entry in supplement.get("template_assertions") or []:
        if not isinstance(entry, dict):
            raise ValueError("template_assertions entries must be objects")
        location = entry.get("location")
        property_name = entry.get("property")
        claim_key(
            entry.get("evidence_id"),
            location,
            property_name,
        )
        record = _supplement_record(
            registry,
            evidence_id=entry.get("evidence_id"),
            location=location,
            prop=property_name,
        )
        value = entry.get("value")
        _resolve_supplement_record(
            record,
            value,
            source=source,
            user_statement=str(entry.get("user_statement") or ""),
            detail="template assertion confirmed by semantic supplement",
        )


def _kind(path: str) -> str:
    extension = os.path.splitext(path)[1].lower()
    if extension in (".docx", ".docm"):
        return "docx"
    if extension == ".json":
        return "json"
    if extension in (".md", ".txt"):
        return "text"
    return "unsupported"


def _resolve_record(
    registry: EvidenceRegistry,
    *,
    object_id: str,
    prop: str,
    value: Any,
    source: str,
    resolution_type: str,
    user_statement: str = "",
    detail: str = "",
) -> None:
    """Resolve an existing non-VERIFIED record or add a new VERIFIED record.

    A reference value that disagrees with an existing VERIFIED value is *not*
    silently authoritative: a new record is added and the conflict detector
    keeps the gate blocked.
    """
    candidates = [
        record
        for record in registry.query(object_id=object_id, property=prop)
        if record.verification_status
        in (
            EvidenceStatus.UNVERIFIED.value,
            EvidenceStatus.AMBIGUOUS.value,
            EvidenceStatus.CONFLICT.value,
        )
    ]
    if candidates:
        for record in candidates:
            if record.verification_status == EvidenceStatus.CONFLICT.value:
                existing = record.value if isinstance(record.value, list) else [record.value]
                existing_values = {
                    item if isinstance(item, str) else canonical_json(item) for item in existing
                }
                existing_canonical = {canonical_json(item) for item in existing_values}
                if canonical_json(value) not in existing_canonical and str(value) not in existing_values:
                    continue
            record.resolutions.append(
                {
                    "resolution_id": "res_" + sha256_text("%s|%s|%s" % (
                        record.evidence_id, source, canonical_json(value)
                    ))[:12],
                    "resolution_type": resolution_type,
                    "value": value,
                    "source": source,
                    "user_statement": user_statement,
                    "resolved_at": _now(),
                }
            )
            record.value = value
            record.source = source
            record.verification_status = EvidenceStatus.VERIFIED.value
            record.blocking = False
            record.resolved_at = _now()
            if detail:
                record.detail = detail
            return

    record = EvidenceRecord(
        evidence_id=stable_evidence_id(object_id, prop, source),
        object_id=object_id,
        location=object_id,
        property=prop,
        value=value,
        source=source,
        evidence_type=EvidenceType.REFERENCE_DOCUMENT.value
        if source.startswith("reference_docx:")
        else EvidenceType.USER_STATEMENT.value,
        verification_status=EvidenceStatus.VERIFIED.value,
        task_relevant=True,
        blocking=False,
        detail=detail,
        resolutions=[
            {
                "resolution_id": "res_" + sha256_text("%s|%s|%s" % (
                    object_id, prop, source
                ))[:12],
                "resolution_type": resolution_type,
                "value": value,
                "source": source,
                "user_statement": user_statement,
                "resolved_at": _now(),
            }
        ],
        resolved_at=_now(),
    )
    registry.add(record)


def _reference_paragraphs(reference_doc) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    by_location: Dict[str, Any] = {}
    by_text: Dict[str, Any] = {}
    for ctx in iter_all_document_paragraphs_with_Wait_context(reference_doc):
        location = str(ctx.get("location_id") or "")
        paragraph = ctx.get("paragraph")
        by_location[location] = paragraph
        text = (getattr(paragraph, "text", "") or "").strip()
        if text:
            by_text.setdefault(text, paragraph)
    return by_location, by_text


def _paragraph_values(paragraph) -> Dict[str, Any]:
    from .analyzer import _length_value, _paragraph_style, _run_fonts

    style_name, size, font = _paragraph_style(paragraph)
    fmt = getattr(paragraph, "paragraph_format", None)
    spacing = None
    if fmt is not None:
        spacing = {
            "space_before": _length_value(fmt.space_before),
            "space_after": _length_value(fmt.space_after),
            "line_spacing": _length_value(fmt.line_spacing),
            "first_line_indent": _length_value(fmt.first_line_indent),
            "left_indent": _length_value(fmt.left_indent),
            "alignment": str(fmt.alignment) if fmt.alignment is not None else None,
        }
    runs = _run_fonts(paragraph)
    font_names = sorted({str(name) for name, _size in runs if name})
    sizes = sorted({str(size) for _name, size in runs if size is not None})
    return {
        "style": {
            "style_name": style_name,
            "effective_sz_half_pt": size,
            "font_east_asia": font,
        },
        "spacing": spacing,
        "font_family": font_names[0] if len(font_names) == 1 else (font_names or None),
        "font_size": sizes[0] if len(sizes) == 1 else (sizes or None),
    }


def _apply_reference_docx(
    registry: EvidenceRegistry,
    spec: Dict[str, Any],
    template_path: str,
    reference_path: str,
) -> None:
    reference_doc = docx.Document(reference_path)
    template_doc = docx.Document(template_path)
    reference_sha = _sha256_file(reference_path)
    source = "reference_docx:%s" % reference_sha
    by_location, by_text = _reference_paragraphs(reference_doc)

    for paragraph in spec.get("structure", {}).get("paragraphs") or []:
        if not isinstance(paragraph, dict):
            continue
        location = str(paragraph.get("location_id") or "")
        if not location:
            continue
        ref_paragraph = by_location.get(location)
        if ref_paragraph is None:
            preview = str(paragraph.get("text_preview") or "").strip()
            ref_paragraph = by_text.get(preview) if preview else None
        if ref_paragraph is None:
            continue
        values = _paragraph_values(ref_paragraph)
        _resolve_record(
            registry,
            object_id=location,
            prop="paragraph.style",
            value=values["style"],
            source=source,
            resolution_type=ResolutionType.USE_REFERENCE.value,
            detail="paragraph style read from the supplied reference document",
        )
        if values["spacing"] is not None:
            _resolve_record(
                registry,
                object_id=location,
                prop="paragraph.spacing",
                value=values["spacing"],
                source=source,
                resolution_type=ResolutionType.USE_REFERENCE.value,
                detail="paragraph spacing read from the supplied reference document",
            )
        if values["font_family"] is not None:
            _resolve_record(
                registry,
                object_id=location,
                prop="font_family",
                value=values["font_family"],
                source=source,
                resolution_type=ResolutionType.USE_REFERENCE.value,
                detail="font family read from the supplied reference document",
            )
        if values["font_size"] is not None:
            _resolve_record(
                registry,
                object_id=location,
                prop="font_size",
                value=values["font_size"],
                source=source,
                resolution_type=ResolutionType.USE_REFERENCE.value,
                detail="font size read from the supplied reference document",
            )

        template_text = str(paragraph.get("text_preview") or "").strip()
        reference_text = (getattr(ref_paragraph, "text", "") or "").strip()
        if template_text and reference_text and template_text != reference_text:
            _resolve_record(
                registry,
                object_id=location,
                prop="red_text.semantic",
                value="placeholder_replaced",
                source=source,
                resolution_type=ResolutionType.USE_REFERENCE.value,
                detail="reference document replaced this text, so the red clue is a placeholder",
            )

    reference_tables = list(reference_doc.tables)
    template_tables = list(template_doc.tables)
    for index, table_spec in enumerate(spec.get("structure", {}).get("tables") or []):
        if not isinstance(table_spec, dict):
            continue
        table_id = str(table_spec.get("table_id") or "")
        if index >= len(reference_tables) or index >= len(template_tables):
            continue
        ref_table = reference_tables[index]
        tpl_table = template_tables[index]
        template_texts = [(cell.text or "").strip() for row in tpl_table.rows for cell in row.cells]
        reference_texts = [(cell.text or "").strip() for row in ref_table.rows for cell in row.cells]
        changed = sum(
            1
            for before, after in zip(template_texts, reference_texts, strict=False)
            if before != after
        )
        if changed and any(reference_texts):
            purpose = "fillable_form"
        elif reference_texts == template_texts:
            purpose = "fixed_or_reference"
        else:
            purpose = "unclear"
        _resolve_record(
            registry,
            object_id=table_id,
            prop="table.purpose",
            value=purpose,
            source=source,
            resolution_type=ResolutionType.USE_REFERENCE.value,
            detail="table purpose inferred from the supplied reference document",
        )

        try:
            signature = table_style_signature(ref_table)
        except Exception:
            signature = {}
        for prop, value in (
            ("table.border", signature.get("borders") or {}),
            ("table.shading", signature.get("header_shading") or []),
            (
                "table.merge",
                [
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
            ),
            ("table.column_width", signature.get("col_widths") or []),
        ):
            if value:
                _resolve_record(
                    registry,
                    object_id=table_id,
                    prop=prop,
                    value=value,
                    source=source,
                    resolution_type=ResolutionType.USE_REFERENCE.value,
                    detail="table property read from the supplied reference document",
                )


def _apply_claims(
    registry: EvidenceRegistry,
    reference_path: str,
    kind: str,
) -> None:
    with open(reference_path, "r", encoding="utf-8") as handle:
        raw = handle.read()
    source = "reference_%s:%s" % (kind, _sha256_file(reference_path))
    claims: List[Dict[str, Any]] = []
    if kind == "json":
        try:
            payload = json.loads(raw)
        except ValueError:
            payload = {}
        if isinstance(payload, dict) and isinstance(payload.get("answers"), list):
            claims = [item for item in payload["answers"] if isinstance(item, dict)]
    else:
        for line in raw.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            match = _CLAIM_ID_RE.search(line)
            if match:
                claims.append({"evidence_id": match.group(1), "value": match.group(2).strip(), "note": line})
                continue
            match = _CLAIM_LOCATION_RE.match(line)
            if match:
                claims.append(
                    {
                        "location": match.group(1),
                        "property": match.group(2),
                        "value": match.group(3).strip(),
                        "note": line,
                    }
                )

    for claim in claims:
        evidence_id = str(claim.get("evidence_id") or "")
        location = str(claim.get("location") or "")
        prop = str(claim.get("property") or "")
        value = claim.get("value")
        note = str(claim.get("note") or claim.get("user_statement") or "")
        if evidence_id:
            record = registry.get(evidence_id)
            if record is None:
                continue
            location = record.location
            prop = record.property
        if not location or not prop:
            continue
        _resolve_record(
            registry,
            object_id=location,
            prop=prop,
            value=value,
            source=source,
            resolution_type=ResolutionType.PROVIDE_VALUE.value,
            user_statement=note,
            detail="explicit answer supplied with the template materials",
        )


def supplement_metadata(supplements: Sequence[Any]) -> List[Dict[str, Any]]:
    metadata: List[Dict[str, Any]] = []
    for item in supplements:
        path = str(item)
        metadata.append(
            {
                "sha256": _sha256_file(path) if os.path.isfile(path) else None,
                "kind": _kind(path),
                "name": os.path.basename(path),
            }
        )
    return metadata


def apply_supplements(
    registry: EvidenceRegistry,
    spec: Dict[str, Any],
    template_path: str,
    supplements: Sequence[Any],
) -> None:
    for item in supplements:
        path = str(item)
        if not os.path.isfile(path):
            raise ValueError("supplement file does not exist: %s" % path)
        kind = _kind(path)
        if kind == "docx":
            _apply_reference_docx(registry, spec, template_path, path)
        elif kind in ("json", "text"):
            semantic = _load_semantic_supplement(path) if kind == "json" else None
            if semantic is not None:
                apply_semantic_supplement(
                    registry,
                    template_path,
                    semantic,
                    supplement_path=path,
                )
            else:
                _apply_claims(registry, path, kind)
        else:
            raise ValueError(
                "unsupported supplement type (only .docx/.json/.md/.txt): %s" % path
            )


def _finalize(payload: Dict[str, Any], records: Iterable[EvidenceRecord], task_type: str) -> Dict[str, Any]:
    from .analyzer import _add_conflict_records, _apply_policy, _required_properties, load_policy

    policy = load_policy()
    kept = [
        record
        for record in records
        if not (record.source == "conflict_detector" and record.verification_status == EvidenceStatus.CONFLICT.value)
    ]
    registry = EvidenceRegistry(kept)
    _add_conflict_records(registry, _required_properties(policy, task_type))
    _apply_policy(registry, task_type, policy)
    mapping = registry.summary()
    digest = registry.digest()
    result = dict(payload)
    result["evidence"] = registry.to_list()
    result["summary"] = mapping
    result["evidence_digest"] = digest
    result["analysis_id"] = "analysis_" + sha256_text(
        "%s|%s|%s|%s"
        % (digest, result.get("template_sha256"), task_type, result.get("analysis_version"))
    )[:12]
    return result


def analyze_supplements(
    template_path: str,
    analysis: Dict[str, Any],
    supplements: Sequence[Any],
) -> Dict[str, Any]:
    spec = {
        "structure": {"paragraphs": [], "tables": []},
        "template": {"template_sha256": analysis.get("template_sha256")},
        "slots": [],
        "protected_regions": [],
    }
    registry = EvidenceRegistry(
        [EvidenceRecord.from_dict(item) for item in analysis.get("evidence") or []]
    )
    # The spec structure is needed for reference matching; rebuild it only when
    # the caller did not provide one.
    from template_intelligence import build_document_spec_from_path

    spec = build_document_spec_from_path(template_path)
    apply_supplements(registry, spec, template_path, supplements)
    result = _finalize(analysis, registry.records(), str(analysis.get("task_type") or "GENERATE"))
    result["supplements"] = supplement_metadata(supplements)
    return result


def resolve_evidence(
    analysis: Dict[str, Any],
    evidence_id: str,
    *,
    resolution_type: str,
    value: Any = None,
    user_statement: str = "",
    source: str = "user_answer",
) -> Dict[str, Any]:
    task_type = str(analysis.get("task_type") or "GENERATE")
    registry = EvidenceRegistry(
        [EvidenceRecord.from_dict(item) for item in analysis.get("evidence") or []]
    )
    record = registry.get(evidence_id)
    if record is None:
        raise ValueError("unknown evidence_id: %s" % evidence_id)
    resolution = str(resolution_type or "").strip().upper()
    if resolution not in {item.value for item in ResolutionType}:
        raise ValueError("unknown resolution type: %r" % resolution_type)
    if resolution == ResolutionType.PRESERVE_AS_IS.value:
        from .analyzer import load_policy

        safe_properties = set(load_policy().get("safe_preserve_allowed") or [])
        if record.property not in safe_properties and record.task_relevant:
            record.resolutions.append(
                {
                    "resolution_id": "res_" + sha256_text("%s|preserve" % evidence_id)[:12],
                    "resolution_type": resolution,
                    "value": "PRESERVE_AS_IS",
                    "source": source,
                    "user_statement": user_statement,
                    "resolved_at": _now(),
                }
            )
            record.detail = (
                record.detail
                + "; preserve request rejected: the object can be touched by the task"
            ).strip("; ")
        else:
            record.value = "PRESERVE_AS_IS"
            record.verification_status = EvidenceStatus.VERIFIED.value
            record.blocking = False
            record.resolved_at = _now()
            record.resolutions.append(
                {
                    "resolution_id": "res_" + sha256_text("%s|preserve" % evidence_id)[:12],
                    "resolution_type": resolution,
                    "value": "PRESERVE_AS_IS",
                    "source": source,
                    "user_statement": user_statement,
                    "resolved_at": _now(),
                }
            )
    else:
        if value is None:
            raise ValueError("resolution %s requires a value" % resolution)
        record.resolutions.append(
            {
                "resolution_id": "res_" + sha256_text("%s|%s" % (evidence_id, canonical_json(value)))[:12],
                "resolution_type": resolution,
                "value": value,
                "source": source,
                "user_statement": user_statement,
                "resolved_at": _now(),
            }
        )
        record.value = value
        record.source = source
        record.verification_status = EvidenceStatus.VERIFIED.value
        record.blocking = False
        record.resolved_at = _now()
    return _finalize(analysis, registry.records(), task_type)


def reanalyze(
    template_path: str,
    task_type: str,
    *,
    previous: Dict[str, Any],
    supplements: Optional[Sequence[Any]] = None,
) -> Dict[str, Any]:
    """Rebuild analysis, then carry forward previous resolutions that still apply."""
    from .analyzer import build_analysis

    fresh = build_analysis(template_path, task_type, supplements=supplements)
    previous_records = {
        str(item.get("evidence_id")): item
        for item in previous.get("evidence") or []
        if isinstance(item, dict)
    }
    records: List[EvidenceRecord] = []
    for item in fresh.get("evidence") or []:
        record = EvidenceRecord.from_dict(item)
        old = previous_records.get(record.evidence_id)
        if (
            old
            and record.verification_status
            in (
                EvidenceStatus.UNVERIFIED.value,
                EvidenceStatus.AMBIGUOUS.value,
                EvidenceStatus.CONFLICT.value,
            )
            and old.get("resolutions")
        ):
            record = EvidenceRecord.from_dict(old)
        records.append(record)
    return _finalize(fresh, records, task_type)


__all__ = [
    "apply_semantic_supplement",
    "apply_supplements",
    "analyze_supplements",
    "resolve_evidence",
    "reanalyze",
]
