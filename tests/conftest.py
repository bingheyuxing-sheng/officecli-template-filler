# -*- coding: utf-8 -*-
"""Shared fixtures for the regression suite.

Tests never touch the user's real gate or cache directories.  The factories
below build only the small, schema-valid objects needed by the invariant tests.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

import docx
import pytest
from docx.shared import RGBColor

from engine import __version__ as ENGINE_VERSION
from qa.gate import compute_commit_eligibility, resolve_required_checks
from template_gate.analyzer import _spec_digest, load_policy
from template_gate.models import ANALYSIS_VERSION


def _sha256_path(path: os.PathLike[str] | str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _make_template(path: os.PathLike[str] | str, text: str = "Project Proposal") -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    document = docx.Document()
    document.add_heading(text, level=0)
    paragraph = document.add_paragraph("Client: ")
    run = paragraph.add_run("{{client}}")
    run.font.color.rgb = RGBColor(0xFF, 0, 0)
    table = document.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "Item"
    table.cell(0, 1).text = "Amount"
    table.cell(1, 0).text = "{{item}}"
    table.cell(1, 1).text = "{{amount}}"
    document.save(target)
    return target


def _make_spec(template_sha256: str) -> Dict[str, Any]:
    fingerprint_ref = {
        "fingerprint_id": "FP_001",
        "structural_hash": "a" * 64,
        "style_hash": "b" * 64,
        "protected_hash": "c" * 64,
        "layout_hash": "d" * 64,
    }
    return {
        "schema_version": "4.0",
        "template": {
            "template_sha256": template_sha256,
            "template_name": "template.docx",
        },
        "fingerprint_ref": fingerprint_ref,
        "slots": [],
        "tables": [],
        "protected_regions": [],
        "errors": [],
        "warnings": [],
    }


def _make_analysis(
    template_path: os.PathLike[str] | str,
    spec: Dict[str, Any],
    task_type: str = "GENERATE",
) -> Dict[str, Any]:
    path = Path(template_path)
    sha256 = _sha256_path(path)
    return {
        "schema_version": "1.0",
        "analysis_id": "analysis_" + "a" * 12,
        "template_sha256": sha256,
        "template_name": path.name,
        "spec_schema_version": spec.get("schema_version", "4.0"),
        "spec_digest": _spec_digest(spec),
        "fingerprint_ref": dict(spec.get("fingerprint_ref") or {}),
        "analysis_version": ANALYSIS_VERSION,
        "parser_version": ENGINE_VERSION,
        "policy_version": str(load_policy().get("version") or "1.0"),
        "task_type": task_type,
        "evidence_digest": "e" * 64,
        "summary": {
            "blocking": 0,
            "unverified": 0,
            "supported": 0,
        },
        "evidence": [],
        "supplements": [],
    }


def _issue(
    code: str = "TEST_FAILURE",
    *,
    severity: str = "high",
    blocking: bool = True,
    detail: str = "synthetic test failure",
) -> Dict[str, Any]:
    return {
        "code": code,
        "severity": severity,
        "location": "document",
        "detail": detail,
        "blocking": blocking,
    }


def _make_qa_report(
    *,
    status: str = "PASSED",
    task_mode: str = "GENERATE",
    gate_mode: str = "STANDARD",
    task_id: str = "TASK_TEST_0001",
    issues: Optional[Iterable[Dict[str, Any]]] = None,
    coverage_gaps: Optional[Iterable[str]] = None,
    missing_checks: Optional[Iterable[str]] = None,
    check_status: str = "PASSED",
    evidence_detail: Optional[str] = "executed by pytest",
    eligible_for_commit: Optional[bool] = None,
    reasons: Optional[Iterable[str]] = None,
    overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    policy = resolve_required_checks(task_mode, gate_mode)
    required = list(policy["required"])
    missing = [str(item) for item in (missing_checks or [])]
    gaps = [str(item) for item in (coverage_gaps or [])]

    checks = []
    for check_id in required:
        status_value = "UNVERIFIED" if check_id in missing else check_status
        evidence: Dict[str, Any] = {"method": "pytest"}
        if status_value in ("UNVERIFIED", "SKIPPED") and evidence_detail is not None:
            evidence["detail"] = evidence_detail
        checks.append(
            {
                "check_id": check_id,
                "required": True,
                "status": status_value,
                "evidence": evidence,
            }
        )

    if issues is None:
        if status == "FAILED":
            resolved_issues = [_issue()]
        elif status == "PENDING_HUMAN_REVIEW":
            resolved_issues = [
                _issue(
                    "TEMPLATE_TEXT_RESIDUAL",
                    severity="medium",
                    blocking=False,
                    detail="placeholder intentionally left for review",
                )
            ]
        else:
            resolved_issues = []
    else:
        resolved_issues = [dict(item) for item in issues]

    if reasons is None:
        resolved_reasons = [
            "missing %s: %s" % (check_id, evidence_detail or "not executed")
            for check_id in missing
        ]
    else:
        resolved_reasons = [str(item) for item in reasons]

    if eligible_for_commit is None:
        eligible = compute_commit_eligibility(
            status=status,
            policy_source=policy["policy_source"],
            task_mode=task_mode,
            missing_checks=missing,
            coverage_gaps=gaps,
            checks=checks,
        )
    else:
        eligible = bool(eligible_for_commit)

    report: Dict[str, Any] = {
        "schema_version": "4.0",
        "task_id": task_id,
        "status": status,
        "task_mode": task_mode,
        "gate_mode": gate_mode,
        "policy_source": policy["policy_source"],
        "required_checks": required,
        "executed_checks": [item for item in required if item not in missing],
        "missing_checks": missing,
        "checks": checks,
        "issues": resolved_issues,
        "warnings": [],
        "coverage_gaps": gaps,
        "repairs": [],
        "final": {
            "eligible_for_commit": eligible,
            "reasons": resolved_reasons,
        },
    }
    if overrides:
        report.update(overrides)
    return report


@pytest.fixture(autouse=True)
def isolated_officecli_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OFFICECLI_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setenv("OFFICECLI_GATE_HOME", str(tmp_path / "gates"))
    monkeypatch.setenv("OFFICECLI_DISABLE_AUTO_CLEANUP", "1")
    monkeypatch.delenv("OFFICECLI_DISABLE_CACHE", raising=False)
    monkeypatch.delenv("OFFICECLI_GATE_TTL_SECONDS", raising=False)


@pytest.fixture
def make_template():
    return _make_template


@pytest.fixture
def make_spec():
    return _make_spec


@pytest.fixture
def make_analysis():
    return _make_analysis


@pytest.fixture
def qa_report():
    return _make_qa_report


@pytest.fixture
def sha256_path():
    return _sha256_path
