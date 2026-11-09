# -*- coding: utf-8 -*-
"""Transaction commit/abort invariants."""

from __future__ import annotations

from pathlib import Path

import pytest

from engine import (
    DocumentTransaction,
    QA_FAILED,
    TransactionAborted,
    TransactionPreflightError,
    resolve_qa_status,
)


def test_commit_publishes_staged_bytes_and_cleans_temporary_files(tmp_path: Path, make_template):
    source = make_template(tmp_path / "template.docx")
    output = tmp_path / "out.docx"
    tx = DocumentTransaction(str(source), str(output), task_mode="GENERATE")

    with tx:
        Path(tx.stage()).write_bytes(b"staged-docx-bytes")
        tx.record_qa({"passed": True})
        tx.commit()

    assert tx.committed is True
    assert output.read_bytes() == b"staged-docx-bytes"
    assert not Path(tx.temp_path).exists()
    assert not Path(tx.pending_path).exists()
    assert tx.output_sha256 is not None


def test_failed_qa_never_publishes_a_final_file(tmp_path: Path, make_template):
    source = make_template(tmp_path / "template.docx")
    output = tmp_path / "out.docx"
    tx = DocumentTransaction(str(source), str(output), task_mode="GENERATE")
    tx.preflight()
    Path(tx.stage()).write_bytes(b"staged-docx-bytes")
    tx.record_qa(status=QA_FAILED)

    with pytest.raises(TransactionAborted):
        tx.commit()

    assert tx.committed is False
    assert not output.exists()
    assert not Path(tx.temp_path).exists()
    assert not Path(tx.pending_path).exists()
    assert tx.abort_reason == "QA_FAILED"


def test_record_gate_allows_a_valid_passed_report(tmp_path: Path, make_template, qa_report):
    source = make_template(tmp_path / "template.docx")
    output = tmp_path / "out.docx"
    report = qa_report(task_id="TASK_TEST_0001")
    tx = DocumentTransaction(
        str(source), str(output), task_mode="GENERATE", task_id="TASK_TEST_0001"
    )
    tx.preflight()
    Path(tx.stage()).write_bytes(b"staged-docx-bytes")
    tx.record_qa(report)
    tx.record_gate(report)

    tx.commit()

    assert tx.committed is True
    assert output.exists()


def test_record_gate_refuses_an_ineligible_report_at_commit(
    tmp_path: Path, make_template, qa_report
):
    source = make_template(tmp_path / "template.docx")
    output = tmp_path / "out.docx"
    report = qa_report(
        status="UNVERIFIED",
        gate_mode="STRICT",
        missing_checks=["VISUAL_PAGE_COUNT"],
        coverage_gaps=["VISUAL_PAGE_COUNT"],
    )
    tx = DocumentTransaction(
        str(source), str(output), task_mode="GENERATE", task_id="TASK_TEST_0001"
    )
    tx.preflight()
    Path(tx.stage()).write_bytes(b"staged-docx-bytes")
    tx.record_qa(report)
    tx.record_gate(report)

    with pytest.raises(TransactionAborted, match="QA_GATE_REJECTED"):
        tx.commit()

    assert not output.exists()


def test_record_gate_rejects_task_id_mismatch(tmp_path: Path, make_template, qa_report):
    source = make_template(tmp_path / "template.docx")
    output = tmp_path / "out.docx"
    report = qa_report(task_id="TASK_OTHER_0001")
    tx = DocumentTransaction(
        str(source), str(output), task_mode="GENERATE", task_id="TASK_TEST_0001"
    )
    tx.preflight()
    Path(tx.stage()).write_bytes(b"staged-docx-bytes")

    with pytest.raises(TransactionAborted, match="QA_TASK_BINDING_MISMATCH"):
        tx.record_gate(report)

    assert output.exists() is False


def test_preflight_rejects_cross_family_output(tmp_path: Path, make_template):
    source = make_template(tmp_path / "template.docx")
    tx = DocumentTransaction(str(source), str(tmp_path / "out.xlsx"))

    report = tx.preflight()

    assert report["passed"] is False
    failed = {item["name"] for item in report["checks"] if item["required"] and not item["ok"]}
    assert "output_container_family" in failed


def test_output_container_family_rejection_raises_on_enter(tmp_path: Path, make_template):
    source = make_template(tmp_path / "template.docx")
    tx = DocumentTransaction(str(source), str(tmp_path / "out.xlsx"))

    with pytest.raises(TransactionPreflightError):
        tx.__enter__()


def test_resolve_qa_status_uses_four_state_precedence():
    failed = {"issues": [{"code": "X", "severity": "high", "blocking": True}]}
    pending = {"issues": [{"code": "TEMPLATE_TEXT_RESIDUAL", "severity": "medium", "blocking": False}]}
    unverified = {"coverage_gaps": ["VISUAL_PAGE_COUNT"]}
    passed = {"passed": True}

    assert resolve_qa_status(passed) == "PASSED"
    assert resolve_qa_status(failed) == "FAILED"
    assert resolve_qa_status(unverified) == "UNVERIFIED"
    assert resolve_qa_status(
        pending, pending_codes=("TEMPLATE_TEXT_RESIDUAL",)
    ) == "PENDING_HUMAN_REVIEW"
    assert resolve_qa_status({"passed": False}) == "FAILED"
    assert resolve_qa_status({"status": "FAILED", "coverage_gaps": ["x"]}) == "FAILED"
    assert resolve_qa_status(
        {"status": "UNVERIFIED", "issues": [{"code": "TEMPLATE_TEXT_RESIDUAL", "severity": "medium", "blocking": False}]},
        pending_codes=("TEMPLATE_TEXT_RESIDUAL",),
    ) == "PENDING_HUMAN_REVIEW"
