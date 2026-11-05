# -*- coding: utf-8 -*-
"""Contract 03 conformance: ContentPlan and FillPlan separation, references and overflow."""

from __future__ import annotations

import unittest

from .helpers import (
    example_document,
    schema_errors,
    semantic_content_plan,
    semantic_fill_plan,
)


class ContentPlanTests(unittest.TestCase):
    def setUp(self) -> None:
        self.spec = example_document("document-spec", "full_valid")

    def test_valid_cases(self) -> None:
        for case in ("minimal_valid", "full_valid"):
            with self.subTest(case=case):
                plan = example_document("content-plan", case)
                self.assertEqual(schema_errors("content_plan", plan), [])
                self.assertEqual(semantic_content_plan(plan, self.spec), [])

    def test_missing_and_type_errors(self) -> None:
        self.assertTrue(schema_errors("content_plan", example_document("content-plan", "missing_required")))
        self.assertTrue(schema_errors("content_plan", example_document("content-plan", "type_error")))

    def test_unknown_slot_reference_is_rejected(self) -> None:
        plan = example_document("content-plan", "boundary_conflict")
        self.assertEqual(schema_errors("content_plan", plan), [])
        errors = semantic_content_plan(plan, self.spec)
        self.assertTrue(any("fact references unknown slot" in item for item in errors), errors)

    def test_target_length_and_completeness_rules(self) -> None:
        plan = example_document("content-plan", "full_valid")
        plan["sections"][0]["requirements"]["target_length"] = {"min": 200, "max": 100}
        plan["completeness"]["allow_missing"] = [
            {"slot_id": "S_5abf927e8f5e", "reason": "optional in this run"}
        ]
        errors = semantic_content_plan(plan, self.spec)
        self.assertTrue(any("target_length max < min" in item for item in errors), errors)
        self.assertTrue(any("allow_missing not required" in item for item in errors), errors)

    def test_fact_source_is_mandatory(self) -> None:
        plan = example_document("content-plan", "full_valid")
        plan["facts"][0]["source"] = ""
        errors = semantic_content_plan(plan, self.spec)
        self.assertTrue(any("FACT_SOURCE_MISSING" in item for item in errors), errors)


class FillPlanTests(unittest.TestCase):
    def setUp(self) -> None:
        self.spec = example_document("document-spec", "full_valid")
        self.content = example_document("content-plan", "full_valid")

    def test_valid_cases(self) -> None:
        minimal = example_document("fill-plan", "minimal_valid")
        self.assertEqual(schema_errors("fill_plan", minimal), [])
        self.assertEqual(semantic_fill_plan(minimal, self.spec), [])

        full = example_document("fill-plan", "full_valid")
        self.assertEqual(schema_errors("fill_plan", full), [])
        self.assertEqual(semantic_fill_plan(full, self.spec, self.content), [])

    def test_missing_and_type_errors(self) -> None:
        self.assertTrue(schema_errors("fill_plan", example_document("fill-plan", "missing_required")))
        self.assertTrue(schema_errors("fill_plan", example_document("fill-plan", "type_error")))

    def test_duplicate_sequence_is_rejected(self) -> None:
        plan = example_document("fill-plan", "boundary_conflict")
        self.assertEqual(schema_errors("fill_plan", plan), [])
        errors = semantic_fill_plan(plan, self.spec)
        self.assertTrue(any("duplicate operation sequence" in item for item in errors), errors)

    def test_unauthorized_slot_is_rejected(self) -> None:
        plan = example_document("fill-plan", "full_valid")
        plan["operations"][1]["slot_id"] = "S_744ef06dee9d"
        errors = semantic_fill_plan(plan, self.spec, self.content)
        self.assertTrue(any("target location mismatch" in item for item in errors), errors)

    def test_value_ref_must_match_fact(self) -> None:
        plan = example_document("fill-plan", "full_valid")
        plan["operations"][2]["value"] = "999999"
        errors = semantic_fill_plan(plan, self.spec, self.content)
        self.assertTrue(any("value/value_ref mismatch" in item for item in errors), errors)

    def test_overflow_must_reject(self) -> None:
        plan = example_document("fill-plan", "full_valid")
        plan["operations"][2]["overflow"]["measured_chars"] = 41
        errors = semantic_fill_plan(plan, self.spec, self.content)
        self.assertTrue(any("CAPACITY_EXCEEDED" in item for item in errors), errors)

    def test_structure_change_must_be_false(self) -> None:
        plan = example_document("fill-plan", "minimal_valid")
        plan["global_policy"]["allow_structure_change"] = True
        errors = schema_errors("fill_plan", plan)
        self.assertTrue(any("False was expected" in item or "is not of type" in item for item in errors), errors)


if __name__ == "__main__":
    unittest.main()
