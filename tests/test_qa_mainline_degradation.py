# -*- coding: utf-8 -*-
"""QA-02: only a genuinely missing ``qa`` package may degrade the QA mainline.

``execute_fill_plan`` used to catch every exception raised while importing
``qa.pipeline`` and silently fall back to a PACKAGE+FORMAT-only report.  A
broken QA module therefore looked like an environment limitation instead of a
defect.  These tests pin the two sides of the boundary.
"""

from __future__ import annotations

import builtins
import os
import tempfile
import unittest
from unittest import mock

import docx

from document_engine.fill_executor import _fallback_qa_report, _run_qa

_REAL_IMPORT = builtins.__import__


def _import_failing_for(target: str, exc: BaseException):
    def _fake(name, *args, **kwargs):
        if name == target:
            raise exc
        return _REAL_IMPORT(name, *args, **kwargs)

    return _fake


class QaMainlineDegradationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="qa-mainline-")
        self.template = os.path.join(self.tmp.name, "template.docx")
        self.staged = os.path.join(self.tmp.name, "staged.docx")
        for path in (self.template, self.staged):
            document = docx.Document()
            document.add_paragraph("合同编号：__")
            document.save(path)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _run(self):
        return _run_qa(None, self.staged, self.template, "TASK_QA_001", "STRICT", None, None, None)

    def test_missing_qa_package_returns_disclosed_fallback(self) -> None:
        missing = ModuleNotFoundError("No module named 'qa'", name="qa")
        with mock.patch("builtins.__import__", side_effect=_import_failing_for("qa.pipeline", missing)):
            report = self._run()
        self.assertEqual(report["status"], "UNVERIFIED")
        self.assertFalse(report["final"]["eligible_for_commit"])
        self.assertTrue(any(str(gap).startswith("CHECK_NOT_IMPLEMENTED:") for gap in report["coverage_gaps"]))

    def test_internal_missing_dependency_propagates(self) -> None:
        broken = ModuleNotFoundError("No module named 'some_dep'", name="some_dep")
        with mock.patch("builtins.__import__", side_effect=_import_failing_for("qa.pipeline", broken)):
            with self.assertRaises(ModuleNotFoundError):
                self._run()

    def test_unexpected_import_error_propagates(self) -> None:
        with mock.patch("builtins.__import__", side_effect=_import_failing_for("qa.pipeline", RuntimeError("boom"))):
            with self.assertRaises(RuntimeError):
                self._run()

    def test_fallback_report_never_claims_eligibility(self) -> None:
        report = _fallback_qa_report(self.staged, self.template, "TASK_QA_002", "STANDARD")
        self.assertEqual(report["status"], "UNVERIFIED")
        self.assertFalse(report["final"]["eligible_for_commit"])


if __name__ == "__main__":
    unittest.main()
