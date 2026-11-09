# -*- coding: utf-8 -*-
"""QAReport schema and Contract 04 eligibility invariants."""

from __future__ import annotations

import pytest

from qa.gate import QAGateError, assert_commit_eligible, validate_qa_report


def test_valid_passed_report_is_accepted(qa_report):
    report = qa_report()

    result = validate_qa_report(report)

    assert result["passed"] is True
    assert result["errors"] == []
    assert assert_commit_eligible(report) is report


@pytest.mark.parametrize(
    "kwargs, expected",
    [
        ({"status": "PASSED", "coverage_gaps": ["VISUAL_PAGE_COUNT"]}, "QA_FALSE_PASS"),
        ({"status": "PASSED", "missing_checks": ["VISUAL_PAGE_COUNT"]}, "QA_FALSE_PASS"),
        (
            {
                "status": "PASSED",
                "issues": [
                    {
                        "code": "FAKE",
                        "severity": "high",
                        "location": "document",
                        "detail": "blocking issue",
                        "blocking": True,
                    }
                ],
            },
            "QA_FALSE_PASS",
        ),
        ({"status": "FAILED", "issues": []}, "FAILED without a blocking or high issue"),
        ({"status": "PASSED", "eligible_for_commit": False}, "QA_ELIGIBILITY_CONTRADICTION"),
    ],
)
def test_invalid_reports_are_rejected(qa_report, kwargs, expected):
    report = qa_report(**kwargs)

    result = validate_qa_report(report)

    assert result["passed"] is False
    assert any(expected in error for error in result["errors"])


def test_required_check_override_is_rejected(qa_report):
    report = qa_report(overrides={"required_checks": ["PACKAGE"]})

    result = validate_qa_report(report)

    assert result["passed"] is False
    assert any("QA_POLICY_OVERRIDE_FORBIDDEN" in error for error in result["errors"])


def test_unverified_standard_is_committable_but_strict_is_not(qa_report):
    standard = qa_report(
        status="UNVERIFIED",
        gate_mode="STANDARD",
        missing_checks=["VISUAL_PAGE_COUNT"],
        coverage_gaps=["VISUAL_PAGE_COUNT"],
    )
    strict = qa_report(
        status="UNVERIFIED",
        gate_mode="STRICT",
        missing_checks=["VISUAL_PAGE_COUNT"],
        coverage_gaps=["VISUAL_PAGE_COUNT"],
    )

    assert validate_qa_report(standard)["passed"] is True
    assert assert_commit_eligible(standard) is standard

    assert validate_qa_report(strict)["passed"] is True
    with pytest.raises(QAGateError):
        assert_commit_eligible(strict)


def test_unverified_check_requires_evidence_detail(qa_report):
    report = qa_report(
        status="UNVERIFIED",
        missing_checks=["VISUAL_PAGE_COUNT"],
        coverage_gaps=["VISUAL_PAGE_COUNT"],
        evidence_detail=None,
    )

    result = validate_qa_report(report)

    assert result["passed"] is False
    assert any("QA_EVIDENCE_MISSING" in error for error in result["errors"])


def test_pending_human_review_is_not_passed(qa_report):
    report = qa_report(status="PENDING_HUMAN_REVIEW")

    result = validate_qa_report(report)

    assert result["passed"] is True
    assert report["status"] != "PASSED"
