# -*- coding: utf-8 -*-
"""Schema-level conformance: every schema is a valid draft and every example behaves as declared."""

from __future__ import annotations

import unittest

from jsonschema import Draft202012Validator

from .helpers import (
    CHECK_IDS,
    SCHEMAS,
    example_document,
    load_json,
    qa_policy,
    schema,
    schema_errors,
)


class SchemaDraftTests(unittest.TestCase):
    def test_every_schema_is_valid_draft_2020_12(self) -> None:
        for name in SCHEMAS:
            with self.subTest(schema=name):
                Draft202012Validator.check_schema(schema(name))

    def test_error_registry_data_matches_schema(self) -> None:
        data = load_json(SCHEMAS["error_registry"].parent.parent / "config" / "error-codes.json")
        self.assertEqual(schema_errors("error_registry", data), [])

    def test_qa_policy_shape(self) -> None:
        policies = qa_policy()
        self.assertIn("GENERATE/STRICT", policies)
        self.assertIn("GENERATE/STANDARD", policies)
        for name, policy in policies.items():
            with self.subTest(policy=name):
                required = policy["required"]
                optional = policy["optional"]
                self.assertTrue(required, "required list must not be empty")
                self.assertEqual(len(required), len(set(required)), "required contains duplicates")
                self.assertEqual(set(required) & set(optional), set(), "required and optional overlap")
                self.assertEqual(set(required) - set(CHECK_IDS), set(), "unknown required check id")
                self.assertEqual(set(optional) - set(CHECK_IDS), set(), "unknown optional check id")


class ExampleConformanceTests(unittest.TestCase):
    def test_document_spec_examples(self) -> None:
        self.assertEqual(schema_errors("document_spec", example_document("document-spec", "minimal_valid")), [])
        self.assertEqual(schema_errors("document_spec", example_document("document-spec", "full_valid")), [])
        self.assertTrue(schema_errors("document_spec", example_document("document-spec", "missing_required")))
        self.assertTrue(schema_errors("document_spec", example_document("document-spec", "type_error")))
        self.assertEqual(schema_errors("document_spec", example_document("document-spec", "boundary_conflict")), [])

    def test_content_plan_examples(self) -> None:
        self.assertEqual(schema_errors("content_plan", example_document("content-plan", "minimal_valid")), [])
        self.assertEqual(schema_errors("content_plan", example_document("content-plan", "full_valid")), [])
        self.assertTrue(schema_errors("content_plan", example_document("content-plan", "missing_required")))
        self.assertTrue(schema_errors("content_plan", example_document("content-plan", "type_error")))
        self.assertEqual(schema_errors("content_plan", example_document("content-plan", "boundary_conflict")), [])

    def test_fill_plan_examples(self) -> None:
        self.assertEqual(schema_errors("fill_plan", example_document("fill-plan", "minimal_valid")), [])
        self.assertEqual(schema_errors("fill_plan", example_document("fill-plan", "full_valid")), [])
        self.assertTrue(schema_errors("fill_plan", example_document("fill-plan", "missing_required")))
        self.assertTrue(schema_errors("fill_plan", example_document("fill-plan", "type_error")))
        self.assertEqual(schema_errors("fill_plan", example_document("fill-plan", "boundary_conflict")), [])

    def test_qa_report_examples(self) -> None:
        self.assertEqual(schema_errors("qa_report", example_document("qa-report", "minimal_valid")), [])
        self.assertEqual(schema_errors("qa_report", example_document("qa-report", "full_valid")), [])
        self.assertTrue(schema_errors("qa_report", example_document("qa-report", "missing_required")))
        self.assertTrue(schema_errors("qa_report", example_document("qa-report", "type_error")))
        self.assertEqual(schema_errors("qa_report", example_document("qa-report", "boundary_conflict")), [])

    def test_tool_envelope_examples(self) -> None:
        self.assertEqual(schema_errors("tool_envelope", example_document("tool-envelope", "minimal_valid")), [])
        self.assertEqual(schema_errors("tool_envelope", example_document("tool-envelope", "full_valid")), [])
        self.assertTrue(schema_errors("tool_envelope", example_document("tool-envelope", "missing_required")))
        self.assertTrue(schema_errors("tool_envelope", example_document("tool-envelope", "type_error")))
        self.assertEqual(schema_errors("tool_envelope", example_document("tool-envelope", "boundary_conflict")), [])


if __name__ == "__main__":
    unittest.main()
