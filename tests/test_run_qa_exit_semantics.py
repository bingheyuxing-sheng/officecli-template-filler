# -*- coding: utf-8 -*-
"""QA-01: ``run_qa.py`` must not signal success when required checks did not run.

The process exit code is the machine-readable contract used by CI.  UNVERIFIED
now exits 1 and requires an explicit ``--allow-unverified`` opt-in, matching the
same disclosure rule the generation path already enforces.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest

import openpyxl

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class RunQaExitSemanticsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="run-qa-exit-")
        path = os.path.join(self.tmp.name, "unverified.xlsx")
        workbook = openpyxl.Workbook()
        sheet = workbook.active
        sheet["A1"] = 1
        sheet["A2"] = 1
        sheet["A3"] = 2
        sheet["B2"] = 10
        sheet["B3"] = 20
        # XLOOKUP is outside the built-in evaluator: the check must stay UNVERIFIED.
        sheet["C1"] = "=XLOOKUP(A1,A2:A3,B2:B3)"
        workbook.save(path)
        self.path = path

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _run(self, *extra):
        return subprocess.run(
            [sys.executable, os.path.join(ROOT, "scripts", "run_qa.py"), self.path, *extra],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )

    def test_unverified_exits_non_zero_and_discloses(self) -> None:
        result = self._run()
        report = json.loads(result.stdout)
        self.assertEqual(report["status"], "UNVERIFIED")
        self.assertFalse(report["passed"])
        self.assertFalse(report["exit_ok"])
        self.assertEqual(result.returncode, 1)

    def test_allow_unverified_opts_into_zero_exit(self) -> None:
        result = self._run("--allow-unverified")
        report = json.loads(result.stdout)
        self.assertEqual(report["status"], "UNVERIFIED")
        self.assertTrue(report["exit_ok"])
        self.assertEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
