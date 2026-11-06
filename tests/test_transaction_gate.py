# -*- coding: utf-8 -*-
"""W2 — transaction-level QAReport gate (second gate).

The executor already refuses to commit an ineligible QAReport. These tests
cover the defense-in-depth gate inside ``DocumentTransaction`` itself: a caller
that sets a passing ``qa_status`` still cannot publish an ineligible report, a
report bound to a different task, or a report describing bytes that changed
after the gate was recorded.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gate_helpers import ensure_gate  # noqa: E402

import docx  # noqa: E402

from content_intelligence import build_content_plan, build_fill_plan  # noqa: E402
from document_engine import execute_fill_plan  # noqa: E402
from engine import DocumentTransaction, TransactionAborted  # noqa: E402
from qa.gate import resolve_required_checks  # noqa: E402
from qa.report_builder import build_qa_report, check_record  # noqa: E402

TASK_ID = "TASK_W2_GATE_001"


def _sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _qa_report(staged: str, *, gate_mode: str = "STRICT", skip_check: str | None = None) -> dict:
    """A contract-valid QAReport: every required check PASSED unless skipped."""
    policy = resolve_required_checks("GENERATE", gate_mode)
    checks = []
    for check_id in policy["required"]:
        if check_id == skip_check:
            checks.append(
                check_record(
                    check_id,
                    "SKIPPED",
                    "w2_gate_stub",
                    artifact_path=staged,
                    detail="forced unavailable for the W2 gate test",
                )
            )
        else:
            checks.append(
                check_record(
                    check_id,
                    "PASSED",
                    "w2_gate_stub",
                    artifact_path=staged,
                    detail="forced pass for the W2 gate test",
                )
            )
    return build_qa_report(
        task_id=TASK_ID,
        task_mode="GENERATE",
        gate_mode=gate_mode,
        checks=checks,
    )


def _source_docx(directory: str, name: str = "source.docx") -> str:
    path = os.path.join(directory, name)
    document = docx.Document()
    document.add_paragraph("原始内容")
    document.save(path)
    return path


def _staged_leftovers(directory: str) -> list:
    return sorted(
        name for name in os.listdir(directory)
        if ".tmp-" in name or ".pending-" in name
    )


def _make_executor_bundle(directory: str) -> tuple:
    """One body slot, described by the real producers."""
    from template_intelligence import build_document_spec_from_path
    from template_intelligence.spec_validator import validate_document_spec

    template = os.path.join(directory, "template.docx")
    document = docx.Document()
    document.add_paragraph("{{项目名称}}")
    document.save(template)
    ensure_gate(template, "GENERATE")

    spec = build_document_spec_from_path(template)
    assert validate_document_spec(spec)["passed"], validate_document_spec(spec)["errors"][:3]
    slot = next(item for item in spec["slots"] if item.get("matched_text") == "{{项目名称}}")

    content = build_content_plan(
        spec,
        plan_id="CP_W2_GATE",
        sections=[
            {"section_id": "SEC_001", "purpose": "项目名称", "target_slots": [slot["slot_id"]]}
        ],
        facts=[],
        required_slots=[slot["slot_id"]],
    )
    plan = build_fill_plan(
        spec,
        content,
        task_id=TASK_ID,
        values_by_slot={slot["slot_id"]: "示例项目"},
    )
    return template, spec, content, plan


class TransactionGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="w2_tx_gate_")
        self.directory = self._tmp.name
        self.source = _source_docx(self.directory)
        self.output = os.path.join(self.directory, "out.docx")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _staged_tx(self, task_id: str | None = TASK_ID) -> DocumentTransaction:
        tx = DocumentTransaction(self.source, self.output, task_mode="GENERATE", task_id=task_id)
        self.assertTrue(tx.preflight()["passed"], tx.preflight())
        document = docx.Document(self.source)
        document.add_paragraph("新增内容")
        document.save(tx.stage())
        return tx

    # ------------------------------------------------------------------ gate

    def test_ineligible_report_is_refused_at_commit(self) -> None:
        """A valid but ineligible report must not publish, even with a passing qa_status."""
        tx = self._staged_tx()
        report = _qa_report(tx.temp_path, gate_mode="STRICT", skip_check="VISUAL_PAGE_COUNT")
        tx.record_qa(report)
        gate = tx.record_gate(report)

        self.assertFalse(gate["eligible"])
        self.assertTrue(gate["missing_checks"])
        self.assertEqual(gate["staged_sha256"], _sha256(tx.temp_path))

        with self.assertRaises(TransactionAborted) as ctx:
            tx.commit()
        self.assertEqual(ctx.exception.reason, "QA_GATE_REJECTED")
        self.assertFalse(tx.committed)
        self.assertFalse(os.path.exists(self.output))
        self.assertEqual(_staged_leftovers(self.directory), [])

    def test_eligible_report_publishes(self) -> None:
        """The same transaction with an eligible report still publishes normally."""
        tx = self._staged_tx()
        report = _qa_report(tx.temp_path, gate_mode="STRICT")
        tx.record_qa(report)
        gate = tx.record_gate(report)

        self.assertTrue(gate["eligible"])
        self.assertTrue(gate["recorded"])
        self.assertEqual(gate["staged_sha256"], _sha256(tx.temp_path))
        self.assertEqual(gate["policy_source"], "GENERATE/STRICT")
        self.assertEqual(gate["task_id"], TASK_ID)

        tx.commit()
        self.assertTrue(tx.committed)
        self.assertTrue(os.path.isfile(self.output))
        self.assertEqual(_sha256(self.output), gate["staged_sha256"])
        self.assertEqual(_staged_leftovers(self.directory), [])

    def test_report_task_id_mismatch_is_refused(self) -> None:
        """A report belonging to another task cannot be bound to this transaction."""
        tx = self._staged_tx()
        report = _qa_report(tx.temp_path)
        report["task_id"] = "TASK_OTHER_001"
        tx.record_qa(report)

        with self.assertRaises(TransactionAborted) as ctx:
            tx.record_gate(report)
        self.assertEqual(ctx.exception.reason, "QA_TASK_BINDING_MISMATCH")
        self.assertFalse(tx.committed)
        self.assertFalse(os.path.exists(self.output))
        self.assertEqual(_staged_leftovers(self.directory), [])
        self.assertEqual(tx.record()["abort_reason"], "QA_TASK_BINDING_MISMATCH")

    def test_staged_file_change_after_gate_is_stale(self) -> None:
        """A change to the staged bytes invalidates the recorded report."""
        tx = self._staged_tx()
        report = _qa_report(tx.temp_path)
        tx.record_qa(report)
        tx.record_gate(report)

        # Simulate a writer/repair touching the staged artifact between gate and commit.
        document = docx.Document(tx.temp_path)
        document.add_paragraph("未经过 QA 的内容")
        document.save(tx.temp_path)

        with self.assertRaises(TransactionAborted) as ctx:
            tx.commit()
        self.assertEqual(ctx.exception.reason, "QA_REPORT_STALE")
        self.assertFalse(tx.committed)
        self.assertFalse(os.path.exists(self.output))
        self.assertEqual(_staged_leftovers(self.directory), [])

    def test_legacy_transaction_without_gate_is_unchanged(self) -> None:
        """Callers that never record a gate keep the v3.5 behaviour."""
        tx = self._staged_tx()
        tx.record_qa({"passed": True, "issues": []})
        tx.commit()

        self.assertTrue(tx.committed)
        self.assertTrue(os.path.isfile(self.output))
        record = tx.record()
        self.assertFalse(record["gate"]["recorded"])
        self.assertIsNone(record["gate"]["qa_report_sha256"])

    def test_invalid_report_is_rejected_at_gate_time(self) -> None:
        """A payload that is not a QAReport 4.0 cannot pass the transaction gate."""
        tx = self._staged_tx()
        tx.record_qa({"passed": True, "issues": []})

        with self.assertRaises(TransactionAborted) as ctx:
            tx.record_gate({"task_id": TASK_ID, "status": "PASSED", "issues": []})
        self.assertEqual(ctx.exception.reason, "QA_GATE_REJECTED")
        self.assertFalse(os.path.exists(self.output))
        self.assertEqual(_staged_leftovers(self.directory), [])

    def test_record_exposes_gate_binding_fields(self) -> None:
        """The transaction summary carries the report binding for audit."""
        tx = self._staged_tx()
        report = _qa_report(tx.temp_path)
        tx.record_qa(report)
        tx.record_gate(report)

        gate = tx.record()["gate"]
        self.assertEqual(
            set(gate),
            {
                "recorded",
                "staged_sha256",
                "qa_report_sha256",
                "policy_source",
                "required_checks",
                "missing_checks",
                "task_id",
            },
        )
        self.assertEqual(gate["required_checks"], report["required_checks"])
        self.assertEqual(gate["missing_checks"], report["missing_checks"])
        self.assertEqual(gate["task_id"], TASK_ID)
        self.assertEqual(gate["qa_report_sha256"], _sha256_canonical(report))

    # --------------------------------------------------------------- executor

    def test_executor_commits_normal_output_through_the_gate(self) -> None:
        """The production path records the gate and still publishes normal output."""
        template, spec, content, plan = _make_executor_bundle(self.directory)
        plan["mode"] = "STANDARD"
        result = execute_fill_plan(
            template, spec, plan,
            os.path.join(self.directory, "executor_out.docx"),
            content_plan=content, allow_unverified=True,
        )

        self.assertIn(result["status"], ("SUCCESS", "UNVERIFIED"), result["errors"])
        self.assertTrue(result["transaction"]["committed"])
        self.assertTrue(result["transaction"]["gate"]["recorded"])
        self.assertTrue(os.path.isfile(result["data"]["artifact_path"]))
        self.assertEqual(
            result["transaction"]["gate"]["task_id"], TASK_ID
        )

    def test_executor_refuses_strict_unverified(self) -> None:
        """STRICT still refuses an unverified report before publishing."""
        template, spec, content, plan = _make_executor_bundle(self.directory)
        plan["mode"] = "STRICT"

        def runner(staged: str) -> dict:
            return _qa_report(staged, gate_mode="STRICT", skip_check="VISUAL_PAGE_COUNT")

        output = os.path.join(self.directory, "strict_out.docx")
        result = execute_fill_plan(
            template, spec, plan, output,
            content_plan=content, qa_runner=runner, allow_unverified=True,
        )
        self.assertEqual(result["status"], "FAILED")
        self.assertFalse(os.path.exists(output))
        self.assertEqual(result["transaction"]["abort_reason"], "QA_NOT_ELIGIBLE")
        self.assertEqual(_staged_leftovers(self.directory), [])


def _sha256_canonical(payload) -> str:
    canonical = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


if __name__ == "__main__":
    unittest.main()
