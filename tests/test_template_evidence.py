# -*- coding: utf-8 -*-
"""W4-1 tests: evidence registry, four-state classification, conflict detection."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

import docx
from docx.oxml import OxmlElement
from docx.shared import RGBColor

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from template_gate import EvidenceRecord, EvidenceRegistry, EvidenceStatus, build_analysis, stable_evidence_id  # noqa: E402


def _write(doc, directory: str, name: str = "template.docx") -> str:
    path = os.path.join(directory, name)
    doc.save(path)
    return path


def _standard_template(directory: str) -> str:
    document = docx.Document()
    document.add_paragraph("{{项目名称}}")
    table = document.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "项目"
    table.cell(0, 1).text = "金额"
    table.cell(1, 0).text = "{{项目名称}}"
    table.cell(1, 1).text = ""
    return _write(document, directory, "standard.docx")


def _appended_sdt(document, text: str) -> None:
    sdt = OxmlElement("w:sdt")
    sdt_pr = OxmlElement("w:sdtPr")
    sdt.append(sdt_pr)
    content = OxmlElement("w:sdtContent")
    paragraph = OxmlElement("w:p")
    run = OxmlElement("w:r")
    node = OxmlElement("w:t")
    node.text = text
    run.append(node)
    paragraph.append(run)
    content.append(paragraph)
    sdt.append(content)
    document.element.body.append(sdt)


class EvidenceRegistryTests(unittest.TestCase):
    def test_conflict_between_two_verified_values(self) -> None:
        registry = EvidenceRegistry()
        registry.add(
            EvidenceRecord(
                evidence_id=stable_evidence_id("body.p[0]", "font_family", "xml", 1),
                object_id="body.p[0]",
                location="body.p[0]",
                property="font_family",
                value="宋体",
                source="xml",
                evidence_type="xml_node",
                verification_status=EvidenceStatus.VERIFIED.value,
                task_relevant=True,
            )
        )
        registry.add(
            EvidenceRecord(
                evidence_id=stable_evidence_id("body.p[0]", "font_family", "style", 1),
                object_id="body.p[0]",
                location="body.p[0]",
                property="font_family",
                value="黑体",
                source="style",
                evidence_type="style_definition",
                verification_status=EvidenceStatus.VERIFIED.value,
                task_relevant=True,
            )
        )
        conflicts = registry.detect_conflicts()
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0]["property"], "font_family")
        self.assertEqual(len(conflicts[0]["values"]), 2)

    def test_digest_is_stable_and_changes_with_content(self) -> None:
        registry = EvidenceRegistry()
        record = EvidenceRecord(
            evidence_id=stable_evidence_id("body.p[0]", "font_size", "xml", 1),
            object_id="body.p[0]",
            location="body.p[0]",
            property="font_size",
            value="24",
            source="xml",
            evidence_type="xml_node",
            verification_status=EvidenceStatus.VERIFIED.value,
        )
        registry.add(record)
        first = registry.digest()
        registry.add(
            EvidenceRecord(
                evidence_id=stable_evidence_id("body.p[1]", "font_size", "xml", 1),
                object_id="body.p[1]",
                location="body.p[1]",
                property="font_size",
                value="24",
                source="xml",
                evidence_type="xml_node",
                verification_status=EvidenceStatus.VERIFIED.value,
            )
        )
        self.assertNotEqual(first, registry.digest())
        self.assertEqual(len(registry.summary()) > 0, True)


class TemplateAnalyzerTests(unittest.TestCase):
    def test_standard_template_has_no_blocking_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = _standard_template(directory)
            analysis = build_analysis(path, "GENERATE")
            self.assertEqual(analysis["task_type"], "GENERATE")
            self.assertGreater(analysis["summary"]["verified"], 0)
            blocking = [item for item in analysis["evidence"] if item["blocking"]]
            self.assertEqual(blocking, [], blocking)
            properties = {item["property"] for item in analysis["evidence"]}
            self.assertIn("page.setup", properties)
            self.assertIn("slot.fillability", properties)
            self.assertIn("table.structure", properties)
            self.assertIn("table.purpose", properties)

    def test_slot_paragraph_with_two_fonts_conflicts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            document = docx.Document()
            paragraph = document.add_paragraph()
            first = paragraph.add_run("{{标")
            first.font.name = "Arial"
            second = paragraph.add_run("题}}")
            second.font.name = "Times New Roman"
            path = _write(document, directory, "font-conflict.docx")

            analysis = build_analysis(path, "GENERATE")
            conflicts = [
                item
                for item in analysis["evidence"]
                if item["property"] == "font_family" and item["verification_status"] == "CONFLICT"
            ]
            self.assertTrue(conflicts)
            self.assertTrue(all(item["blocking"] for item in conflicts))
            self.assertGreaterEqual(analysis["summary"]["blocking"], 1)

    def test_table_purpose_is_ambiguous_when_mixed_and_unlabelled(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            document = docx.Document()
            table = document.add_table(rows=2, cols=2)
            table.cell(1, 0).text = "一段说明文字"
            path = _write(document, directory, "ambiguous-table.docx")

            analysis = build_analysis(path, "GENERATE")
            purposes = [
                item
                for item in analysis["evidence"]
                if item["property"] == "table.purpose"
            ]
            self.assertEqual(len(purposes), 1)
            self.assertEqual(purposes[0]["verification_status"], "AMBIGUOUS")
            self.assertTrue(purposes[0]["blocking"])

    def test_red_text_is_ambiguous_not_verified(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            document = docx.Document()
            paragraph = document.add_paragraph()
            run = paragraph.add_run("请填写此说明")
            run.font.color.rgb = RGBColor(0xFF, 0x00, 0x00)
            path = _write(document, directory, "red-text.docx")

            analysis = build_analysis(path, "GENERATE")
            red = [
                item
                for item in analysis["evidence"]
                if item["property"] == "red_text.semantic"
            ]
            self.assertTrue(red)
            self.assertTrue(all(item["verification_status"] == "AMBIGUOUS" for item in red))
            self.assertTrue(any(item["blocking"] for item in red))

    def test_sdt_is_protected_and_not_blocking(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            document = docx.Document()
            document.add_paragraph("正文")
            _appended_sdt(document, "受控内容")
            path = _write(document, directory, "sdt.docx")

            analysis = build_analysis(path, "GENERATE")
            protected = [
                item
                for item in analysis["evidence"]
                if item["property"] == "sdt.editability"
            ]
            self.assertTrue(protected)
            self.assertTrue(all(item["verification_status"] == "VERIFIED" for item in protected))
            self.assertFalse(any(item["blocking"] for item in protected))

    def test_evidence_digest_is_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = _standard_template(directory)
            first = build_analysis(path, "GENERATE")
            second = build_analysis(path, "GENERATE")
            self.assertEqual(first["evidence_digest"], second["evidence_digest"])
            self.assertEqual(first["analysis_id"], second["analysis_id"])


if __name__ == "__main__":
    unittest.main()
