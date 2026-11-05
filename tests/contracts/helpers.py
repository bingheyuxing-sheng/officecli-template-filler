# -*- coding: utf-8 -*-
"""Shared loaders, reference algorithms and semantic checkers for W0 contracts."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_DIR = ROOT / "schemas"
EXAMPLE_DIR = ROOT / "examples"
CONFIG_DIR = ROOT / "config"

SCHEMAS = {
    "document_spec": SCHEMA_DIR / "document_spec-4.0.schema.json",
    "document_spec_legacy": SCHEMA_DIR / "document_spec-legacy-3.0.schema.json",
    "document_spec_legacy_cli": SCHEMA_DIR / "document_spec-legacy-cli.schema.json",
    "content_plan": SCHEMA_DIR / "content_plan-4.0.schema.json",
    "fill_plan": SCHEMA_DIR / "fill_plan-4.0.schema.json",
    "qa_report": SCHEMA_DIR / "qa_report-4.0.schema.json",
    "tool_envelope": SCHEMA_DIR / "tool_envelope-4.0.schema.json",
    "error_registry": SCHEMA_DIR / "error_code_registry-4.0.schema.json",
}

SLOT_ID_RE = re.compile(r"^S_[0-9a-f]{12}(-c[2-9][0-9]*)?$")
SLOT_KEY_RE = re.compile(r"^[0-9a-f]{16}$")
LOCATION_RE = re.compile(
    r"^(body|footnotes|endnotes|comments|sec\[[0-9]+\]\."
    r"(header|footer|first_page_header|first_page_footer|even_page_header|even_page_footer))"
    r"(\.[a-z_]+\[[0-9]+\])+$"
)

CHECK_IDS = (
    "PACKAGE",
    "FORMAT",
    "FIDELITY",
    "CONTENT",
    "DATA",
    "VISUAL_PAGE_COUNT",
    "VISUAL_PIXEL",
    "OCR",
    "REVIEW_INTEGRITY",
    "EXCEL_FORMULA",
)


def load_json(path: Path) -> Any:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def schema(name: str) -> Dict[str, Any]:
    return load_json(SCHEMAS[name])


def validator(name: str) -> Draft202012Validator:
    return Draft202012Validator(schema(name))


def schema_errors(name: str, instance: Any) -> List[str]:
    return sorted(error.message for error in validator(name).iter_errors(instance))


def example(contract: str, case_name: str) -> Dict[str, Any]:
    data = load_json(EXAMPLE_DIR / contract / "cases.json")
    return data["cases"][case_name]


def example_document(contract: str, case_name: str) -> Dict[str, Any]:
    return example(contract, case_name)["document"]


def error_registry() -> Dict[str, Dict[str, Any]]:
    data = load_json(CONFIG_DIR / "error-codes.json")
    return {entry["code"]: entry for entry in data["codes"]}


def qa_policy() -> Dict[str, Any]:
    return load_json(CONFIG_DIR / "qa-policy.json")["policies"]


# ---------------------------------------------------------------------------
# Contract 01 reference algorithm (test-only; production implementation is W1)
# ---------------------------------------------------------------------------


def normalize_text(text: str) -> str:
    value = unicodedata.normalize("NFKC", text)
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def slot_id_ref(template_sha256: str, location_id: str, matched_text: str, occurrence: int) -> str:
    canonical = f"v1|{template_sha256}|{location_id}|{normalize_text(matched_text)}|{occurrence}"
    return "S_" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12]


def slot_key_ref(location_id: str, matched_text: str, occurrence: int) -> str:
    canonical = f"v1|{location_id}|{normalize_text(matched_text)}|{occurrence}"
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def validate_slot_inputs(template_sha256: str, location_id: str, matched_text: str, occurrence: int) -> List[str]:
    errors: List[str] = []
    if not re.match(r"^[0-9a-f]{64}$", template_sha256 or ""):
        errors.append("SLOT_TEMPLATE_SHA_INVALID")
    if not LOCATION_RE.match(location_id or ""):
        errors.append("SLOT_LOCATION_INVALID")
    if not isinstance(occurrence, int) or occurrence < 1:
        errors.append("SLOT_OCCURRENCE_INVALID")
    if not normalize_text(matched_text) and matched_text != "":
        errors.append("SLOT_TEXT_EMPTY_UNEVIDENCED")
    return errors


def resolve_collisions(items: Iterable[tuple]) -> List[str]:
    """items: (canonical_string, base_id) -> deterministic suffixed ids."""
    ordered = sorted(items, key=lambda item: item[0])
    result: List[str] = []
    for index, (_canonical, base_id) in enumerate(ordered):
        result.append(base_id if index == 0 else f"{base_id}-c{index + 1}")
    return result


# ---------------------------------------------------------------------------
# Semantic checkers (rules JSON Schema cannot express)
# ---------------------------------------------------------------------------


def semantic_document_spec(doc: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    id_fields = {
        "slot_id": [item["slot_id"] for item in doc.get("slots", [])],
        "region_id": [item["region_id"] for item in doc.get("protected_regions", [])],
        "profile_id": [item["profile_id"] for item in doc.get("capacity_profiles", [])],
        "constraint_id": [item["constraint_id"] for item in doc.get("layout_constraints", [])],
    }
    for field, values in id_fields.items():
        duplicates = {value for value in values if values.count(value) > 1}
        for value in sorted(duplicates):
            errors.append(f"duplicate {field}: {value}")

    template = doc.get("template", {})
    expected_id = "T_" + str(template.get("template_sha256", ""))[:12]
    if template.get("template_id") != expected_id:
        errors.append("template_id does not derive from template_sha256")
    if template.get("parent_sha256") and template.get("parent_sha256") == template.get("template_sha256"):
        errors.append("parent_sha256 equals template_sha256")

    locations = {item["location_id"] for item in doc.get("structure", {}).get("paragraphs", [])}
    locations |= {item["table_id"] for item in doc.get("structure", {}).get("tables", [])}
    for slot in doc.get("slots", []):
        if slot["location_id"] not in locations:
            errors.append(f"slot location not in structure: {slot['slot_id']}")
        if slot.get("protection_status") == "PROTECTED" and slot.get("confirmation_tier") != "PROTECTED_DO_NOT_TOUCH":
            errors.append(f"protected slot tier mismatch: {slot['slot_id']}")
        if slot.get("candidate_type") == "internal_fact" and slot.get("confirmation_tier") != "MUST_ASK_USER":
            errors.append(f"internal_fact tier mismatch: {slot['slot_id']}")
        if slot.get("candidate_type") == "control_or_field" and slot.get("protection_status") != "PROTECTED":
            errors.append(f"control_or_field not protected: {slot['slot_id']}")
        if slot["span"]["end"] <= slot["span"]["start"]:
            errors.append(f"slot span inverted: {slot['slot_id']}")

    if doc.get("errors"):
        errors.append("DocumentSpec errors array is non-empty")

    fingerprint = doc.get("fingerprint_ref", {})
    for key in ("structural_hash", "style_hash", "protected_hash", "layout_hash"):
        value = str(fingerprint.get(key, ""))
        if len(value) != 64 or set(value) == {"0"}:
            errors.append(f"fingerprint hash invalid: {key}")
    return errors


def semantic_content_plan(plan: Dict[str, Any], spec: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    slot_ids = {slot["slot_id"] for slot in spec.get("slots", [])}
    fact_ids = {fact["fact_id"] for fact in plan.get("facts", [])}
    section_ids = [section["section_id"] for section in plan.get("sections", [])]
    if len(section_ids) != len(set(section_ids)):
        errors.append("duplicate section_id")

    for section in plan.get("sections", []):
        for slot_id in section.get("target_slots", []):
            if slot_id not in slot_ids:
                errors.append(f"UNKNOWN_SLOT: {slot_id}")
        for fact_id in section.get("fact_refs", []):
            if fact_id not in fact_ids:
                errors.append(f"unknown fact_ref: {fact_id}")
        target_length = section.get("requirements", {}).get("target_length")
        if isinstance(target_length, dict) and target_length.get("max", 0) < target_length.get("min", 0):
            errors.append(f"target_length max < min: {section['section_id']}")

    for fact in plan.get("facts", []):
        if not str(fact.get("source", "")).strip():
            errors.append(f"FACT_SOURCE_MISSING: {fact['fact_id']}")
        if str(fact.get("source", "")).strip().upper() in ("UNVERIFIED", "MODEL_GENERATED"):
            if fact.get("verification_status") != str(fact.get("source", "")).strip().upper():
                errors.append(f"fact status/source mismatch: {fact['fact_id']}")
        for slot_id in fact.get("used_by_slots", []):
            if slot_id not in slot_ids:
                errors.append(f"fact references unknown slot: {fact['fact_id']} -> {slot_id}")

    completeness = plan.get("completeness", {})
    required = set(completeness.get("required_slots", []))
    optional = set(completeness.get("optional_slots", []))
    if required & optional:
        errors.append("required_slots and optional_slots overlap")
    for item in completeness.get("allow_missing", []):
        if item["slot_id"] not in required:
            errors.append(f"allow_missing not required: {item['slot_id']}")
        if not str(item.get("reason", "")).strip():
            errors.append(f"allow_missing without reason: {item['slot_id']}")
    return errors


def semantic_fill_plan(plan: Dict[str, Any], spec: Dict[str, Any], content: Optional[Dict[str, Any]] = None) -> List[str]:
    errors: List[str] = []
    spec_slots = {slot["slot_id"]: slot for slot in spec.get("slots", [])}
    allowed = set(plan.get("baseline", {}).get("allowed_slot_ids", []))
    if allowed - set(spec_slots):
        errors.append("allowed_slot_ids contains unknown slots")

    op_ids = [op["op_id"] for op in plan.get("operations", [])]
    sequences = [op["sequence"] for op in plan.get("operations", [])]
    if len(op_ids) != len(set(op_ids)):
        errors.append("duplicate op_id")
    if len(sequences) != len(set(sequences)):
        errors.append("duplicate operation sequence")

    facts = {fact["fact_id"]: fact for fact in (content or {}).get("facts", [])}
    sequences_by_id = {op["op_id"]: op["sequence"] for op in plan.get("operations", [])}

    for op in plan.get("operations", []):
        slot_id = op["slot_id"]
        if slot_id not in spec_slots:
            errors.append(f"UNKNOWN_SLOT: {slot_id}")
            continue
        if slot_id not in allowed:
            errors.append(f"UNAUTHORIZED_SLOT_TARGET: {slot_id}")
        slot = spec_slots[slot_id]
        if op["target"]["location_id"] != slot["location_id"]:
            errors.append(f"target location mismatch: {op['op_id']}")
        if not str(op.get("source_ref", "")).strip():
            errors.append(f"SOURCE_REF_MISSING: {op['op_id']}")
        if any(check not in ("slot_exists", "not_protected", "capacity_ok", "source_verified", "template_sha_match")
               for check in op.get("preconditions", [])):
            errors.append(f"unknown precondition: {op['op_id']}")
        if op["type"] == "fill_cell":
            target = op["target"]
            if not all(key in target for key in ("table_id", "row", "col")):
                errors.append(f"fill_cell target incomplete: {op['op_id']}")
        if op["type"] == "replace_image" and "image_role" not in op["target"]:
            errors.append(f"replace_image target missing image_role: {op['op_id']}")
        if not str(op.get("value", "")).strip():
            errors.append(f"operation value empty: {op['op_id']}")

        value_ref = op.get("value_ref")
        if value_ref:
            if not content:
                errors.append(f"value_ref without ContentPlan: {op['op_id']}")
            elif value_ref not in facts:
                errors.append(f"value_ref unknown fact: {value_ref}")
            else:
                expected = str(facts[value_ref]["value"])
                if str(op.get("value")) != expected:
                    errors.append(f"value/value_ref mismatch: {op['op_id']}")

        for dependency in op.get("depends_on", []):
            if dependency not in sequences_by_id:
                errors.append(f"depends_on unknown op: {dependency}")
            elif sequences_by_id[dependency] >= op["sequence"]:
                errors.append(f"depends_on must point to a lower sequence: {op['op_id']}")

        overflow = op.get("overflow", {})
        limit_source = overflow.get("limit_source")
        limit_value = overflow.get("limit_value")
        if limit_source != "none" and isinstance(limit_value, int) and overflow.get("measured_chars", 0) > limit_value:
            errors.append(f"CAPACITY_EXCEEDED: {op['op_id']}")

    policy = plan.get("global_policy", {})
    if policy.get("allow_structure_change") is not False:
        errors.append("structure change must be false")
    return errors


def semantic_qa_report(report: Dict[str, Any], policy: Optional[Dict[str, Any]] = None) -> List[str]:
    errors: List[str] = []
    policies = policy or qa_policy()
    source = report.get("policy_source")
    expected_binding = f"{report.get('task_mode')}/{report.get('gate_mode')}"
    if source != expected_binding:
        errors.append(f"QA_POLICY_SOURCE_MISMATCH: {source} != {expected_binding}")
    if source not in policies:
        errors.append(f"unknown policy_source: {source}")
        expected = set()
    else:
        expected = set(policies[source]["required"])

    required = set(report.get("required_checks", []))
    missing = set(report.get("missing_checks", []))
    if expected and required != expected:
        errors.append("QA_POLICY_OVERRIDE_FORBIDDEN")

    if missing - required:
        errors.append("missing_checks contains non-required checks")

    checks = {check["check_id"]: check for check in report.get("checks", [])}
    for check_id in required:
        if check_id not in checks:
            errors.append(f"required check record missing: {check_id}")
            continue
        if not checks[check_id]["required"]:
            errors.append(f"required flag false for required check: {check_id}")
    for check_id, check in checks.items():
        if check["required"] != (check_id in required):
            errors.append(f"required flag mismatch: {check_id}")

    status = report.get("status")
    all_passed = all(
        checks.get(check_id, {}).get("status") == "PASSED" for check_id in required
    )
    if status == "PASSED":
        if missing:
            errors.append("QA_FALSE_PASS: status PASSED with missing_checks")
        if not all_passed:
            errors.append("QA_FALSE_PASS: not every required check is PASSED")
        if report.get("coverage_gaps"):
            errors.append("QA_FALSE_PASS: coverage_gaps present")
        for issue in report.get("issues", []):
            if issue.get("blocking") or issue.get("severity") == "high":
                errors.append("QA_FALSE_PASS: blocking issue under PASSED")

    for issue in report.get("issues", []):
        if issue.get("blocking") is False and issue.get("severity") == "high":
            errors.append(f"high severity must be blocking: {issue['code']}")
        if issue.get("blocking") and issue.get("code") not in error_registry():
            errors.append(f"unregistered issue code: {issue['code']}")

    if status == "FAILED" and not any(
        issue.get("blocking") or issue.get("severity") == "high" for issue in report.get("issues", [])
    ):
        errors.append("FAILED without a blocking or high issue")

    final = report.get("final", {})
    eligible = final.get("eligible_for_commit")
    strict = str(source or "").endswith("/STRICT")
    if strict:
        expected_eligible = status == "PASSED" and not missing and not report.get("coverage_gaps")
    else:
        expected_eligible = status in ("PASSED", "PENDING_HUMAN_REVIEW", "UNVERIFIED") and not missing
    if eligible != expected_eligible:
        errors.append("QA_ELIGIBILITY_CONTRADICTION")

    for repair in report.get("repairs", []):
        if repair.get("applied") and not repair.get("recheck"):
            errors.append(f"QA_REPAIR_UNVERIFIED: {repair['repair_id']}")
    return errors


def semantic_envelope(envelope: Dict[str, Any], registry: Optional[Dict[str, Any]] = None) -> List[str]:
    errors: List[str] = []
    codes = registry or error_registry()
    for item in envelope.get("warnings", []):
        if item["code"] not in codes:
            errors.append(f"unregistered warning code: {item['code']}")
    for item in envelope.get("errors", []):
        if item["code"] not in codes:
            errors.append(f"unregistered error code: {item['code']}")

    status = envelope.get("status")
    next_action = envelope.get("next_action")
    if status == "SUCCESS" and envelope.get("errors"):
        errors.append("SUCCESS with errors")
    if status == "FAILED" and not any(
        item.get("severity") in ("blocking", "high") for item in envelope.get("errors", [])
    ):
        errors.append("FAILED without blocking/high error")
    if next_action == "COMMIT":
        if status == "SUCCESS":
            pass
        elif status == "UNVERIFIED":
            if envelope.get("data", {}).get("qa_eligible") is not True:
                errors.append("COMMIT without SUCCESS or qa_eligible")
            elif not envelope.get("data", {}).get("missing_checks"):
                errors.append("UNVERIFIED COMMIT without missing_checks disclosure")
        else:
            errors.append("COMMIT without SUCCESS or qa_eligible")
    if next_action == "STOP" and status not in ("BLOCKED", "FAILED"):
        errors.append("STOP without BLOCKED/FAILED")
    if next_action == "ASK_USER" and not (
        status == "NEEDS_CONFIRMATION"
        or any(item.get("human_intervention") for item in envelope.get("errors", []))
    ):
        errors.append("ASK_USER without a human decision")
    if next_action == "RETRY" and not any(item.get("retryable") for item in envelope.get("errors", [])):
        errors.append("RETRY without a retryable error")

    for artifact in envelope.get("artifacts", []):
        path = str(artifact.get("path", ""))
        if ".tmp-" in path or ".pending-" in path:
            errors.append(f"staged path exposed as artifact: {path}")
    return errors
