# -*- coding: utf-8 -*-
"""REVIEW external-findings path: findings become inline Word comments, never a report."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
import zipfile

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from gate_helpers import ensure_gate  # noqa: E402

import docx

from engine import audit_review_integrity, execute_review_plan  # noqa: E402
from engine.review_engine import build_findings_review_plan  # noqa: E402


class TestReviewFindings(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(prefix="office_review_findings_")
        self.work_dir = self.temp_dir.name

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _target(self) -> str:
        path = os.path.join(self.work_dir, "proposal.docx")
        document = docx.Document()
        document.add_paragraph("一、培养目标")
        document.add_paragraph("本专业培养信息技术安全技术应用人才。")
        table = document.add_table(rows=2, cols=2)
        table.cell(0, 0).text = "课程"
        table.cell(0, 1).text = "学分"
        table.cell(1, 0).text = "网络安全实训"
        table.cell(1, 1).text = "4"
        document.save(path)
        ensure_gate(path, "REVIEW")
        return path

    def test_findings_become_comments_in_the_target_document(self) -> None:
        target = self._target()
        output = os.path.join(self.work_dir, "proposal_reviewed.docx")
        findings = {
            "findings": [
                {
                    "location": "body.p[1]",
                    "comment": "与表1不一致：本课程总学时应为 16。",
                    "code": "CONTENT_VALUE_CONFLICT",
                    "severity": "high",
                },
                {
                    "location": "body.tbl[0].r[1].c[1]",
                    "detail": "表格学分与正文表述不一致，请核对。",
                    "severity": "medium",
                },
            ]
        }

        plan = build_findings_review_plan(target, findings)
        result = execute_review_plan(plan, output)

        self.assertEqual(result["comments_added"], 2)
        self.assertTrue(result["track_changes_enabled"])
        self.assertTrue(os.path.exists(output))

        qa = audit_review_integrity(output)
        self.assertTrue(qa["passed"], qa)

        with zipfile.ZipFile(output) as archive:
            comments = archive.read("word/comments.xml").decode("utf-8")
            settings = archive.read("word/settings.xml").decode("utf-8")
        self.assertIn("CONTENT_VALUE_CONFLICT", comments)
        self.assertIn("表格学分与正文表述不一致", comments)
        self.assertIn("trackChanges", settings)

    def test_unresolved_location_is_rejected_instead_of_dropped(self) -> None:
        target = self._target()
        with self.assertRaises(ValueError) as raised:
            build_findings_review_plan(
                target,
                [{"location": "body.p[999]", "comment": "无法定位的批注"}],
            )
        self.assertIn("COMMENT_LOCATION_UNRESOLVED", str(raised.exception))

    def test_revisions_can_be_tracked_alongside_comments(self) -> None:
        target = self._target()
        output = os.path.join(self.work_dir, "proposal_reviewed_with_revision.docx")
        plan = build_findings_review_plan(
            target,
            [{"location": "body.p[1]", "comment": "请核对数字。"}],
            text_revisions=[{
                "location_id": "body.p[1]",
                "old_text": "信息技术安全技术应用人才",
                "new_text": "信息技术安全技术应用专业人才",
                "reason": "与专业名称一致",
            }],
        )
        result = execute_review_plan(plan, output)
        self.assertEqual(result["comments_added"], 1)
        self.assertEqual(result["tracked_text_revisions"], 1)


if __name__ == "__main__":
    unittest.main()
