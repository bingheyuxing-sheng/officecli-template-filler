# -*- coding: utf-8 -*-
"""W1-E: QAReport 4.0 gate, builder and full-runner tests (Contract 04)."""

from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from qa import (
    QAGateError,
    assert_commit_eligible,
    build_qa_report,
    check_record,
    resolve_required_checks,
    run_full_qa,
    validate_qa_report,
)

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples" / "qa-report" / "cases.json"
POLICY = ROOT / "config" / "qa-policy.json"
OUT_DOCX = ROOT / "tests" / "fixtures" / "legacy" / "legacy_out.docx"
REF_DOCX = ROOT / "tests" / "fixtures" / "legacy" / "legacy_ref.docx"


def _load_cases() -> dict:
    with open(EXAMPLES, "r", encoding="utf-8") as handle:
        return json.load(handle)["cases"]


def _example_document(case_name: str) -> dict:
    return copy.deepcopy(_load_cases()[case_name]["document"])


def _passing_checks(required, *, omit=(), overrides=None):
    records = []
    overrides = overrides or {}
    for check_id in required:
        if check_id in omit:
            continue
        status, detail = overrides.get(check_id, ("PASSED", "stub evidence"))
        records.append(
            check_record(check_id, status, "stub_implementation", detail=detail, required=True)
        )
    return records


def _record(report: dict, check_id: str) -> dict:
    for record in report.get("checks", []):
        if record.get("check_id") == check_id:
            return record
    raise AssertionError("no check record for %s" % check_id)


class QAReportExamplesTests(unittest.TestCase):
    def test_valid_cases_are_accepted(self) -> None:
        for case in ("minimal_valid", "full_valid"):
            with self.subTest(case=case):
                result = validate_qa_report(_example_document(case))
                self.assertTrue(result["passed"], result["errors"])
                self.assertEqual(result["errors"], [])

    def test_schema_invalid_cases_are_rejected(self) -> None:
        for case in ("missing_required", "type_error"):
            with self.subTest(case=case):
                result = validate_qa_report(_example_document(case))
                self.assertFalse(result["passed"])
                self.assertTrue(
                    any(item.startswith("SCHEMA_ERROR") for item in result["errors"]),
                    result["errors"],
                )

    def test_boundary_conflict_is_a_false_pass(self) -> None:
        result = validate_qa_report(_example_document("boundary_conflict"))
        self.assertFalse(result["passed"])
        joined = "\n".join(result["errors"])
        self.assertIn("QA_FALSE_PASS", joined)
        self.assertIn("QA_ELIGIBILITY_CONTRADICTION", joined)


class QAPolicyBindingTests(unittest.TestCase):
    def test_generate_strict_required_set_matches_policy(self) -> None:
        with open(POLICY, "r", encoding="utf-8") as handle:
            expected = json.load(handle)["policies"]["GENERATE/STRICT"]
        policy = resolve_required_checks("GENERATE", "STRICT")
        self.assertEqual(policy["policy_source"], "GENERATE/STRICT")
        self.assertEqual(policy["required"], expected["required"])
        self.assertEqual(policy["optional"], expected["optional"])

    def test_review_replica_has_a_different_required_set(self) -> None:
        generate = resolve_required_checks("GENERATE", "STRICT")
        review = resolve_required_checks("REVIEW", "REPLICA")
        self.assertNotEqual(generate["required"], review["required"])
        self.assertEqual(review["policy_source"], "REVIEW/REPLICA")
        self.assertIn("REVIEW_INTEGRITY", review["required"])
        self.assertNotIn("FIDELITY", review["required"])

    def test_unknown_policy_pair_raises(self) -> None:
        for task_mode, gate_mode in (
            ("REVIEW", "STRICT"),
            ("GENERATE", "REPLICA"),
            ("BOGUS", "STRICT"),
        ):
            with self.subTest(pair="%s/%s" % (task_mode, gate_mode)):
                with self.assertRaises(ValueError):
                    resolve_required_checks(task_mode, gate_mode)

    def test_policy_override_and_source_mismatch_are_rejected(self) -> None:
        overridden = _example_document("minimal_valid")
        overridden["required_checks"] = ["PACKAGE"]
        self.assertIn(
            "QA_POLICY_OVERRIDE_FORBIDDEN", "\n".join(validate_qa_report(overridden)["errors"])
        )

        mismatched = _example_document("minimal_valid")
        mismatched["policy_source"] = "REVIEW/REPLICA"
        self.assertIn(
            "QA_POLICY_SOURCE_MISMATCH", "\n".join(validate_qa_report(mismatched)["errors"])
        )


class QAReportBuilderTests(unittest.TestCase):
    def test_missing_required_check_is_unverified_not_passed(self) -> None:
        required = resolve_required_checks("GENERATE", "STRICT")["required"]
        report = build_qa_report(
            task_id="TASK_W1E_010",
            task_mode="GENERATE",
            gate_mode="STRICT",
            checks=_passing_checks(required, omit=("FIDELITY",)),
        )
        self.assertEqual(report["status"], "UNVERIFIED")
        self.assertIn("FIDELITY", report["missing_checks"])
        self.assertFalse(report["final"]["eligible_for_commit"])
        record = _record(report, "FIDELITY")
        self.assertEqual(record["status"], "SKIPPED")
        self.assertIn("detail", record["evidence"])

    def test_standard_unverified_is_eligible_with_disclosure(self) -> None:
        required = resolve_required_checks("GENERATE", "STANDARD")["required"]
        report = build_qa_report(
            task_id="TASK_W1E_011",
            task_mode="GENERATE",
            gate_mode="STANDARD",
            checks=_passing_checks(required, omit=("FIDELITY",)),
        )
        self.assertEqual(report["status"], "UNVERIFIED")
        self.assertTrue(report["final"]["eligible_for_commit"])
        reasons = " ".join(report["final"]["reasons"])
        self.assertIn("FIDELITY", reasons)
        self.assertTrue(validate_qa_report(report)["passed"])
        assert_commit_eligible(report)

    def test_failed_without_a_blocking_issue_is_invalid(self) -> None:
        report = _example_document("minimal_valid")
        report["status"] = "FAILED"
        report["final"] = {"eligible_for_commit": False, "reasons": ["failure"]}
        result = validate_qa_report(report)
        self.assertFalse(result["passed"])
        self.assertIn("FAILED without a blocking or high issue", "\n".join(result["errors"]))

    def test_applied_repair_requires_a_recheck(self) -> None:
        missing_recheck = _example_document("full_valid")
        del missing_recheck["repairs"][0]["recheck"]
        result = validate_qa_report(missing_recheck)
        self.assertFalse(result["passed"])
        self.assertIn("QA_REPAIR_UNVERIFIED", "\n".join(result["errors"]))

        skipped_recheck = _example_document("full_valid")
        skipped_recheck["repairs"][0]["recheck"] = {"status": "SKIPPED", "report_ref": None}
        result = validate_qa_report(skipped_recheck)
        self.assertFalse(result["passed"])
        self.assertIn("QA_REPAIR_UNVERIFIED", "\n".join(result["errors"]))

    def test_high_severity_must_be_blocking(self) -> None:
        report = _example_document("minimal_valid")
        report["issues"] = [
            {
                "code": "TEMPLATE_TEXT_RESIDUAL",
                "severity": "high",
                "location": "body.p[0]",
                "detail": "residual",
                "blocking": False,
            }
        ]
        result = validate_qa_report(report)
        self.assertFalse(result["passed"])
        self.assertIn("QA_ISSUE_CONTRADICTION", "\n".join(result["errors"]))

    def test_required_check_skipped_can_never_be_passed(self) -> None:
        required = resolve_required_checks("GENERATE", "STRICT")["required"]
        report = build_qa_report(
            task_id="TASK_W1E_012",
            task_mode="GENERATE",
            gate_mode="STRICT",
            checks=_passing_checks(
                required,
                overrides={"PACKAGE": ("SKIPPED", "no package audit performed")},
            ),
        )
        self.assertNotEqual(report["status"], "PASSED")
        self.assertIn("PACKAGE", report["missing_checks"])


class QAGateAssertTests(unittest.TestCase):
    def test_valid_eligible_report_is_returned(self) -> None:
        report = _example_document("minimal_valid")
        self.assertEqual(assert_commit_eligible(report), report)

    def test_invalid_or_ineligible_report_raises_with_report_attached(self) -> None:
        invalid = _example_document("boundary_conflict")
        with self.assertRaises(QAGateError) as context:
            assert_commit_eligible(invalid)
        self.assertIs(context.exception.report, invalid)

        ineligible = _example_document("minimal_valid")
        ineligible["status"] = "UNVERIFIED"
        ineligible["final"] = {"eligible_for_commit": False, "reasons": ["required checks not verified"]}
        self.assertTrue(validate_qa_report(ineligible)["passed"])
        with self.assertRaises(QAGateError):
            assert_commit_eligible(ineligible)


class FullQARunnerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fixture_report = run_full_qa(
            str(OUT_DOCX),
            template_path=str(REF_DOCX),
            task_id="TASK_W1E_001",
            task_mode="GENERATE",
            gate_mode="STRICT",
        )
        # The same artifact against itself is a clean baseline: no template diff
        # can exist, so the run must be PASSED or UNVERIFIED (never FAILED).
        cls.clean_report = run_full_qa(
            str(OUT_DOCX),
            template_path=str(OUT_DOCX),
            task_id="TASK_W1E_002",
            task_mode="GENERATE",
            gate_mode="STRICT",
        )

    def test_report_is_schema_and_semantically_valid(self) -> None:
        for report in (self.fixture_report, self.clean_report):
            result = validate_qa_report(report)
            self.assertTrue(result["passed"], result["errors"])
            self.assertEqual(report["policy_source"], "GENERATE/STRICT")
            self.assertEqual(
                set(report["required_checks"]),
                set(resolve_required_checks("GENERATE", "STRICT")["required"]),
            )
        self.assertIn(self.clean_report["status"], ("PASSED", "UNVERIFIED"))

    def test_visual_page_count_is_never_passed_without_backend_evidence(self) -> None:
        for report in (self.fixture_report, self.clean_report):
            record = _record(report, "VISUAL_PAGE_COUNT")
            if record["status"] == "PASSED":
                detail = record["evidence"].get("detail", "").lower()
                self.assertIn("backend", detail)
                self.assertIn("page count", detail)
                self.assertTrue(Path(record["evidence"]["artifact_path"]).is_file())
            elif record["status"] == "UNVERIFIED":
                detail = str(record["evidence"].get("detail") or "")
                self.assertTrue(
                    detail in ("PDF_BACKEND_UNAVAILABLE", "PDF_PAGE_COUNT_UNVERIFIED")
                    or detail.startswith("CAPABILITY_UNAVAILABLE["),
                    "UNVERIFIED must name the missing capability, got: %r" % detail,
                )
            else:
                # FAILED is only allowed when a real blocking finding exists.
                self.assertEqual(record["status"], "FAILED")
                self.assertTrue(
                    any(
                        issue.get("check_id") == "VISUAL_PAGE_COUNT"
                        and issue.get("severity") == "high"
                        for issue in report["issues"]
                    )
                )

    def test_unavailable_checks_never_produce_false_failures(self) -> None:
        report = self.fixture_report
        statuses = {item["check_id"]: item["status"] for item in report["checks"]}
        failed_checks = {check_id for check_id, status in statuses.items() if status == "FAILED"}
        for issue in report["issues"]:
            self.assertIn(issue["check_id"], failed_checks)
        self.assertNotEqual(statuses["DATA"], "PASSED")
        self.assertEqual(_record(report, "DATA")["evidence"]["detail"], "DATA_FACTS_NOT_PROVIDED")

        # A skipped required check can never yield PASSED, and an absent fact
        # source keeps the clean baseline UNVERIFIED rather than a false pass.
        for candidate in (self.fixture_report, self.clean_report):
            self.assertNotEqual(candidate["status"], "PASSED")
            self.assertTrue(candidate["missing_checks"])


if __name__ == "__main__":
    unittest.main()
