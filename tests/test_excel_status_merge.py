# -*- coding: utf-8 -*-
"""W3-2: Excel formula status merge must keep renderer limits out of FAILED.

Host-independent (E2): both branches are exercised with mocks — no soffice on
PATH, and a fake soffice whose "recalculated" workbook is fabricated here.
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import openpyxl

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.excel_engine import recalculate_and_verify_excel_formulas  # noqa: E402

XLOOKUP = "=XLOOKUP(A1,A2:A3,B2:B3)"


class _FakeGuard:
    """Stand-in for TaskResourceGuard: writes a fabricated recalculation workbook."""

    def __init__(self, cached: dict):
        self.cached = cached  # {"Sheet!C3": "#NAME?" | 10 | None}

    def run_owned_command(self, command, timeout=None, check=False):
        out_dir = command[command.index("--outdir") + 1]
        target = command[-1]
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Sheet"
        for key, value in self.cached.items():
            sheet, coord = key.split("!")
            ws[coord] = value
        wb.save(os.path.join(out_dir, os.path.basename(target)))
        return SimpleNamespace(returncode=0)


class ExcelStatusMergeTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        path = os.path.join(self._tmp.name, "book.xlsx")
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Sheet"
        ws["B1"] = 1
        ws["B2"] = 2
        ws["C1"] = "=SUM(B1:B2)"
        ws["C2"] = "=1/0"
        ws["C3"] = XLOOKUP
        wb.save(path)
        wb.close()
        self.path = path

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp.name, ignore_errors=True)

    def test_no_soffice_branch_keeps_builtin_verdicts(self) -> None:
        with mock.patch("engine.excel_engine.shutil.which", return_value=None):
            report = recalculate_and_verify_excel_formulas(self.path)
        self.assertEqual(report["formula_status"]["Sheet!C1"], "VERIFIED")
        self.assertEqual(report["formula_status"]["Sheet!C2"], "FAILED")
        self.assertEqual(report["formula_status"]["Sheet!C3"], "UNSUPPORTED")
        self.assertEqual(report["unverified_count"], 1)
        self.assertEqual(report["engine"], "builtin_decimal_evaluator")
        prov = report["formula_provenance"]["Sheet!C3"]
        self.assertEqual(prov["builtin_status"], "UNSUPPORTED")
        self.assertIsNone(prov["external_status"])
        self.assertEqual(prov["final_status"], "UNSUPPORTED")

    def _with_soffice(self, cached: dict) -> dict:
        with mock.patch(
            "engine.excel_engine.shutil.which", return_value="/fake/soffice"
        ):
            return recalculate_and_verify_excel_formulas(
                self.path, guard=_FakeGuard(cached)
            )

    def test_renderer_name_error_stays_unsupported_not_failed(self) -> None:
        report = self._with_soffice({"Sheet!C1": 3, "Sheet!C2": "#DIV/0!", "Sheet!C3": "#NAME?"})
        self.assertEqual(report["formula_status"]["Sheet!C3"], "UNSUPPORTED")
        self.assertEqual(report["unverified_count"], 1)
        self.assertEqual(report["coverage_gaps"], ["FORMULAS_UNVERIFIED"])
        self.assertFalse(
            any("LIBREOFFICE_EVAL_ERROR" in item and "C3" in item for item in report["formula_errors"]),
            "renderer #NAME? for an unsupported formula must not become a blocking error",
        )
        prov = report["formula_provenance"]["Sheet!C3"]
        self.assertEqual(
            (prov["builtin_status"], prov["external_status"], prov["final_status"]),
            ("UNSUPPORTED", "FAILED", "UNSUPPORTED"),
        )

    def test_external_computed_value_verifies_unsupported_formula(self) -> None:
        report = self._with_soffice({"Sheet!C1": 3, "Sheet!C2": "#DIV/0!", "Sheet!C3": 10})
        self.assertEqual(report["formula_status"]["Sheet!C3"], "VERIFIED_EXTERNAL")
        self.assertEqual(report["unverified_count"], 0)
        self.assertEqual(report["engine"], "libreoffice+builtin")

    def test_builtin_verified_wins_over_renderer_gap(self) -> None:
        report = self._with_soffice({"Sheet!C1": "#NAME?", "Sheet!C2": "#DIV/0!", "Sheet!C3": "#NAME?"})
        self.assertEqual(report["formula_status"]["Sheet!C1"], "VERIFIED")
        prov = report["formula_provenance"]["Sheet!C1"]
        self.assertEqual(prov["external_status"], "FAILED")
        self.assertEqual(prov["final_status"], "VERIFIED")
        self.assertFalse(any("C1" in item for item in report["formula_errors"]))

    def test_genuinely_failed_formula_still_surfaces_error(self) -> None:
        report = self._with_soffice({"Sheet!C1": 3, "Sheet!C2": "#DIV/0!", "Sheet!C3": "#NAME?"})
        self.assertEqual(report["formula_status"]["Sheet!C2"], "FAILED")
        self.assertTrue(
            any(item.startswith("LIBREOFFICE_EVAL_ERROR Sheet!C2") for item in report["formula_errors"])
        )

    def test_missing_cached_value_is_not_recalculated(self) -> None:
        report = self._with_soffice({"Sheet!C1": 3, "Sheet!C2": "#DIV/0!", "Sheet!C3": None})
        self.assertEqual(report["formula_status"]["Sheet!C3"], "NOT_RECALCULATED")
        self.assertEqual(report["unverified_count"], 1)


if __name__ == "__main__":
    unittest.main()
