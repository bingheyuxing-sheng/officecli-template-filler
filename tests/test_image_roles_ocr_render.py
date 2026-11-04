# -*- coding: utf-8 -*-
"""P2 tests: image roles, OCR adapter degradation and chart rendering status."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from unittest import mock

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

import docx
from PIL import Image

from engine import (
    audit_image_text,
    chart_render_status,
    detect_ocr_backend,
    find_images,
    find_placeholder_text,
    ocr_image,
    render_chart_image,
    replace_image_by_role,
)
from engine.chart_render import _validate


def _image(path: str, size, color) -> str:
    Image.new("RGB", size, color).save(path, format="PNG")
    return path


class TestImageRoleSuite(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(prefix="office_roles_")
        self.work_dir = self.temp_dir.name

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _document(self):
        logo = _image(os.path.join(self.work_dir, "logo.png"), (300, 120), (0, 80, 160))
        stamp = _image(os.path.join(self.work_dir, "stamp.png"), (200, 200), (200, 20, 20))
        chart = _image(os.path.join(self.work_dir, "chart.png"), (800, 500), (240, 240, 240))
        path = os.path.join(self.work_dir, "roles.docx")
        document = docx.Document()
        header_paragraph = document.sections[0].header.paragraphs[0]
        header_paragraph.add_run().add_picture(logo)
        header_paragraph.add_run().add_picture(stamp)
        document.add_paragraph("课程结构示意图")
        document.add_picture(chart)
        document.save(path)
        return path, logo, stamp, chart

    def test_find_images_classifies_header_and_body(self) -> None:
        path, _logo, _stamp, _chart = self._document()
        document = docx.Document(path)
        found = find_images(document)
        self.assertGreaterEqual(len(found), 3)
        roles = {item["role"] for item in found}
        self.assertIn("logo", roles)
        self.assertIn("illustration", roles)
        for item in found:
            self.assertTrue(item["evidence"], "every guess must state its evidence")

    def test_filter_by_role(self) -> None:
        path, _logo, _stamp, _chart = self._document()
        document = docx.Document(path)
        illustrations = find_images(document, role="illustration")
        self.assertTrue(illustrations)
        self.assertTrue(all(item["role"] == "illustration" for item in illustrations))
        with self.assertRaises(ValueError):
            find_images(document, role="not-a-role")

    def test_ambiguous_role_refuses_to_replace(self) -> None:
        path, logo, _stamp, _chart = self._document()
        document = docx.Document(path)
        header = document.sections[0].header.paragraphs[0]
        header.add_run().add_picture(logo)  # a second logo
        with self.assertRaises(ValueError) as context:
            replace_image_by_role(document, "logo", logo)
        self.assertIn("images matched", str(context.exception))

    def test_replace_by_role_replaces_single_match(self) -> None:
        path, _logo, _stamp, _chart = self._document()
        document = docx.Document(path)
        replacement = _image(os.path.join(self.work_dir, "new_chart.png"), (600, 400), (10, 10, 10))
        result = replace_image_by_role(document, "illustration", replacement)
        self.assertTrue(result["effective"])
        self.assertEqual(result["role"], "illustration")


class TestOcrSuite(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(prefix="office_ocr_")
        self.work_dir = self.temp_dir.name

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_placeholder_patterns(self) -> None:
        self.assertEqual(find_placeholder_text("姓名：***"), ["***"])
        self.assertEqual(find_placeholder_text("请在此处填写XXXX"), ["XXXX"])
        self.assertEqual(find_placeholder_text("正常文字"), [])

    def test_missing_backend_reports_gap(self) -> None:
        with mock.patch("engine.ocr_engine.detect_ocr_backend", return_value={"name": "none", "reader": None, "reason": "OCR_UNAVAILABLE"}):
            self.assertEqual(detect_ocr_backend()["name"], "none")
            result = ocr_image(os.path.join(self.work_dir, "missing.png"), reader=None)
        self.assertEqual(result["error"], "OCR_UNAVAILABLE")

    def test_injected_reader_detects_placeholder_in_image(self) -> None:
        image = _image(os.path.join(self.work_dir, "placeholder.png"), (120, 60), (255, 255, 255))
        path = os.path.join(self.work_dir, "ocr.docx")
        document = docx.Document()
        document.add_picture(image)
        document.save(path)

        def reader(_path):
            return [[[[0, 0], [10, 0], [10, 10], [0, 10]], "此处为***示例", 0.98]]

        report = audit_image_text(path, reader=reader)
        codes = [item["code"] for item in report["issues"]]
        self.assertIn("PLACEHOLDER_TEXT_IN_IMAGE", codes)
        self.assertFalse(report["passed"])
        self.assertTrue(report["images"][0]["placeholder_hits"])

    def test_ocr_without_backend_is_unverified_not_passed(self) -> None:
        image = _image(os.path.join(self.work_dir, "plain.png"), (60, 60), (0, 0, 0))
        path = os.path.join(self.work_dir, "plain.docx")
        document = docx.Document()
        document.add_picture(image)
        document.save(path)
        with mock.patch("engine.ocr_engine.detect_ocr_backend", return_value={"name": "none", "reader": None, "reason": "OCR_UNAVAILABLE"}):
            report = audit_image_text(path)
        self.assertIn("OCR_UNAVAILABLE", report["coverage_gaps"])
        self.assertEqual(report["unverified_count"], 1)


class TestChartRenderSuite(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(prefix="office_render_")
        self.work_dir = self.temp_dir.name

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_invalid_spec_is_reported(self) -> None:
        self.assertIsNotNone(_validate({"kind": "table", "rows": []}))
        self.assertIsNotNone(_validate({"kind": "bar", "categories": ["a"], "series": {"x": [1, 2]}}))
        self.assertIsNotNone(_validate({"kind": "pie", "categories": ["a"], "values": []}))
        result = render_chart_image({"kind": "unknown"}, os.path.join(self.work_dir, "x.png"))
        self.assertEqual(result["status"], "INVALID_SPEC")
        self.assertIsNone(result["path"])

    def test_missing_backend_returns_explicit_status(self) -> None:
        with mock.patch("engine.chart_render._load_matplotlib", return_value=(None, "ImportError: no matplotlib")):
            self.assertFalse(chart_render_status()["available"])
            result = render_chart_image(
                {"kind": "table", "rows": [["A", "B"], ["1", "2"]]},
                os.path.join(self.work_dir, "table.png"),
            )
        self.assertEqual(result["status"], "RENDER_BACKEND_UNAVAILABLE")
        self.assertIsNone(result["path"])

    def test_cjk_labels_without_font_are_refused(self) -> None:
        with mock.patch("engine.chart_render._load_matplotlib", return_value=(object(), None)), \
                mock.patch("engine.chart_render._cjk_font", return_value=None):
            result = render_chart_image(
                {"kind": "pie", "categories": ["必修", "选修"], "values": [70, 30]},
                os.path.join(self.work_dir, "pie.png"),
            )
        self.assertEqual(result["status"], "CJK_FONT_UNAVAILABLE")
        self.assertIsNone(result["path"])
        self.assertFalse(os.path.exists(os.path.join(self.work_dir, "pie.png")))


if __name__ == "__main__":
    unittest.main()
