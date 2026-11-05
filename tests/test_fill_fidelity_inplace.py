# -*- coding: utf-8 -*-
"""Regression: authorized fills must not rewrite run structure.

Real-corpus fills previously triggered FIDELITY ``UNAUTHORIZED_TEMPLATE_CHANGE``
because the executor deleted emptied runs and rebuilt paragraphs through the v3
strict-style path, changing the structural fingerprint of an authorized slot.
The v4 path replaces spans in place, keeps emptied runs, and the structural
hash ignores ``w:color`` (the only attribute an authorized fill strips).
Also covers the STANDARD/UNVERIFIED commit gate for coverage-gap-only reports
(contract 04 §7: eligibility keys on disclosure, not on a per-checker count).
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

import docx
from docx.oxml.ns import qn
from docx.shared import Pt, RGBColor

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from content_intelligence import build_content_plan, build_fill_plan  # noqa: E402
from document_engine import execute_fill_plan  # noqa: E402
from document_engine.fill_executor import _apply_operation  # noqa: E402
from template_intelligence import build_document_spec_from_path  # noqa: E402
from template_intelligence.fingerprint import compute_four_hashes  # noqa: E402

TOKEN = "{{项目名称}}"
VALUE = "示例项目"


def passing_qa(_staged_path):
    return {
        "schema_version": "4.0",
        "task_id": "TASK_FIDELITY_001",
        "status": "PASSED",
        "task_mode": "GENERATE",
        "gate_mode": "STRICT",
        "policy_source": "GENERATE/STRICT",
        "required_checks": ["PACKAGE", "FORMAT"],
        "executed_checks": ["PACKAGE", "FORMAT"],
        "missing_checks": [],
        "checks": [],
        "issues": [],
        "coverage_gaps": [],
        "repairs": [],
        "final": {"eligible_for_commit": True, "reasons": []},
    }


def _make_split_token_paragraph(document):
    """One logical token split across two red bold runs (real-corpus shape)."""
    paragraph = document.add_paragraph()
    first = paragraph.add_run("{{项目")
    first.font.color.rgb = RGBColor(0xFF, 0x00, 0x00)
    first.bold = True
    first.font.size = Pt(14)
    second = paragraph.add_run("名称}}")
    second.font.color.rgb = RGBColor(0xFF, 0x00, 0x00)
    second.bold = True
    second.font.size = Pt(14)
    return paragraph


def _run_nodes(paragraph):
    return paragraph._p.findall(qn("w:r"))


def _has_color(run):
    rpr = run._r.find(qn("w:rPr"))
    if rpr is None:
        return False
    return any(child.tag == qn("w:color") for child in rpr)


def _is_bold(run):
    rpr = run._r.find(qn("w:rPr"))
    if rpr is None:
        return False
    bold = rpr.find(qn("w:b"))
    return bold is not None and bold.get(qn("w:val")) != "0"


class _PlanCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="fid_inplace_")
        self.directory = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _plan_for_first_paragraph(self, template_path: Path):
        spec = build_document_spec_from_path(str(template_path))
        slot = next(s for s in spec["slots"] if s["location_id"] == "body.p[0]")
        content = build_content_plan(
            spec,
            plan_id="CP_FID_001",
            sections=[{
                "section_id": "SEC_001",
                "purpose": "项目名称",
                "target_slots": [slot["slot_id"]],
            }],
            facts=[],
            required_slots=[slot["slot_id"]],
        )
        plan = build_fill_plan(
            spec, content, task_id="TASK_FIDELITY_001", mode="STRICT",
            values_by_slot={slot["slot_id"]: VALUE},
        )
        return spec, content, plan, slot


class ReplaceTextInPlaceTests(_PlanCase):
    def test_split_token_fill_keeps_runs_formatting_and_structural_hash(self) -> None:
        template = self.directory / "split.docx"
        document = docx.Document()
        _make_split_token_paragraph(document)
        document.save(str(template))

        spec, content, plan, slot = self._plan_for_first_paragraph(template)
        self.assertEqual(slot["matched_text"], TOKEN)
        output = self.directory / "split-out.docx"

        result = execute_fill_plan(
            str(template), spec, plan, str(output),
            content_plan=content, qa_runner=passing_qa,
        )
        self.assertEqual(result["status"], "SUCCESS", result["errors"])

        filled = docx.Document(str(output)).paragraphs[0]
        self.assertEqual(filled.text, VALUE)
        # Emptied runs are kept: the element tree must not lose nodes.
        self.assertEqual(len(_run_nodes(filled)), 2)
        first = filled.runs[0]
        self.assertTrue(_is_bold(first), "authorized fill must keep bold rPr")
        self.assertFalse(_has_color(first), "placeholder red colour must be stripped")

        template_hashes = compute_four_hashes(docx.Document(str(template)))
        output_hashes = compute_four_hashes(docx.Document(str(output)))
        self.assertEqual(template_hashes["structural_hash"],
                         output_hashes["structural_hash"])
        self.assertEqual(template_hashes["style_hash"], output_hashes["style_hash"])
        self.assertEqual(template_hashes["layout_hash"], output_hashes["layout_hash"])

    def test_missing_token_fallback_replaces_in_place(self) -> None:
        """When the token is gone the value must still land without rebuilding runs."""
        document = docx.Document()
        paragraph = document.add_paragraph()
        run = paragraph.add_run("旧值文本")
        run.bold = True
        run.font.size = Pt(12)
        before = compute_four_hashes(document)

        operation = {
            "op_id": "OP_001", "sequence": 1, "type": "replace_text",
            "slot_id": "S_000000000001",
            "target": {"location_id": "body.p[0]"},
            "value": VALUE, "policy": "STRICT",
        }
        slot = {"matched_text": "{{不存在}}", "occurrence": None}
        paragraphs = {"body.p[0]": document.paragraphs[0]}
        text_before, text_after = _apply_operation(
            document, operation, slot, paragraphs, tables={}, cell=None,
        )
        self.assertEqual(text_before, "旧值文本")
        self.assertEqual(text_after, VALUE)
        self.assertEqual(len(_run_nodes(document.paragraphs[0])), 1)
        self.assertTrue(_is_bold(document.paragraphs[0].runs[0]))
        after = compute_four_hashes(document)
        self.assertEqual(before["structural_hash"], after["structural_hash"])

    def test_empty_paragraph_still_uses_strict_style_path(self) -> None:
        document = docx.Document()
        document.add_paragraph("")
        operation = {
            "op_id": "OP_001", "sequence": 1, "type": "replace_text",
            "slot_id": "S_000000000001",
            "target": {"location_id": "body.p[0]"},
            "value": VALUE, "policy": "STRICT",
        }
        slot = {"matched_text": TOKEN, "occurrence": None}
        _apply_operation(
            document, operation, slot,
            {"body.p[0]": document.paragraphs[0]}, tables={}, cell=None,
        )
        self.assertEqual(document.paragraphs[0].text, VALUE)


class FillParagraphInPlaceTests(unittest.TestCase):
    def test_red_clue_paragraph_replaced_in_place(self) -> None:
        document = docx.Document()
        paragraph = document.add_paragraph()
        run = paragraph.add_run("请填写")
        run.font.color.rgb = RGBColor(0xFF, 0x00, 0x00)
        run.bold = True
        before = compute_four_hashes(document)

        operation = {
            "op_id": "OP_001", "sequence": 1, "type": "fill_paragraph",
            "slot_id": "S_000000000001",
            "target": {"location_id": "body.p[0]"},
            "value": VALUE, "policy": "STRICT",
        }
        slot = {"matched_text": "请填写", "occurrence": None}
        text_before, text_after = _apply_operation(
            document, operation, slot,
            {"body.p[0]": document.paragraphs[0]}, tables={}, cell=None,
        )
        self.assertEqual(text_before, "请填写")
        self.assertEqual(text_after, VALUE)
        self.assertEqual(len(_run_nodes(document.paragraphs[0])), 1)
        self.assertTrue(_is_bold(document.paragraphs[0].runs[0]))
        after = compute_four_hashes(document)
        self.assertEqual(before["structural_hash"], after["structural_hash"])

    def test_empty_paragraph_fill_creates_run(self) -> None:
        document = docx.Document()
        document.add_paragraph("")
        operation = {
            "op_id": "OP_001", "sequence": 1, "type": "fill_paragraph",
            "slot_id": "S_000000000001",
            "target": {"location_id": "body.p[0]"},
            "value": VALUE, "policy": "STRICT",
        }
        slot = {"matched_text": "", "occurrence": None}
        _apply_operation(
            document, operation, slot,
            {"body.p[0]": document.paragraphs[0]}, tables={}, cell=None,
        )
        self.assertEqual(document.paragraphs[0].text, VALUE)


class FormatResidualInheritanceTests(unittest.TestCase):
    """A blank the template already had is not a fill defect; a targeted one is."""

    def _template(self, directory: Path) -> Path:
        template = directory / "blank.docx"
        document = docx.Document()
        document.add_paragraph("姓名：___________")
        document.save(str(template))
        return template

    def _section(self):
        return {
            "passed": False,
            "structured_issues": [
                {
                    "code": "TEMPLATE_TEXT_RESIDUAL",
                    "severity": "high",
                    "location": "body_p_token:body_p_token.0",
                    "detail": "___________",
                }
            ],
        }

    def test_untouched_template_blank_demotes_to_warning(self) -> None:
        from qa.pipeline import _adjust_inherited_residuals

        with tempfile.TemporaryDirectory(prefix="residual_") as tmp:
            template = self._template(Path(tmp))
            adjusted, warnings = _adjust_inherited_residuals(
                self._section(), str(template), {"operations": []}
            )
        self.assertTrue(adjusted["passed"])
        self.assertEqual(adjusted["structured_issues"], [])
        self.assertEqual(len(warnings), 1)
        self.assertEqual(warnings[0]["severity"], "medium")

    def test_residual_in_a_targeted_paragraph_stays_blocking(self) -> None:
        from qa.pipeline import _adjust_inherited_residuals

        with tempfile.TemporaryDirectory(prefix="residual_") as tmp:
            template = self._template(Path(tmp))
            plan = {
                "operations": [
                    {"type": "replace_text", "target": {"location_id": "body.p[0]"}}
                ]
            }
            adjusted, warnings = _adjust_inherited_residuals(
                self._section(), str(template), plan
            )
        self.assertFalse(adjusted["passed"])
        self.assertEqual(len(adjusted["structured_issues"]), 1)
        self.assertEqual(warnings, [])


class FingerprintColourBoundaryTests(unittest.TestCase):
    def _doc_with_color(self, rgb):
        document = docx.Document()
        paragraph = document.add_paragraph()
        run = paragraph.add_run("文本")
        run.bold = True
        run.font.color.rgb = rgb
        return document

    def test_colour_only_difference_is_not_structural(self) -> None:
        red = self._doc_with_color(RGBColor(0xFF, 0x00, 0x00))
        blue = self._doc_with_color(RGBColor(0x00, 0x00, 0xFF))
        self.assertEqual(
            compute_four_hashes(red)["structural_hash"],
            compute_four_hashes(blue)["structural_hash"],
        )

    def test_run_deletion_is_structural(self) -> None:
        red = self._doc_with_color(RGBColor(0xFF, 0x00, 0x00))
        stripped = self._doc_with_color(RGBColor(0xFF, 0x00, 0x00))
        paragraph = stripped.paragraphs[0]
        paragraph._p.remove(_run_nodes(paragraph)[0])
        self.assertNotEqual(
            compute_four_hashes(red)["structural_hash"],
            compute_four_hashes(stripped)["structural_hash"],
        )

    def test_bold_change_is_still_structural(self) -> None:
        with_bold = self._doc_with_color(RGBColor(0xFF, 0x00, 0x00))
        without_bold = docx.Document()
        paragraph = without_bold.add_paragraph()
        run = paragraph.add_run("文本")
        run.font.color.rgb = RGBColor(0xFF, 0x00, 0x00)
        self.assertNotEqual(
            compute_four_hashes(with_bold)["structural_hash"],
            compute_four_hashes(without_bold)["structural_hash"],
        )


def gap_only_qa(_staged_path):
    return {
        "schema_version": "4.0",
        "task_id": "TASK_FIDELITY_001",
        "status": "UNVERIFIED",
        "missing_checks": [],
        "coverage_gaps": ["VISUAL_PIXEL:PYMUPDF_UNAVAILABLE"],
        "issues": [],
        "checks": [],
    }


class UnverifiedGateTests(_PlanCase):
    def _standard_plan(self, template_path: Path):
        spec = build_document_spec_from_path(str(template_path))
        slot = next(s for s in spec["slots"] if s["location_id"] == "body.p[0]")
        content = build_content_plan(
            spec,
            plan_id="CP_FID_002",
            sections=[{
                "section_id": "SEC_001",
                "purpose": "项目名称",
                "target_slots": [slot["slot_id"]],
            }],
            facts=[],
            required_slots=[slot["slot_id"]],
        )
        plan = build_fill_plan(
            spec, content, task_id="TASK_FIDELITY_001", mode="STANDARD",
            values_by_slot={slot["slot_id"]: VALUE},
        )
        return spec, content, plan

    def test_coverage_gap_only_unverified_commits_in_standard(self) -> None:
        template = self.directory / "gap.docx"
        document = docx.Document()
        _make_split_token_paragraph(document)
        document.save(str(template))

        spec, content, plan = self._standard_plan(template)
        output = self.directory / "gap-out.docx"
        result = execute_fill_plan(
            str(template), spec, plan, str(output),
            content_plan=content, qa_runner=gap_only_qa,
            allow_unverified=True,
        )
        self.assertEqual(result["status"], "UNVERIFIED", result["errors"])
        self.assertTrue(result["transaction"]["committed"])
        self.assertTrue(output.is_file())

    def test_coverage_gap_only_unverified_refused_without_allowance(self) -> None:
        template = self.directory / "gap2.docx"
        document = docx.Document()
        _make_split_token_paragraph(document)
        document.save(str(template))

        spec, content, plan = self._standard_plan(template)
        output = self.directory / "gap2-out.docx"
        result = execute_fill_plan(
            str(template), spec, plan, str(output),
            content_plan=content, qa_runner=gap_only_qa,
        )
        self.assertEqual(result["status"], "FAILED")
        self.assertFalse(output.exists())
        self.assertEqual(result["transaction"]["abort_reason"], "QA_NOT_ELIGIBLE")


class StoryIteratorPurityTests(unittest.TestCase):
    """python-docx lazily CREATES a header/footer part (and a ``w:headerReference``
    inside ``w:sectPr``) when ``.paragraphs``/``.tables``/``._element``/``.part``
    are read off a linked header. Story iterators and fingerprints are read-only
    analyzers: they must never materialize phantom parts."""

    def _plain_document(self):
        document = docx.Document()
        document.add_paragraph(TOKEN)
        return document

    def test_iterators_do_not_create_phantom_headers(self) -> None:
        from engine.ooxml_utils import (
            iter_all_document_paragraphs_with_Wait_context,
            iter_all_document_tables_with_context,
        )

        document = self._plain_document()
        list(iter_all_document_paragraphs_with_Wait_context(document))
        list(iter_all_document_tables_with_context(document))
        self.assertFalse(
            document.element.body.xpath(".//w:headerReference | .//w:footerReference"),
            "story iterators materialized a phantom header/footer",
        )

    def test_compute_four_hashes_is_repeatable(self) -> None:
        document = self._plain_document()
        first = compute_four_hashes(document)
        second = compute_four_hashes(document)
        self.assertEqual(first, second)
        self.assertFalse(
            document.element.body.xpath(".//w:headerReference | .//w:footerReference"),
        )

    def test_spec_fingerprint_matches_fresh_parse(self) -> None:
        """The spec's structural hash must equal the hash of the untouched file."""
        with tempfile.TemporaryDirectory(prefix="fid_purity_") as tmp:
            path = Path(tmp) / "plain.docx"
            self._plain_document().save(str(path))
            spec = build_document_spec_from_path(str(path))
            fresh = compute_four_hashes(docx.Document(str(path)))
            self.assertEqual(
                spec["fingerprint_ref"]["structural_hash"],
                fresh["structural_hash"],
            )

    def test_real_header_still_enumerated(self) -> None:
        from engine.ooxml_utils import iter_all_document_paragraphs_with_Wait_context

        document = self._plain_document()
        header = document.sections[0].header
        header.is_linked_to_previous = False
        header.paragraphs[0].text = "页眉文字"
        locations = [
            ctx["location_id"]
            for ctx in iter_all_document_paragraphs_with_Wait_context(document)
        ]
        self.assertTrue(
            any(loc.startswith("sec[0].header.") for loc in locations),
            "a defined header must keep being enumerated",
        )


if __name__ == "__main__":
    unittest.main()
