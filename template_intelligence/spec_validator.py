# -*- coding: utf-8 -*-
"""DocumentSpec 4.0 validator: JSON Schema plus the semantic rules of Contract 02 §14.

The validator is read-only. It never mutates the document it is given and never
persists anything; callers decide what to do with the report.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "schemas" / "document_spec-4.0.schema.json"

INVALID_SPEC = "INVALID_DOCUMENT_SPEC"
UNUSABLE_SPEC = "DOCUMENT_SPEC_UNUSABLE"
SLOT_ID_CONFLICT = "SLOT_ID_CONFLICT"
SLOT_LOCATION_UNRESOLVED = "SLOT_LOCATION_UNRESOLVED"
TEMPLATE_SHA_MISMATCH = "TEMPLATE_SHA_MISMATCH"

SLOT_ID_RE = re.compile(r"^S_[0-9a-f]{12}(-c[2-9][0-9]*)?$")
SLOT_KEY_RE = re.compile(r"^[0-9a-f]{16}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
ZERO_SHA256 = "0" * 64

COMPATIBILITY_LEVELS = frozenset({"L1", "L2", "L3", "L4"})
FINGERPRINT_HASH_FIELDS = (
    "structural_hash",
    "style_hash",
    "protected_hash",
    "layout_hash",
)

_VALIDATOR: Optional[Draft202012Validator] = None


class SpecValidationError(ValueError):
    """Raised when ``raise_on_failure`` is requested and the spec is invalid."""

    def __init__(self, report: Dict[str, Any]) -> None:
        self.report = report
        errors = report.get("errors", [])
        summary = "; ".join(
            "{code} at {location}".format(**item) for item in errors[:3]
        )
        if len(errors) > 3:
            summary += "; ..."
        super().__init__(
            "DocumentSpec 4.0 validation failed with {} error(s): {}".format(
                len(errors), summary
            )
        )


def _get_validator() -> Draft202012Validator:
    global _VALIDATOR
    if _VALIDATOR is None:
        with open(SCHEMA_PATH, "r", encoding="utf-8") as handle:
            schema = json.load(handle)
        _VALIDATOR = Draft202012Validator(schema)
    return _VALIDATOR


def _json_location(parts: Iterable[Any]) -> str:
    location = "$"
    for part in parts:
        if isinstance(part, int):
            location += "[{}]".format(part)
        else:
            location += ".{}".format(part)
    return location


def _object_items(container: Any) -> List[Tuple[int, Dict[str, Any]]]:
    """Indexed object members, preserving original indices for error locations."""
    if not isinstance(container, list):
        return []
    return [
        (index, item)
        for index, item in enumerate(container)
        if isinstance(item, dict)
    ]


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _error(code: str, location: str, detail: str, severity: str = "blocking") -> Dict[str, str]:
    return {
        "code": code,
        "location": location,
        "detail": detail,
        "severity": severity,
    }


def _schema_errors(spec: Any) -> List[Dict[str, str]]:
    errors = []
    for error in _get_validator().iter_errors(spec):
        errors.append(
            _error(
                INVALID_SPEC,
                _json_location(error.absolute_path),
                error.message,
            )
        )
    return errors


def _duplicate_id_errors(
    items: List[Tuple[int, Dict[str, Any]]],
    field: str,
    collection: str,
    code: str,
) -> List[Dict[str, str]]:
    errors = []
    first_index: Dict[str, int] = {}
    for index, item in items:
        value = item.get(field)
        if not isinstance(value, str):
            continue
        if value in first_index:
            errors.append(
                _error(
                    code,
                    "$.{}[{}].{}".format(collection, index, field),
                    "duplicate {} {!r}; first declared at {}[{}]".format(
                        field, value, collection, first_index[value]
                    ),
                )
            )
        else:
            first_index[value] = index
    return errors


def _semantic_errors(spec: Dict[str, Any]) -> List[Dict[str, str]]:
    errors: List[Dict[str, str]] = []

    template = spec.get("template")
    template = template if isinstance(template, dict) else {}
    structure = spec.get("structure")
    structure = structure if isinstance(structure, dict) else {}

    slots = _object_items(spec.get("slots"))
    regions = _object_items(spec.get("protected_regions"))
    profiles = _object_items(spec.get("capacity_profiles"))
    constraints = _object_items(spec.get("layout_constraints"))

    errors.extend(_duplicate_id_errors(slots, "slot_id", "slots", SLOT_ID_CONFLICT))
    errors.extend(
        _duplicate_id_errors(
            regions, "region_id", "protected_regions", INVALID_SPEC
        )
    )
    errors.extend(
        _duplicate_id_errors(
            profiles, "profile_id", "capacity_profiles", INVALID_SPEC
        )
    )
    errors.extend(
        _duplicate_id_errors(
            constraints, "constraint_id", "layout_constraints", INVALID_SPEC
        )
    )

    template_sha256 = template.get("template_sha256")
    if isinstance(template_sha256, str):
        expected_id = "T_" + template_sha256[:12]
        if template.get("template_id") != expected_id:
            errors.append(
                _error(
                    TEMPLATE_SHA_MISMATCH,
                    "$.template.template_id",
                    "template_id must equal 'T_' + first 12 hex of template_sha256 "
                    "({!r})".format(expected_id),
                )
            )
    parent_sha256 = template.get("parent_sha256")
    if (
        isinstance(parent_sha256, str)
        and isinstance(template_sha256, str)
        and parent_sha256 == template_sha256
    ):
        errors.append(
            _error(
                TEMPLATE_SHA_MISMATCH,
                "$.template.parent_sha256",
                "parent_sha256 must differ from template_sha256",
            )
        )
    if "compatibility" in template and template.get("compatibility") not in COMPATIBILITY_LEVELS:
        errors.append(
            _error(
                INVALID_SPEC,
                "$.template.compatibility",
                "compatibility must be one of L1, L2, L3, L4",
            )
        )

    resolved_locations = set()
    for _index, paragraph in _object_items(structure.get("paragraphs")):
        location_id = paragraph.get("location_id")
        if isinstance(location_id, str):
            resolved_locations.add(location_id)
    for _index, table in _object_items(structure.get("tables")):
        table_id = table.get("table_id")
        if isinstance(table_id, str):
            resolved_locations.add(table_id)

    for index, slot in slots:
        prefix = "$.slots[{}]".format(index)
        slot_id = slot.get("slot_id")

        if isinstance(slot_id, str) and not SLOT_ID_RE.match(slot_id):
            errors.append(
                _error(
                    INVALID_SPEC,
                    prefix + ".slot_id",
                    "slot_id {!r} does not match ^S_[0-9a-f]{{12}}(-c[2-9][0-9]*)?$".format(
                        slot_id
                    ),
                )
            )

        slot_key = slot.get("slot_key")
        if isinstance(slot_key, str) and not SLOT_KEY_RE.match(slot_key):
            errors.append(
                _error(
                    INVALID_SPEC,
                    prefix + ".slot_key",
                    "slot_key {!r} does not match ^[0-9a-f]{{16}}$".format(slot_key),
                )
            )

        location_id = slot.get("location_id")
        if isinstance(location_id, str) and location_id not in resolved_locations:
            errors.append(
                _error(
                    SLOT_LOCATION_UNRESOLVED,
                    prefix + ".location_id",
                    "slot location {!r} does not resolve in structure.paragraphs[].location_id "
                    "or structure.tables[].table_id".format(location_id),
                )
            )

        protection_status = slot.get("protection_status")
        confirmation_tier = slot.get("confirmation_tier")
        if (
            protection_status == "PROTECTED"
            and confirmation_tier != "PROTECTED_DO_NOT_TOUCH"
        ):
            errors.append(
                _error(
                    INVALID_SPEC,
                    prefix + ".confirmation_tier",
                    "protection_status PROTECTED requires confirmation_tier "
                    "PROTECTED_DO_NOT_TOUCH",
                )
            )
        if (
            confirmation_tier == "PROTECTED_DO_NOT_TOUCH"
            and protection_status != "PROTECTED"
        ):
            errors.append(
                _error(
                    INVALID_SPEC,
                    prefix + ".protection_status",
                    "confirmation_tier PROTECTED_DO_NOT_TOUCH requires protection_status "
                    "PROTECTED",
                )
            )

        candidate_type = slot.get("candidate_type")
        if candidate_type == "control_or_field":
            if protection_status != "PROTECTED":
                errors.append(
                    _error(
                        INVALID_SPEC,
                        prefix + ".protection_status",
                        "candidate_type control_or_field requires protection_status PROTECTED",
                    )
                )
            if confirmation_tier != "PROTECTED_DO_NOT_TOUCH":
                errors.append(
                    _error(
                        INVALID_SPEC,
                        prefix + ".confirmation_tier",
                        "candidate_type control_or_field requires confirmation_tier "
                        "PROTECTED_DO_NOT_TOUCH",
                    )
                )
        if candidate_type == "internal_fact" and confirmation_tier != "MUST_ASK_USER":
            errors.append(
                _error(
                    INVALID_SPEC,
                    prefix + ".confirmation_tier",
                    "candidate_type internal_fact requires confirmation_tier MUST_ASK_USER",
                )
            )

        span = slot.get("span")
        if isinstance(span, dict):
            start = span.get("start")
            end = span.get("end")
            if _is_int(start) and _is_int(end) and not (0 <= start < end):
                errors.append(
                    _error(
                        INVALID_SPEC,
                        prefix + ".span",
                        "span must satisfy 0 <= start < end, got start={}, end={}".format(
                            start, end
                        ),
                    )
                )

        occurrence = slot.get("occurrence")
        if _is_int(occurrence) and occurrence < 1:
            errors.append(
                _error(
                    INVALID_SPEC,
                    prefix + ".occurrence",
                    "occurrence must be an integer >= 1, got {}".format(occurrence),
                )
            )

    fingerprint = spec.get("fingerprint_ref")
    if isinstance(fingerprint, dict):
        for field in FINGERPRINT_HASH_FIELDS:
            value = fingerprint.get(field)
            valid = (
                isinstance(value, str)
                and bool(SHA256_RE.match(value))
                and value != ZERO_SHA256
            )
            if not valid:
                errors.append(
                    _error(
                        INVALID_SPEC,
                        "$.fingerprint_ref.{}".format(field),
                        "{} must be 64 lowercase hex characters and not all zeros".format(
                            field
                        ),
                    )
                )

    if spec.get("errors"):
        errors.append(
            _error(
                UNUSABLE_SPEC,
                "$.errors",
                "errors array is non-empty; DocumentSpec is unusable for filling",
            )
        )

    return errors


def _sort_key(item: Dict[str, str]) -> Tuple[str, str, str]:
    return (item["code"], item["location"], item["detail"])


def _report(errors: List[Dict[str, str]]) -> Dict[str, Any]:
    return {
        "passed": not errors,
        "errors": errors,
        "warnings": [],
    }


def validate_document_spec(
    spec: Dict[str, Any], *, raise_on_failure: bool = False
) -> Dict[str, Any]:
    """Validate a DocumentSpec 4.0 object.

    Returns ``{"passed", "errors", "warnings"}``. Schema violations are reported
    first, then semantic violations; both blocks are ordered deterministically.
    """
    schema_errors = sorted(_schema_errors(spec), key=_sort_key)
    semantic_errors = (
        sorted(_semantic_errors(spec), key=_sort_key) if isinstance(spec, dict) else []
    )
    report = _report(schema_errors + semantic_errors)
    if raise_on_failure and report["errors"]:
        raise SpecValidationError(report)
    return report


def validate_document_spec_file(
    path: str, *, raise_on_failure: bool = False
) -> Dict[str, Any]:
    """Load a DocumentSpec 4.0 JSON file and validate it."""
    file_path = Path(path)
    try:
        with open(file_path, "r", encoding="utf-8") as handle:
            spec = json.load(handle)
    except OSError as exc:
        report = _report(
            [_error(INVALID_SPEC, "$", "cannot read DocumentSpec file: {}".format(exc))]
        )
    except json.JSONDecodeError as exc:
        report = _report(
            [
                _error(
                    INVALID_SPEC,
                    "$",
                    "DocumentSpec file is not valid JSON: {}".format(exc),
                )
            ]
        )
    else:
        if not isinstance(spec, dict):
            report = _report(
                [
                    _error(
                        INVALID_SPEC,
                        "$",
                        "DocumentSpec root must be a JSON object, got {}".format(
                            type(spec).__name__
                        ),
                    )
                ]
            )
        else:
            report = validate_document_spec(spec)
    if raise_on_failure and report["errors"]:
        raise SpecValidationError(report)
    return report


__all__ = [
    "SpecValidationError",
    "validate_document_spec",
    "validate_document_spec_file",
]
