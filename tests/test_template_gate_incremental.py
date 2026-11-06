# -*- coding: utf-8 -*-
"""W4-4 tests: supplements, conflict handling and incremental re-analysis."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

import docx

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from template_gate import build_analysis  # noqa: E402
from template_gate.supplements import analyze_supplements, reanalyze, resolve_evidence  # noqa: E402


def _ambiguous_template(directory: str) -> str:
    path = os.path.join(directory, "template.docx")
    document = docx.Document()
    table = document.add_table(rows=2, cols=2)
    table.cell(1, 0).text = "一段说明文字"
    document.save(path)
    return path


def _filled_reference(directory: str) -> str:
    path = os.path.join(directory, "reference.docx")
    document = docx.Document()
    table = document.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "项目"
    table.cell(0, 1).text = "金额"
    table.cell(1, 0).text = "项目A"
    table.cell(1, 1).text = "100"
    document.save(path)
    return path


def _font_conflict_template(directory: str) -> str:
    path = os.path.join(directory, "conflict.docx")
    document = docx.Document()
    paragraph = document.add_paragraph()
    first = paragraph.add_run("{{标")
    first.font.name = "Arial"
    second = paragraph.add_run("题}}")
    second.font.name = "Times New Roman"
    document.save(path)
    return path


def _font_reference(directory: str, font: str) -> str:
    path = os.path.join(directory, "font-reference-%s.docx" % font.replace(" ", "_"))
    document = docx.Document()
    paragraph = document.add_paragraph()
    run = paragraph.add_run("{{标题}}")
    run.font.name = font
    document.save(path)
    return path


def _find(analysis: dict, prop: str) -> list:
    return [item for item in analysis["evidence"] if item["property"] == prop]


class SupplementTests(unittest.TestCase):
    def test_reference_resolves_ambiguous_table_purpose(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            template = _ambiguous_template(directory)
            reference = _filled_reference(directory)
            analysis = build_analysis(template, "GENERATE")
            self.assertGreaterEqual(analysis["summary"]["blocking"], 1)
            updated = analyze_supplements(template, analysis, [reference])
        self.assertGreaterEqual(updated["summary"]["verified"], 1)
        self.assertEqual(updated["summary"]["blocking"], 0)
        purpose = _find(updated, "table.purpose")[0]
        self.assertEqual(purpose["verification_status"], "VERIFIED")
        self.assertIn("reference_docx:", purpose["source"])

    def test_reference_resolves_font_conflict_only_when_value_matches(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            template = _font_conflict_template(directory)
            matching = _font_reference(directory, "Arial")
            analysis = build_analysis(template, "GENERATE")
            updated = analyze_supplements(template, analysis, [matching])
        self.assertEqual(updated["summary"]["blocking"], 0)

    def test_reference_conflict_keeps_gate_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            template = _font_conflict_template(directory)
            different = _font_reference(directory, "Calibri")
            analysis = build_analysis(template, "GENERATE")
            updated = analyze_supplements(template, analysis, [different])
        self.assertGreaterEqual(updated["summary"]["blocking"], 1)

    def test_user_answer_resolves_blocking_item(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            template = _ambiguous_template(directory)
            analysis = build_analysis(template, "GENERATE")
            purpose = _find(analysis, "table.purpose")[0]
            resolved = resolve_evidence(
                analysis,
                purpose["evidence_id"],
                resolution_type="PROVIDE_VALUE",
                value="fillable_form",
                user_statement="这个表格需要填写",
            )
        self.assertEqual(resolved["summary"]["blocking"], 0)
        self.assertEqual(_find(resolved, "table.purpose")[0]["verification_status"], "VERIFIED")

    def test_preserve_as_is_does_not_clear_a_task_relevant_item(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            template = _ambiguous_template(directory)
            analysis = build_analysis(template, "GENERATE")
            purpose = _find(analysis, "table.purpose")[0]
            preserved = resolve_evidence(
                analysis,
                purpose["evidence_id"],
                resolution_type="PRESERVE_AS_IS",
                user_statement="保留原样",
            )
        self.assertGreaterEqual(preserved["summary"]["blocking"], 1)

    def test_json_claim_answer_is_applied_by_address(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            template = _ambiguous_template(directory)
            answers = os.path.join(directory, "answers.json")
            with open(answers, "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "answers": [
                            {
                                "location": "body.tbl[0]",
                                "property": "table.purpose",
                                "value": "fixed_or_reference",
                                "note": "该表格是固定说明表",
                            }
                        ]
                    },
                    handle,
                    ensure_ascii=False,
                )
            analysis = build_analysis(template, "GENERATE")
            updated = analyze_supplements(template, analysis, [answers])
        self.assertEqual(updated["summary"]["blocking"], 0)

    def test_unsupported_supplement_type_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            template = _ambiguous_template(directory)
            unsupported = os.path.join(directory, "reference.pdf")
            with open(unsupported, "w", encoding="utf-8") as handle:
                handle.write("not a real pdf")
            analysis = build_analysis(template, "GENERATE")
            with self.assertRaises(ValueError):
                analyze_supplements(template, analysis, [unsupported])

    def test_reanalysis_keeps_previous_resolution(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            template = _ambiguous_template(directory)
            analysis = build_analysis(template, "GENERATE")
            purpose = _find(analysis, "table.purpose")[0]
            resolved = resolve_evidence(
                analysis,
                purpose["evidence_id"],
                resolution_type="PROVIDE_VALUE",
                value="fillable_form",
                user_statement="需要填写",
            )
            again = reanalyze(template, "GENERATE", previous=resolved)
        self.assertEqual(again["summary"]["blocking"], 0)
        self.assertEqual(_find(again, "table.purpose")[0]["verification_status"], "VERIFIED")


if __name__ == "__main__":
    unittest.main()
