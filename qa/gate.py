# -*- coding: utf-8 -*-
"""QAReport 4.0 policy gate (Contract 04).

The policy matrix is system-owned: callers may not supply or weaken
``required_checks``.  Everything here is derived from ``config/qa-policy.json``
and the frozen JSON Schema ``schemas/qa_report-4.0.schema.json``.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "config" / "qa-policy.json"
SCHEMA_PATH = ROOT / "schemas" / "qa_report-4.0.schema.json"

# Statuses that mean a required check did not produce a verdict.
UNEXECUTED_STATUSES = frozenset({"SKIPPED", "UNVERIFIED"})


class QAGateError(ValueError):
    """Raised when a QAReport is invalid or does not authorize a commit."""

    def __init__(self, message: str, report: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message)
        self.report = report


@lru_cache(maxsize=1)
def _policies() -> Dict[str, Dict[str, Any]]:
    with open(POLICY_PATH, "r", encoding="utf-8") as handle:
        return json.load(handle)["policies"]


@lru_cache(maxsize=1)
def _validator() -> Draft202012Validator:
    with open(SCHEMA_PATH, "r", encoding="utf-8") as handle:
        return Draft202012Validator(json.load(handle))


def resolve_required_checks(task_mode: str, gate_mode: str) -> Dict[str, List[str]]:
    """Return the policy-owned check set for ``task_mode/gate_mode``.

    ``policy_source`` is always ``"{task_mode}/{gate_mode}"``; an unknown pair
    raises ``ValueError`` rather than falling back to a weaker policy.
    """
    policy_source = "%s/%s" % (
        str(task_mode or "").strip().upper(),
        str(gate_mode or "").strip().upper(),
    )
    policies = _policies()
    if policy_source not in policies:
        raise ValueError("unknown QA policy pair: %s" % policy_source)
    policy = policies[policy_source]
    return {
        "policy_source": policy_source,
        "required": list(policy["required"]),
        "optional": list(policy.get("optional", [])),
    }


def compute_commit_eligibility(
    *,
    status: Any,
    policy_source: Any,
    task_mode: Any,
    missing_checks: Any,
    coverage_gaps: Any,
    checks: Any,
) -> bool:
    """Contract 04 §7 eligibility table, applied to a report's own fields."""
    status = str(status or "")
    source = str(policy_source or "")
    missing = [item for item in (missing_checks or []) if isinstance(item, str)]
    gaps = [item for item in (coverage_gaps or []) if isinstance(item, str)]

    if source.endswith("/STRICT"):
        return status == "PASSED" and not missing and not gaps

    if source.endswith("/STANDARD"):
        if status not in ("PASSED", "PENDING_HUMAN_REVIEW", "UNVERIFIED"):
            return False
        # UNVERIFIED may still be committed only when the missing checks are
        # disclosed (Contract 04 §7).  The reason text is the disclosure.
        return True

    if str(task_mode or "").upper() == "REVIEW":
        if status not in ("PASSED", "PENDING_HUMAN_REVIEW"):
            return False
        return _status_of(checks, "REVIEW_INTEGRITY") == "PASSED"

    # REPAIR/REPLICA and any other policy: only a clean pass is committable.
    return status == "PASSED" and not missing and not gaps


def _status_of(checks: Any, check_id: str) -> Optional[str]:
    if not isinstance(checks, list):
        return None
    for record in checks:
        if isinstance(record, dict) and record.get("check_id") == check_id:
            return record.get("status")
    return None


def _records_by_id(checks: Any) -> Dict[str, List[Dict[str, Any]]]:
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    if not isinstance(checks, list):
        return grouped
    for record in checks:
        if isinstance(record, dict) and isinstance(record.get("check_id"), str):
            grouped.setdefault(record["check_id"], []).append(record)
    return grouped


def _string_list(value: Any) -> List[str]:
    return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []


def _issues_of(report: Dict[str, Any]) -> List[Any]:
    issues: List[Any] = []
    top_level = report.get("issues")
    if isinstance(top_level, list):
        issues.extend(top_level)
    checks = report.get("checks")
    if isinstance(checks, list):
        for record in checks:
            if isinstance(record, dict) and isinstance(record.get("issues"), list):
                issues.extend(record["issues"])
    return issues


def _is_blocking(issue: Any) -> bool:
    if not isinstance(issue, dict):
        return False
    return issue.get("blocking") is True or str(issue.get("severity") or "").lower() == "high"


def validate_qa_report(report: Any) -> Dict[str, Any]:
    """Validate a QAReport against the schema and Contract 04 semantics.

    Returns ``{"passed", "errors", "warnings"}``.  Never raises for a
    malformed report; schema and semantic failures are collected as errors so
    the caller can report all reasons at once.
    """
    errors: List[str] = []
    warnings: List[str] = []

    if not isinstance(report, dict):
        return {"passed": False, "errors": ["QA_REPORT_NOT_OBJECT"], "warnings": warnings}

    for error in sorted(_validator().iter_errors(report), key=lambda item: list(item.absolute_path)):
        path = "/".join(str(part) for part in error.absolute_path) or "$"
        errors.append("SCHEMA_ERROR[%s]: %s" % (path, error.message))

    policies = _policies()
    task_mode = report.get("task_mode")
    gate_mode = report.get("gate_mode")
    policy_source = report.get("policy_source")
    expected_binding = "%s/%s" % (task_mode, gate_mode)
    if policy_source != expected_binding:
        errors.append("QA_POLICY_SOURCE_MISMATCH: %s != %s" % (policy_source, expected_binding))

    policy = policies.get(policy_source) if isinstance(policy_source, str) else None
    if policy is None:
        errors.append("QA_POLICY_SOURCE_UNKNOWN: %s" % (policy_source,))
        expected_required: List[str] = []
    else:
        expected_required = list(policy["required"])

    required = _string_list(report.get("required_checks"))
    required_set = set(required)
    if expected_required and required_set != set(expected_required):
        errors.append(
            "QA_POLICY_OVERRIDE_FORBIDDEN: required_checks differs from policy %s" % policy_source
        )

    missing = _string_list(report.get("missing_checks"))
    missing_set = set(missing)
    if missing_set - required_set:
        errors.append("QA_CONTRACT: missing_checks contains non-required checks")

    grouped = _records_by_id(report.get("checks"))
    for check_id in required:
        records = grouped.get(check_id, [])
        if not records:
            errors.append("required check record missing: %s" % check_id)
        elif len(records) > 1:
            errors.append("duplicate check record: %s" % check_id)
        elif records[0].get("required") is not True:
            errors.append("required flag false for required check: %s" % check_id)
    for check_id, records in grouped.items():
        is_required = check_id in required_set
        for record in records:
            if record.get("required") != is_required:
                errors.append("required flag mismatch: %s" % check_id)

    # Evidence rules: a check without a verdict must say why.
    for check_id, records in grouped.items():
        for record in records:
            status = record.get("status")
            evidence = record.get("evidence") if isinstance(record.get("evidence"), dict) else {}
            detail = str(evidence.get("detail") or "").strip()
            if status in UNEXECUTED_STATUSES and not detail:
                errors.append("QA_EVIDENCE_MISSING: %s %s requires evidence.detail" % (check_id, status))
            if status == "PASSED" and not str(evidence.get("method") or "").strip():
                errors.append("QA_EVIDENCE_MISSING: %s PASSED requires evidence.method" % check_id)

    status = report.get("status")
    issues = _issues_of(report)
    blocking_issues = [issue for issue in issues if _is_blocking(issue)]

    for issue in issues:
        if not isinstance(issue, dict):
            continue
        if issue.get("blocking") is False and str(issue.get("severity") or "").lower() == "high":
            errors.append(
                "QA_ISSUE_CONTRADICTION: high severity issue %s must be blocking"
                % issue.get("code")
            )

    all_required_passed = all(
        len(grouped.get(check_id, [])) == 1
        and grouped[check_id][0].get("status") == "PASSED"
        for check_id in required
    )
    coverage_gaps = report.get("coverage_gaps") if isinstance(report.get("coverage_gaps"), list) else []

    if status == "PASSED":
        if missing:
            errors.append("QA_FALSE_PASS: status PASSED with missing_checks")
        if not all_required_passed:
            errors.append("QA_FALSE_PASS: not every required check is PASSED")
        if coverage_gaps:
            errors.append("QA_FALSE_PASS: coverage_gaps present")
        if blocking_issues:
            errors.append("QA_FALSE_PASS: blocking or high issue under PASSED")

    if status == "FAILED" and not blocking_issues:
        errors.append("FAILED without a blocking or high issue")

    repairs = report.get("repairs") if isinstance(report.get("repairs"), list) else []
    seen_repair_ids = set()
    for repair in repairs:
        if not isinstance(repair, dict):
            continue
        repair_id = repair.get("repair_id")
        if isinstance(repair_id, str):
            if repair_id in seen_repair_ids:
                errors.append("duplicate repair_id: %s" % repair_id)
            seen_repair_ids.add(repair_id)
        if repair.get("applied") is True:
            recheck = repair.get("recheck") if isinstance(repair.get("recheck"), dict) else {}
            recheck_status = recheck.get("status")
            if not recheck_status:
                errors.append("QA_REPAIR_UNVERIFIED: %s was applied without a recheck" % repair_id)
            elif recheck_status == "SKIPPED":
                errors.append("QA_REPAIR_UNVERIFIED: %s recheck was skipped" % repair_id)

    final = report.get("final") if isinstance(report.get("final"), dict) else {}
    expected_eligible = compute_commit_eligibility(
        status=status,
        policy_source=policy_source,
        task_mode=task_mode,
        missing_checks=missing,
        coverage_gaps=coverage_gaps,
        checks=report.get("checks"),
    )
    if final.get("eligible_for_commit") != expected_eligible:
        errors.append(
            "QA_ELIGIBILITY_CONTRADICTION: eligible_for_commit=%r expected=%r under %s"
            % (final.get("eligible_for_commit"), expected_eligible, policy_source)
        )
    elif (
        expected_eligible
        and str(policy_source or "").endswith("/STANDARD")
        and status == "UNVERIFIED"
        and missing
    ):
        reason_text = " ".join(_string_list(final.get("reasons")))
        undisclosed = [check_id for check_id in missing if check_id not in reason_text]
        if undisclosed:
            errors.append(
                "QA_ELIGIBILITY_CONTRADICTION: missing_checks not disclosed in reasons: %s"
                % ", ".join(undisclosed)
            )

    return {"passed": not errors, "errors": errors, "warnings": warnings}


def assert_commit_eligible(report: Any) -> Dict[str, Any]:
    """Raise ``QAGateError`` unless ``report`` is valid and authorizes a commit."""
    result = validate_qa_report(report)
    if not result["passed"]:
        raise QAGateError(
            "QAReport is invalid: " + "; ".join(result["errors"][:5]),
            report=report if isinstance(report, dict) else None,
        )
    final = report.get("final") if isinstance(report.get("final"), dict) else {}
    if final.get("eligible_for_commit") is not True:
        raise QAGateError(
            "QAReport is not eligible for commit (status=%s, policy_source=%s)"
            % (report.get("status"), report.get("policy_source")),
            report=report,
        )
    return report
