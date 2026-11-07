# -*- coding: utf-8 -*-
"""W4-3 tests: Analysis Report structure, Markdown rendering and CLI."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import docx
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from template_gate import build_analysis  # noqa: E402
from template_gate.report import build_report, render_markdown, report_digest  # noqa: E402


def _standard(directory: str) -> str:
    path = os.path.join(directory, "standard.docx")
    document = docx.Document()
    document.add_paragraph("{{项目名称}}")
    table = document.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "项目"
    table.cell(0, 1).text = "金额"
    table.cell(1, 0).text = "{{项目名称}}"
    document.save(path)
    return path


def _ambiguous(directory: str) -> str:
    path = os.path.join(directory, "ambiguous.docx")
    document = docx.Document()
    table = document.add_table(rows=2, cols=2)
    table.cell(1, 0).text = "一段说明文字"
    document.save(path)
    return path


class AnalysisReportTests(unittest.TestCase):
    def test_standard_report_has_all_sections(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            analysis = build_analysis(_standard(directory), "GENERATE")
        report = build_report(analysis)
        self.assertEqual(report["blocking_items"], [])
        self.assertGreaterEqual(report["basics"]["table_count"], 1)
        self.assertTrue(report["quality"]["coverage"] > 0)
        self.assertIn("模板解析已经完成", report["confirmation"]["prompt"])
        markdown = render_markdown(report)
        for heading in ("## 1. 模板基本信息", "## 2. 页面和样式规则", "## 3. 文档结构", "## 4. 解析质量", "## 5. 阻断性问题", "## 7. 用户确认"):
            self.assertIn(heading, markdown)
        self.assertIn("当前没有阻断性问题。", markdown)

    def test_blocking_report_contains_seven_fields(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            analysis = build_analysis(_ambiguous(directory), "GENERATE")
        report = build_report(analysis)
        self.assertTrue(report["blocking_items"])
        item = report["blocking_items"][0]
        for key in (
            "item_id",
            "location",
            "current_result",
            "reason",
            "possible_error",
            "required_materials",
            "acceptable_resolutions",
        ):
            self.assertIn(key, item)
        markdown = render_markdown(report)
        self.assertIn("## 5. 阻断性问题", markdown)
        self.assertIn(item["item_id"], markdown)
        self.assertIn("明确要求保留原样", markdown)

    def test_report_digest_ignores_generated_at(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            analysis = build_analysis(_standard(directory), "GENERATE")
        first = build_report(analysis)
        second = build_report(analysis)
        # Windows' clock resolution can return the same microsecond twice, so
        # assert the invariant (digest ignores the timestamp) rather than
        # requiring two different timestamps.
        self.assertEqual(first["report_digest"], second["report_digest"])
        self.assertEqual(report_digest(first), report_digest(second))
        mutated = dict(first)
        mutated["generated_at"] = "1999-01-01T00:00:00+00:00"
        self.assertEqual(report_digest(mutated), report_digest(first))

    def test_report_validates_against_schema(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            analysis = build_analysis(_ambiguous(directory), "GENERATE")
        report = build_report(analysis)
        with open(ROOT / "schemas" / "template_analysis_report-1.0.schema.json", "r", encoding="utf-8") as handle:
            schema = json.load(handle)
        errors = sorted(Draft202012Validator(schema).iter_errors(report), key=lambda item: list(item.absolute_path))
        self.assertEqual(errors, [], [error.message for error in errors])


class TemplateGateCliTests(unittest.TestCase):
    def test_analyze_and_report_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            template = _standard(directory)
            analysis_path = os.path.join(directory, "analysis.json")
            report_path = os.path.join(directory, "report.md")
            script = str(ROOT / "scripts" / "template_gate.py")

            analyze = subprocess.run(
                [sys.executable, script, "analyze", "--template", template, "--task-type", "GENERATE", "--out", analysis_path],
                capture_output=True,
                text=True,
                cwd=str(ROOT),
            )
            self.assertEqual(analyze.returncode, 0, analyze.stderr)
            self.assertTrue(os.path.isfile(analysis_path))

            report = subprocess.run(
                [sys.executable, script, "report", "--analysis", analysis_path, "--out", report_path],
                capture_output=True,
                text=True,
                cwd=str(ROOT),
            )
            self.assertEqual(report.returncode, 0, report.stderr)
            self.assertTrue(os.path.isfile(report_path))
            with open(report_path, "r", encoding="utf-8") as handle:
                rendered = handle.read()
            self.assertIn("模板分析报告", rendered)
            self.assertIn("用户确认", rendered)


if __name__ == "__main__":
    unittest.main()
