# -*- coding: utf-8 -*-
"""Cross-contract integration: producer/consumer references must agree."""

from __future__ import annotations

import unittest

from .helpers import (
    error_registry,
    example_document,
    qa_policy,
    semantic_content_plan,
    semantic_document_spec,
    semantic_envelope,
    semantic_fill_plan,
    semantic_qa_report,
)


class CrossContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.spec = example_document("document-spec", "full_valid")
        self.content = example_document("content-plan", "full_valid")
        self.fill = example_document("fill-plan", "full_valid")
        self.qa = example_document("qa-report", "full_valid")
        self.envelope = example_document("tool-envelope", "full_valid")

    def test_template_identity_is_consistent(self) -> None:
        template_id = self.spec["template"]["template_id"]
        self.assertEqual(self.content["template_id"], template_id)
        self.assertEqual(self.fill["template_id"], template_id)
        self.assertEqual(self.fill["baseline"]["template_sha256"], self.spec["template"]["template_sha256"])
        self.assertEqual(self.fill["baseline"]["fingerprint_id"], self.spec["fingerprint_ref"]["fingerprint_id"])

    def test_task_identity_is_consistent(self) -> None:
        self.assertEqual(self.fill["task_id"], self.qa["task_id"])
        self.assertEqual(self.fill["task_id"], self.envelope["task_id"])

    def test_content_targets_exist_in_spec(self) -> None:
        slot_ids = {slot["slot_id"] for slot in self.spec["slots"]}
        targeted = {
            slot_id
            for section in self.content["sections"]
            for slot_id in section["target_slots"]
        }
        self.assertEqual(targeted - slot_ids, set())

    def test_fill_plan_targets_and_authorization(self) -> None:
        slot_by_id = {slot["slot_id"]: slot for slot in self.spec["slots"]}
        allowed = set(self.fill["baseline"]["allowed_slot_ids"])
        self.assertEqual(allowed - set(slot_by_id), set())
        for operation in self.fill["operations"]:
            slot = slot_by_id[operation["slot_id"]]
            with self.subTest(op=operation["op_id"]):
                self.assertIn(operation["slot_id"], allowed)
                self.assertEqual(operation["target"]["location_id"], slot["location_id"])

    def test_fill_values_match_content_facts(self) -> None:
        facts = {fact["fact_id"]: fact for fact in self.content["facts"]}
        for operation in self.fill["operations"]:
            value_ref = operation.get("value_ref")
            if not value_ref:
                continue
            with self.subTest(op=operation["op_id"]):
                self.assertIn(value_ref, facts)
                self.assertEqual(str(operation["value"]), str(facts[value_ref]["value"]))

    def test_qa_required_checks_come_from_policy(self) -> None:
        expected = set(qa_policy()[self.qa["policy_source"]]["required"])
        self.assertEqual(set(self.qa["required_checks"]), expected)
        self.assertEqual(set(self.qa["executed_checks"]) - expected - set(qa_policy()[self.qa["policy_source"]]["optional"]), set())

    def test_all_referenced_codes_are_registered(self) -> None:
        registry = error_registry()
        referenced = {issue["code"] for issue in self.qa["issues"]}
        referenced |= {item["code"] for item in self.qa["warnings"]}
        referenced |= {item["code"] for item in self.envelope["warnings"]}
        referenced |= {item["code"] for item in self.envelope["errors"]}
        self.assertEqual(referenced - set(registry), set())

    def test_semantic_checks_pass_for_full_chain(self) -> None:
        self.assertEqual(semantic_document_spec(self.spec), [])
        self.assertEqual(semantic_content_plan(self.content, self.spec), [])
        self.assertEqual(semantic_fill_plan(self.fill, self.spec, self.content), [])
        self.assertEqual(semantic_qa_report(self.qa), [])
        self.assertEqual(semantic_envelope(self.envelope), [])


if __name__ == "__main__":
    unittest.main()
