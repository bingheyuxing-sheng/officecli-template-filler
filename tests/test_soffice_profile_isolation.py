# -*- coding: utf-8 -*-
"""W3-5: every soffice invocation must carry its own -env:UserInstallation.

Host-independent (E2): the process runner is mocked; no LibreOffice is needed.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import engine.pdf_backend as pdf_backend  # noqa: E402
import engine.excel_engine as excel_engine  # noqa: E402


def _profile_path_from(command):
    from urllib.parse import urlparse
    from urllib.request import url2pathname

    arg = next(item for item in command if item.startswith("-env:UserInstallation="))
    return url2pathname(urlparse(arg.split("=", 1)[1]).path)


class SofficeProfileIsolationTests(unittest.TestCase):
    def test_libreoffice_pdf_call_gets_private_profile(self) -> None:
        captured = []

        def fake_run(command, timeout):
            captured.append(list(command))
            return 1, "", "boom"

        with mock.patch.object(pdf_backend, "_run", fake_run):
            pdf_backend._convert_with_libreoffice("soffice", "src.docx", "out", "out.pdf")

        self.assertEqual(len(captured), 1)
        command = captured[0]
        self.assertEqual(command[0], "soffice")
        self.assertTrue(command[1].startswith("-env:UserInstallation=file:"), command[1])
        profile = _profile_path_from(command)
        self.assertIn("lo-profile-", str(profile))
        self.assertFalse(os.path.exists(str(profile)), "profile dir must be removed after the call")

    def test_two_pdf_calls_get_distinct_profiles(self) -> None:
        seen = []

        def fake_run(command, timeout):
            seen.append(_profile_path_from(command))
            return 1, "", "x"

        with mock.patch.object(pdf_backend, "_run", fake_run):
            pdf_backend._convert_with_libreoffice("soffice", "a.docx", "out", "a.pdf")
            pdf_backend._convert_with_libreoffice("soffice", "b.docx", "out", "b.pdf")
        self.assertNotEqual(str(seen[0]), str(seen[1]))

    def test_excel_recalculation_call_gets_private_profile(self) -> None:
        captured = {}

        class FakeGuard:
            def run_owned_command(self, command, timeout=None, check=False):
                captured["command"] = list(command)
                return SimpleNamespace(returncode=1)

        with tempfile.TemporaryDirectory() as tmp:
            book = os.path.join(tmp, "b.xlsx")
            import openpyxl
            wb = openpyxl.Workbook()
            wb.active["A1"] = "=SUM(B1:B2)"
            wb.save(book)
            wb.close()
            with mock.patch.object(excel_engine.shutil, "which", return_value="/fake/soffice"):
                report = excel_engine.recalculate_and_verify_excel_formulas(book, guard=FakeGuard())

        command = captured["command"]
        self.assertTrue(command[1].startswith("-env:UserInstallation=file:"), command[1])
        self.assertEqual(command[2], "--headless")
        self.assertEqual(report["engine"], "builtin_decimal_evaluator")  # recalc failed -> builtin only

    def test_wps_path_untouched(self) -> None:
        captured = []

        def fake_run(command, timeout):
            captured.append(list(command))
            return 1, "", "x"

        with mock.patch.object(pdf_backend, "_run", fake_run):
            pdf_backend._convert_with_wps("kwpsconvert.exe", "src.docx", "out.pdf")
        self.assertFalse(any(str(item).startswith("-env:") for item in captured[0]))


if __name__ == "__main__":
    unittest.main()
