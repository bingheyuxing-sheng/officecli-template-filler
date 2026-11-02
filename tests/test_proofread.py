# -*- coding: utf-8 -*-
"""
v3.5 M8 — PROOFREAD mode tests.

Proofreading a single document must produce a real Word deliverable in revision mode
(plus a snapshot), not a report about typos.
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

from engine import audit_review_integrity, list_revisions, review_snapshot_path


class TestProofreadSuite(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(prefix="office_proofread_")
        self.work_dir = self.temp_dir.name

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_v35_proofread_cli_emits_tracked_docx(self) -> None:
        """The deliverable is a .docx with tracked fixes and a snapshot, not a text report."""
        target = os.path.join(self.work_dir, "draft.docx")
        document = docx.Document()
        document.add_paragraph("试验结果不符合规范，请核对。")
        document.save(target)

        revisions = os.path.join(self.work_dir, "revisions.json")
        with open(revisions, "w", encoding="utf-8") as handle:
            json.dump([{"old_text": "试验", "new_text": "实验", "reason": "错别字"}], handle, ensure_ascii=False)

        output = os.path.join(self.work_dir, "proofread.docx")
        report_path = os.path.join(self.work_dir, "proofread_report.json")
        result = subprocess.run(
            [
                sys.executable,
                os.path.join(ROOT_DIR, "scripts", "proofread_document.py"),
                "--target", target,
                "--out", output,
                "--revisions", revisions,
                "--report", report_path,
            ],
            cwd=ROOT_DIR,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

        with open(report_path, "r", encoding="utf-8") as handle:
            report = json.load(handle)
        self.assertEqual(report["task_mode"], "PROOFREAD")
        self.assertTrue(report["passed"])
        self.assertTrue(report["transaction"]["committed"])

        self.assertTrue(os.path.isfile(output))
        self.assertTrue(os.path.isfile(review_snapshot_path(output)))
        revisions_written = list_revisions(output)
        self.assertTrue(any(item["type"] == "del" and item["text"] == "试验" for item in revisions_written))
        self.assertTrue(any(item["type"] == "ins" and item["text"] == "实验" for item in revisions_written))
        self.assertTrue(audit_review_integrity(output)["passed"])


if __name__ == "__main__":
    unittest.main()
