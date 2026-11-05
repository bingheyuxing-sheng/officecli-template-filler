# -*- coding: utf-8 -*-
"""W1-C tests: ContentPlan / FillPlan builders and validators (Contract 03)."""

from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from content_intelligence import (
    build_content_plan,
    build_fill_plan,
    validate_content_plan,
    validate_fill_plan,
)

ROOT = Path(__file__).resolve().parents[1]

SLOT_NAME = "S_d6df35f1e6cd"      # body.p[0], explicit_token
SLOT_BODY = "S_5abf927e8f5e"      # body.p[2], explicit_token
SLOT_TABLE = "S_42824f695c11"     # body.tbl[1].r[2].c[1].p[0], hard limit 40
SLOT_IMAGE = "S_744ef06dee9d"     # body.p[5], red_run_clue + image


def _load_spec() -> dict:
    with open(ROOT / "examples" / "document-spec" / "cases.json", encoding="utf-8") as handle:
        return json.load(handle)["cases"]["full_valid"]["document"]


def _sections() -> list[dict]:
    return [
        {
            "section_id": "SEC_001",
            "purpose": "项目概述",
            "target_slots": [SLOT_NAME, SLOT_BODY],
            "requirements": {
                "must_include": ["项目名称"],
                "target_length": {"min": 10, "max": 200},
                "min_sources": 1,
            },
            "source_refs": ["SRC_001"],
            "fact_refs": ["F_001"],
        },
        {
            "section_id": "SEC_002",
            "purpose": "预算金额",
            "target_slots": [SLOT_TABLE],
            "fact_refs": ["F_002"],
        },
        {
            "section_id": "SEC_003",
            "purpose": "配图",
            "target_slots": [SLOT_IMAGE],
        },
    ]


def _facts() -> list[dict]:
    return [
        {
            "fact_id": "F_001",
            "label": "项目名称",
            "value": "示例项目",
            "unit": "none",
            "source": "USER_INPUT",
            "verification_status": "VERIFIED",
            "used_by_slots": [SLOT_NAME],
        },
        {
            "fact_id": "F_002",
            "label": "合计金额",
            "value": 120000,
            "unit": "yuan",
            "source": "budget.xlsx!Sheet1!B2",
            "verification_status": "VERIFIED",
            "used_by_slots": [SLOT_TABLE],
        },
    ]


def _values() -> dict:
    return {SLOT_BODY: "本项目面向区域产业升级需求，建设必要性包括技术迭代与人才培养。"}


def _images() -> dict:
    return {SLOT_IMAGE: "assets/flow.png"}


def _codes(result: dict) -> list[str]:
    return [error["code"] for error in result["errors"]]


class ContentPlanBuilderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.spec = _load_spec()

    def _build(self, **overrides) -> dict:
        arguments = {
            "plan_id": "CP_001",
            "sections": _sections(),
            "facts": _facts(),
        }
        arguments.update(overrides)
        return build_content_plan(self.spec, **arguments)

    def test_build_is_schema_valid_and_deterministic(self) -> None:
        plan = self._build()
        self.assertEqual(plan["schema_version"], "4.0")
        self.assertEqual(plan["template_id"], self.spec["template"]["template_id"])
        result = validate_content_plan(plan, self.spec)
        self.assertTrue(result["passed"], result["errors"])
        self.assertEqual(result["errors"], [])
        self.assertEqual(plan, self._build())

    def test_completeness_defaults_follow_section_order(self) -> None:
        plan = self._build()
        self.assertEqual(
            plan["completeness"]["required_slots"],
            [SLOT_NAME, SLOT_BODY, SLOT_TABLE, SLOT_IMAGE],
        )
        self.assertEqual(plan["completeness"]["optional_slots"], [])
        self.assertEqual(plan["completeness"]["allow_missing"], [])

        explicit = self._build(
            required_slots=[SLOT_NAME],
            optional_slots=[SLOT_BODY, SLOT_IMAGE],
        )
        self.assertEqual(explicit["completeness"]["required_slots"], [SLOT_NAME])
        self.assertEqual(explicit["completeness"]["optional_slots"], [SLOT_BODY, SLOT_IMAGE])
        result = validate_content_plan(explicit, self.spec)
        self.assertTrue(result["passed"], result["errors"])

    def test_missing_fact_source_is_reported(self) -> None:
        facts = copy.deepcopy(_facts())
        facts[0]["source"] = "   "
        plan = self._build(facts=facts)
        result = validate_content_plan(plan, self.spec)
        self.assertFalse(result["passed"])
        self.assertIn("FACT_SOURCE_MISSING", _codes(result))

    def test_unknown_slot_is_reported(self) -> None:
        plan = self._build(
            sections=[{"section_id": "SEC_009", "purpose": "未知", "target_slots": ["S_deadbeef0000"]}],
            facts=[],
        )
        result = validate_content_plan(plan, self.spec)
        self.assertFalse(result["passed"])
        self.assertIn("UNKNOWN_SLOT", _codes(result))

    def test_required_optional_overlap_is_reported(self) -> None:
        plan = self._build()
        plan["completeness"]["optional_slots"] = [SLOT_BODY]
        result = validate_content_plan(plan, self.spec)
        self.assertFalse(result["passed"])
        self.assertIn("REQUIRED_OPTIONAL_OVERLAP", _codes(result))


class FillPlanBuilderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.spec = _load_spec()

    def _content_plan(self, **overrides) -> dict:
        arguments = {"plan_id": "CP_001", "sections": _sections(), "facts": _facts()}
        arguments.update(overrides)
        return build_content_plan(self.spec, **arguments)

    def _fill_plan(self, content_plan: dict | None = None, **overrides) -> dict:
        plan = content_plan or self._content_plan()
        arguments = {
            "task_id": "TASK_W1C_001",
            "mode": "STRICT",
            "values_by_slot": _values(),
            "images_by_slot": _images(),
        }
        arguments.update(overrides)
        return build_fill_plan(self.spec, plan, **arguments)

    def test_build_is_schema_valid_and_deterministic(self) -> None:
        plan = self._fill_plan()
        result = validate_fill_plan(plan, self.spec, self._content_plan())
        self.assertTrue(result["passed"], result["errors"])
        self.assertEqual(result["errors"], [])
        self.assertEqual(plan, self._fill_plan())
        self.assertEqual(plan["schema_version"], "4.0")
        self.assertEqual(plan["mode"], "STRICT")
        self.assertEqual(plan["global_policy"]["allow_structure_change"], False)
        self.assertEqual(plan["global_policy"]["styles"], "DENY")
        self.assertEqual(plan["global_policy"]["page_setup"], "DENY")

    def test_operation_mapping_and_targets(self) -> None:
        plan = self._fill_plan()
        operations = plan["operations"]
        self.assertEqual(len(operations), 4)
        self.assertEqual(
            [operation["type"] for operation in operations],
            ["replace_text", "replace_text", "fill_cell", "replace_image"],
        )
        self.assertEqual([operation["sequence"] for operation in operations], [1, 2, 3, 4])
        self.assertEqual(
            [operation["op_id"] for operation in operations],
            ["OP_001", "OP_002", "OP_003", "OP_004"],
        )
        self.assertEqual(
            [operation["slot_id"] for operation in operations],
            [SLOT_NAME, SLOT_BODY, SLOT_TABLE, SLOT_IMAGE],
        )

        table = operations[2]
        self.assertEqual(
            table["target"],
            {
                "location_id": "body.tbl[1].r[2].c[1].p[0]",
                "table_id": "body.tbl[1]",
                "row": 2,
                "col": 1,
            },
        )
        self.assertEqual(table["source_ref"], "F_002")
        self.assertEqual(table["overflow"]["limit_source"], "fixed_height_cell")
        self.assertEqual(table["overflow"]["limit_value"], 40)

        image = operations[3]
        self.assertEqual(
            image["target"], {"location_id": "body.p[5]", "image_role": "illustration"}
        )
        self.assertEqual(image["source_ref"], "IMAGE_INPUT")
        self.assertEqual(image["overflow"]["measured_chars"], 0)

        paragraph = operations[1]
        self.assertEqual(paragraph["source_ref"], "USER_INPUT")
        self.assertEqual(paragraph["overflow"]["measured_chars"], len(_values()[SLOT_BODY]))
        self.assertEqual(paragraph["overflow"]["limit_source"], "none")
        self.assertIsNone(paragraph["overflow"]["limit_value"])

        # red_run_clue -> fill_paragraph
        red_spec = copy.deepcopy(self.spec)
        for slot in red_spec["slots"]:
            if slot["slot_id"] == SLOT_BODY:
                slot["candidate_type"] = "red_run_clue"
        red_plan = build_fill_plan(
            red_spec,
            self._content_plan(),
            task_id="TASK_W1C_006",
            values_by_slot=_values(),
            images_by_slot=_images(),
        )
        self.assertEqual(red_plan["operations"][1]["type"], "fill_paragraph")

        # explicit_token with *** and no image -> fill_paragraph
        token_spec = copy.deepcopy(self.spec)
        for slot in token_spec["slots"]:
            if slot["slot_id"] == SLOT_IMAGE:
                slot["candidate_type"] = "explicit_token"
                slot["matched_text"] = "***"
        token_plan = build_fill_plan(
            token_spec,
            self._content_plan(),
            task_id="TASK_W1C_007",
            values_by_slot={**_values(), SLOT_IMAGE: "示意图说明"},
            images_by_slot={},
        )
        self.assertEqual(token_plan["operations"][3]["type"], "fill_paragraph")

    def test_value_ref_equality_and_preconditions(self) -> None:
        plan = self._fill_plan()
        name_op, _, table_op, _ = plan["operations"]

        self.assertEqual(name_op["value_ref"], "F_001")
        self.assertEqual(name_op["value"], "示例项目")
        self.assertEqual(name_op["source_ref"], "F_001")
        self.assertEqual(
            name_op["preconditions"], ["slot_exists", "not_protected", "template_sha_match"]
        )

        self.assertEqual(table_op["value_ref"], "F_002")
        self.assertEqual(table_op["value"], "120000")
        self.assertIn("capacity_ok", table_op["preconditions"])

        facts = copy.deepcopy(_facts())
        facts.append(
            {
                "fact_id": "F_003",
                "label": "项目背景",
                "value": "背景说明",
                "unit": "none",
                "source": "UNVERIFIED",
                "verification_status": "UNVERIFIED",
                "used_by_slots": [SLOT_BODY],
            }
        )
        content_plan = self._content_plan(facts=facts)
        unverified_plan = build_fill_plan(
            self.spec,
            content_plan,
            task_id="TASK_W1C_002",
            values_by_slot=_values(),
            images_by_slot=_images(),
        )
        body_op = unverified_plan["operations"][1]
        self.assertEqual(body_op["value_ref"], "F_003")
        self.assertIn("source_verified", body_op["preconditions"])
        result = validate_fill_plan(unverified_plan, self.spec, content_plan)
        self.assertTrue(result["passed"], result["errors"])

    def test_baseline_authorizes_exactly_the_operation_slots(self) -> None:
        plan = self._fill_plan()
        baseline = plan["baseline"]
        self.assertEqual(
            baseline["allowed_slot_ids"],
            [SLOT_NAME, SLOT_BODY, SLOT_TABLE, SLOT_IMAGE],
        )
        spec_slots = {slot["slot_id"] for slot in self.spec["slots"]}
        self.assertTrue(set(baseline["allowed_slot_ids"]).issubset(spec_slots))
        self.assertEqual(
            set(baseline["allowed_slot_ids"]),
            {operation["slot_id"] for operation in plan["operations"]},
        )
        self.assertEqual(baseline["template_sha256"], self.spec["template"]["template_sha256"])
        self.assertEqual(baseline["fingerprint_id"], self.spec["fingerprint_ref"]["fingerprint_id"])
        self.assertEqual(baseline["spec_schema_version"], "4.0")

    def test_unknown_slot_and_unauthorized_slot(self) -> None:
        content_plan = self._content_plan()
        plan = self._fill_plan(content_plan)
        plan["operations"][0]["slot_id"] = "S_deadbeef0000"
        result = validate_fill_plan(plan, self.spec, content_plan)
        self.assertFalse(result["passed"])
        self.assertIn("UNKNOWN_SLOT", _codes(result))

        plan = self._fill_plan(content_plan)
        plan["baseline"]["allowed_slot_ids"].remove(SLOT_BODY)
        result = validate_fill_plan(plan, self.spec, content_plan)
        self.assertFalse(result["passed"])
        self.assertIn("UNAUTHORIZED_SLOT_TARGET", _codes(result))

    def test_protected_slot_is_rejected(self) -> None:
        spec = copy.deepcopy(self.spec)
        for slot in spec["slots"]:
            if slot["slot_id"] == SLOT_BODY:
                slot["protection_status"] = "PROTECTED"
                slot["confirmation_tier"] = "PROTECTED_DO_NOT_TOUCH"
        plan = build_fill_plan(
            spec,
            self._content_plan(),
            task_id="TASK_W1C_003",
            values_by_slot=_values(),
            images_by_slot=_images(),
        )
        result = validate_fill_plan(plan, spec, self._content_plan())
        self.assertFalse(result["passed"])
        self.assertIn("PROTECTED_SLOT_VIOLATION", _codes(result))

    def test_duplicate_sequence_is_rejected(self) -> None:
        plan = copy.deepcopy(self._fill_plan())
        plan["operations"][1]["sequence"] = plan["operations"][0]["sequence"]
        result = validate_fill_plan(plan, self.spec, self._content_plan())
        self.assertFalse(result["passed"])
        self.assertIn("DUPLICATE_SEQUENCE", _codes(result))

    def test_overflow_beyond_hard_limit_is_rejected(self) -> None:
        content_plan = build_content_plan(
            self.spec,
            plan_id="CP_004",
            sections=[{"section_id": "SEC_004", "purpose": "预算", "target_slots": [SLOT_TABLE]}],
            facts=[],
        )
        plan = build_fill_plan(
            self.spec,
            content_plan,
            task_id="TASK_W1C_004",
            values_by_slot={SLOT_TABLE: "x" * 41},
        )
        table_op = plan["operations"][0]
        self.assertEqual(table_op["type"], "fill_cell")
        self.assertEqual(table_op["overflow"]["measured_chars"], 41)
        result = validate_fill_plan(plan, self.spec, content_plan)
        self.assertFalse(result["passed"])
        self.assertIn("CAPACITY_EXCEEDED", _codes(result))

    def test_structure_change_is_forbidden(self) -> None:
        plan = copy.deepcopy(self._fill_plan())
        plan["global_policy"]["allow_structure_change"] = True
        result = validate_fill_plan(plan, self.spec, self._content_plan())
        self.assertFalse(result["passed"])
        self.assertIn("INVALID_FILL_PLAN", _codes(result))
        self.assertIn("FORMAT_REPAIR_FORBIDDEN", _codes(result))

    def test_content_plan_integrity_violations(self) -> None:
        content_plan = self._content_plan()

        plan = self._fill_plan(content_plan)
        plan["operations"][0]["value"] = "另一个项目"
        result = validate_fill_plan(plan, self.spec, content_plan)
        self.assertIn("VALUE_REF_MISMATCH", _codes(result), result["errors"])

        plan = build_fill_plan(
            self.spec, content_plan, task_id="TASK_W1C_005", values_by_slot={}, images_by_slot={}
        )
        result = validate_fill_plan(plan, self.spec, content_plan)
        self.assertIn("REQUIRED_SLOT_MISSING", _codes(result), result["errors"])
        self.assertEqual(
            {operation["slot_id"] for operation in plan["operations"]},
            {SLOT_NAME, SLOT_TABLE},
        )

        plan = self._fill_plan(content_plan)
        plan["operations"][0]["preconditions"].remove("not_protected")
        result = validate_fill_plan(plan, self.spec, content_plan)
        self.assertIn("PRECONDITION_MISSING", _codes(result), result["errors"])


if __name__ == "__main__":
    unittest.main()
