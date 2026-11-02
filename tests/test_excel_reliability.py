# -*- coding: utf-8 -*-
"""
v3.5 M4/M5 — Excel reliability tests.

M4: formula row-shifting uses openpyxl's Translator (string literals and sheet-qualified
references stay correct) and every formula carries an explicit verification status.
M5: workbooks that contain parts openpyxl cannot preserve are refused unless the caller
explicitly accepts the loss.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

import openpyxl

from engine import (
    inspect_excel_objects,
    recalculate_and_verify_excel_formulas,
    shift_excel_formula_row_refs,
    translate_excel_formula_row_refs,
)


class TestExcelReliabilitySuite(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(prefix="office_excel_rel_")
        self.work_dir = self.temp_dir.name

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _workbook(self, name: str, cells) -> str:
        path = os.path.join(self.work_dir, name)
        workbook = openpyxl.Workbook()
        sheet = workbook.active
        for coordinate, value in cells.items():
            sheet[coordinate] = value
        workbook.save(path)
        workbook.close()
        return path

    def _inject_part(self, source: str, target: str, part_name: str, payload: bytes) -> None:
        with zipfile.ZipFile(source) as zin, zipfile.ZipFile(target, "w") as zout:
            for item in zin.namelist():
                zout.writestr(item, zin.read(item))
            zout.writestr(part_name, payload)
        shutil.move(target, source)

    # ------------------------------------------------------------------ M4

    def test_v35_formula_translator_preserves_string_literal(self) -> None:
        """A row shift must not rewrite text inside a string literal or an absolute ref."""
        translated, reason = translate_excel_formula_row_refs(
            '=IF(A5="A5",Sheet1!B5,$C$5)', 5, 6
        )
        self.assertIsNone(reason)
        self.assertEqual(translated, '=IF(A6="A5",Sheet1!B6,$C$5)')
        self.assertEqual(
            shift_excel_formula_row_refs("=C5*D5/$E$2", 5, 8),
            "=C8*D8/$E$2",
        )

    def test_v35_formula_translator_marks_unsupported(self) -> None:
        """Formulas that cannot be shifted safely are refused with an explicit reason."""
        cases = (
            ("=SUM(Table1[Amount])", "UNSUPPORTED_STRUCTURED_REFERENCE"),
            ("=[Book1.xlsx]Sheet1!A5", "UNSUPPORTED_EXTERNAL_WORKBOOK"),
            ('=INDIRECT("A"&B5)', "UNSUPPORTED_DYNAMIC_REFERENCE"),
            ("=OFFSET(A5,1,0)", "UNSUPPORTED_DYNAMIC_REFERENCE"),
        )
        for formula, expected_reason in cases:
            translated, reason = translate_excel_formula_row_refs(formula, 5, 6)
            self.assertEqual(reason, expected_reason, formula)
            self.assertEqual(translated, formula)

    def test_v35_formula_status_matrix(self) -> None:
        """Every formula must end up VERIFIED / FAILED / UNSUPPORTED, never silently passed."""
        path = self._workbook("status.xlsx", {
            "B1": 1,
            "B2": 2,
            "C1": "=SUM(B1:B2)",
            "C2": "=1/0",
            "C3": "=XLOOKUP(A1,A2:A3,B2:B3)",
        })

        report = recalculate_and_verify_excel_formulas(path)
        statuses = report["formula_status"]
        self.assertEqual(statuses["Sheet!C1"], "VERIFIED")
        self.assertEqual(statuses["Sheet!C2"], "FAILED")
        self.assertEqual(statuses["Sheet!C3"], "UNSUPPORTED")
        self.assertEqual(report["unverified_count"], 1)
        self.assertIn("FORMULAS_UNVERIFIED", report["coverage_gaps"])
        self.assertEqual(report["status_counts"].get("VERIFIED"), 1)

    def test_v35_excel_qa_unverified_not_passed(self) -> None:
        """`run_qa.py` must report UNVERIFIED (not PASSED) when a formula could not be checked."""
        path = self._workbook("xlookup.xlsx", {
            "A1": 1, "A2": 1, "A3": 2, "B2": 10, "B3": 20,
            "C1": "=XLOOKUP(A1,A2:A3,B2:B3)",
        })
        result = subprocess.run(
            [sys.executable, os.path.join(ROOT_DIR, "scripts", "run_qa.py"), path],
            cwd=ROOT_DIR,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        report = json.loads(result.stdout)
        self.assertEqual(report["status"], "UNVERIFIED")
        self.assertFalse(report["passed"])
        self.assertIn("FORMULAS_UNVERIFIED", report["coverage_gaps"])

    # ------------------------------------------------------------------ M5

    def test_v35_xlsm_object_preflight_detects_activex(self) -> None:
        """A package part that openpyxl drops must be reported as a loss risk."""
        path = self._workbook("activex.xlsx", {"A1": "{{name}}"})
        self._inject_part(path, path + ".tmp", "xl/activeX/activeX1.xml", b"<ax:ocx/>")

        report = inspect_excel_objects(path)
        self.assertTrue(report["object_loss_risk"])
        types = {item["type"] for item in report["loss_risk_objects"]}
        self.assertIn("activex", types)
        self.assertTrue(all(item["preserved_by_openpyxl"] is False for item in report["loss_risk_objects"]))

    def test_v35_xlsm_refuses_when_object_loss_unauthorized(self) -> None:
        """Generation stops before writing anything when object loss is not authorized."""
        template = self._workbook("guarded.xlsx", {"A1": "{{name}}"})
        self._inject_part(template, template + ".tmp", "xl/activeX/activeX1.xml", b"<ax:ocx/>")
        payload = os.path.join(self.work_dir, "payload.json")
        with open(payload, "w", encoding="utf-8") as handle:
            json.dump({"replacements": {"name": "示例"}}, handle)
        output = os.path.join(self.work_dir, "guarded_out.xlsx")

        refused = subprocess.run(
            [
                sys.executable,
                os.path.join(ROOT_DIR, "scripts", "generate_excel.py"),
                "--template", template, "--payload", payload, "--out", output,
            ],
            cwd=ROOT_DIR,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        self.assertEqual(refused.returncode, 3, refused.stderr)
        report = json.loads(refused.stdout)
        self.assertEqual(report["error"], "OBJECT_LOSS_RISK")
        self.assertFalse(os.path.exists(output))

        allowed = subprocess.run(
            [
                sys.executable,
                os.path.join(ROOT_DIR, "scripts", "generate_excel.py"),
                "--template", template, "--payload", payload, "--out", output,
                "--allow-object-loss",
            ],
            cwd=ROOT_DIR,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        self.assertEqual(allowed.returncode, 0, allowed.stderr)
        self.assertTrue(os.path.isfile(output))


if __name__ == "__main__":
    unittest.main()
