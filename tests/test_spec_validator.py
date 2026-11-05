# -*- coding: utf-8 -*-
"""W1-B: DocumentSpec 4.0 validator tests (JSON Schema + Contract 02 §14)."""

from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from template_intelligence.spec_validator import (
    SpecValidationError,
    validate_document_spec,
    validate_document_spec_file,
)

ROOT = Path(__file__).resolve().parents[1]
CASES_PATH = ROOT / "examples" / "document-spec" / "cases.json"


def _case(name: str) -> dict:
    with open(CASES_PATH, "r", encoding="utf-8") as handle:
        return json.load(handle)["cases"][name]


def _document(name: str) -> dict:
    return copy.deepcopy(_case(name)["document"])


def _codes(report: dict) -> list:
    return [error["code"] for error in report["errors"]]


def _details(report: dict) -> str:
    return " ".join(error["detail"] for error in report["errors"])


class DocumentSpecValidatorTests(unittest.TestCase):
    def test_minimal_valid_passes(self) -> None:
        report = validate_document_spec(_document("minimal_valid"))
        self.assertTrue(report["passed"], report)
        self.assertEqual(report["errors"], [])
        self.assertEqual(report["warnings"], [])

    def test_full_valid_passes(self) -> None:
        report = validate_document_spec(_document("full_valid"))
        self.assertTrue(report["passed"], report)

    def test_missing_required_fails_schema(self) -> None:
        report = validate_document_spec(_document("missing_required"))
        self.assertFalse(report["passed"])
        self.assertEqual(_codes(report), ["INVALID_DOCUMENT_SPEC"])
        self.assertIn("'slots' is a required property", _details(report))

    def test_type_error_fails_schema(self) -> None:
        report = validate_document_spec(_document("type_error"))
        self.assertFalse(report["passed"])
        self.assertTrue(all(code == "INVALID_DOCUMENT_SPEC" for code in _codes(report)))
        self.assertIn("$.slots", [error["location"] for error in report["errors"]])

    def test_boundary_conflict_reports_slot_id_conflict(self) -> None:
        report = validate_document_spec(_document("boundary_conflict"))
        self.assertFalse(report["passed"])
        self.assertEqual(_codes(report), ["SLOT_ID_CONFLICT"])
        self.assertIn("duplicate slot_id", _details(report))

    def test_protected_iff_protected_do_not_touch(self) -> None:
        for status, tier, expected in (
            ("PROTECTED", "AUTO_DERIVE_OR_BIND", "requires confirmation_tier"),
            ("FILLABLE", "PROTECTED_DO_NOT_TOUCH", "requires protection_status PROTECTED"),
        ):
            with self.subTest(status=status, tier=tier):
                doc = _document("full_valid")
                doc["slots"][0]["protection_status"] = status
                doc["slots"][0]["confirmation_tier"] = tier
                report = validate_document_spec(doc)
                self.assertFalse(report["passed"])
                self.assertIn(expected, _details(report))

    def test_internal_fact_requires_must_ask_user(self) -> None:
        doc = _document("full_valid")
        doc["slots"][0]["candidate_type"] = "internal_fact"
        doc["slots"][0]["confirmation_tier"] = "AUTO_DERIVE_OR_BIND"
        report = validate_document_spec(doc)
        self.assertFalse(report["passed"])
        self.assertIn("internal_fact requires confirmation_tier MUST_ASK_USER", _details(report))

    def test_control_or_field_requires_protected(self) -> None:
        doc = _document("full_valid")
        doc["slots"][0]["candidate_type"] = "control_or_field"
        report = validate_document_spec(doc)
        self.assertFalse(report["passed"])
        self.assertIn("control_or_field requires protection_status PROTECTED", _details(report))
        self.assertIn(
            "control_or_field requires confirmation_tier PROTECTED_DO_NOT_TOUCH",
            _details(report),
        )

    def test_slot_location_must_resolve_in_structure(self) -> None:
        doc = _document("full_valid")
        doc["structure"]["paragraphs"] = [
            item
            for item in doc["structure"]["paragraphs"]
            if item["location_id"] != "body.p[5]"
        ]
        report = validate_document_spec(doc)
        self.assertFalse(report["passed"])
        self.assertIn("SLOT_LOCATION_UNRESOLVED", _codes(report))
        self.assertIn("body.p[5]", _details(report))

    def test_template_identity_rules(self) -> None:
        with self.subTest(rule="template_id derivation"):
            doc = _document("minimal_valid")
            doc["template"]["template_id"] = "T_ffffffffffff"
            report = validate_document_spec(doc)
            self.assertFalse(report["passed"])
            self.assertIn("TEMPLATE_SHA_MISMATCH", _codes(report))
        with self.subTest(rule="parent_sha256 equals template_sha256"):
            doc = _document("full_valid")
            doc["template"]["parent_sha256"] = doc["template"]["template_sha256"]
            report = validate_document_spec(doc)
            self.assertFalse(report["passed"])
            self.assertIn("TEMPLATE_SHA_MISMATCH", _codes(report))
            self.assertIn("parent_sha256 must differ", _details(report))

    def test_all_zero_fingerprint_hash_is_rejected(self) -> None:
        doc = _document("minimal_valid")
        doc["fingerprint_ref"]["structural_hash"] = "0" * 64
        report = validate_document_spec(doc)
        self.assertFalse(report["passed"])
        self.assertIn("INVALID_DOCUMENT_SPEC", _codes(report))
        self.assertIn("structural_hash", _details(report))
        self.assertIn("not all zeros", _details(report))

    def test_span_must_be_forward_and_occurrence_positive(self) -> None:
        doc = _document("full_valid")
        doc["slots"][0]["span"] = {"start": 3, "end": 2}
        report = validate_document_spec(doc)
        self.assertFalse(report["passed"])
        self.assertIn("0 <= start < end", _details(report))

        doc = _document("full_valid")
        doc["slots"][0]["occurrence"] = 0
        report = validate_document_spec(doc)
        self.assertFalse(report["passed"])
        self.assertIn("occurrence must be an integer >= 1", _details(report))

    def test_non_empty_errors_makes_spec_unusable(self) -> None:
        doc = _document("minimal_valid")
        doc["errors"] = [
            {"code": "ANALYSIS_FAILED", "severity": "blocking", "detail": "unreadable part"}
        ]
        report = validate_document_spec(doc)
        self.assertFalse(report["passed"])
        self.assertEqual(_codes(report), ["DOCUMENT_SPEC_UNUSABLE"])

    def test_duplicate_region_profile_and_constraint_ids(self) -> None:
        doc = _document("full_valid")
        doc["protected_regions"].append(copy.deepcopy(doc["protected_regions"][0]))
        doc["capacity_profiles"].append(copy.deepcopy(doc["capacity_profiles"][0]))
        doc["layout_constraints"].append(copy.deepcopy(doc["layout_constraints"][0]))
        report = validate_document_spec(doc)
        self.assertFalse(report["passed"])
        self.assertEqual(_codes(report), ["INVALID_DOCUMENT_SPEC"] * 3)
        for field in ("region_id", "profile_id", "constraint_id"):
            self.assertIn("duplicate {}".format(field), _details(report))

    def test_raise_on_failure_attaches_report(self) -> None:
        valid = validate_document_spec(_document("minimal_valid"), raise_on_failure=True)
        self.assertTrue(valid["passed"])
        with self.assertRaises(SpecValidationError) as caught:
            validate_document_spec(_document("boundary_conflict"), raise_on_failure=True)
        error = caught.exception
        self.assertIsInstance(error, ValueError)
        self.assertFalse(error.report["passed"])
        self.assertEqual(_codes(error.report), ["SLOT_ID_CONFLICT"])

    def test_validator_does_not_mutate_input(self) -> None:
        doc = _document("full_valid")
        before = json.dumps(doc, sort_keys=True)
        first = validate_document_spec(doc)
        second = validate_document_spec(doc)
        self.assertEqual(json.dumps(doc, sort_keys=True), before)
        self.assertEqual(first, second)
        self.assertEqual(set(first), {"passed", "errors", "warnings"})

    def test_file_entry_point(self) -> None:
        doc = _document("minimal_valid")
        with tempfile.TemporaryDirectory() as tmp:
            valid_path = Path(tmp) / "spec.json"
            valid_path.write_text(json.dumps(doc), encoding="utf-8")
            report = validate_document_spec_file(str(valid_path))
            self.assertTrue(report["passed"], report)

            broken_path = Path(tmp) / "broken.json"
            broken_path.write_text("{not json", encoding="utf-8")
            report = validate_document_spec_file(str(broken_path))
            self.assertFalse(report["passed"])
            self.assertEqual(_codes(report), ["INVALID_DOCUMENT_SPEC"])

            missing_path = Path(tmp) / "missing.json"
            report = validate_document_spec_file(str(missing_path))
            self.assertFalse(report["passed"])
            self.assertEqual(_codes(report), ["INVALID_DOCUMENT_SPEC"])


if __name__ == "__main__":
    unittest.main()
