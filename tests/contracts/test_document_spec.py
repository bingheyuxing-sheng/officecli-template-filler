# -*- coding: utf-8 -*-
"""Contract 02 conformance: schema validity plus semantic rules the schema cannot express."""

from __future__ import annotations

import unittest

from .helpers import example_document, schema_errors, semantic_document_spec


class DocumentSpecTests(unittest.TestCase):
    def test_minimal_and_full_are_valid(self) -> None:
        for case in ("minimal_valid", "full_valid"):
            with self.subTest(case=case):
                doc = example_document("document-spec", case)
                self.assertEqual(schema_errors("document_spec", doc), [])
                self.assertEqual(semantic_document_spec(doc), [])

    def test_missing_required_and_type_error(self) -> None:
        self.assertIn(
            "'slots' is a required property",
            " ".join(schema_errors("document_spec", example_document("document-spec", "missing_required"))),
        )
        self.assertTrue(schema_errors("document_spec", example_document("document-spec", "type_error")))

    def test_boundary_conflict_is_rejected_semantically(self) -> None:
        doc = example_document("document-spec", "boundary_conflict")
        self.assertEqual(schema_errors("document_spec", doc), [])
        errors = semantic_document_spec(doc)
        self.assertTrue(any("duplicate slot_id" in item for item in errors), errors)

    def test_protection_and_tier_rules(self) -> None:
        doc = example_document("document-spec", "full_valid")
        slot = doc["slots"][0]
        self.assertEqual(slot["protection_status"], "FILLABLE")
        slot["protection_status"] = "PROTECTED"
        slot["confirmation_tier"] = "AUTO_DERIVE_OR_BIND"
        errors = semantic_document_spec(doc)
        self.assertTrue(any("protected slot tier mismatch" in item for item in errors), errors)

    def test_template_id_derivation(self) -> None:
        doc = example_document("document-spec", "minimal_valid")
        doc["template"]["template_id"] = "T_ffffffffffff"
        errors = semantic_document_spec(doc)
        self.assertTrue(any("template_id does not derive" in item for item in errors), errors)

    def test_slot_location_must_exist_in_structure(self) -> None:
        doc = example_document("document-spec", "full_valid")
        doc["structure"]["paragraphs"] = [
            item for item in doc["structure"]["paragraphs"] if item["location_id"] != "body.p[5]"
        ]
        errors = semantic_document_spec(doc)
        self.assertTrue(any("slot location not in structure" in item for item in errors), errors)

    def test_non_empty_errors_blocks_filling(self) -> None:
        doc = example_document("document-spec", "minimal_valid")
        doc["errors"] = [{"code": "ANALYSIS_FAILED", "severity": "blocking", "detail": "unreadable part"}]
        errors = semantic_document_spec(doc)
        self.assertTrue(any("errors array is non-empty" in item for item in errors), errors)


if __name__ == "__main__":
    unittest.main()
