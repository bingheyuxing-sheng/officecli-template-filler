# -*- coding: utf-8 -*-
"""
v3.5 M6 — Layout fingerprint tests.

Layout QA must tolerate content replacement (that is the whole point of generating a
document) while still catching real geometry drift: fonts, sizes, indents, margins,
table column widths and image aspect ratios.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import types
import unittest
from unittest import mock

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

import docx
from docx.oxml.ns import qn
from docx.shared import Pt

from engine import (
    build_review_plan,
    compare_layout_fingerprints,
    execute_review_plan,
    fingerprint_docx,
    run_visual_layout_qa,
)


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

    def test_v35_layout_qa_normalizes_tracked_changes(self) -> None:
        """REVIEW splits runs and adds comments; that is revision structure, not layout drift."""
        reference = self._docx("review_ref.docx", "正文内容", size=12)
        target = self._docx("review_target.docx", "正文内容", size=18)
        output = os.path.join(self.work_dir, "review_out.docx")
        execute_review_plan(
            build_review_plan(
                reference,
                target,
                text_revisions=[{"old_text": "正文内容", "new_text": "正文材料"}],
            ),
            output,
            snapshot_path="",
        )

        report = compare_layout_fingerprints(output, reference)
        self.assertTrue(report["passed"], report["issues"])
        self.assertNotIn("LAYOUT_RUN_COUNT", {item["code"] for item in report["issues"]})
        self.assertNotIn("LAYOUT_PARAGRAPH_COUNT", {item["code"] for item in report["issues"]})

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
    def test_layout_qa_counts_and_full_story_locations(self) -> None:
        reference = os.path.join(self.work_dir, "story_ref.docx")
        output = os.path.join(self.work_dir, "story_out.docx")
        ref_doc = docx.Document()
        ref_doc.add_paragraph("正文")
        outer = ref_doc.add_table(rows=1, cols=1)
        outer.cell(0, 0).add_table(rows=1, cols=1).cell(0, 0).text = "嵌套"
        ref_doc.sections[0].header.add_paragraph("页眉")
        ref_doc.save(reference)
        out_doc = docx.Document(reference)
        out_doc.add_paragraph("新增")
        out_doc.add_table(rows=1, cols=2)
        out_doc.save(output)

        fingerprint = fingerprint_docx(reference)
        locations = {item["location"] for item in fingerprint["paragraphs"]}
        table_locations = {item["location"] for item in fingerprint["tables"]}
        self.assertTrue(any(location.startswith("sec[0].header") for location in locations))
        self.assertTrue(any(".tbl[0].r[0].c[0].tbl[0]" in location for location in table_locations))
        report = compare_layout_fingerprints(output, reference)
        codes = {item["code"] for item in report["issues"]}
        self.assertIn("LAYOUT_PARAGRAPH_COUNT", codes)
        self.assertIn("LAYOUT_TABLE_COUNT", codes)

    def _run_mock_pdf_qa(self, page_count: int, output_samples: bytes, reference_samples: bytes):
        output = self._docx("same.docx", "正文")
        reference_dir = os.path.join(self.work_dir, "reference")
        os.makedirs(reference_dir)
        reference = os.path.join(reference_dir, "same.docx")
        docx.Document(output).save(reference)

        class Pixmap:
            width = 2
            height = 2

            def __init__(self, samples):
                self.samples = samples

        class Page:
            def __init__(self, samples):
                self.samples = samples

            def get_pixmap(self, **_kwargs):
                return Pixmap(self.samples)

        class Pdf:
            def __init__(self, samples):
                self.page_count = page_count
                self.samples = samples
                self.closed = False

            def __getitem__(self, _index):
                return Page(self.samples)

            def close(self):
                self.closed = True

        opened = []

        def open_pdf(path):
            pdf = Pdf(reference_samples if "reference_pdf" in path else output_samples)
            opened.append(pdf)
            return pdf

        fake_fitz = types.SimpleNamespace(open=open_pdf, Matrix=lambda *_args: object(), csGRAY=object())
        conversion_dirs = []

        def convert(_binary, source, destination):
            conversion_dirs.append(destination)
            return os.path.join(destination, os.path.splitext(os.path.basename(source))[0] + ".pdf"), None

        with mock.patch("engine.qa_engine.shutil.which", return_value="soffice"), \
                mock.patch("engine.qa_engine.find_pdf_backend", return_value={"name": "libreoffice", "executable": "soffice"}), \
                mock.patch("engine.qa_engine._convert_docx_to_pdf", side_effect=convert), \
                mock.patch("engine.qa_engine.check_font_availability", return_value={"checked": True, "missing": []}), \
                mock.patch.dict(sys.modules, {"fitz": fake_fitz}):
            report = run_visual_layout_qa(output, reference_docx_path=reference, output_dir=self.work_dir)
        return report, conversion_dirs, opened

    def test_visual_qa_pixel_issue_and_same_basename_isolation(self) -> None:
        report, conversion_dirs, opened = self._run_mock_pdf_qa(1, bytes([255] * 4), bytes([0] * 4))
        issue = next(item for item in report["issues"] if item["code"] == "RENDER_PAGE_PIXEL_DIFF")
        self.assertEqual(issue["severity"], "medium")
        self.assertTrue(report["page_diff_available"])
        self.assertEqual(len(set(conversion_dirs)), 2)
        self.assertTrue(all(pdf.closed for pdf in opened))

    def test_visual_qa_partial_page_diff(self) -> None:
        report, _dirs, _opened = self._run_mock_pdf_qa(11, bytes([0] * 4), bytes([0] * 4))
        self.assertIn("PDF_PAGE_DIFF_PARTIAL", {item["code"] for item in report["issues"]})
        self.assertEqual(report["page_diff_coverage"]["pages_compared"], 10)
        self.assertEqual(report["page_diff_coverage"]["pages_total"], 11)

    def test_visual_qa_reports_fitz_unavailable(self) -> None:
        output = self._docx("fitz_out.docx", "正文")
        reference = self._docx("fitz_ref.docx", "正文")
        with mock.patch("engine.qa_engine.shutil.which", return_value="soffice"), \
                mock.patch("engine.qa_engine.find_pdf_backend", return_value={"name": "libreoffice", "executable": "soffice"}), \
                mock.patch("engine.qa_engine._convert_docx_to_pdf", return_value=("fake.pdf", None)), \
                mock.patch("engine.qa_engine.check_font_availability", return_value={"checked": True, "missing": []}), \
                mock.patch.dict(sys.modules, {"fitz": None}):
            report = run_visual_layout_qa(output, reference_docx_path=reference)
        self.assertFalse(report["page_diff_available"])
        self.assertIn("PDF_PAGE_DIFF_UNAVAILABLE", report["coverage_gaps"])
        self.assertIn("PyMuPDF unavailable", report["page_diff_error"])

    def test_visual_qa_reference_coverage_and_schema_enum(self) -> None:
        output = self._docx("no_ref.docx", "正文")
        with mock.patch("engine.qa_engine.shutil.which", return_value=None), \
                mock.patch("engine.qa_engine.find_pdf_backend", return_value={"name": "none", "executable": None}), \
                mock.patch("engine.qa_engine.check_font_availability", return_value={"checked": True, "missing": []}):
            no_reference = run_visual_layout_qa(output)
            missing_reference = run_visual_layout_qa(output, reference_docx_path=os.path.join(self.work_dir, "missing.docx"))
        self.assertIn("REFERENCE_LAYOUT_NOT_PROVIDED", no_reference["coverage_gaps"])
        self.assertIn("REFERENCE_DOCX_NOT_FOUND", missing_reference["coverage_gaps"])
        self.assertEqual(len(no_reference["coverage_gaps"]), len(set(no_reference["coverage_gaps"])))
        schema_path = os.path.join(ROOT_DIR, "schemas", "qa_report.schema.json")
        with open(schema_path, "r", encoding="utf-8") as handle:
            schema = json.load(handle)
        self.assertIn("UNVERIFIED", schema["properties"]["status"]["enum"])
        visual_properties = schema["properties"]["visual_qa"]["properties"]
        self.assertIn("page_diff_available", visual_properties)
        self.assertIn("page_diff_coverage", visual_properties)


if __name__ == "__main__":
    unittest.main()
