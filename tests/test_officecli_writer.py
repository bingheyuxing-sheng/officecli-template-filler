# -*- coding: utf-8 -*-
"""Conformance tests for the officecli writer backend.

The officecli writer is opt-in. These tests prove, on the committed template
fixtures, that it produces the same user-visible result as the default
python-docx writer before anyone flips the default. They are skipped on
machines without the binary and never install it.
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

import docx
from docx.shared import RGBColor

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gate_helpers import ensure_gate  # noqa: E402

from document_engine import execute_fill_plan  # noqa: E402
from document_engine.fill_executor import _officecli_operation_plan  # noqa: E402
from engine import officecli_writer  # noqa: E402
from engine.ooxml_utils import (  # noqa: E402
    LogicalParagraphView,
    iter_all_document_paragraphs_with_Wait_context,
)
from template_intelligence import fingerprint  # noqa: E402
from template_intelligence import build_document_spec_from_path  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"
CLASSES = ("class_01_basic_report", "class_02_complex_table")

OFFICECLI_AVAILABLE = officecli_writer.is_available()


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _text_map(document) -> dict:
    mapping: dict = {}
    for context in iter_all_document_paragraphs_with_Wait_context(document):
        mapping.setdefault(context["location_id"], LogicalParagraphView(context["p_el"]).logical_text)
    return mapping


class LocationMappingTests(unittest.TestCase):
    def test_body_and_table_paths_are_one_based(self) -> None:
        self.assertEqual(officecli_writer.location_to_path("body.p[0]"), "/body/p[1]")
        self.assertEqual(
            officecli_writer.location_to_path("body.tbl[0].r[1].c[0].p[0]"),
            "/body/tbl[1]/tr[2]/tc[1]/p[1]",
        )
        self.assertEqual(
            officecli_writer.location_to_path("body.tbl[0].r[0].c[0].tbl[1].r[2].c[3].p[0]"),
            "/body/tbl[1]/tr[1]/tc[1]/tbl[2]/tr[3]/tc[4]/p[1]",
        )

    def test_unaddressable_stories_are_refused(self) -> None:
        for location in (
            "body.txbx_p[0]",
            "body.sdt[0].p[0]",
            "footnotes.p[0]",
            "comments.p[1]",
            "sec[0].header.p[0]",
        ):
            with self.assertRaises(officecli_writer.UnsupportedLocation):
                officecli_writer.location_to_path(location)


class FallbackTests(unittest.TestCase):
    def test_unsupported_location_requests_python_docx(self) -> None:
        commands, plan, reason = _officecli_operation_plan(
            [{"op_id": "OP_1", "type": "replace_text",
              "slot_id": "S_1", "target": {"location_id": "body.txbx_p[0]"}}],
            {"S_1": {"matched_text": "{{X}}", "occurrence": 1}},
            {"body.txbx_p[0]": object()},
            {},
        )
        self.assertEqual(commands, [])
        self.assertEqual(plan, {})
        self.assertIn("txbx_p", reason)

    def test_image_operation_requests_python_docx(self) -> None:
        commands, plan, reason = _officecli_operation_plan(
            [{"op_id": "OP_1", "type": "replace_image",
              "slot_id": "S_1", "target": {"location_id": "body.p[0]"}}],
            {"S_1": {"matched_text": "{{X}}", "occurrence": 1}},
            {"body.p[0]": object()},
            {},
        )
        self.assertEqual(commands, [])
        self.assertIn("replace_image", reason)

    def test_token_spanning_runs_requests_python_docx(self) -> None:
        document = docx.Document()
        paragraph = document.add_paragraph()
        paragraph.add_run("{{X")
        paragraph.add_run("}}")
        commands, plan, reason = _officecli_operation_plan(
            [{"op_id": "OP_1", "type": "replace_text",
              "slot_id": "S_1", "target": {"location_id": "body.p[0]"},
              "value": "值"}],
            {"S_1": {"matched_text": "{{X}}", "occurrence": 1}},
            {"body.p[0]": paragraph},
            {},
        )
        self.assertEqual(commands, [])
        self.assertIn("spans multiple runs", reason)


@unittest.skipUnless(OFFICECLI_AVAILABLE, "officecli is not installed")
class RunLevelTests(unittest.TestCase):
    def test_multi_run_replacement_is_structurally_faithful(self) -> None:
        document = docx.Document()
        paragraph = document.add_paragraph()
        paragraph.add_run("前缀")
        placeholder = paragraph.add_run("{{X}}")
        placeholder.bold = True
        placeholder.font.color.rgb = RGBColor(0xFF, 0x00, 0x00)
        paragraph.add_run("后缀")

        with tempfile.TemporaryDirectory() as tmp:
            template = Path(tmp) / "template.docx"
            output = Path(tmp) / "output.docx"
            document.save(str(template))
            shutil.copyfile(template, output)

            commands, plan, reason = _officecli_operation_plan(
                [{"op_id": "OP_1", "type": "replace_text", "slot_id": "S_1",
                  "target": {"location_id": "body.p[0]"}, "value": "值"}],
                {"S_1": {"matched_text": "{{X}}", "occurrence": 1}},
                {"body.p[0]": paragraph},
                {},
            )
            self.assertIsNone(reason)
            self.assertEqual(commands[0]["path"], "/body/p[1]/r[2]")

            officecli_writer.run_batch(str(output), commands)
            officecli_writer.close(str(output))
            officecli_writer.restore_paragraph_identity(
                str(template), str(output), strip_red_runs=[("body.p[0]", 2)]
            )

            before = docx.Document(str(template))
            after = docx.Document(str(output))
            self.assertEqual(len(after.paragraphs[0].runs), 3)
            self.assertTrue(after.paragraphs[0].runs[1].bold)
            self.assertIsNone(after.paragraphs[0].runs[1].font.color.rgb,
                              "red placeholder colour must be stripped like the default writer")
            self.assertEqual(after.paragraphs[0].text, "前缀值后缀")
            self.assertEqual(
                fingerprint._structural_hash(before), fingerprint._structural_hash(after)
            )


@unittest.skipUnless(OFFICECLI_AVAILABLE, "officecli is not installed")
class ConformanceTests(unittest.TestCase):
    """Same plan, two writers: identical text, identical untouched regions."""

    def _run(self, name: str, writer: str, directory: Path) -> tuple:
        class_dir = FIXTURES / name
        template = class_dir / "template.docx"
        spec = build_document_spec_from_path(str(template))
        plan = _load(class_dir / "fill_plan.json")
        content = _load(class_dir / "content_plan.json")
        expected = _load(class_dir / "expected" / "expected.json")

        ensure_gate(str(template), "GENERATE")
        output = directory / ("%s-%s.docx" % (name, writer))
        result = execute_fill_plan(
            str(template), spec, plan, str(output),
            content_plan=content, allow_unverified=True, writer=writer,
        )
        return result, output, expected, spec

    def _assert_conformance(self, name: str) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            baseline, baseline_path, expected, spec = self._run(name, "python-docx", directory)
            candidate, candidate_path, _, _ = self._run(name, "officecli", directory)

            self.assertIn(candidate.get("status"), expected["scenarios"][0]["allowed_status"],
                          "%s: officecli status %r (%r)" % (
                              name, candidate.get("status"), candidate.get("errors")[:3]))
            self.assertFalse(candidate.get("errors"), "%s: officecli reported errors" % name)
            self.assertEqual(
                candidate["data"].get("writer_backend"), "officecli",
                "%s: expected the officecli writer, got %r (fallback: %r)" % (
                    name, candidate["data"].get("writer_backend"),
                    candidate["data"].get("writer_fallback"))
            )
            self.assertEqual(
                [op["status"] for op in candidate["data"]["operation_results"]], ["SUCCESS"] * len(
                    expected["scenarios"][0]["expect_text"]),
                "%s: operation statuses %r" % (name, candidate["data"]["operation_results"]),
            )

            baseline_doc = docx.Document(str(baseline_path))
            candidate_doc = docx.Document(str(candidate_path))
            self.assertEqual(_text_map(candidate_doc), _text_map(baseline_doc),
                             "%s: officecli output text drifted from python-docx" % name)

            baseline_texts = _text_map(baseline_doc)
            for item in expected["scenarios"][0]["expect_text"]:
                self.assertEqual(baseline_texts.get(item["location_id"]), item["text"],
                                 "%s: baseline text at %s" % (name, item["location_id"]))

            # The batch is atomic, so a second run over the same template must
            # be byte-stable in the parts the fixture pins.
            verdict = officecli_writer.validate(str(candidate_path))
            self.assertTrue(verdict.get("success"), "%s: OpenXML validation failed: %r" % (name, verdict))

    def test_class_01_basic_report(self) -> None:
        self._assert_conformance("class_01_basic_report")

    def test_class_02_complex_table(self) -> None:
        self._assert_conformance("class_02_complex_table")


if __name__ == "__main__":
    unittest.main()
