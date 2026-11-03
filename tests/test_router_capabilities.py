# -*- coding: utf-8 -*-
"""
v3.5 M3 — Router & capability registry tests.

The router must not name a mode the engine cannot execute, and it must not send a PDF
into the Word generator. `analyze_excel_template.py` keeps the documented Step 2 honest
for workbook inputs.
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

import openpyxl

from engine import (
    CapabilityNotAvailable,
    get_capability,
    require_capability,
    route_document_task,
)


class TestRouterCapabilitiesSuite(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(prefix="office_router_test_")
        self.work_dir = self.temp_dir.name

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_v35_capability_registry_blocks_unimplemented_modes(self) -> None:
        """Every routed mode must declare whether it has a real handler."""
        expected_handlers = {
            "GENERATE": "scripts/generate_document.py",
            "EXCEL_GENERATE": "scripts/generate_excel.py",
            "REPAIR": "scripts/repair_document.py",
            "REVIEW": "scripts/review_document.py",
            "REFORMAT": "scripts/reformat_document.py",
        }
        for mode, handler in expected_handlers.items():
            capability = get_capability(mode)
            self.assertTrue(capability["enabled"], mode)
            self.assertEqual(capability["handler"], handler)
            self.assertIsNone(capability["reason"])
            self.assertEqual(require_capability(mode)["task_mode"], mode)

        for mode in ("POLISH", "MERGE"):
            capability = get_capability(mode)
            self.assertFalse(capability["enabled"], mode)
            self.assertEqual(capability["reason"], "CAPABILITY_NOT_AVAILABLE")
            with self.assertRaises(CapabilityNotAvailable):
                require_capability(mode)

        proofread = get_capability("PROOFREAD")
        self.assertTrue(proofread["enabled"])
        self.assertEqual(proofread["handler"], "scripts/proofread_document.py")

        docx_path = os.path.join(self.work_dir, "draft.docx")
        routing = route_document_task([docx_path], "统一字体和字号重新排版")
        self.assertEqual(routing["task_mode"], "REFORMAT")
        self.assertTrue(routing["capability"]["enabled"])
        self.assertIsNone(routing["capability"]["reason"])

        generate = route_document_task([docx_path], "按模板生成一份方案")
        self.assertTrue(generate["capability"]["enabled"])

    def test_v35_router_maps_proofread_intent(self) -> None:
        """Single-document proofreading is its own mode, not a restyle job."""
        docx_path = os.path.join(self.work_dir, "draft.docx")
        for intent in ("帮我校对一下错别字", "proofread this draft", "检查数据错误和逻辑问题"):
            routing = route_document_task([docx_path], intent)
            self.assertEqual(routing["task_mode"], "PROOFREAD", intent)
            self.assertTrue(routing["capability"]["enabled"])
            self.assertEqual(routing["web_search_policy"], "DISABLED_BY_DEFAULT")

        restyle = route_document_task([docx_path], "统一字体和字号重新排版")
        self.assertEqual(restyle["task_mode"], "REFORMAT")

    def test_v35_router_rejects_pdf(self) -> None:
        """A PDF (or any non-Office container) is a verdict, not a GENERATE job."""
        pdf_path = os.path.join(self.work_dir, "scan.pdf")
        with open(pdf_path, "wb") as handle:
            handle.write(b"%PDF-1.4")

        routing = route_document_task([pdf_path], "生成报告")
        self.assertEqual(routing["task_mode"], "UNSUPPORTED_INPUT")
        self.assertIn(pdf_path, routing["unsupported_files"])
        self.assertIn(".docx", routing["supported_formats"])
        self.assertFalse(routing["capability"]["enabled"])
        self.assertEqual(routing["capability"]["reason"], "UNSUPPORTED_INPUT")

        mixed = route_document_task([os.path.join(self.work_dir, "a.docx"), pdf_path], "审核")
        self.assertEqual(mixed["task_mode"], "UNSUPPORTED_INPUT")

    def test_v35_excel_analyzer_emits_spec(self) -> None:
        """`analyze_excel_template.py` must describe sheets, formulas and placeholders."""
        template = os.path.join(self.work_dir, "excel_template.xlsx")
        workbook = openpyxl.Workbook()
        sheet = workbook.active
        sheet.title = "预算"
        sheet["A1"] = "项目"
        sheet["B1"] = "{{project}}"
        sheet["B2"] = 10
        sheet["B3"] = "=SUM(B2:B2)"
        sheet.merge_cells("A4:B4")
        workbook.save(template)
        workbook.close()

        out_path = os.path.join(self.work_dir, "excel_spec.json")
        result = subprocess.run(
            [
                sys.executable,
                os.path.join(ROOT_DIR, "scripts", "analyze_excel_template.py"),
                "--input", template,
                "--out", out_path,
            ],
            cwd=ROOT_DIR,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

        with open(out_path, "r", encoding="utf-8") as handle:
            spec = json.load(handle)
        self.assertEqual(spec["file_type"], "xlsx")
        self.assertEqual(spec["sheet_count"], 1)
        self.assertEqual(spec["formula_count"], 1)
        self.assertIn("{{project}}", spec["placeholder_tokens"])
        sheet_spec = spec["sheets"][0]
        self.assertEqual(sheet_spec["name"], "预算")
        self.assertIn("A4:B4", sheet_spec["merged_ranges"])
        self.assertTrue(sheet_spec["formula_samples"])

    def test_v35_skill_step2_uses_excel_analyzer(self) -> None:
        """SKILL.md Step 2 must route by container type instead of always using Word."""
        with open(os.path.join(ROOT_DIR, "SKILL.md"), "r", encoding="utf-8") as handle:
            content = handle.read()
        step_two = content.split("### Step 2:", 1)[1].split("### Step 3:", 1)[0]
        self.assertIn("analyze_excel_template.py", step_two)
        self.assertIn("analyze_template.py", step_two)
        self.assertIn(".xlsx", step_two)
        self.assertIn("UNSUPPORTED_INPUT", step_two)


if __name__ == "__main__":
    unittest.main()
