# -*- coding: utf-8 -*-
"""CP-W2-002 / W3-4B: SDT containers are discovered as protected, addressable positions.

Covers body, header/footer, table-cell and nested SDT containers, locked controls,
textbox location stability (no `w:txbxContent` descent), slot-id determinism and
FillPlan/executor rejection without mutation.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

import docx
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from content_intelligence import (  # noqa: E402
    build_content_plan,
    build_fill_plan,
    validate_fill_plan,
)
from document_engine import execute_fill_plan  # noqa: E402
from engine.ooxml_utils import iter_all_document_paragraphs_with_Wait_context  # noqa: E402
from template_intelligence import (  # noqa: E402
    build_document_spec_from_path,
    make_slot_id,
)
from template_intelligence.spec_validator import validate_document_spec  # noqa: E402
from template_intelligence.fingerprint import compute_four_hashes  # noqa: E402


def _wrap_in_sdt(container_el, el, lock_value=None):
    """Move `el` into a new direct `w:sdt/w:sdtContent` of `container_el`."""
    sdt = OxmlElement("w:sdt")
    if lock_value is not None:
        sdt_pr = OxmlElement("w:sdtPr")
        lock = OxmlElement("w:lock")
        lock.set(qn("w:val"), lock_value)
        sdt_pr.append(lock)
        sdt.append(sdt_pr)
    content = OxmlElement("w:sdtContent")
    el.addprevious(sdt)
    container_el.remove(el)
    content.append(el)
    sdt.append(content)
    return sdt


def _sdt_content(sdt):
    return sdt.find(qn("w:sdtContent"))


def _append_body_sdt(doc, paragraphs, lock_value=None):
    """Wrap one or more body paragraphs so the first is `sdt[0]`."""
    body = doc.element.body
    first, rest = paragraphs[0], paragraphs[1:]
    sdt = _wrap_in_sdt(body, first._p, lock_value=lock_value)
    content = _sdt_content(sdt)
    for paragraph in rest:
        content.append(paragraph._p)
    return sdt


def _table_in_sdt(doc, rows=1, cols=2):
    table = doc.add_table(rows=rows, cols=cols)
    sdt = _wrap_in_sdt(doc.element.body, table._tbl)
    return table, sdt


class SdtDiscoveryCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.counter = 0

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp.name, ignore_errors=True)

    def _save(self, doc) -> str:
        self.counter += 1
        path = os.path.join(self._tmp.name, "sdt_%d.docx" % self.counter)
        doc.save(path)
        return path

    def _spec(self, doc):
        path = self._save(doc)
        spec = build_document_spec_from_path(path)
        report = validate_document_spec(spec)
        self.assertTrue(report["passed"], report["errors"][:5])
        return spec

    def _slot(self, spec, location):
        return next(slot for slot in spec["slots"] if slot["location_id"] == location)

    def _regions(self, spec, location):
        return [
            region for region in spec["protected_regions"]
            if region["kind"] == "sdt" and region["location_id"] == location
        ]


class ContainerDiscoveryTests(SdtDiscoveryCase):
    def test_body_sdt_paragraph_discovered_and_protected(self) -> None:
        doc = docx.Document()
        doc.add_paragraph("{{正文}}")
        control = doc.add_paragraph("{{受控字段}}")
        _append_body_sdt(doc, [control])
        spec = self._spec(doc)

        slot = self._slot(spec, "body.sdt[0].p[0]")
        self.assertEqual(slot["candidate_type"], "control_or_field")
        self.assertEqual(slot["protection_status"], "PROTECTED")
        self.assertEqual(slot["confirmation_tier"], "PROTECTED_DO_NOT_TOUCH")
        self.assertIn("body.sdt[0].p[0]", [p["location_id"] for p in spec["structure"]["paragraphs"]])
        regions = self._regions(spec, "body.sdt[0]")
        self.assertEqual(len(regions), 1)
        self.assertEqual(regions[0]["severity"], "blocking")
        self.assertIn("1 paragraph", regions[0]["evidence"])
        self.assertEqual(spec["template"]["capabilities"]["sdt_edit"], False)
        self.assertEqual(spec["template"]["compatibility"], "L3")
        self.assertIn(
            "body.sdt[0]",
            [item.get("location_id") for item in spec["unsupported_features"]
             if item["code"] == "SDT_BODY_UNSUPPORTED"],
        )

    def test_multiple_paragraphs_in_one_container_are_indexed_directly(self) -> None:
        doc = docx.Document()
        first = doc.add_paragraph("{{第一段}}")
        second = doc.add_paragraph("{{第二段}}")
        _append_body_sdt(doc, [first, second])
        spec = self._spec(doc)
        self.assertEqual(self._slot(spec, "body.sdt[0].p[0]")["candidate_type"], "control_or_field")
        self.assertEqual(self._slot(spec, "body.sdt[0].p[1]")["candidate_type"], "control_or_field")
        self.assertFalse(
            [slot for slot in spec["slots"] if ".sdt[" in slot["location_id"]
             and slot["protection_status"] == "FILLABLE"]
        )

    def test_header_story_sdt_discovered(self) -> None:
        doc = docx.Document()
        doc.add_paragraph("{{正文}}")
        header = doc.sections[0].header
        header.is_linked_to_previous = False
        paragraph = header.paragraphs[0]
        paragraph.text = "{{页眉受控}}"
        _wrap_in_sdt(header._element, paragraph._p)
        spec = self._spec(doc)

        slot = self._slot(spec, "sec[0].header.sdt[0].p[0]")
        self.assertEqual(slot["scope"], "header_footer")
        self.assertEqual(slot["protection_status"], "PROTECTED")
        self.assertEqual(len(self._regions(spec, "sec[0].header.sdt[0]")), 1)
        self.assertIn(
            "sec[0].header.sdt[0]",
            [item.get("location_id") for item in spec["unsupported_features"]
             if item["code"] == "SDT_BODY_UNSUPPORTED"],
        )

    def test_even_page_footer_sdt_discovered(self) -> None:
        doc = docx.Document()
        doc.add_paragraph("{{正文}}")
        footer = doc.sections[0].even_page_footer
        footer.is_linked_to_previous = False
        paragraph = footer.paragraphs[0]
        paragraph.text = "{{页脚受控}}"
        _wrap_in_sdt(footer._element, paragraph._p)
        spec = self._spec(doc)
        self.assertEqual(
            self._slot(spec, "sec[0].even_page_footer.sdt[0].p[0]")["protection_status"],
            "PROTECTED",
        )
        self.assertEqual(len(self._regions(spec, "sec[0].even_page_footer.sdt[0]")), 1)

    def test_cell_level_sdt_discovered(self) -> None:
        doc = docx.Document()
        doc.add_paragraph("{{正文}}")
        table = doc.add_table(rows=1, cols=1)
        cell = table.cell(0, 0)
        paragraph = cell.paragraphs[0]
        paragraph.text = "{{单元格受控}}"
        _wrap_in_sdt(cell._tc, paragraph._p)
        spec = self._spec(doc)

        slot = self._slot(spec, "body.tbl[0].r[0].c[0].sdt[0].p[0]")
        self.assertEqual(slot["scope"], "table")
        self.assertEqual(slot["protection_status"], "PROTECTED")
        self.assertEqual(len(self._regions(spec, "body.tbl[0].r[0].c[0].sdt[0]")), 1)

    def test_nested_sdt_uses_container_relative_index(self) -> None:
        doc = docx.Document()
        p0 = doc.add_paragraph("{{内层一}}")
        p1 = doc.add_paragraph("{{内层二}}")
        body = doc.element.body
        outer = OxmlElement("w:sdt")
        outer_content = OxmlElement("w:sdtContent")
        outer.append(outer_content)
        for paragraph in (p0, p1):
            inner = OxmlElement("w:sdt")
            inner_content = OxmlElement("w:sdtContent")
            body.remove(paragraph._p)
            inner_content.append(paragraph._p)
            inner.append(inner_content)
            outer_content.append(inner)
        sect_pr = body.find(qn("w:sectPr"))
        if sect_pr is not None:
            sect_pr.addprevious(outer)
        else:
            body.append(outer)
        spec = self._spec(doc)

        first = self._slot(spec, "body.sdt[0].sdt[0].p[0]")
        second = self._slot(spec, "body.sdt[0].sdt[1].p[0]")
        self.assertEqual(first["protection_status"], "PROTECTED")
        self.assertEqual(second["protection_status"], "PROTECTED")
        self.assertEqual(len(self._regions(spec, "body.sdt[0].sdt[0]")), 1)
        self.assertEqual(len(self._regions(spec, "body.sdt[0].sdt[1]")), 1)

    def test_table_inside_body_sdt_exposed_with_sdt_path(self) -> None:
        doc = docx.Document()
        doc.add_paragraph("{{正文}}")
        table, sdt = _table_in_sdt(doc)
        table.cell(0, 0).text = "{{受控表格}}"
        spec = self._spec(doc)

        self.assertIn("body.sdt[0].tbl[0]", [item["table_id"] for item in spec["structure"]["tables"]])
        slot = self._slot(spec, "body.sdt[0].tbl[0].r[0].c[0].p[0]")
        self.assertEqual(slot["protection_status"], "PROTECTED")
        self.assertEqual(len(self._regions(spec, "body.sdt[0]")), 1)
        self.assertEqual(_sdt_content(sdt).findall(qn("w:tbl"))[0], table._tbl)

    def test_locked_and_plain_sdt_both_discovered(self) -> None:
        doc = docx.Document()
        plain = doc.add_paragraph("{{普通控件}}")
        locked = doc.add_paragraph("{{锁定控件}}")
        _append_body_sdt(doc, [plain])
        _append_body_sdt(doc, [locked], lock_value="sdtContentLocked")
        # The first wrapping inserted sdt[0] before the paragraph; the second inserted
        # sdt[0] before its paragraph, so re-read the real order from the document.
        spec = self._spec(doc)
        sdt_locations = [
            slot["location_id"] for slot in spec["slots"] if ".sdt[" in slot["location_id"]
        ]
        self.assertEqual(len(sdt_locations), 2, sdt_locations)
        self.assertTrue(all(
            self._slot(spec, location)["protection_status"] == "PROTECTED"
            for location in sdt_locations
        ))

    def test_inline_sdt_in_paragraph_is_not_a_container(self) -> None:
        doc = docx.Document()
        paragraph = doc.add_paragraph()
        sdt = OxmlElement("w:sdt")
        content = OxmlElement("w:sdtContent")
        run = paragraph.add_run("{{内联}}")
        run._r.addprevious(sdt)
        paragraph._p.remove(run._r)
        content.append(run._r)
        sdt.append(content)
        spec = self._spec(doc)

        locations = [slot["location_id"] for slot in spec["slots"]]
        self.assertIn("body.p[0]", locations)
        self.assertFalse([location for location in locations if ".sdt[" in location])
        self.assertFalse([item for item in spec["unsupported_features"]
                          if item["code"] == "SDT_BODY_UNSUPPORTED"])
        self.assertTrue(self._regions(spec, "body.p[0]"), "inline control stays a paragraph-level region")

    def test_non_sdt_locations_are_unchanged_by_sdt_discovery(self) -> None:
        doc = docx.Document()
        doc.add_paragraph("{{普通字段}}")
        table = doc.add_table(rows=1, cols=1)
        table.cell(0, 0).text = "{{表格字段}}"
        outer = doc.add_paragraph()
        txbx = OxmlElement("w:txbxContent")
        inner_p = OxmlElement("w:p")
        inner_p.append(OxmlElement("w:r"))
        txbx.append(inner_p)
        outer._p.append(txbx)
        header = doc.sections[0].header
        header.is_linked_to_previous = False
        header.paragraphs[0].text = "页眉"

        legacy_path = self._save(doc)
        legacy_locations = [
            ctx["location_id"]
            for ctx in iter_all_document_paragraphs_with_Wait_context(docx.Document(legacy_path))
        ]

        doc.add_paragraph("{{受控字段}}")
        _append_body_sdt(doc, [doc.paragraphs[-1]])
        sdt_path = self._save(doc)
        sdt_locations = [
            ctx["location_id"]
            for ctx in iter_all_document_paragraphs_with_Wait_context(docx.Document(sdt_path))
        ]

        self.assertFalse([loc for loc in legacy_locations if ".sdt[" in loc])
        non_sdt = [loc for loc in sdt_locations if ".sdt[" not in loc]
        self.assertEqual(non_sdt, legacy_locations)
        self.assertIn("body.sdt[0].p[0]", sdt_locations)
        self.assertIn("body.txbx_p[0]", non_sdt)


class TextboxAndStabilityTests(SdtDiscoveryCase):
    def _textbox_document(self):
        doc = docx.Document()
        outer = doc.add_paragraph()
        txbx = OxmlElement("w:txbxContent")
        inner_p = OxmlElement("w:p")
        run = OxmlElement("w:r")
        text = OxmlElement("w:t")
        text.text = "{{文本框内容}}"
        run.append(text)
        inner_p.append(run)
        txbx.append(inner_p)
        outer._p.append(txbx)
        _append_body_sdt(doc, [outer])
        return doc

    def test_textbox_paragraph_keeps_txbx_location_inside_sdt(self) -> None:
        spec = self._spec(self._textbox_document())
        self.assertEqual(
            self._slot(spec, "body.txbx_p[0]")["location_id"], "body.txbx_p[0]"
        )
        self.assertFalse(
            [slot for slot in spec["slots"] if ".sdt[" in slot["location_id"]
             and "txbx" in slot["location_id"]]
        )
        self.assertIn("body.txbx_p[0]", [p["location_id"] for p in spec["structure"]["paragraphs"]])
        # The enclosing SDT still protects the textbox content.
        self.assertEqual(self._slot(spec, "body.txbx_p[0]")["protection_status"], "PROTECTED")

    def test_textbox_slot_id_uses_unchanged_location(self) -> None:
        doc = self._textbox_document()
        spec = self._spec(doc)
        slot = self._slot(spec, "body.txbx_p[0]")
        expected = make_slot_id(
            spec["template"]["template_sha256"], "body.txbx_p[0]", "{{文本框内容}}", 1
        )
        self.assertEqual(slot["slot_id"], expected)

    def test_two_runs_are_identical(self) -> None:
        doc = self._textbox_document()
        path = self._save(doc)
        first = build_document_spec_from_path(path)
        second = build_document_spec_from_path(path)
        first_slots = [(slot["slot_id"], slot["location_id"]) for slot in first["slots"]]
        second_slots = [(slot["slot_id"], slot["location_id"]) for slot in second["slots"]]
        self.assertEqual(first_slots, second_slots)
        first_regions = [(region["region_id"], region["kind"], region["location_id"])
                         for region in first["protected_regions"]]
        second_regions = [(region["region_id"], region["kind"], region["location_id"])
                          for region in second["protected_regions"]]
        self.assertEqual(first_regions, second_regions)

    def test_structural_hash_stable_across_authorized_text_fill(self) -> None:
        doc = docx.Document()
        doc.add_paragraph("{{可填正文}}")
        control = doc.add_paragraph("{{受控字段}}")
        _append_body_sdt(doc, [control])
        # python-docx lazily instantiates header/footer proxies on first section access;
        # production analysis already touches them, so warm up before measuring.
        compute_four_hashes(doc)
        before = compute_four_hashes(doc)
        doc.paragraphs[0].runs[0].text = "已填正文"
        after = compute_four_hashes(doc)
        self.assertEqual(before["structural_hash"], after["structural_hash"])
        self.assertEqual(before["style_hash"], after["style_hash"])


class SdtFillRejectionTests(SdtDiscoveryCase):
    def test_fill_plan_targeting_sdt_slot_is_rejected_without_mutation(self) -> None:
        doc = docx.Document()
        doc.add_paragraph("{{普通字段}}")
        control = doc.add_paragraph("{{受控字段}}")
        _append_body_sdt(doc, [control])
        path = self._save(doc)
        spec = build_document_spec_from_path(path)
        slot = self._slot(spec, "body.sdt[0].p[0]")
        self.assertEqual(slot["protection_status"], "PROTECTED")

        content = build_content_plan(
            spec,
            plan_id="CP_SDT_001",
            sections=[{
                "section_id": "SEC_001",
                "purpose": "受控字段",
                "target_slots": [slot["slot_id"]],
            }],
            facts=[],
            required_slots=[slot["slot_id"]],
        )
        plan = build_fill_plan(
            spec,
            content,
            task_id="TASK_SDT_001",
            values_by_slot={slot["slot_id"]: "新值"},
        )

        validation = validate_fill_plan(plan, spec, content_plan=content)
        codes = [item["code"] for item in validation["errors"]]
        self.assertIn("PROTECTED_SLOT_VIOLATION", codes)

        before = hashlib.sha256(Path(path).read_bytes()).hexdigest()
        output = os.path.join(self._tmp.name, "sdt-out.docx")
        result = execute_fill_plan(path, spec, plan, output, content_plan=content)
        after = hashlib.sha256(Path(path).read_bytes()).hexdigest()

        self.assertEqual(result["status"], "BLOCKED")
        self.assertIn("PROTECTED_SLOT_VIOLATION", [item["code"] for item in result["errors"]])
        self.assertFalse(os.path.exists(output))
        self.assertEqual(result["artifacts"], [])
        self.assertEqual(before, after, "the template must stay byte-identical")


if __name__ == "__main__":
    unittest.main()
