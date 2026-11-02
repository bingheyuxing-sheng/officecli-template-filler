# -*- coding: utf-8 -*-
"""
v3.5 M6 — Layout fingerprint tests.

Layout QA must tolerate content replacement (that is the whole point of generating a
document) while still catching real geometry drift: fonts, sizes, indents, margins,
table column widths and image aspect ratios.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

import docx
from docx.oxml.ns import qn
from docx.shared import Pt

from engine import compare_layout_fingerprints, fingerprint_docx, run_visual_layout_qa


class TestLayoutQaSuite(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(prefix="office_layout_qa_")
        self.work_dir = self.temp_dir.name

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _docx(self, name: str, text: str, size: int = 12) -> str:
        path = os.path.join(self.work_dir, name)
        document = docx.Document()
        run = document.add_paragraph().add_run(text)
        run.font.size = Pt(size)
        document.save(path)
        return path

    @staticmethod
    def _table_with_widths(document, widths):
        table = document.add_table(rows=2, cols=len(widths))
        grid = table._tbl.tblGrid
        columns = grid.findall(qn("w:gridCol"))
        for column, width in zip(columns, widths):
            column.set(qn("w:w"), str(width))
        for row in table.rows:
            for cell in row.cells:
                cell.paragraphs[0].add_run("内容")
        return table

    def test_v35_layout_qa_ignores_text_content_change(self) -> None:
        """Replacing placeholder text must not be reported as a layout defect."""
        reference = self._docx("content_ref.docx", "甲方名称：{{party}}")
        output = self._docx("content_out.docx", "甲方名称：某某科技有限公司")

        report = compare_layout_fingerprints(output, reference)
        self.assertTrue(report["passed"], report["issues"])
        self.assertEqual(report["issues"], [])

    def test_v35_layout_qa_detects_font_size_drift(self) -> None:
        """Same text position with a different size is a real layout change."""
        reference = self._docx("font_ref.docx", "正文内容", size=12)
        output = self._docx("font_out.docx", "正文内容", size=16)

        report = compare_layout_fingerprints(output, reference)
        self.assertFalse(report["passed"])
        self.assertTrue(any(item["code"] == "LAYOUT_FONT_DRIFT" for item in report["issues"]))

    def test_v35_layout_qa_detects_table_width_drift(self) -> None:
        """Column-ratio drift beyond 5% must be reported."""
        ref_path = os.path.join(self.work_dir, "table_ref.docx")
        out_path = os.path.join(self.work_dir, "table_out.docx")

        ref_doc = docx.Document()
        self._table_with_widths(ref_doc, [2000, 2000, 4000])
        ref_doc.save(ref_path)

        out_doc = docx.Document()
        self._table_with_widths(out_doc, [4000, 2000, 2000])
        out_doc.save(out_path)

        report = compare_layout_fingerprints(out_path, ref_path)
        self.assertTrue(any(item["code"] == "LAYOUT_TABLE_DRIFT" for item in report["issues"]))

    def test_v35_visual_qa_includes_layout_fingerprint(self) -> None:
        """`run_visual_layout_qa()` must expose the fingerprint result against a reference."""
        reference = self._docx("visual_ref.docx", "模板正文", size=12)
        output = self._docx("visual_out.docx", "模板正文", size=16)

        report = run_visual_layout_qa(output, reference_docx_path=reference)
        self.assertIsNotNone(report["layout_fingerprint"])
        codes = {item["code"] for item in report["structured_issues"]}
        self.assertIn("LAYOUT_FONT_DRIFT", codes)

    def test_v35_fingerprint_has_no_text_content(self) -> None:
        """The fingerprint must describe geometry only, never the text itself."""
        path = self._docx("fingerprint.docx", "机密文本内容")
        fingerprint = fingerprint_docx(path)
        serialized = str(fingerprint)
        self.assertNotIn("机密文本内容", serialized)
        self.assertIn("paragraphs", fingerprint)
        self.assertIn("sections", fingerprint)


if __name__ == "__main__":
    unittest.main()
