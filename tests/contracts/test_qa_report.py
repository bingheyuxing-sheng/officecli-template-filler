# -*- coding: utf-8 -*-
"""Contract 04 conformance: policy-owned checks, four states and commit eligibility."""

from __future__ import annotations

import unittest

from .helpers import example_document, schema_errors, semantic_qa_report


class QaReportTests(unittest.TestCase):
    def test_valid_cases(self) -> None:
        for case in ("minimal_valid", "full_valid"):
            with self.subTest(case=case):
                report = example_document("qa-report", case)
                self.assertEqual(schema_errors("qa_report", report), [])
                self.assertEqual(semantic_qa_report(report), [])

    def test_missing_and_type_errors(self) -> None:
        self.assertTrue(schema_errors("qa_report", example_document("qa-report", "missing_required")))
        self.assertTrue(schema_errors("qa_report", example_document("qa-report", "type_error")))

    def test_false_pass_is_rejected(self) -> None:
        report = example_document("qa-report", "boundary_conflict")
        self.assertEqual(schema_errors("qa_report", report), [])
        errors = semantic_qa_report(report)
        self.assertTrue(any("QA_FALSE_PASS" in item for item in errors), errors)
        self.assertTrue(any("QA_ELIGIBILITY_CONTRADICTION" in item for item in errors), errors)

    def test_policy_source_must_match_task_and_gate_mode(self) -> None:
        report = example_document("qa-report", "minimal_valid")
        report["policy_source"] = "REVIEW/REPLICA"
        errors = semantic_qa_report(report)
        self.assertTrue(any("QA_POLICY_SOURCE_MISMATCH" in item for item in errors), errors)

    def test_policy_override_is_rejected(self) -> None:
        report = example_document("qa-report", "minimal_valid")
        report["required_checks"] = ["PACKAGE"]
        errors = semantic_qa_report(report)
        self.assertTrue(any("QA_POLICY_OVERRIDE_FORBIDDEN" in item for item in errors), errors)

    def test_unverified_cannot_pass(self) -> None:
        report = example_document("qa-report", "minimal_valid")
        report["missing_checks"] = ["FIDELITY"]
        report["checks"] = [item for item in report["checks"] if item["check_id"] != "FIDELITY"]
        report["executed_checks"] = [item for item in report["executed_checks"] if item != "FIDELITY"]
        errors = semantic_qa_report(report)
        self.assertTrue(any("required check record missing" in item for item in errors), errors)
        self.assertTrue(any("QA_FALSE_PASS" in item for item in errors), errors)

    def test_strict_eligibility_requires_passed(self) -> None:
        report = example_document("qa-report", "minimal_valid")
        report["status"] = "UNVERIFIED"
        report["missing_checks"] = ["FIDELITY"]
        report["final"]["eligible_for_commit"] = True
        errors = semantic_qa_report(report)
        self.assertTrue(any("QA_ELIGIBILITY_CONTRADICTION" in item for item in errors), errors)

    def test_high_severity_must_be_blocking(self) -> None:
        report = example_document("qa-report", "minimal_valid")
        report["issues"] = [
            {
                "code": "TEMPLATE_TEXT_RESIDUAL",
                "severity": "high",
                "location": "body.p[0]",
                "detail": "residual",
                "blocking": False,
            }
        ]
        errors = semantic_qa_report(report)
        self.assertTrue(any("high severity must be blocking" in item for item in errors), errors)


if __name__ == "__main__":
    unittest.main()
