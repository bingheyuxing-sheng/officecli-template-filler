# -*- coding: utf-8 -*-
"""Regression: template tokens that were never registered as slots must not block.

A template paragraph registers only a label slot; the underscore blanks beside
it are legitimate template content. The residual scanner still reports them as
``TEMPLATE_TEXT_RESIDUAL`` because ``TOKEN_PATTERN`` matches ``_{3,}``, and the
inheritance downgrade kept them blocking merely because the paragraph was
attempted — failing an otherwise correct fill. Blocking is now reserved for
tokens that are the ``matched_text`` of a fillable slot AND whose paragraph was
targeted by the plan.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

import docx

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from qa.pipeline import _adjust_inherited_residuals  # noqa: E402

BLANK1 = "___________"
BLANK2 = "__________________"
LABEL = "备注字段"
PARAGRAPH = "项目：%s%s：%s" % (BLANK1, LABEL, BLANK2)


def _residual(index: int, detail: str) -> dict:
    return {
        "code": "TEMPLATE_TEXT_RESIDUAL",
        "severity": "high",
        "location": "body_p_token:body_p_token.%d" % index,
        "detail": detail,
        "blocking": True,
    }


class ResidualInheritanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="residual_")
        self.template = Path(self._tmp.name) / "template.docx"
        document = docx.Document()
        document.add_paragraph(PARAGRAPH)
        document.add_paragraph("普通段落")
        document.add_paragraph("填充段")
        document.save(str(self.template))
        self.fill_plan = {
            "operations": [
                {"type": "fill_paragraph", "target": {"location_id": "body.p[2]"}},
            ]
        }
        self.spec = {
            "slots": [
                {"slot_id": "S_1", "matched_text": LABEL, "protection_status": "CONDITIONAL"},
                {"slot_id": "S_2", "matched_text": "项目", "protection_status": "PROTECTED"},
            ]
        }

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _formatting(self, issues):
        return {"passed": not issues, "issues": issues,
                "structured_issues": issues}

    def test_never_slot_blanks_downgraded_on_attempted_paragraph(self) -> None:
        issues = [_residual(0, BLANK1), _residual(0, BLANK2)]
        adjusted, inherited = _adjust_inherited_residuals(
            self._formatting(issues), str(self.template), self.fill_plan, self.spec,
        )
        self.assertEqual(adjusted["issues"], [])
        self.assertTrue(adjusted["passed"])
        self.assertEqual(len(inherited), 2)
        self.assertNotIn(BLANK1, str(adjusted["issues"]))

    def test_registered_unfilled_slot_stays_blocking(self) -> None:
        token = "{{项目名称}}"
        document = docx.Document()
        document.add_paragraph("抬头")
        document.add_paragraph(token)
        path = Path(self._tmp.name) / "token.docx"
        document.save(str(path))
        plan = {"operations": [
            {"type": "replace_text", "target": {"location_id": "body.p[1]"}},
        ]}
        spec = {"slots": [{"slot_id": "S_9", "matched_text": token,
                           "protection_status": "OPEN"}]}
        adjusted, inherited = _adjust_inherited_residuals(
            self._formatting([_residual(1, token)]), str(path), plan, spec,
        )
        self.assertEqual(len(adjusted["issues"]), 1,
                         "a targeted, registered slot left unfilled must stay blocking")
        self.assertFalse(adjusted["passed"])
        self.assertEqual(inherited, [])

    def test_unattempted_paragraph_still_downgraded_without_spec(self) -> None:
        """Legacy behaviour preserved: no spec argument, unattempted paragraph."""
        issues = [_residual(7, BLANK1)]
        adjusted, inherited = _adjust_inherited_residuals(
            self._formatting(issues), str(self.template), self.fill_plan,
        )
        self.assertEqual(adjusted["issues"], [])
        self.assertEqual(len(inherited), 1)

    def test_protected_slot_token_downgraded(self) -> None:
        """PROTECTED slots are never fillable; their tokens are inherited content."""
        token = "{{受保护}}"
        document = docx.Document()
        document.add_paragraph("抬头")
        document.add_paragraph(token)
        path = Path(self._tmp.name) / "protected.docx"
        document.save(str(path))
        plan = {"operations": [
            {"type": "replace_text", "target": {"location_id": "body.p[1]"}},
        ]}
        spec = {"slots": [{"slot_id": "S_3", "matched_text": token,
                           "protection_status": "PROTECTED"}]}
        adjusted, inherited = _adjust_inherited_residuals(
            self._formatting([_residual(1, token)]), str(path), plan, spec,
        )
        self.assertEqual(adjusted["issues"], [])
        self.assertEqual(len(inherited), 1)


if __name__ == "__main__":
    unittest.main()
