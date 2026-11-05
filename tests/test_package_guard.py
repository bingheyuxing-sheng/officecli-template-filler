# -*- coding: utf-8 -*-
"""W3-7: pre-parse ZIP resource quotas (audit P2-03).

Every violation is triggered with small injected limits so the tests stay
fast and host-independent; the config file only tunes the production defaults.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

import docx
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.package_guard import DEFAULT_LIMITS, check_package, load_limits  # noqa: E402
from template_intelligence import build_document_spec_from_path  # noqa: E402


def _make_docx(path: str) -> None:
    document = docx.Document()
    document.add_paragraph("{{项目名称}}")
    document.save(path)


def _make_zip(path: str, entries) -> None:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in entries:
            zf.writestr(name, data)


class PackageGuardTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = self._tmp.name

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_clean_docx_passes_defaults(self) -> None:
        path = os.path.join(self.dir, "ok.docx")
        _make_docx(path)
        verdict = check_package(path)
        self.assertTrue(verdict["ok"], verdict)

    def test_entry_count_limit(self) -> None:
        path = os.path.join(self.dir, "many.zip")
        _make_zip(path, [("f%d.txt" % i, b"x") for i in range(10)])
        verdict = check_package(path, {"max_entries": 5})
        self.assertFalse(verdict["ok"])
        self.assertEqual(verdict["code"], "PACKAGE_LIMIT_EXCEEDED")
        self.assertIn("max_entries", [v["limit"] for v in verdict["violations"]])

    def test_single_entry_limit(self) -> None:
        path = os.path.join(self.dir, "big.zip")
        _make_zip(path, [("big.bin", b"a" * 5000)])
        verdict = check_package(path, {"max_entry_bytes": 1000})
        self.assertIn("max_entry_bytes", [v["limit"] for v in verdict["violations"]])

    def test_total_uncompressed_limit(self) -> None:
        path = os.path.join(self.dir, "sum.zip")
        _make_zip(path, [("a.bin", b"a" * 3000), ("b.bin", b"b" * 3000)])
        verdict = check_package(path, {"max_total_uncompressed_bytes": 4000})
        self.assertIn("max_total_uncompressed_bytes", [v["limit"] for v in verdict["violations"]])

    def test_compression_ratio_limit(self) -> None:
        path = os.path.join(self.dir, "bomb.zip")
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("zeros.bin", "\0" * (2 * 1024 * 1024))
        verdict = check_package(path, {"max_compression_ratio": 10})
        self.assertIn("max_compression_ratio", [v["limit"] for v in verdict["violations"]])

    def test_input_size_limit_short_circuits(self) -> None:
        path = os.path.join(self.dir, "fat.docx")
        _make_docx(path)
        verdict = check_package(path, {"max_input_bytes": 10})
        self.assertFalse(verdict["ok"])
        self.assertEqual(verdict["violations"][0]["limit"], "max_input_bytes")

    def test_image_pixel_limit(self) -> None:
        png = os.path.join(self.dir, "big.png")
        Image.new("RGB", (64, 64), (1, 2, 3)).save(png)
        path = os.path.join(self.dir, "media.zip")
        with zipfile.ZipFile(path, "w") as zf:
            zf.write(png, "word/media/image1.png")
        verdict = check_package(path, {"max_total_image_pixels": 100})
        self.assertIn("max_total_image_pixels", [v["limit"] for v in verdict["violations"]])

    def test_non_zip_is_not_readable(self) -> None:
        path = os.path.join(self.dir, "fake.docx")
        with open(path, "wb") as handle:
            handle.write(b"not a zip")
        verdict = check_package(path)
        self.assertFalse(verdict["ok"])
        self.assertEqual(verdict["code"], "PACKAGE_NOT_READABLE")

    def test_config_file_merges_over_defaults(self) -> None:
        limits = load_limits()
        for key in DEFAULT_LIMITS:
            self.assertGreater(limits[key], 0)
        custom = os.path.join(self.dir, "limits.json")
        with open(custom, "w", encoding="utf-8") as handle:
            json.dump({"limits": {"max_entries": 7, "unknown_key": 1}}, handle)
        merged = load_limits(custom)
        self.assertEqual(merged["max_entries"], 7)
        self.assertNotIn("unknown_key", merged)


class BaselineInheritanceTests(unittest.TestCase):
    """WPS templates that already lack ``xml:space`` must not block an authorized fill."""

    XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = self._tmp.name

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self.dir, ignore_errors=True)

    def _docx_with_missing_space(self, name: str, extra: int = 0) -> str:
        path = os.path.join(self.dir, name)
        document = docx.Document()
        document.add_paragraph(" 前导空格 ")
        for index in range(extra):
            document.add_paragraph(" 额外空格 %d " % index)
        for t_el in document.element.body.xpath(".//w:t"):
            t_el.attrib.pop(self.XML_SPACE, None)
        document.save(path)
        return path

    def test_inherited_space_preserve_is_disclosed_not_blocking(self) -> None:
        from engine.qa_engine import audit_docx_package_integrity

        template = self._docx_with_missing_space("template.docx")
        output = os.path.join(self.dir, "output.docx")
        with open(template, "rb") as source, open(output, "wb") as target:
            target.write(source.read())

        report = audit_docx_package_integrity(output, baseline_path=template)
        self.assertTrue(report["passed"], report["structured_issues"])
        self.assertEqual(report["inherited_space_preserve"], report["missing_space_preserve"])
        self.assertEqual(
            [item["code"] for item in report["structured_issues"]],
            ["PACKAGE_SPACE_PRESERVE_MISSING"],
        )
        self.assertEqual(report["structured_issues"][0]["severity"], "medium")

        strict = audit_docx_package_integrity(output)
        self.assertFalse(strict["passed"])
        self.assertEqual(strict["inherited_space_preserve"], 0)

    def test_new_space_preserve_beyond_baseline_is_blocking(self) -> None:
        from engine.qa_engine import audit_docx_package_integrity

        template = self._docx_with_missing_space("template.docx")
        output = self._docx_with_missing_space("output.docx", extra=2)
        report = audit_docx_package_integrity(output, baseline_path=template)
        self.assertFalse(report["passed"])
        self.assertEqual(report["inherited_space_preserve"], 0)
        self.assertGreater(report["effective_space_preserve"], 0)

    def test_format_qa_does_not_raise_when_raise_on_failure_is_false(self) -> None:
        from engine.qa_engine import audit_format_and_text_qa

        template = self._docx_with_missing_space("template.docx")
        report = audit_format_and_text_qa(
            docx.Document(template),
            docx_path=template,
            reference_docx_path=template,
            raise_on_failure=False,
            comparison_profile="STYLE_GUIDE",
        )
        self.assertTrue(report["passed"], report["structured_issues"])
        self.assertGreater(report["inherited_space_preserve"], 0)


class GuardIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = self._tmp.name
        self.docx_path = os.path.join(self.dir, "t.docx")
        _make_docx(self.docx_path)

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_spec_builder_rejects_before_parsing(self) -> None:
        with mock.patch("engine.package_guard.load_limits",
                        return_value={**DEFAULT_LIMITS, "max_input_bytes": 10}):
            spec = build_document_spec_from_path(self.docx_path)
        self.assertTrue(spec["errors"])
        self.assertIn("PACKAGE_LIMIT_EXCEEDED", spec["errors"][0]["detail"])

    def test_fill_executor_blocks_over_quota(self) -> None:
        from document_engine import execute_fill_plan

        with mock.patch("engine.package_guard.load_limits",
                        return_value={**DEFAULT_LIMITS, "max_input_bytes": 10}):
            result = execute_fill_plan(self.docx_path, {}, {}, os.path.join(self.dir, "out.docx"))
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(result["errors"][0]["code"], "PACKAGE_LIMIT_EXCEEDED")
        self.assertFalse(os.path.exists(os.path.join(self.dir, "out.docx")))

    def test_cli_rejects_non_zip(self) -> None:
        import subprocess
        path = os.path.join(self.dir, "fake.docx")
        with open(path, "wb") as handle:
            handle.write(b"junk")
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "analyze_template.py"), "--input", path],
            cwd=str(ROOT), capture_output=True, text=True, timeout=120,
        )
        self.assertEqual(result.returncode, 2)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["error"], "PACKAGE_NOT_READABLE")


if __name__ == "__main__":
    unittest.main()
