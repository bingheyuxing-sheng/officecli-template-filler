# -*- coding: utf-8 -*-
"""Deterministic builders for ContentPlan 4.0 and FillPlan 4.0 (Contract 03).

The builders are pure functions: they never read or write DOCX content, never
call a model, and never invent facts, sources, or values.  Anything the caller
does not supply is left missing so that validation can report it.
"""

from __future__ import annotations

import copy
import re
from typing import Any, Dict, List, Optional

SCHEMA_VERSION = "4.0"

DENY_OPERATIONS: tuple[str, ...] = (
    "modify_page_margin",
    "modify_section_properties",
    "modify_global_styles",
    "rebuild_table",
    "move_existing_image",
    "delete_protected_content",
    "insert_row",
    "insert_paragraph",
    "merge_cells",
)

SECTION_FIELDS: tuple[str, ...] = (
    "section_id",
    "purpose",
    "target_slots",
    "requirements",
    "source_refs",
    "fact_refs",
)

IMAGE_ROLES: frozenset[str] = frozenset({"logo", "stamp", "qr", "illustration", "photo"})
IMAGE_TOKEN_TEXTS: frozenset[str] = frozenset({"***", "___"})
PARAGRAPH_CANDIDATE_TYPES: frozenset[str] = frozenset({"red_run_clue", "internal_fact"})

# Greedy ``.*`` picks the *last* ``.tbl[n].r[r].c[c]`` segment, so a slot located
# inside a nested table targets the nested table instead of the outer one.
_TABLE_TARGET_RE = re.compile(
    r"^(?P<table_id>.*\.tbl\[[0-9]+\])\.r\[(?P<row>[0-9]+)\]\.c\[(?P<col>[0-9]+)\]"
)


def _spec_template(spec: Dict[str, Any]) -> Dict[str, Any]:
    template = spec.get("template")
    if not isinstance(template, dict):
        raise ValueError("DocumentSpec is missing the template block")
    return template


def _unique(items: List[str]) -> List[str]:
    result: List[str] = []
    for item in items:
        if item not in result:
            result.append(item)
    return result


def _copy_section(section: Dict[str, Any]) -> Dict[str, Any]:
    return {
        field: copy.deepcopy(section[field])
        for field in SECTION_FIELDS
        if field in section
    }


def _parse_table_target(location_id: str) -> Optional[Dict[str, Any]]:
    """Split ``body.tbl[n].r[r].c[c]...`` into table_id / row / col.

    For ``body.tbl[0].r[0].c[0].tbl[0].r[1].c[1].p[0]`` the resolved table_id is
    the nested ``body.tbl[0].r[0].c[0].tbl[0]`` — the innermost table segment.
    """
    match = _TABLE_TARGET_RE.match(location_id or "")
    if match is None:
        return None
    return {
        "table_id": match.group("table_id"),
        "row": int(match.group("row")),
        "col": int(match.group("col")),
    }


def _is_image_slot(spec: Dict[str, Any], slot: Dict[str, Any]) -> bool:
    image_locations = {
        image.get("location_id")
        for image in spec.get("structure", {}).get("images", [])
        if isinstance(image, dict)
    }
    return (
        slot.get("location_id") in image_locations
        or slot.get("semantic_role") in IMAGE_ROLES
    )


def _resolve_slot_value(
    spec: Dict[str, Any],
    slot: Dict[str, Any],
    fact: Optional[Dict[str, Any]],
    values_by_slot: Optional[Dict[str, str]],
    images_by_slot: Optional[Dict[str, str]],
) -> Optional[Dict[str, Any]]:
    slot_id = slot["slot_id"]
    if isinstance(fact, dict) and "value" in fact:
        fact_id = fact.get("fact_id")
        if not isinstance(fact_id, str) or not fact_id:
            raise ValueError("fact bound to slot %s has no fact_id" % slot_id)
        return {
            "value": str(fact["value"]),
            "source_ref": fact_id,
            "value_ref": fact_id,
            "is_image": False,
        }
    if values_by_slot and slot_id in values_by_slot:
        return {
            "value": str(values_by_slot[slot_id]),
            "source_ref": "USER_INPUT",
            "value_ref": None,
            "is_image": False,
        }
    if images_by_slot and slot_id in images_by_slot and _is_image_slot(spec, slot):
        return {
            "value": str(images_by_slot[slot_id]),
            "source_ref": "IMAGE_INPUT",
            "value_ref": None,
            "is_image": True,
        }
    return None


def _operation_type(slot: Dict[str, Any], is_image: bool) -> str:
    location_id = slot.get("location_id") or ""
    if ".tbl[" in location_id:
        return "fill_cell"
    if is_image:
        return "replace_image"
    if (
        slot.get("candidate_type") == "explicit_token"
        and slot.get("matched_text") in IMAGE_TOKEN_TEXTS
    ):
        return "fill_paragraph"
    if slot.get("candidate_type") in PARAGRAPH_CANDIDATE_TYPES:
        return "fill_paragraph"
    return "replace_text"


def _hard_limit(slot: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    capacity = slot.get("capacity")
    if not isinstance(capacity, dict):
        return None
    hard_limit = capacity.get("hard_limit")
    return hard_limit if isinstance(hard_limit, dict) else None


def _preconditions(slot: Dict[str, Any], fact: Optional[Dict[str, Any]]) -> List[str]:
    checks = ["slot_exists", "not_protected"]
    if _hard_limit(slot) is not None:
        checks.append("capacity_ok")
    if isinstance(fact, dict) and fact.get("verification_status") != "VERIFIED":
        checks.append("source_verified")
    checks.append("template_sha_match")
    return checks


def _overflow(slot: Dict[str, Any], op_type: str, value: str) -> Dict[str, Any]:
    hard_limit = _hard_limit(slot)
    if hard_limit is not None:
        limit_source: str = hard_limit.get("kind", "none")
        limit_value: Optional[int] = hard_limit.get("value")
    else:
        limit_source = "none"
        limit_value = None
    return {
        "measured_chars": 0 if op_type == "replace_image" else len(value),
        "limit_source": limit_source,
        "limit_value": limit_value,
        "strategy": "REJECT",
    }


def build_content_plan(
    spec: Dict[str, Any],
    *,
    plan_id: str,
    sections: List[Dict[str, Any]],
    facts: Optional[List[Dict[str, Any]]] = None,
    required_slots: Optional[List[str]] = None,
    optional_slots: Optional[List[str]] = None,
    allow_missing: Optional[List[Dict[str, str]]] = None,
) -> Dict[str, Any]:
    """Build a ContentPlan 4.0 from a DocumentSpec 4.0.

    ``sections`` items carry ``section_id``, ``purpose``, ``target_slots`` and
    optionally ``requirements``, ``source_refs``, ``fact_refs``.  Facts are
    copied verbatim from the caller-provided SSOT; nothing is derived.
    By default ``required_slots`` is the ordered union of every section's
    ``target_slots``; ``optional_slots`` and ``allow_missing`` default to [].
    """
    template_id = _spec_template(spec).get("template_id")
    if not isinstance(template_id, str) or not template_id:
        raise ValueError("DocumentSpec is missing template.template_id")

    sections_out: List[Dict[str, Any]] = []
    target_slot_union: List[str] = []
    for section in sections:
        if not isinstance(section, dict):
            raise ValueError("section entries must be objects")
        sections_out.append(_copy_section(section))
        for slot_id in section.get("target_slots", []) or []:
            if slot_id not in target_slot_union:
                target_slot_union.append(slot_id)

    if required_slots is None:
        required = target_slot_union
    else:
        required = list(required_slots)

    return {
        "schema_version": SCHEMA_VERSION,
        "plan_id": plan_id,
        "template_id": template_id,
        "sections": sections_out,
        "facts": copy.deepcopy(list(facts or [])),
        "completeness": {
            "required_slots": required,
            "optional_slots": list(optional_slots or []),
            "allow_missing": copy.deepcopy(list(allow_missing or [])),
        },
    }


def build_fill_plan(
    spec: Dict[str, Any],
    content_plan: Dict[str, Any],
    *,
    task_id: str,
    mode: str = "STRICT",
    values_by_slot: Optional[Dict[str, str]] = None,
    images_by_slot: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Build a schema-shaped FillPlan 4.0 from a DocumentSpec and ContentPlan.

    Value precedence per slot: fact bound through ``used_by_slots`` ->
    ``values_by_slot`` literal -> ``images_by_slot`` image -> skip.  A skipped
    required slot stays missing; the incomplete plan is reported by
    :func:`content_intelligence.plan_validator.validate_fill_plan`.
    """
    template = _spec_template(spec)
    template_sha256 = template.get("template_sha256")
    if not isinstance(template_sha256, str) or not template_sha256:
        raise ValueError("DocumentSpec is missing template.template_sha256")
    fingerprint = spec.get("fingerprint_ref")
    if not isinstance(fingerprint, dict) or not fingerprint.get("fingerprint_id"):
        raise ValueError("DocumentSpec is missing fingerprint_ref.fingerprint_id")

    slots: Dict[str, Dict[str, Any]] = {}
    for slot in spec.get("slots", []) or []:
        if isinstance(slot, dict) and isinstance(slot.get("slot_id"), str):
            slots[slot["slot_id"]] = slot

    fact_by_slot: Dict[str, Dict[str, Any]] = {}
    for fact in content_plan.get("facts", []) or []:
        if not isinstance(fact, dict):
            continue
        for slot_id in fact.get("used_by_slots", []) or []:
            fact_by_slot.setdefault(slot_id, fact)

    operations: List[Dict[str, Any]] = []
    allowed_slots: List[str] = []
    emitted: set[str] = set()

    for section in content_plan.get("sections", []) or []:
        if not isinstance(section, dict):
            continue
        target_slots = section.get("target_slots")
        if not isinstance(target_slots, list):
            continue
        for slot_id in target_slots:
            if slot_id in emitted:
                continue
            slot = slots.get(slot_id)
            if slot is None:
                continue
            resolved = _resolve_slot_value(
                spec,
                slot,
                fact_by_slot.get(slot_id),
                values_by_slot,
                images_by_slot,
            )
            if resolved is None:
                continue

            op_type = _operation_type(slot, resolved["is_image"])
            target: Dict[str, Any] = {"location_id": slot["location_id"]}
            if op_type == "fill_cell":
                parsed = _parse_table_target(slot["location_id"])
                if parsed is None:
                    raise ValueError(
                        "slot %s has a table location that cannot be parsed: %s"
                        % (slot_id, slot["location_id"])
                    )
                target.update(parsed)
            elif op_type == "replace_image":
                target["image_role"] = "illustration"

            sequence = len(operations) + 1
            operation: Dict[str, Any] = {
                "op_id": "OP_%03d" % sequence,
                "sequence": sequence,
                "type": op_type,
                "slot_id": slot_id,
                "target": target,
                "source_ref": resolved["source_ref"],
                "value": resolved["value"],
                "policy": "STRICT",
                "preconditions": _preconditions(slot, fact_by_slot.get(slot_id)),
                "overflow": _overflow(slot, op_type, resolved["value"]),
            }
            if resolved["value_ref"]:
                operation["value_ref"] = resolved["value_ref"]

            operations.append(operation)
            emitted.add(slot_id)
            allowed_slots.append(slot_id)

    return {
        "schema_version": SCHEMA_VERSION,
        "task_id": task_id,
        "template_id": template.get("template_id"),
        "mode": mode,
        "baseline": {
            "template_sha256": template_sha256,
            "spec_schema_version": SCHEMA_VERSION,
            "fingerprint_id": fingerprint["fingerprint_id"],
            "allowed_slot_ids": allowed_slots,
        },
        "operations": operations,
        "global_policy": {
            "allow_structure_change": False,
            "deny_operations": list(DENY_OPERATIONS),
            "styles": "DENY",
            "page_setup": "DENY",
        },
    }
