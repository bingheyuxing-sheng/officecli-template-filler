# -*- coding: utf-8 -*-
"""W2 — heading detection lives in ``engine.alignment``; logic QA does not import workflow.

The structural helper was moved out of ``workflow`` so that ``logic_qa`` has no
dependency on workflow orchestration. ``workflow.is_heading_paragraph`` stays
importable as public API and must behave identically.
"""

from __future__ import annotations

import importlib
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import docx  # noqa: E402
from docx.enum.style import WD_STYLE_TYPE  # noqa: E402
from docx.oxml import OxmlElement  # noqa: E402
from docx.oxml.ns import qn  # noqa: E402

import engine.logic_qa as logic_qa  # noqa: E402
from engine.alignment import is_heading_paragraph  # noqa: E402
from engine.workflow import is_heading_paragraph as workflow_is_heading_paragraph  # noqa: E402


def _paragraph_with_outline_level(text: str = "带大纲级别的段落", level: int = 2):
    document = docx.Document()
    paragraph = document.add_paragraph(text)
    p_pr = paragraph._p.get_or_add_pPr()
    outline = OxmlElement("w:outlineLvl")
    outline.set(qn("w:val"), str(level - 1))
    p_pr.append(outline)
    return paragraph


def _paragraph_with_style(style_name: str):
    document = docx.Document()
    if style_name not in [style.name for style in document.styles]:
        document.styles.add_style(style_name, WD_STYLE_TYPE.PARAGRAPH)
    return document.add_paragraph("样式段落", style=style_name)


class HeadingDetectionTests(unittest.TestCase):
    def test_heading_style_is_a_heading(self) -> None:
        document = docx.Document()
        heading = document.add_heading("第一章 总则", level=1)
        body = document.add_paragraph("这是一段正文。")

        self.assertTrue(is_heading_paragraph(heading))
        self.assertFalse(is_heading_paragraph(body))

    def test_outline_level_is_a_heading(self) -> None:
        outline = _paragraph_with_outline_level(level=2)
        self.assertTrue(is_heading_paragraph(outline))

    def test_toc_and_caption_styles_are_excluded(self) -> None:
        """TOC/TOC and caption styles must never count as body headings."""
        for style_name in ("TOC 1", "Caption", "题注"):
            paragraph = _paragraph_with_style(style_name)
            self.assertFalse(
                is_heading_paragraph(paragraph),
                "%s must not be treated as a heading" % style_name,
            )

        # A TOC entry with an outline level is still a TOC entry.
        document = docx.Document()
        style = "TOC 2"
        if style not in [item.name for item in document.styles]:
            document.styles.add_style(style, WD_STYLE_TYPE.PARAGRAPH)
        paragraph = document.add_paragraph("目录条目", style=style)
        p_pr = paragraph._p.get_or_add_pPr()
        outline = OxmlElement("w:outlineLvl")
        outline.set(qn("w:val"), "0")
        p_pr.append(outline)
        self.assertFalse(is_heading_paragraph(paragraph))

    def test_workflow_api_delegates_to_the_same_helper(self) -> None:
        """Public ``workflow.is_heading_paragraph`` stays importable and identical."""
        document = docx.Document()
        heading = document.add_heading("第二章 范围", level=1)
        body = document.add_paragraph("正文。")
        outline = _paragraph_with_outline_level()

        for paragraph in (heading, body, outline):
            self.assertEqual(
                workflow_is_heading_paragraph(paragraph),
                is_heading_paragraph(paragraph),
            )
        self.assertIsNotNone(workflow_is_heading_paragraph)


class LogicQaIndependenceTests(unittest.TestCase):
    def _document(self):
        document = docx.Document()
        document.add_heading("第一章 总则", level=1)
        document.add_heading("第二章 范围", level=1)
        return document

    def test_logic_qa_source_has_no_workflow_reference(self) -> None:
        source = Path(logic_qa.__file__).read_text(encoding="utf-8")
        self.assertNotIn("workflow", source)

    def test_audit_logic_runs_with_workflow_unimportable(self) -> None:
        """Reload logic_qa with ``engine.workflow`` blocked, then run a real audit."""
        with mock.patch.dict(sys.modules, {"engine.workflow": None}):
            reloaded = importlib.reload(logic_qa)
            report = reloaded.audit_logic(self._document())

        self.assertTrue(report["passed"] is False)
        self.assertIn(
            "LOGIC_EMPTY_SECTION",
            {issue["code"] for issue in report["issues"]},
        )
        self.assertEqual(report["checked_paragraphs"], 2)


if __name__ == "__main__":
    unittest.main()
