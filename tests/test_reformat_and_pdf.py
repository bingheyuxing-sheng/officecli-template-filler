# -*- coding: utf-8 -*-
"""P1 regression tests: WPS/LibreOffice PDF path and REFORMAT diff plan/apply."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from unittest import mock

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from gate_helpers import ensure_gate  # noqa: E402

import docx
from docx.oxml.ns import qn
from docx.shared import Pt

from engine import (
    build_reformat_plan,
    convert_docx_to_pdf,
    execute_reformat_plan,
    is_track_changes_enabled,
    list_format_revisions,
    pdf_page_count,
)


class TestPdfBackendSuite(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(prefix="office_pdf_")
        self.work_dir = self.temp_dir.name

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _docx(self) -> str:
        path = os.path.join(self.work_dir, "source.docx")
        document = docx.Document()
        document.add_paragraph("PDF source")
        document.save(path)
        return path

    def test_wps_word2pdf_creates_pdf(self) -> None:
        source = self._docx()
        out_dir = os.path.join(self.work_dir, "pdf")

        def fake_run(command, timeout):
            pdf_path = command[4]
            with open(pdf_path, "wb") as handle:
                handle.write(b"%PDF-1.4")
            return 0, '{"type":"completed","status":"success"}', ""

        with mock.patch("engine.pdf_backend._run", side_effect=fake_run):
            pdf_path, error, backend_name = convert_docx_to_pdf(
                source, out_dir, {"name": "wps", "executable": "kwpsconvert.exe"}
            )
        self.assertIsNone(error)
        self.assertEqual(backend_name, "wps")
        self.assertTrue(os.path.isfile(pdf_path))

    def test_wps_pdfinfo_returns_page_count(self) -> None:
        pdf_path = os.path.join(self.work_dir, "probe.pdf")
        with open(pdf_path, "wb") as handle:
            handle.write(b"%PDF-1.4")
        with mock.patch(
            "engine.pdf_backend._run",
            return_value=(0, '{"type":"completed","page_count":3}', ""),
        ):
            count, source, error = pdf_page_count(
                pdf_path, {"name": "wps", "executable": "kwpsconvert.exe"}
            )
        self.assertEqual(count, 3)
        self.assertEqual(source, "wps_pdfinfo")
        self.assertIsNone(error)

    def test_wps_vip_error_is_reported(self) -> None:
        source = self._docx()
        with mock.patch("engine.pdf_backend._run", return_value=(100, "", "")):
            pdf_path, error, backend_name = convert_docx_to_pdf(
                source, os.path.join(self.work_dir, "pdf"), {"name": "wps", "executable": "kwpsconvert.exe"}
            )
        self.assertIsNone(pdf_path)
        self.assertIn("WPS_VIP_REQUIRED", error)
        self.assertEqual(backend_name, "wps")

    def test_no_backend_is_explicit(self) -> None:
        source = self._docx()
        pdf_path, error, backend_name = convert_docx_to_pdf(
            source, os.path.join(self.work_dir, "pdf"), {"name": "none", "executable": None}
        )
        self.assertIsNone(pdf_path)
        self.assertEqual(error, "NO_PDF_BACKEND")
        self.assertEqual(backend_name, "none")


class TestReformatSuite(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(prefix="office_reformat_")
        self.work_dir = self.temp_dir.name

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _path(self, name: str) -> str:
        return os.path.join(self.work_dir, name)

    @staticmethod
    def _table(document, width: int = 2500):
        table = document.add_table(rows=2, cols=2)
        for column in table._tbl.tblGrid.findall(qn("w:gridCol")):
            column.set(qn("w:w"), str(width))
        for row in table.rows:
            for cell in row.cells:
                cell.paragraphs[0].add_run("单元格")
                cell.paragraphs[0].runs[0].font.size = Pt(9)
        return table

    def _documents(self):
        ref_path = self._path("reference.docx")
        tgt_path = self._path("target.docx")

        ref = docx.Document()
        body = ref.add_paragraph("正文内容")
        body.alignment = 3
        body.runs[0].font.size = Pt(12)
        self._table(ref, 3000)
        ref.save(ref_path)

        target = docx.Document()
        body = target.add_paragraph("正文内容")
        body.alignment = 3
        body.runs[0].font.size = Pt(14)
        self._table(target, 2000)
        target.add_paragraph("新增内容").runs[0].font.size = Pt(12)
        target.save(tgt_path)
        return ref_path, tgt_path

    def test_plan_contains_actions_and_new_content(self) -> None:
        ref_path, tgt_path = self._documents()
        plan = build_reformat_plan(ref_path, tgt_path)
        actions = {item["action_type"] for item in plan["actions"]}
        self.assertIn("RESTORE_PARAGRAPH_FORMAT", actions)
        self.assertIn("RESTORE_TABLE_STYLE", actions)
        self.assertGreaterEqual(plan["summary"]["auto_fix"], 2)
        self.assertGreaterEqual(plan["summary"]["keep"], 1)
        self.assertTrue(any(item["property"] == "paragraph.new" for item in plan["diffs"]))

    def test_apply_writes_tracked_format_revisions(self) -> None:
        ref_path, tgt_path = self._documents()
        output = self._path("formatted.docx")
        ensure_gate(ref_path, "REFORMAT")
        plan = build_reformat_plan(ref_path, tgt_path)
        result = execute_reformat_plan(plan, output)
        self.assertGreaterEqual(result["applied_actions"], 1)
        self.assertTrue(os.path.isfile(output))
        self.assertTrue(is_track_changes_enabled(docx.Document(output)))
        revisions = list_format_revisions(output)
        self.assertTrue(revisions, "REFORMAT output must carry w:*PrChange marks")
        self.assertTrue(all(item.get("revision_id") is not None for item in revisions))

    def test_plan_only_cli_does_not_write_output(self) -> None:
        ref_path, tgt_path = self._documents()
        plan_path = self._path("plan.json")
        output = self._path("should_not_exist.docx")
        import subprocess

        result = subprocess.run(
            [
                sys.executable,
                os.path.join(ROOT_DIR, "scripts", "reformat_document.py"),
                "--reference", ref_path,
                "--target", tgt_path,
                "--plan-out", plan_path,
                "--out", output,
                "--plan-only",
            ],
            cwd=ROOT_DIR,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(os.path.isfile(plan_path))
        self.assertFalse(os.path.exists(output))
        with open(plan_path, "r", encoding="utf-8") as handle:
            plan = json.load(handle)
        self.assertEqual(plan["task_mode"], "REFORMAT")
        self.assertTrue(plan["diffs"])


if __name__ == "__main__":
    unittest.main()
