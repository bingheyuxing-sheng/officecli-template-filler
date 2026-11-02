# -*- coding: utf-8 -*-
"""
v3.5 M1 — Transaction layer tests.

A deliverable may only appear at its final path after QA has run against the
staged file and has not failed. Failed or unverified-QA runs must leave zero
staged artifacts behind.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

import docx
from docx.shared import Pt, RGBColor

from engine import (
    DocumentTransaction,
    TransactionAborted,
    TransactionPreflightError,
    resolve_qa_status,
)


class TestTransactionSuite(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(prefix="office_tx_test_")
        self.work_dir = self.temp_dir.name

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    # ------------------------------------------------------------------ helpers

    def _source_docx(self, name: str = "source.docx", text: str = "原始内容") -> str:
        path = os.path.join(self.work_dir, name)
        document = docx.Document()
        document.add_paragraph(text)
        document.save(path)
        return path

    def _staged_leftovers(self) -> list:
        return [
            name for name in os.listdir(self.work_dir)
            if ".tmp-" in name or ".pending-" in name
        ]

    # ------------------------------------------------------------------ tests

    def test_v35_transaction_atomic_commit(self) -> None:
        """A successful QA run publishes the staged file and leaves no intermediates."""
        source = self._source_docx()
        output = os.path.join(self.work_dir, "out.docx")
        tx = DocumentTransaction(source, output, task_mode="TEST")

        self.assertTrue(tx.preflight()["passed"], tx.preflight())
        with tx:
            document = docx.Document(source)
            document.add_paragraph("新增内容")
            document.save(tx.stage())
            tx.record_qa({"passed": True, "issues": []})
            self.assertFalse(os.path.exists(output), "final path must not exist before commit")
            tx.commit()

        self.assertTrue(tx.committed)
        self.assertTrue(os.path.isfile(output))
        self.assertEqual(tx.qa_status, "PASSED")
        self.assertEqual(self._staged_leftovers(), [])
        record = tx.record()
        self.assertTrue(record["transaction_id"])
        self.assertTrue(record["input_sha256"])
        self.assertTrue(record["output_sha256"])
        self.assertNotEqual(record["input_sha256"], record["output_sha256"])
        self.assertIsNone(record["abort_reason"])

    def test_v35_transaction_aborts_on_qa_failure(self) -> None:
        """Failed QA must delete the staged file and never create the final path."""
        source = self._source_docx()
        output = os.path.join(self.work_dir, "out.docx")
        tx = DocumentTransaction(source, output, task_mode="TEST")

        with self.assertRaises(TransactionAborted):
            with tx:
                document = docx.Document(source)
                document.add_paragraph("残留文字")
                document.save(tx.stage())
                self.assertTrue(os.path.isfile(tx.temp_path))
                tx.record_qa({
                    "passed": False,
                    "issues": [{
                        "code": "RED_TEXT_RESIDUAL",
                        "location": "body.p[1]",
                        "detail": "残留文字",
                        "severity": "high",
                    }],
                })
                tx.commit()

        self.assertFalse(tx.committed)
        self.assertEqual(tx.qa_status, "FAILED")
        self.assertEqual(tx.record()["abort_reason"], "QA_FAILED")
        self.assertFalse(os.path.exists(output))
        self.assertEqual(self._staged_leftovers(), [])

    def test_v35_transaction_refuses_commit_without_qa(self) -> None:
        """No QA report means no proof, so the deliverable must not be published."""
        source = self._source_docx()
        output = os.path.join(self.work_dir, "out.docx")
        tx = DocumentTransaction(source, output, task_mode="TEST")

        with self.assertRaises(TransactionAborted) as ctx:
            with tx:
                document = docx.Document(source)
                document.save(tx.stage())
                tx.commit()

        self.assertEqual(ctx.exception.reason, "QA_NOT_RUN")
        self.assertFalse(os.path.exists(output))
        self.assertEqual(self._staged_leftovers(), [])

    def test_v35_transaction_unverified_is_committed_but_not_passed(self) -> None:
        """Coverage gaps publish the file yet keep the status honest (UNVERIFIED)."""
        source = self._source_docx()
        output = os.path.join(self.work_dir, "out.docx")
        tx = DocumentTransaction(source, output, task_mode="TEST")

        with tx:
            document = docx.Document(source)
            document.save(tx.stage())
            tx.record_qa({
                "passed": True,
                "issues": [],
                "coverage_gaps": ["RENDER_PDF_NOT_PRODUCED"],
                "unverified_count": 1,
            })
            tx.commit()

        self.assertTrue(tx.committed)
        self.assertEqual(tx.qa_status, "UNVERIFIED")
        self.assertTrue(os.path.isfile(output))

    def test_v35_transaction_preflight_rejects_unsupported_input(self) -> None:
        """A non-Office input must fail preflight instead of producing a fake document."""
        source = os.path.join(self.work_dir, "input.pdf")
        with open(source, "wb") as handle:
            handle.write(b"%PDF-1.4")
        output = os.path.join(self.work_dir, "out.docx")
        tx = DocumentTransaction(source, output, task_mode="TEST")

        report = tx.preflight()
        self.assertFalse(report["passed"])
        failed = [c["name"] for c in report["checks"] if c["required"] and not c["ok"]]
        self.assertIn("source_extension", failed)

        with self.assertRaises(TransactionPreflightError):
            with tx:
                pass

    def test_v35_transaction_preflight_rejects_cross_family_output(self) -> None:
        """Word input must not be published as an Excel deliverable."""
        source = self._source_docx()
        output = os.path.join(self.work_dir, "out.xlsx")
        tx = DocumentTransaction(source, output, task_mode="TEST")

        report = tx.preflight()
        self.assertFalse(report["passed"])
        failed = [c["name"] for c in report["checks"] if c["required"] and not c["ok"]]
        self.assertIn("output_container_family", failed)

    def test_v35_generate_cli_aborts_on_residual_placeholder(self) -> None:
        """The generate entrypoint must exit non-zero and leave no output when QA fails."""
        template = os.path.join(self.work_dir, "template.docx")
        document = docx.Document()
        document.add_paragraph("项目名称：{{project}}")
        document.save(template)
        payload = os.path.join(self.work_dir, "payload.json")
        with open(payload, "w", encoding="utf-8") as handle:
            json.dump({"tokens": {}}, handle)
        output = os.path.join(self.work_dir, "generated.docx")

        result = subprocess.run(
            [
                sys.executable,
                os.path.join(ROOT_DIR, "scripts", "generate_document.py"),
                "--template", template,
                "--data", payload,
                "--out", output,
            ],
            cwd=ROOT_DIR,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        self.assertNotEqual(result.returncode, 0, result.stdout)
        report = json.loads(result.stdout)
        self.assertFalse(report["transaction"]["committed"])
        self.assertEqual(report["transaction"]["qa_status"], "FAILED")
        self.assertIn("TEMPLATE_TEXT_RESIDUAL", json.dumps(report["qa_issues"], ensure_ascii=False))
        self.assertFalse(os.path.exists(output))
        self.assertEqual(self._staged_leftovers(), [])

    def test_v35_repair_cli_checks_format_not_only_package(self) -> None:
        """REPAIR must verify the repaired formatting against the reference before committing."""
        reference = os.path.join(self.work_dir, "ref.docx")
        ref_doc = docx.Document()
        ref_para = ref_doc.add_paragraph()
        ref_run = ref_para.add_run("正文内容")
        ref_run.font.size = Pt(12)
        ref_doc.save(reference)

        broken = os.path.join(self.work_dir, "broken.docx")
        broken_doc = docx.Document()
        broken_para = broken_doc.add_paragraph()
        broken_run = broken_para.add_run("正文内容")
        broken_run.font.size = Pt(18)
        broken_run.font.color.rgb = RGBColor(0xFF, 0x00, 0x00)
        broken_doc.save(broken)

        output = os.path.join(self.work_dir, "repaired.docx")
        result = subprocess.run(
            [
                sys.executable,
                os.path.join(ROOT_DIR, "scripts", "repair_document.py"),
                "--reference", reference,
                "--broken", broken,
                "--out", output,
            ],
            cwd=ROOT_DIR,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        report = json.loads(result.stdout)
        self.assertTrue(report["package_qa_passed"], report)
        self.assertTrue(report["format_qa_passed"], report)
        self.assertTrue(report["transaction"]["committed"])
        self.assertTrue(os.path.isfile(output))
        self.assertEqual(self._staged_leftovers(), [])

    def test_v35_run_qa_unverified_outranks_pending_review(self) -> None:
        """A missing render check must not hide behind intentional placeholder residue."""
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "run_qa_module", os.path.join(ROOT_DIR, "scripts", "run_qa.py")
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        residual = [{"code": "TEMPLATE_TEXT_RESIDUAL", "location": "body.p[0]",
                     "detail": "{{x}}", "severity": "medium"}]
        status, failures, pending = module.resolve_report_status(
            residual, ["RENDER_PDF_NOT_PRODUCED"], 1, True
        )
        self.assertEqual(status, "UNVERIFIED")
        self.assertEqual(failures, [])
        self.assertEqual(len(pending), 1)

        status, _failures, _pending = module.resolve_report_status(residual, [], 0, True)
        self.assertEqual(status, "PENDING_HUMAN_REVIEW")

    def test_v35_qa_status_folding(self) -> None:
        """Status folding must never turn an unverifiable check into PASSED."""
        self.assertEqual(resolve_qa_status({"passed": True, "issues": []}), "PASSED")
        self.assertEqual(
            resolve_qa_status({"passed": True, "coverage_gaps": ["X"], "unverified_count": 0}),
            "UNVERIFIED",
        )
        self.assertEqual(
            resolve_qa_status({"passed": True, "issues": [{"code": "TEMPLATE_TEXT_RESIDUAL"}]}),
            "FAILED",
        )
        self.assertEqual(
            resolve_qa_status(
                {"passed": True, "issues": [{"code": "TEMPLATE_TEXT_RESIDUAL"}]},
                pending_codes=("TEMPLATE_TEXT_RESIDUAL",),
            ),
            "PENDING_HUMAN_REVIEW",
        )
        self.assertEqual(resolve_qa_status({"passed": False, "issues": []}), "FAILED")


if __name__ == "__main__":
    unittest.main()
