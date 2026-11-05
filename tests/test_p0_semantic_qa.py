# -*- coding: utf-8 -*-
"""P0 regression tests: role routing, semantic QA profiles, severity, fonts, file locks."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from unittest import mock

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

import docx
from docx.shared import Pt

from engine import (
    DocumentTransaction,
    QAValidationError,
    TransactionAborted,
    audit_format_and_text_qa,
    check_font_availability,
    compare_layout_fingerprints,
    route_document_task,
)
from engine import qa_engine

import importlib.util

_run_qa_spec = importlib.util.spec_from_file_location(
    "p0_run_qa_module", os.path.join(ROOT_DIR, "scripts", "run_qa.py")
)
run_qa_module = importlib.util.module_from_spec(_run_qa_spec)
_run_qa_spec.loader.exec_module(run_qa_module)


class TestP0SemanticQaSuite(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(prefix="office_p0_qa_")
        self.work_dir = self.temp_dir.name

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _path(self, name: str) -> str:
        return os.path.join(self.work_dir, name)

    @staticmethod
    def _add_paragraph(document, text: str, size_pt: float):
        paragraph = document.add_paragraph()
        run = paragraph.add_run(text)
        run.font.size = Pt(size_pt)
        return paragraph

    def _template_docx(self) -> str:
        path = self._path("template.docx")
        document = docx.Document()
        self._add_paragraph(document, "封面标题", 36)
        self._add_paragraph(document, "正文内容", 14)
        table = document.add_table(rows=2, cols=2)
        table.cell(0, 0).paragraphs[0].add_run("表头")
        table.cell(0, 0).paragraphs[0].runs[0].font.size = Pt(9)
        table.cell(1, 0).paragraphs[0].add_run("数据")
        table.cell(1, 0).paragraphs[0].runs[0].font.size = Pt(9)
        document.save(path)
        return path

    def _output_docx(self, reference: str, body_pt: float = 14) -> str:
        path = self._path("output.docx")
        document = docx.Document()
        self._add_paragraph(document, "封面标题", 36)
        self._add_paragraph(document, "新增段落", body_pt)
        self._add_paragraph(document, "正文内容", body_pt)
        table = document.add_table(rows=2, cols=2)
        table.cell(0, 0).paragraphs[0].add_run("表头")
        table.cell(0, 0).paragraphs[0].runs[0].font.size = Pt(9)
        table.cell(0, 1).paragraphs[0].add_run("新填内容")
        table.cell(0, 1).paragraphs[0].runs[0].font.size = Pt(9)
        table.cell(1, 0).paragraphs[0].add_run("数据")
        table.cell(1, 0).paragraphs[0].runs[0].font.size = Pt(9)
        # A genuinely new table (4 columns, no caption/header match).
        new_table = document.add_table(rows=1, cols=4)
        for cell in new_table.rows[0].cells:
            cell.paragraphs[0].add_run("新增表")
            cell.paragraphs[0].runs[0].font.size = Pt(7)
        document.save(path)
        return path

    def test_router_treats_xlsx_as_data_source_not_merge(self) -> None:
        docx_path = self._path("a.docx")
        xlsx_path = self._path("b.xlsx")
        routing = route_document_task([docx_path, xlsx_path], "根据模板生成新方案")
        self.assertEqual(routing["task_mode"], "GENERATE")
        self.assertEqual(routing["data_sources"], [xlsx_path])
        self.assertTrue(routing["capability"]["enabled"])

        legacy = route_document_task([xlsx_path, docx_path])
        self.assertEqual(legacy["task_mode"], "MERGE")

        reformat = route_document_task([docx_path, xlsx_path], "按模板修改格式")
        self.assertEqual(reformat["task_mode"], "REFORMAT")
        self.assertEqual(reformat["data_sources"], [xlsx_path])

    def test_router_dual_document_repair_is_not_reformat(self) -> None:
        first = self._path("first.docx")
        second = self._path("second.docx")
        routing = route_document_task([second, first], "按模板修复格式")
        self.assertEqual(routing["task_mode"], "REPAIR")
        self.assertTrue(routing["capability"]["enabled"])

    def test_style_guide_aligns_cover_new_content_and_new_table(self) -> None:
        template = self._template_docx()
        output = self._output_docx(template)
        report = audit_format_and_text_qa(
            docx.Document(output),
            docx_path=output,
            reference_docx_path=template,
            raise_on_failure=False,
            comparison_profile="STYLE_GUIDE",
        )
        self.assertTrue(report["passed"], report["issues"])
        self.assertEqual(report["size_anomalies"], [])
        self.assertNotIn(
            "table_cell_font_or_size",
            [item[0] for item in report["table_style_anomalies"]],
        )
        self.assertIn(1, report["alignment"]["new_tables"])

    def test_style_guide_still_reports_real_body_drift(self) -> None:
        template = self._template_docx()
        output = self._output_docx(template, body_pt=16)
        with self.assertRaises(QAValidationError):
            audit_format_and_text_qa(
                docx.Document(output),
                docx_path=output,
                reference_docx_path=template,
                raise_on_failure=True,
                comparison_profile="STYLE_GUIDE",
            )

    def test_style_guide_layout_ignores_insertions_and_new_tables(self) -> None:
        template = self._template_docx()
        output = self._output_docx(template)
        report = compare_layout_fingerprints(output, template, comparison_profile="STYLE_GUIDE")
        self.assertTrue(report["passed"], report["issues"])
        self.assertNotIn("LAYOUT_PARAGRAPH_COUNT", {item["code"] for item in report["issues"]})
        self.assertNotIn("LAYOUT_TABLE_COUNT", {item["code"] for item in report["issues"]})
        self.assertIn("LAYOUT_NEW_TABLE", {item["code"] for item in report["informational"]})
        self.assertIn("LAYOUT_NEW_PARAGRAPH", {item["code"] for item in report["informational"]})

    def test_medium_issues_are_warnings_not_hard_failures(self) -> None:
        medium = [{"code": "LAYOUT_POSITION_DRIFT", "location": "body.p[3]", "detail": "x", "severity": "medium"}]
        high = [{"code": "FONT_SIZE_ANOMALY", "location": "body.p[3]", "detail": "x", "severity": "high"}]
        self.assertEqual(run_qa_module.resolve_report_status(medium, [], 0, False)[0], "PASSED")
        self.assertEqual(run_qa_module.resolve_report_status(high, [], 0, False)[0], "FAILED")
        self.assertEqual(
            run_qa_module.resolve_report_status(medium, ["RENDER_PDF_NOT_PRODUCED"], 1, False)[0],
            "UNVERIFIED",
        )

    def test_font_alias_maps_simhei_to_heiti(self) -> None:
        with mock.patch.object(
            qa_engine,
            "_installed_font_names",
            return_value=(
                {"simhei (truetype)", "fangsong (truetype)", "simsun & nsimsun (truetype)"},
                "windows_registry",
            ),
        ):
            report = check_font_availability(["黑体", "仿宋", "宋体", "仿宋_GB2312"])
        self.assertEqual(report["missing"], ["仿宋_GB2312"])

    def test_permission_error_reports_output_file_lock(self) -> None:
        source = self._template_docx()
        output = self._path("locked.docx")
        tx = DocumentTransaction(source, output, task_mode="GENERATE")
        tx.preflight()
        with open(tx.stage(), "wb") as handle:
            handle.write(b"staged")
        tx.record_qa({"passed": True, "issues": []})
        with mock.patch("engine.transaction.os.replace", side_effect=PermissionError("locked")):
            with self.assertRaises(TransactionAborted) as ctx:
                tx.commit()
        record = ctx.exception.record
        self.assertEqual(record["abort_reason"], "OUTPUT_FILE_LOCKED")
        self.assertEqual(record["lock_info"]["code"], "OUTPUT_FILE_LOCKED")
        self.assertIn("editor_sdk_pids", record["lock_info"])
        self.assertFalse(os.path.exists(output))


if __name__ == "__main__":
    unittest.main()
