# -*- coding: utf-8 -*-
"""Regression: real-world Excel workbooks must not crash or hang the analyzer.

Two exam-corpus workbooks made openpyxl raise TypeError while parsing charts
(PageItem/Nested), and one 5.5 MB workbook took ~33 s in full mode. The fix
falls back to read-only and uses read-only for large inputs, disclosing what
was not inspected instead of claiming full structural coverage.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import openpyxl

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine import excel_spec  # noqa: E402
from engine.excel_spec import extract_excel_spec  # noqa: E402


def _make_book(path: str, with_merge: bool = False) -> None:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Sheet"
    ws["A1"] = "{{项目名称}}"
    ws["B2"] = "=SUM(B1:B2)"
    if with_merge:
        ws.merge_cells("A3:B3")
    wb.save(path)
    wb.close()


class ExcelSpecResilienceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = self._tmp.name
        self.path = os.path.join(self.dir, "book.xlsx")
        _make_book(self.path, with_merge=True)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_small_workbook_uses_full_scan(self) -> None:
        spec = extract_excel_spec(self.path)
        self.assertEqual(spec["scan_mode"], "full")
        self.assertEqual(spec["degraded"], [])
        self.assertIn("A3:B3", spec["sheets"][0]["merged_ranges"])
        self.assertEqual(spec["placeholder_tokens"], ["{{项目名称}}"])
        self.assertEqual(spec["errors"], [])

    def test_large_workbook_uses_read_only_scan(self) -> None:
        with mock.patch.object(excel_spec, "_FULL_SCAN_MAX_BYTES", 1):
            spec = extract_excel_spec(self.path)
        self.assertEqual(spec["scan_mode"], "read_only_large")
        self.assertTrue(any("LARGE_WORKBOOK_READ_ONLY_SCAN" in n for n in spec["degraded"]))
        self.assertEqual(spec["sheet_count"], 1)
        self.assertEqual(spec["placeholder_tokens"], ["{{项目名称}}"])
        self.assertEqual(spec["errors"], [])

    def test_chart_parse_error_falls_back_read_only(self) -> None:
        real_open = excel_spec._open_excel_workbook
        calls = []

        def fail_full_then_succeed(path, is_xlsm, read_only):
            calls.append(read_only)
            if len(calls) == 1:
                raise TypeError("PageItem.__init__() got an unexpected keyword argument 'count'")
            return real_open(path, is_xlsm, read_only)

        with mock.patch.object(excel_spec, "_open_excel_workbook", fail_full_then_succeed):
            spec = extract_excel_spec(self.path)
        self.assertEqual(calls, [False, True], "full scan must be retried read-only")
        self.assertEqual(spec["scan_mode"], "read_only_fallback")
        self.assertTrue(any("FULL_SCAN_FAILED" in n for n in spec["degraded"]))
        self.assertEqual(spec["sheet_count"], 1)
        self.assertEqual(spec["placeholder_tokens"], ["{{项目名称}}"])
        self.assertEqual(spec["errors"], [])

    def test_both_modes_fail_returns_structured_error(self) -> None:
        def always_fail(path, is_xlsm, read_only):
            raise TypeError("Nested.from_tree() missing 1 required positional argument: 'node'")

        with mock.patch.object(excel_spec, "_open_excel_workbook", always_fail):
            spec = extract_excel_spec(self.path)
        self.assertEqual(spec["errors"][0]["code"], "EXCEL_PARSE_FAILED")
        self.assertEqual(spec["sheet_count"], 0)
        self.assertIn("Workbook could not be parsed", " ".join(spec["compatibility"]["notes"]))


if __name__ == "__main__":
    unittest.main()
