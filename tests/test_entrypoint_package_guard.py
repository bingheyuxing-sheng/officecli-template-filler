# -*- coding: utf-8 -*-
"""SEC-01: every CLI entrypoint must reject an over-budget package before parsing.

A DOCX/XLSX is a ZIP container; a few KB can inflate to gigabytes.  Generation
and template analysis already applied ``engine.package_guard``; review,
proofread, repair, reformat, run_qa, render and the template-gate CLI did not.
These tests drive each real ``main()`` with a high-ratio archive and require a
structured ``PACKAGE_LIMIT_EXCEEDED`` rejection with exit code 2.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import pathlib
import sys
import tempfile
import unittest
import zipfile
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"

# 2 MiB of zeros compresses to a few KB: well above the 200x ratio guard and
# above ratio_min_entry_bytes, while staying far below max_input_bytes.
BOMB_ENTRY_BYTES = 2 * 1024 * 1024


def _load_script(name: str):
    path = SCRIPTS / ("%s.py" % name)
    spec = importlib.util.spec_from_file_location("guard_%s" % name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class EntrypointPackageGuardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="pkg-guard-cli-")
        self.bomb = os.path.join(self.tmp.name, "bomb.docx")
        with zipfile.ZipFile(self.bomb, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("word/document.xml", b"\0" * BOMB_ENTRY_BYTES)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _invoke(self, script: str, argv: list):
        module = _load_script(script)
        stdout = io.StringIO()
        with mock.patch.object(sys, "argv", [script] + argv), contextlib.redirect_stdout(stdout):
            code = module.main()
        payload = None
        text = stdout.getvalue().strip()
        if text:
            try:
                payload = json.loads(text)
            except ValueError:
                payload = None
        return code, payload

    def _assert_rejected(self, script: str, argv: list) -> None:
        code, payload = self._invoke(script, argv)
        self.assertEqual(code, 2, "%s must exit 2 on an over-budget package" % script)
        self.assertIsNotNone(payload, "%s must print a structured rejection" % script)
        self.assertEqual(payload.get("error"), "PACKAGE_LIMIT_EXCEEDED", payload)
        guard = payload.get("package_guard") or {}
        self.assertFalse(guard.get("ok"))
        limits = {item.get("limit") for item in guard.get("violations") or []}
        self.assertIn("max_compression_ratio", limits)

    def test_review_document_rejects_before_parsing(self) -> None:
        self._assert_rejected(
            "review_document",
            ["--target", self.bomb, "--out", os.path.join(self.tmp.name, "out.docx")],
        )

    def test_proofread_document_rejects_before_parsing(self) -> None:
        self._assert_rejected(
            "proofread_document",
            ["--target", self.bomb, "--out", os.path.join(self.tmp.name, "out.docx")],
        )

    def test_repair_document_rejects_before_parsing(self) -> None:
        self._assert_rejected(
            "repair_document",
            ["--reference", self.bomb, "--broken", self.bomb],
        )

    def test_reformat_document_rejects_before_parsing(self) -> None:
        self._assert_rejected(
            "reformat_document",
            ["--reference", self.bomb, "--target", self.bomb],
        )

    def test_run_qa_rejects_before_parsing(self) -> None:
        self._assert_rejected("run_qa", [self.bomb])

    def test_render_document_rejects_before_parsing(self) -> None:
        self._assert_rejected("render_document", [self.bomb])

    def test_template_gate_analyze_rejects_before_parsing(self) -> None:
        self._assert_rejected(
            "template_gate",
            ["analyze", "--template", self.bomb, "--task-type", "GENERATE"],
        )


if __name__ == "__main__":
    unittest.main()
