# -*- coding: utf-8 -*-
"""Validators for ContentPlan 4.0 and FillPlan 4.0 (Contract 03).

Each validator combines JSON Schema validation with the semantic rules that
JSON Schema cannot express, and cross-validates references against the
DocumentSpec 4.0 and (optionally) the ContentPlan that produced the FillPlan.

Error records are ``{"code", "location", "detail", "severity"}``.  Registered
codes from ``config/error-codes.json`` are reused wherever a matching code
exists; codes that the frozen registry does not define are named after the
rule they enforce and are declared in this module.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

from jsonschema import Draft202012Validator

from .plan_builder import _parse_table_target

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIR = ROOT / "schemas"
CONFIG_DIR = ROOT / "config"

CONTENT_PLAN_SCHEMA = "content_plan-4.0.schema.json"
FILL_PLAN_SCHEMA = "fill_plan-4.0.schema.json"

ALLOWED_PRECONDITIONS = frozenset(
    {"slot_exists", "not_protected", "capacity_ok", "source_verified", "template_sha_match"}
)
MANDATORY_PRECONDITIONS = ("slot_exists", "not_protected", "template_sha_match")

_FACT_ID_RE = re.compile(r"^F_[0-9A-Za-z_-]{1,32}$")
_SOURCE_MARKERS = ("UNVERIFIED", "MODEL_GENERATED")


@lru_cache(maxsize=2)
def _schema_validator(name: str) -> Draft202012Validator:
    with open(SCHEMA_DIR / name, "r", encoding="utf-8") as handle:
        return Draft202012Validator(json.load(handle))


@lru_cache(maxsize=1)
def _error_registry() -> Dict[str, Dict[str, Any]]:
    try:
        with open(CONFIG_DIR / "error-codes.json", "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return {entry["code"]: entry for entry in data.get("codes", [])}
    except (OSError, ValueError, KeyError):
        return {}


def _issue(
    code: str,
    location: str,
    detail: str,
    default_severity: str = "blocking",
) -> Dict[str, Any]:
    registered = _error_registry().get(code, {}).get("severity")
    return {
        "code": code,
        "location": location,
        "detail": detail,
        "severity": registered or default_severity,
    }


def _schema_issues(instance: Any, schema_name: str, code: str) -> List[Dict[str, Any]]:
    issues: List[Dict[str, Any]] = []
    for error in _schema_validator(schema_name).iter_errors(instance):
        location = "/".join(str(part) for part in error.absolute_path) or "$"
        issues.append(_issue(code, location, error.message))
    return issues


def _list_of_str(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


# ---------------------------------------------------------------------------
# ContentPlan
# ---------------------------------------------------------------------------


def validate_content_plan(plan: Any, spec: Dict[str, Any]) -> Dict[str, Any]:
    """Schema validation plus Contract 03 §2 rules and DocumentSpec references."""
    errors = _schema_issues(plan, CONTENT_PLAN_SCHEMA, "INVALID_CONTENT_PLAN")
    warnings: List[Dict[str, Any]] = []
    if isinstance(plan, dict):
        _check_content_plan(plan, spec, errors, warnings)
    return {"passed": not errors, "errors": errors, "warnings": warnings}


def _check_content_plan(
    plan: Dict[str, Any],
    spec: Dict[str, Any],
    errors: List[Dict[str, Any]],
    warnings: List[Dict[str, Any]],
) -> None:
    spec_template = spec.get("template") if isinstance(spec.get("template"), dict) else {}
    spec_slots = {
        slot["slot_id"]
        for slot in spec.get("slots", []) or []
        if isinstance(slot, dict) and isinstance(slot.get("slot_id"), str)
    }

    if plan.get("template_id") != spec_template.get("template_id"):
        errors.append(
            _issue(
                "TEMPLATE_ID_MISMATCH",
                "template_id",
                "ContentPlan template_id %r does not match DocumentSpec %r"
                % (plan.get("template_id"), spec_template.get("template_id")),
            )
        )

    facts = [fact for fact in plan.get("facts", []) or [] if isinstance(fact, dict)]
    declared_fact_ids: set[str] = set()
    for fact in facts:
        fact_id = fact.get("fact_id")
        if isinstance(fact_id, str):
            if fact_id in declared_fact_ids:
                errors.append(
                    _issue("DUPLICATE_FACT_ID", "facts/%s" % fact_id, "duplicate fact_id %s" % fact_id)
                )
            declared_fact_ids.add(fact_id)

    sections = [section for section in plan.get("sections", []) or [] if isinstance(section, dict)]
    seen_section_ids: set[str] = set()
    slot_requirements: Dict[str, Dict[str, Any]] = {}

    for section in sections:
        section_id = section.get("section_id")
        section_location = "sections/%s" % section_id
        if isinstance(section_id, str):
            if section_id in seen_section_ids:
                errors.append(
                    _issue(
                        "DUPLICATE_SECTION_ID",
                        section_location,
                        "duplicate section_id %s" % section_id,
                    )
                )
            seen_section_ids.add(section_id)

        target_slots = _list_of_str(section.get("target_slots"))
        for slot_id in target_slots:
            if slot_id not in spec_slots:
                errors.append(
                    _issue("UNKNOWN_SLOT", "%s/target_slots" % section_location,
                           "Slot %s does not exist in DocumentSpec" % slot_id)
                )

        for fact_id in _list_of_str(section.get("fact_refs")):
            if fact_id not in declared_fact_ids:
                errors.append(
                    _issue("UNKNOWN_FACT_REF", "%s/fact_refs" % section_location,
                           "fact_ref %s is not declared in facts[]" % fact_id)
                )

        requirements = section.get("requirements")
        target_length: Optional[Dict[str, Any]] = None
        must_include: Optional[List[str]] = None
        if isinstance(requirements, dict):
            candidate_length = requirements.get("target_length")
            if isinstance(candidate_length, dict):
                target_length = candidate_length
                minimum = candidate_length.get("min")
                maximum = candidate_length.get("max")
                if isinstance(minimum, int) and isinstance(maximum, int) and maximum < minimum:
                    errors.append(
                        _issue("TARGET_LENGTH_INVALID", "%s/requirements/target_length" % section_location,
                               "target_length max must be >= min")
                    )
            if isinstance(requirements.get("must_include"), list):
                must_include = _list_of_str(requirements["must_include"])

        for slot_id in target_slots:
            previous = slot_requirements.get(slot_id)
            current = {"section_id": section_id, "target_length": target_length,
                       "must_include": must_include}
            if previous is not None:
                if (
                    previous["target_length"] is not None
                    and target_length is not None
                    and previous["target_length"] != target_length
                ):
                    errors.append(
                        _issue(
                            "SECTION_REQUIREMENT_CONFLICT",
                            "sections/%s" % section_id,
                            "slot %s has contradicting target_length in %s and %s"
                            % (slot_id, previous["section_id"], section_id),
                        )
                    )
                if (
                    previous["must_include"] is not None
                    and must_include is not None
                    and set(previous["must_include"]) != set(must_include)
                ):
                    errors.append(
                        _issue(
                            "SECTION_REQUIREMENT_CONFLICT",
                            "sections/%s" % section_id,
                            "slot %s has contradicting must_include in %s and %s"
                            % (slot_id, previous["section_id"], section_id),
                        )
                    )
            else:
                slot_requirements[slot_id] = current

    claimed_by: Dict[str, str] = {}
    for fact in facts:
        fact_id = fact.get("fact_id")
        fact_location = "facts/%s" % fact_id
        source = fact.get("source")
        if not isinstance(source, str) or not source.strip():
            errors.append(
                _issue("FACT_SOURCE_MISSING", fact_location, "Fact %s has no source" % fact_id)
            )
        else:
            marker = source.strip().upper()
            if marker in _SOURCE_MARKERS and fact.get("verification_status") != marker:
                errors.append(
                    _issue(
                        "FACT_STATUS_MISMATCH",
                        "%s/verification_status" % fact_location,
                        "source %s requires verification_status %s" % (marker, marker),
                    )
                )

        for slot_id in _list_of_str(fact.get("used_by_slots")):
            if slot_id not in spec_slots:
                errors.append(
                    _issue("UNKNOWN_SLOT", "%s/used_by_slots" % fact_location,
                           "Fact %s references unknown slot %s" % (fact_id, slot_id))
                )
                continue
            owner = claimed_by.get(slot_id)
            if owner is not None and owner != fact_id:
                errors.append(
                    _issue(
                        "FACT_SLOT_CONFLICT",
                        "%s/used_by_slots" % fact_location,
                        "slot %s is claimed by both %s and %s" % (slot_id, owner, fact_id),
                    )
                )
            else:
                claimed_by[slot_id] = fact_id

    completeness = plan.get("completeness")
    if isinstance(completeness, dict):
        required = _list_of_str(completeness.get("required_slots"))
        optional = _list_of_str(completeness.get("optional_slots"))
        required_set = set(required)

        for slot_id in required:
            if slot_id not in spec_slots:
                errors.append(
                    _issue("UNKNOWN_SLOT", "completeness/required_slots",
                           "Slot %s does not exist in DocumentSpec" % slot_id)
                )
        for slot_id in optional:
            if slot_id not in spec_slots:
                errors.append(
                    _issue("UNKNOWN_SLOT", "completeness/optional_slots",
                           "Slot %s does not exist in DocumentSpec" % slot_id)
                )
        for slot_id in sorted(required_set & set(optional)):
            errors.append(
                _issue("REQUIRED_OPTIONAL_OVERLAP", "completeness",
                       "slot %s is both required and optional" % slot_id)
            )

        for item in completeness.get("allow_missing", []) or []:
            if not isinstance(item, dict):
                continue
            slot_id = item.get("slot_id")
            if slot_id not in required_set:
                errors.append(
                    _issue("ALLOW_MISSING_NOT_REQUIRED", "completeness/allow_missing",
                           "allow_missing entry %s is not a required slot" % slot_id)
                )
            reason = item.get("reason")
            if not isinstance(reason, str) or not reason.strip():
                errors.append(
                    _issue("ALLOW_MISSING_NO_REASON", "completeness/allow_missing",
                           "allow_missing entry %s has no reason" % slot_id)
                )

        covered = required_set | set(optional)
        for slot_id in slot_requirements:
            if slot_id not in covered:
                warnings.append(
                    _issue(
                        "COMPLETENESS_UNCOVERED_SLOT",
                        "completeness",
                        "targeted slot %s is neither required nor optional" % slot_id,
                        default_severity="low",
                    )
                )


# ---------------------------------------------------------------------------
# FillPlan
# ---------------------------------------------------------------------------


def validate_fill_plan(
    plan: Any,
    spec: Dict[str, Any],
    content_plan: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Schema validation plus Contract 03 §3 rules and DocumentSpec cross-checks."""
    errors = _schema_issues(plan, FILL_PLAN_SCHEMA, "INVALID_FILL_PLAN")
    warnings: List[Dict[str, Any]] = []
    if isinstance(plan, dict):
        _check_fill_plan(plan, spec, content_plan, errors, warnings)
    return {"passed": not errors, "errors": errors, "warnings": warnings}


def _check_fill_plan(
    plan: Dict[str, Any],
    spec: Dict[str, Any],
    content_plan: Optional[Dict[str, Any]],
    errors: List[Dict[str, Any]],
    warnings: List[Dict[str, Any]],
) -> None:
    template = spec.get("template") if isinstance(spec.get("template"), dict) else {}
    fingerprint = spec.get("fingerprint_ref") if isinstance(spec.get("fingerprint_ref"), dict) else {}
    spec_slots: Dict[str, Dict[str, Any]] = {}
    for slot in spec.get("slots", []) or []:
        if isinstance(slot, dict) and isinstance(slot.get("slot_id"), str):
            spec_slots[slot["slot_id"]] = slot

    baseline = plan.get("baseline") if isinstance(plan.get("baseline"), dict) else {}

    if plan.get("template_id") != template.get("template_id"):
        errors.append(
            _issue("TEMPLATE_ID_MISMATCH", "template_id",
                   "FillPlan template_id %r does not match DocumentSpec %r"
                   % (plan.get("template_id"), template.get("template_id")))
        )
    if baseline.get("template_sha256") != template.get("template_sha256"):
        errors.append(
            _issue("TEMPLATE_SHA_MISMATCH", "baseline/template_sha256",
                   "Declared %r does not match actual %r"
                   % (baseline.get("template_sha256"), template.get("template_sha256")))
        )
    if baseline.get("fingerprint_id") != fingerprint.get("fingerprint_id"):
        errors.append(
            _issue("FINGERPRINT_MISMATCH", "baseline/fingerprint_id",
                   "fingerprint_id %r does not match DocumentSpec %r"
                   % (baseline.get("fingerprint_id"), fingerprint.get("fingerprint_id")))
        )

    allowed = _list_of_str(baseline.get("allowed_slot_ids"))
    allowed_set = set(allowed)
    for slot_id in allowed:
        if slot_id not in spec_slots:
            errors.append(
                _issue("UNKNOWN_SLOT", "baseline/allowed_slot_ids",
                       "Slot %s does not exist in DocumentSpec" % slot_id)
            )

    operations = [op for op in plan.get("operations", []) or [] if isinstance(op, dict)]

    op_ids: List[str] = [op["op_id"] for op in operations if isinstance(op.get("op_id"), str)]
    sequences: List[Any] = [op.get("sequence") for op in operations]
    for op_id in sorted({item for item in op_ids if op_ids.count(item) > 1}):
        errors.append(_issue("DUPLICATE_OP_ID", "operations", "duplicate op_id %s" % op_id))
    for sequence in sorted(
        {item for item in sequences if sequences.count(item) > 1}, key=lambda value: str(value)
    ):
        errors.append(
            _issue("DUPLICATE_SEQUENCE", "operations", "duplicate operation sequence %r" % (sequence,))
        )

    sequences_by_id: Dict[str, Any] = {
        op.get("op_id"): op.get("sequence")
        for op in operations
        if isinstance(op.get("op_id"), str)
    }

    facts_by_id: Dict[str, Dict[str, Any]] = {}
    if isinstance(content_plan, dict):
        for fact in content_plan.get("facts", []) or []:
            if isinstance(fact, dict) and isinstance(fact.get("fact_id"), str):
                facts_by_id[fact["fact_id"]] = fact

    for operation in operations:
        _check_operation(
            operation, spec, spec_slots, allowed_set, facts_by_id,
            content_plan, sequences_by_id, errors, warnings,
        )

    policy = plan.get("global_policy") if isinstance(plan.get("global_policy"), dict) else {}
    if policy.get("allow_structure_change") is not False:
        errors.append(
            _issue("FORMAT_REPAIR_FORBIDDEN", "global_policy/allow_structure_change",
                   "allow_structure_change must be false in FillPlan 4.0")
        )

    if isinstance(content_plan, dict):
        _check_against_content_plan(
            plan, operations, spec, content_plan, template, errors
        )


def _check_operation(
    operation: Dict[str, Any],
    spec: Dict[str, Any],
    spec_slots: Dict[str, Dict[str, Any]],
    allowed_set: set[str],
    facts_by_id: Dict[str, Dict[str, Any]],
    content_plan: Optional[Dict[str, Any]],
    sequences_by_id: Dict[str, Any],
    errors: List[Dict[str, Any]],
    warnings: List[Dict[str, Any]],
) -> None:
    op_id = operation.get("op_id")
    location = "operations/%s" % op_id
    target = operation.get("target") if isinstance(operation.get("target"), dict) else {}
    target_location = target.get("location_id")
    slot_id = operation.get("slot_id")
    slot = spec_slots.get(slot_id)

    if slot is None:
        errors.append(
            _issue("UNKNOWN_SLOT", location,
                   "Slot %r does not exist in DocumentSpec" % (slot_id,))
        )
        return

    if slot_id not in allowed_set:
        errors.append(
            _issue("UNAUTHORIZED_SLOT_TARGET", location,
                   "Slot %s is outside baseline.allowed_slot_ids" % slot_id)
        )

    if target_location != slot.get("location_id"):
        errors.append(
            _issue("TARGET_LOCATION_MISMATCH", "%s/target/location_id" % location,
                   "target location %r does not equal slot location %r"
                   % (target_location, slot.get("location_id")))
        )

    if slot.get("protection_status") == "PROTECTED":
        errors.append(
            _issue("PROTECTED_SLOT_VIOLATION", location,
                   "Operation %s targets protected slot %s" % (op_id, slot_id))
        )
    _check_protected_regions(spec, target_location, op_id, location, errors, warnings)

    preconditions = _list_of_str(operation.get("preconditions"))
    for check in preconditions:
        if check not in ALLOWED_PRECONDITIONS:
            errors.append(
                _issue("PRECONDITION_INVALID", "%s/preconditions" % location,
                       "unknown precondition %r" % check)
            )
    missing_checks = [check for check in MANDATORY_PRECONDITIONS if check not in preconditions]
    if missing_checks:
        errors.append(
            _issue("PRECONDITION_MISSING", "%s/preconditions" % location,
                   "STRICT operation is missing preconditions: %s" % ", ".join(missing_checks))
        )

    source_ref = operation.get("source_ref")
    if not isinstance(source_ref, str) or not source_ref.strip():
        errors.append(
            _issue("SOURCE_REF_MISSING", "%s/source_ref" % location,
                   "Operation %s has no source_ref" % op_id)
        )
        source_ref = None
    else:
        source_ref = source_ref.strip()
        if source_ref not in ("USER_INPUT", "IMAGE_INPUT") and not _FACT_ID_RE.match(source_ref):
            errors.append(
                _issue("SOURCE_REF_INVALID", "%s/source_ref" % location,
                       "source_ref %r is neither USER_INPUT, IMAGE_INPUT nor a fact id" % source_ref)
            )

    value = operation.get("value")
    if isinstance(value, str) and value == "":
        errors.append(_issue("VALUE_MISSING", "%s/value" % location, "operation value is empty"))

    op_type = operation.get("type")
    if op_type == "fill_cell":
        _check_fill_cell_target(operation, target, target_location, slot, preconditions,
                                op_id, location, errors)
    elif op_type == "replace_image":
        if target.get("image_role") not in {"logo", "stamp", "qr", "illustration", "photo"}:
            errors.append(
                _issue("TARGET_INCOMPLETE", "%s/target/image_role" % location,
                       "replace_image requires a valid image_role")
            )

    if source_ref and source_ref in facts_by_id and isinstance(content_plan, dict):
        fact = facts_by_id[source_ref]
        if fact.get("verification_status") != "VERIFIED" and "source_verified" not in preconditions:
            errors.append(
                _issue("PRECONDITION_MISSING", "%s/preconditions" % location,
                       "source_verified is required for unverified fact %s" % source_ref)
            )

    value_ref = operation.get("value_ref")
    if value_ref:
        if content_plan is None:
            errors.append(
                _issue("INVALID_FILL_PLAN", "%s/value_ref" % location,
                       "value_ref %s cannot be verified without a ContentPlan" % value_ref)
            )
        elif value_ref not in facts_by_id:
            errors.append(
                _issue("UNKNOWN_FACT_REF", "%s/value_ref" % location,
                       "value_ref %s is not declared in ContentPlan facts[]" % value_ref)
            )
        else:
            expected = str(facts_by_id[value_ref].get("value"))
            if not isinstance(value, str) or value != expected:
                errors.append(
                    _issue("VALUE_REF_MISMATCH", "%s/value" % location,
                           "value %r does not equal fact %s value %r"
                           % (value, value_ref, expected))
                )

    sequence = operation.get("sequence")
    for dependency in _list_of_str(operation.get("depends_on")):
        if dependency not in sequences_by_id:
            errors.append(
                _issue("UNKNOWN_DEPENDENCY", "%s/depends_on" % location,
                       "depends_on references unknown op %s" % dependency)
            )
        elif isinstance(sequence, int) and isinstance(sequences_by_id[dependency], int):
            if sequences_by_id[dependency] >= sequence:
                errors.append(
                    _issue("DEPENDENCY_ORDER", "%s/depends_on" % location,
                           "depends_on %s must have a lower sequence than %s" % (dependency, op_id))
                )

    _check_overflow(operation, slot, op_id, location, errors)


def _check_fill_cell_target(
    operation: Dict[str, Any],
    target: Dict[str, Any],
    target_location: Any,
    slot: Dict[str, Any],
    preconditions: List[str],
    op_id: Any,
    location: str,
    errors: List[Dict[str, Any]],
) -> None:
    parsed = _parse_table_target(target_location) if isinstance(target_location, str) else None
    if parsed is None:
        errors.append(
            _issue("TARGET_INCOMPLETE", "%s/target" % location,
                   "fill_cell location cannot be parsed into table_id/row/col")
        )
    else:
        for key in ("table_id", "row", "col"):
            if key not in target:
                errors.append(
                    _issue("TARGET_INCOMPLETE", "%s/target/%s" % (location, key),
                           "fill_cell target is missing %s" % key)
                )
            elif target.get(key) != parsed[key]:
                errors.append(
                    _issue("TARGET_FIELD_MISMATCH", "%s/target/%s" % (location, key),
                           "target %s %r does not match location %r"
                           % (key, target.get(key), parsed[key]))
                )

    capacity = slot.get("capacity") if isinstance(slot.get("capacity"), dict) else {}
    hard_limit = capacity.get("hard_limit")
    if isinstance(hard_limit, dict) and "capacity_ok" not in preconditions:
        errors.append(
            _issue("PRECONDITION_MISSING", "%s/preconditions" % location,
                   "fill_cell on a hard-limited slot requires capacity_ok")
        )


def _check_protected_regions(
    spec: Dict[str, Any],
    target_location: Any,
    op_id: Any,
    location: str,
    errors: List[Dict[str, Any]],
    warnings: List[Dict[str, Any]],
) -> None:
    if not isinstance(target_location, str):
        return
    for region in spec.get("protected_regions", []) or []:
        if not isinstance(region, dict):
            continue
        region_location = region.get("location_id")
        if not isinstance(region_location, str):
            continue
        if not (
            target_location == region_location
            or target_location.startswith(region_location + ".")
        ):
            continue
        detail = "Operation %s falls inside protected region %s (%s)" % (
            op_id, region.get("region_id"), region_location
        )
        if region.get("severity") == "warning":
            warnings.append(
                _issue("PROTECTED_REGION_WARNING", location, detail, default_severity="medium")
            )
        else:
            errors.append(_issue("PROTECTED_SLOT_VIOLATION", location, detail))


def _check_overflow(
    operation: Dict[str, Any],
    slot: Dict[str, Any],
    op_id: Any,
    location: str,
    errors: List[Dict[str, Any]],
) -> None:
    overflow = operation.get("overflow") if isinstance(operation.get("overflow"), dict) else {}
    measured = overflow.get("measured_chars")
    limit_source = overflow.get("limit_source")
    limit_value = overflow.get("limit_value")
    capacity = slot.get("capacity") if isinstance(slot.get("capacity"), dict) else {}
    hard_limit = capacity.get("hard_limit")

    if isinstance(hard_limit, dict):
        limit = hard_limit.get("value")
        if limit_source != hard_limit.get("kind") or limit_value != limit:
            errors.append(
                _issue(
                    "OVERFLOW_LIMIT_MISMATCH",
                    "%s/overflow" % location,
                    "overflow limit %r/%r does not match slot hard_limit %r/%r"
                    % (limit_source, limit_value, hard_limit.get("kind"), limit),
                )
            )
        if isinstance(measured, int) and isinstance(limit, int) and measured > limit:
            errors.append(
                _issue("CAPACITY_EXCEEDED", "%s/overflow" % location,
                       "Operation %s measured %d > limit %d" % (op_id, measured, limit))
            )
        return

    if limit_source != "none":
        errors.append(
            _issue("OVERFLOW_LIMIT_MISMATCH", "%s/overflow" % location,
                   "slot %s has no hard_limit but overflow declares %r"
                   % (slot.get("slot_id"), limit_source))
        )
        if isinstance(measured, int) and isinstance(limit_value, int) and measured > limit_value:
            errors.append(
                _issue("CAPACITY_EXCEEDED", "%s/overflow" % location,
                       "Operation %s measured %d > limit %d" % (op_id, measured, limit_value))
            )


def _check_against_content_plan(
    plan: Dict[str, Any],
    operations: List[Dict[str, Any]],
    spec: Dict[str, Any],
    content_plan: Dict[str, Any],
    template: Dict[str, Any],
    errors: List[Dict[str, Any]],
) -> None:
    if content_plan.get("template_id") != template.get("template_id"):
        errors.append(
            _issue("TEMPLATE_ID_MISMATCH", "content_plan/template_id",
                   "ContentPlan template_id %r does not match DocumentSpec %r"
                   % (content_plan.get("template_id"), template.get("template_id")))
        )

    op_slots = {
        operation.get("slot_id") for operation in operations
        if isinstance(operation.get("slot_id"), str)
    }
    completeness = content_plan.get("completeness")
    required = _list_of_str(completeness.get("required_slots")) if isinstance(completeness, dict) else []
    allow_missing = set()
    if isinstance(completeness, dict):
        for item in completeness.get("allow_missing", []) or []:
            if isinstance(item, dict) and isinstance(item.get("slot_id"), str):
                allow_missing.add(item["slot_id"])

    for slot_id in required:
        if slot_id in allow_missing:
            continue
        if slot_id not in op_slots:
            errors.append(
                _issue("REQUIRED_SLOT_MISSING", "operations",
                       "required slot %s has no operation and no allow_missing entry" % slot_id)
            )

    targeted: set[str] = set()
    for section in content_plan.get("sections", []) or []:
        if isinstance(section, dict):
            targeted.update(_list_of_str(section.get("target_slots")))

    facts = [fact for fact in content_plan.get("facts", []) or [] if isinstance(fact, dict)]
    for fact in facts:
        fact_id = fact.get("fact_id")
        for slot_id in _list_of_str(fact.get("used_by_slots")):
            if slot_id not in targeted:
                continue
            matched = any(
                operation.get("slot_id") == slot_id and operation.get("value_ref") == fact_id
                for operation in operations
            )
            if not matched:
                errors.append(
                    _issue("FACT_OPERATION_MISSING", "operations",
                           "targeted slot %s has fact %s but no value_ref operation"
                           % (slot_id, fact_id))
                )
