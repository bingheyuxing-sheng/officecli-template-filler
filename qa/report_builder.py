# -*- coding: utf-8 -*-
"""QAReport 4.0 builder (Contract 04).

The overall status and ``final.eligible_for_commit`` are computed here from
evidence, never asserted by a caller.  Every built report is validated with
:func:`qa.gate.validate_qa_report` before it is returned.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .gate import (
    UNEXECUTED_STATUSES,
    compute_commit_eligibility,
    resolve_required_checks,
    validate_qa_report,
)

_SEVERITIES = frozenset({"high", "medium", "low"})


def _normalize_severity(value: Any) -> str:
    severity = str(value or "high").strip().lower()
    return severity if severity in _SEVERITIES else "high"


def check_record(
    check_id: str,
    status: str,
    method: str,
    *,
    artifact_path: Optional[str] = None,
    detail: Optional[str] = None,
    required: Optional[bool] = None,
    issues: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Build one ``checks[]`` record.  ``required`` is normalized by the builder."""
    evidence: Dict[str, Any] = {"method": str(method)}
    if artifact_path is not None:
        evidence["artifact_path"] = str(artifact_path)
    if detail is not None:
        evidence["detail"] = str(detail)
    record: Dict[str, Any] = {
        "check_id": check_id,
        "required": bool(required) if required is not None else False,
        "status": status,
        "evidence": evidence,
    }
    if issues:
        record["issues"] = list(issues)
    return record


def _list_arg(value: Any, name: str) -> List[Any]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("%s must be a list" % name)
    return value


def _normalize_issues(issues: Any) -> List[Dict[str, Any]]:
    normalized: List[Dict[str, Any]] = []
    for item in _list_arg(issues, "issues"):
        if not isinstance(item, dict):
            raise ValueError("issue record must be an object")
        record = dict(item)
        severity = _normalize_severity(record.get("severity"))
        record["severity"] = severity
        record.setdefault("blocking", severity == "high")
        record.setdefault("location", "report")
        normalized.append(record)
    return normalized


def _normalize_warnings(warnings: Any) -> List[Dict[str, Any]]:
    normalized: List[Dict[str, Any]] = []
    for item in _list_arg(warnings, "warnings"):
        if not isinstance(item, dict):
            raise ValueError("warning record must be an object")
        record = dict(item)
        record["severity"] = _normalize_severity(record.get("severity"))
        normalized.append(record)
    return normalized


def build_qa_report(
    *,
    task_id: str,
    task_mode: str,
    gate_mode: str,
    checks: List[Dict[str, Any]],
    issues: Optional[List[Dict[str, Any]]] = None,
    warnings: Optional[List[Dict[str, Any]]] = None,
    coverage_gaps: Optional[List[str]] = None,
    repairs: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Assemble and validate a QAReport 4.0.

    Required checks are derived from ``config/qa-policy.json``; a caller-supplied
    ``required`` flag is overwritten with the policy membership.
    """
    task_mode = str(task_mode or "").strip().upper()
    gate_mode = str(gate_mode or "").strip().upper()
    policy = resolve_required_checks(task_mode, gate_mode)
    policy_source = policy["policy_source"]
    required = list(policy["required"])

    records: List[Dict[str, Any]] = []
    for item in _list_arg(checks, "checks"):
        if not isinstance(item, dict):
            raise ValueError("check record must be an object")
        check_id = item.get("check_id")
        if not isinstance(check_id, str) or not check_id:
            raise ValueError("check record has no check_id")
        record = dict(item)
        record["required"] = check_id in required
        records.append(record)

    check_ids = [record["check_id"] for record in records]
    duplicates = sorted({check_id for check_id in check_ids if check_ids.count(check_id) > 1})
    if duplicates:
        raise ValueError("duplicate check record: %s" % ", ".join(duplicates))

    status_by_id = {record["check_id"]: record.get("status") for record in records}
    # Contract 04 §3.3: every required check appears exactly once.  A required
    # check with no record is recorded as SKIPPED with its policy reason, so the
    # absence is visible instead of silently disappearing.
    for check_id in required:
        if check_id in status_by_id:
            continue
        record = check_record(
            check_id,
            "SKIPPED",
            "policy_check_not_executed",
            required=True,
            detail="REQUIRED_CHECK_NOT_EXECUTED",
        )
        records.append(record)
        status_by_id[check_id] = "SKIPPED"
    check_ids = [record["check_id"] for record in records]
    missing = [
        check_id
        for check_id in required
        if check_id not in status_by_id or status_by_id[check_id] in UNEXECUTED_STATUSES
    ]
    executed = [
        check_id
        for check_id in check_ids
        if status_by_id.get(check_id) != "SKIPPED" and check_id not in missing
    ]

    issue_records = _normalize_issues(issues)
    warning_records = _normalize_warnings(warnings)
    gaps = [str(item) for item in _list_arg(coverage_gaps, "coverage_gaps") if str(item).strip()]

    blocking_issues = [
        issue
        for issue in issue_records
        if issue.get("blocking") is True or issue.get("severity") == "high"
    ]
    failed_required = [check_id for check_id in required if status_by_id.get(check_id) == "FAILED"]
    pending_required = [
        check_id for check_id in required if status_by_id.get(check_id) == "PENDING_HUMAN_REVIEW"
    ]

    # Contract 04 §2 precedence: FAILED > PENDING_HUMAN_REVIEW > UNVERIFIED > PASSED.
    if blocking_issues or failed_required:
        status = "FAILED"
    elif pending_required:
        status = "PENDING_HUMAN_REVIEW"
    elif missing or gaps:
        status = "UNVERIFIED"
    else:
        status = "PASSED"

    reasons: List[str] = []
    if status == "FAILED":
        for issue in blocking_issues[:5]:
            reasons.append(
                "blocking issue %s at %s" % (issue.get("code"), issue.get("location"))
            )
        for check_id in failed_required:
            reasons.append("required check %s failed" % check_id)
        if not reasons:
            reasons.append("qa failed")
    elif status == "PENDING_HUMAN_REVIEW":
        reasons.append("human review required for: %s" % ", ".join(pending_required))
    elif status == "UNVERIFIED":
        if missing:
            reasons.append("required checks not verified: %s" % ", ".join(missing))
        if gaps:
            reasons.append("coverage gaps: %s" % ", ".join(gaps))
        if not reasons:
            reasons.append("required checks not verified")
    else:
        reasons.append("all required checks passed")

    eligible = compute_commit_eligibility(
        status=status,
        policy_source=policy_source,
        task_mode=task_mode,
        missing_checks=missing,
        coverage_gaps=gaps,
        checks=records,
    )
    if eligible:
        reasons.append("commit eligible under %s" % policy_source)
    else:
        reasons.append("commit not eligible under %s (status %s)" % (policy_source, status))

    report: Dict[str, Any] = {
        "schema_version": "4.0",
        "task_id": task_id,
        "status": status,
        "task_mode": task_mode,
        "gate_mode": gate_mode,
        "policy_source": policy_source,
        "required_checks": list(required),
        "executed_checks": executed,
        "missing_checks": missing,
        "checks": records,
        "issues": issue_records,
        "warnings": warning_records,
        "coverage_gaps": gaps,
        "repairs": _list_arg(repairs, "repairs"),
        "final": {"eligible_for_commit": eligible, "reasons": reasons},
    }

    result = validate_qa_report(report)
    if not result["passed"]:
        raise ValueError(
            "invalid QAReport: " + "; ".join(result["errors"][:8])
        )
    return report
