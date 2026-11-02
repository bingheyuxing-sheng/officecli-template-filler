# -*- coding: utf-8 -*-
"""
v3.5 M2 — Revision lifecycle tests.

T1: every `w:*PrChange` mark must carry the OOXML-mandated container element
(`<w:rPrChange><w:rPr>...</w:rPr></w:rPrChange>`), and a revision id may not be
reused across document parts because accept/reject matches by id alone.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
import zipfile

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

import docx
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt
from lxml import etree

from engine import (
    accept_revision,
    audit_review_integrity,
    build_review_plan,
    execute_review_plan,
    list_format_revisions,
    list_revisions,
    reject_revision,
    restore_revision,
    review_snapshot_path,
)
from engine.review_engine import _find_by_path, _node_path

FORMAT_CHANGE_WRAPPERS = {
    "rPrChange": "rPr",
    "pPrChange": "pPr",
    "tblPrChange": "tblPr",
    "trPrChange": "trPr",
    "tcPrChange": "tcPr",
    "sectPrChange": "sectPr",
}


def _local_name(tag) -> str:
    return tag.rsplit("}", 1)[-1]


class TestRevisionLifecycleSuite(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(prefix="office_rev_test_")
        self.work_dir = self.temp_dir.name

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _iter_format_marks(self, docx_path: str):
        with zipfile.ZipFile(docx_path) as archive:
            for name in archive.namelist():
                if not name.startswith("word/") or not name.endswith(".xml"):
                    continue
                try:
                    root = etree.fromstring(archive.read(name))
                except etree.XMLSyntaxError:
                    continue
                for node in root.iter():
                    tag = _local_name(node.tag)
                    if tag in FORMAT_CHANGE_WRAPPERS:
                        yield name, tag, node

    def _build_review_output(self, text_revisions=None) -> str:
        ref_path = os.path.join(self.work_dir, "t1_ref.docx")
        tgt_path = os.path.join(self.work_dir, "t1_target.docx")
        out_path = os.path.join(self.work_dir, "t1_review.docx")

        ref = docx.Document()
        ref_run = ref.add_paragraph().add_run("模板正文段落")
        ref_run.font.name = "宋体"
        ref_run._r.get_or_add_rPr().get_or_add_rFonts().set(qn("w:eastAsia"), "宋体")
        ref_run.font.size = Pt(12)
        ref_cell = ref.add_table(rows=1, cols=1).cell(0, 0)
        ref_cell.paragraphs[0].add_run("表格")
        shading = OxmlElement("w:shd")
        shading.set(qn("w:val"), "clear")
        shading.set(qn("w:fill"), "D9E2F3")
        ref_cell._tc.get_or_add_tcPr().append(shading)
        ref.save(ref_path)

        tgt = docx.Document()
        tgt_run = tgt.add_paragraph().add_run("生成正文段落")
        tgt_run.font.name = "楷体"
        tgt_run._r.get_or_add_rPr().get_or_add_rFonts().set(qn("w:eastAsia"), "楷体")
        tgt_run.font.size = Pt(16)
        tgt.add_table(rows=1, cols=1).cell(0, 0).paragraphs[0].add_run("表格")
        tgt.save(tgt_path)

        plan = build_review_plan(ref_path, tgt_path, text_revisions=text_revisions)
        execute_review_plan(plan, out_path)
        return out_path

    def test_v35_format_revision_mark_is_schema_valid(self) -> None:
        """Every *PrChange must wrap its old properties in exactly one container element."""
        out_path = self._build_review_output()

        marks = list(self._iter_format_marks(out_path))
        self.assertTrue(marks, "REVIEW produced no format revisions")

        for part_name, tag, node in marks:
            wrapper_name = FORMAT_CHANGE_WRAPPERS[tag]
            containers = [child for child in node if _local_name(child.tag) == wrapper_name]
            self.assertEqual(
                len(containers),
                1,
                f"{tag}[{node.get(qn('w:id'))}] in {part_name} has {len(containers)} "
                f"<w:{wrapper_name}> containers",
            )

        revisions = list_format_revisions(out_path)
        self.assertTrue(revisions)
        self.assertTrue(all(item["legacy_flat_mark"] is False for item in revisions))
        self.assertTrue(all(item["wrapper_tag"] == FORMAT_CHANGE_WRAPPERS[item["type"]] for item in revisions))
        # Old properties are readable from the container, which T3 reject depends on.
        self.assertTrue(any(item["old_properties"] for item in revisions))

        audit = audit_review_integrity(out_path)
        self.assertTrue(audit["passed"], audit["issues"])

    def test_v35_list_revisions_includes_format_marks(self) -> None:
        """`include_format=True` must return text and format marks, each with an explicit kind."""
        out_path = self._build_review_output(
            text_revisions=[{"old_text": "生成正文段落", "new_text": "模板正文段落"}],
        )

        text_only = list_revisions(out_path)
        self.assertTrue(text_only)
        self.assertTrue(all(item["kind"] == "text" for item in text_only))
        self.assertFalse(any(item["type"] in FORMAT_CHANGE_WRAPPERS for item in text_only))

        combined = list_revisions(out_path, include_format=True)
        self.assertEqual({item["kind"] for item in combined}, {"text", "format"})
        self.assertEqual(len(combined), len(text_only) + len(list_format_revisions(out_path)))
        format_items = [item for item in combined if item["kind"] == "format"]
        self.assertTrue(all(item["wrapper_tag"] for item in format_items))
        self.assertTrue(all("old_properties" in item for item in format_items))

    def test_v35_revision_node_path_roundtrip(self) -> None:
        """The snapshot locator must resolve back to the exact revision mark."""
        out_path = self._build_review_output()
        with zipfile.ZipFile(out_path) as archive:
            root = etree.fromstring(archive.read("word/document.xml"))

        marks = [
            node for node in root.iter()
            if _local_name(node.tag) in FORMAT_CHANGE_WRAPPERS or _local_name(node.tag) in ("ins", "del")
        ]
        self.assertTrue(marks)
        for mark in marks:
            path = _node_path(root, mark)
            self.assertIsNotNone(path, _local_name(mark.tag))
            self.assertIs(_find_by_path(root, path), mark)
        self.assertIsNone(_find_by_path(root, [0, 0, 999]))

    def _build_single_paragraph_review(self) -> str:
        """Review output whose only run-level change is 楷体/16 -> 宋体/12."""
        ref_path = os.path.join(self.work_dir, "t3_ref.docx")
        tgt_path = os.path.join(self.work_dir, "t3_target.docx")
        out_path = os.path.join(self.work_dir, "t3_review.docx")

        ref = docx.Document()
        ref_run = ref.add_paragraph().add_run("模板正文")
        ref_run.font.name = "宋体"
        ref_run._r.get_or_add_rPr().get_or_add_rFonts().set(qn("w:eastAsia"), "宋体")
        ref_run.font.size = Pt(12)
        ref.save(ref_path)

        tgt = docx.Document()
        tgt_run = tgt.add_paragraph().add_run("模板正文")
        tgt_run.font.name = "楷体"
        tgt_run._r.get_or_add_rPr().get_or_add_rFonts().set(qn("w:eastAsia"), "楷体")
        tgt_run.font.size = Pt(16)
        tgt.save(tgt_path)

        execute_review_plan(build_review_plan(ref_path, tgt_path), out_path)
        return out_path

    def _format_marks(self, docx_path: str, type_name: str):
        marks = []
        with zipfile.ZipFile(docx_path) as archive:
            for name in archive.namelist():
                if not name.startswith("word/") or not name.endswith(".xml"):
                    continue
                try:
                    root = etree.fromstring(archive.read(name))
                except etree.XMLSyntaxError:
                    continue
                for node in root.iter():
                    if _local_name(node.tag) == type_name:
                        marks.append((name, node.get(qn("w:id")), node))
        return marks

    def _run_level_rpr_change_id(self, docx_path: str) -> str:
        for _part, rev_id, node in self._format_marks(docx_path, "rPrChange"):
            rpr = node.getparent()
            owner = rpr.getparent() if rpr is not None else None
            # Paragraph-mark rPr sits in w:pPr; only a real run has w:r here.
            if owner is not None and _local_name(owner.tag) == "r":
                return rev_id
        self.fail("no run-level rPrChange found")

    def test_v35_format_revision_accept_keeps_new_properties(self) -> None:
        """Accepting a format revision keeps the restored (current) properties."""
        out_path = self._build_single_paragraph_review()
        rev_id = self._run_level_rpr_change_id(out_path)
        reviewed_run = docx.Document(out_path).paragraphs[0].runs[0]
        restored_size = reviewed_run.font.size
        restored_font = reviewed_run._r.rPr.rFonts.get(qn("w:eastAsia"))
        accepted_path = os.path.join(self.work_dir, "t3_accepted.docx")

        result = accept_revision(out_path, accepted_path, rev_id)
        self.assertEqual(result["status"], "APPLIED")
        self.assertEqual(result["kind"], "format")
        self.assertEqual(result["type"], "rPrChange")

        run = docx.Document(accepted_path).paragraphs[0].runs[0]
        self.assertEqual(run.font.size, restored_size)
        self.assertEqual(run._r.rPr.rFonts.get(qn("w:eastAsia")), restored_font)
        self.assertNotIn(rev_id, [item["revision_id"] for item in list_format_revisions(accepted_path)])

    def test_v35_format_revision_reject_restores_old_properties(self) -> None:
        """Rejecting a format revision restores the pre-change properties and drops the mark."""
        out_path = self._build_single_paragraph_review()
        rev_id = self._run_level_rpr_change_id(out_path)
        rejected_path = os.path.join(self.work_dir, "t3_rejected.docx")

        result = reject_revision(out_path, rejected_path, rev_id)
        self.assertEqual(result["status"], "APPLIED")

        run = docx.Document(rejected_path).paragraphs[0].runs[0]
        self.assertEqual(run.font.size.pt, 16.0)
        self.assertEqual(run._r.rPr.rFonts.get(qn("w:eastAsia")), "楷体")
        self.assertNotIn(rev_id, [item["revision_id"] for item in list_format_revisions(rejected_path)])

    def test_v35_cell_shading_format_revision_reject_and_accept(self) -> None:
        """tcPrChange reject removes the restored shading; accept keeps it."""
        out_path = self._build_review_output()
        tc_marks = self._format_marks(out_path, "tcPrChange")
        self.assertTrue(tc_marks, "review output has no tcPrChange")
        rev_id = tc_marks[0][1]

        rejected_path = os.path.join(self.work_dir, "t3_shd_rejected.docx")
        reject_revision(out_path, rejected_path, rev_id)
        rejected_cell = docx.Document(rejected_path).tables[0].cell(0, 0)
        self.assertIsNone(rejected_cell._tc.tcPr.find(qn("w:shd")))

        accepted_path = os.path.join(self.work_dir, "t3_shd_accepted.docx")
        accept_revision(out_path, accepted_path, rev_id)
        accepted_cell = docx.Document(accepted_path).tables[0].cell(0, 0)
        shading = accepted_cell._tc.tcPr.find(qn("w:shd"))
        self.assertIsNotNone(shading)
        self.assertEqual(shading.get(qn("w:fill")) or shading.get(qn("w:color")), "D9E2F3")

    def test_v35_revision_action_reports_not_found(self) -> None:
        """An unknown revision id must report NOT_FOUND and write no output file."""
        out_path = self._build_single_paragraph_review()
        missing_path = os.path.join(self.work_dir, "t3_missing.docx")

        result = accept_revision(out_path, missing_path, "999999")
        self.assertEqual(result["status"], "NOT_FOUND")
        self.assertEqual(result["changed"], 0)
        self.assertIsNone(result["output_docx"])
        self.assertFalse(os.path.exists(missing_path))

    def test_v35_sectpr_change_reports_unsupported(self) -> None:
        """sectPrChange is documented as unsupported: report it instead of half-applying."""
        path = os.path.join(self.work_dir, "t3_sectpr.docx")
        document = docx.Document()
        document.add_paragraph("正文")
        change = OxmlElement("w:sectPrChange")
        change.set(qn("w:id"), "321")
        change.set(qn("w:author"), "Tester")
        change.set(qn("w:date"), "2026-01-01T00:00:00Z")
        change.append(OxmlElement("w:sectPr"))
        document.sections[0]._sectPr.append(change)
        document.save(path)

        result = accept_revision(path, os.path.join(self.work_dir, "t3_sectpr_out.docx"), "321")
        self.assertEqual(result["status"], "UNSUPPORTED_REVISION_TYPE")
        self.assertEqual(result["changed"], 0)
        self.assertIsNone(result["output_docx"])

    def test_v35_review_snapshot_written_with_deliverable(self) -> None:
        """REVIEW must leave a snapshot describing every revision it wrote."""
        out_path = self._build_review_output(
            text_revisions=[{"old_text": "生成正文段落", "new_text": "模板正文段落"}],
        )
        snapshot_file = review_snapshot_path(out_path)
        self.assertTrue(os.path.isfile(snapshot_file))

        with open(snapshot_file, "r", encoding="utf-8") as handle:
            snapshot = json.load(handle)
        self.assertEqual(snapshot["schema_version"], "1.0")
        self.assertGreater(snapshot["revision_count"], 0)
        self.assertEqual(snapshot["revision_count"], len(snapshot["revisions"]))
        self.assertEqual({item["kind"] for item in snapshot["revisions"]}, {"text", "format"})
        for item in snapshot["revisions"]:
            self.assertTrue(item["parent_tag"])
            self.assertTrue(item["mark_xml"])
            self.assertIsNotNone(etree.fromstring(item["mark_xml"].encode("utf-8")))

        # `snapshot_path=""` opts out for callers that publish through a transaction.
        tiny = os.path.join(self.work_dir, "t4_tiny.docx")
        docx.Document().save(tiny)
        skipped = os.path.join(self.work_dir, "t4_no_snapshot.docx")
        execute_review_plan(build_review_plan(tiny, tiny), skipped, snapshot_path="")
        self.assertFalse(os.path.exists(review_snapshot_path(skipped)))

    def test_v35_restore_accepted_format_revision_from_snapshot(self) -> None:
        """A format revision accepted earlier can be rebuilt from the snapshot and re-rejected."""
        out_path = self._build_single_paragraph_review()
        rev_id = self._run_level_rpr_change_id(out_path)
        accepted_path = os.path.join(self.work_dir, "t4_accepted.docx")
        accept_revision(out_path, accepted_path, rev_id)
        self.assertNotIn(rev_id, [item["revision_id"] for item in list_format_revisions(accepted_path)])

        restored_path = os.path.join(self.work_dir, "t4_restored.docx")
        result = restore_revision(
            accepted_path, restored_path, rev_id,
            snapshot_path=review_snapshot_path(out_path),
        )
        self.assertEqual(result["status"], "RESTORED")
        self.assertIn(rev_id, [item["revision_id"] for item in list_format_revisions(restored_path)])

        # The rebuilt mark still carries the pre-change properties, so reject works again.
        rejected_path = os.path.join(self.work_dir, "t4_rejected.docx")
        reject_revision(restored_path, rejected_path, rev_id)
        run = docx.Document(rejected_path).paragraphs[0].runs[0]
        self.assertEqual(run.font.size.pt, 16.0)
        self.assertEqual(run._r.rPr.rFonts.get(qn("w:eastAsia")), "楷体")

    def test_v35_restore_without_snapshot_reports_missing(self) -> None:
        """Without a snapshot the restore must refuse instead of guessing a location."""
        out_path = self._build_single_paragraph_review()
        rev_id = self._run_level_rpr_change_id(out_path)
        accepted_path = os.path.join(self.work_dir, "t4_accepted_missing.docx")
        accept_revision(out_path, accepted_path, rev_id)

        restored_path = os.path.join(self.work_dir, "t4_restored_missing.docx")
        result = restore_revision(
            accepted_path, restored_path, rev_id,
            snapshot_path=os.path.join(self.work_dir, "absent_snapshot.json"),
        )
        self.assertEqual(result["status"], "SNAPSHOT_MISSING")
        self.assertEqual(result["changed"], 0)
        self.assertIsNone(result["output_docx"])
        self.assertFalse(os.path.exists(restored_path))

    def test_v35_restore_rejects_location_mismatch(self) -> None:
        """If the recorded parent moved, restore reports LOCATION_LOST and writes nothing."""
        out_path = self._build_single_paragraph_review()
        rev_id = self._run_level_rpr_change_id(out_path)
        accepted_path = os.path.join(self.work_dir, "t4_moved.docx")
        accept_revision(out_path, accepted_path, rev_id)

        document = docx.Document(accepted_path)
        paragraph = document.paragraphs[0]
        paragraph._p.getparent().remove(paragraph._p)
        document.save(accepted_path)

        restored_path = os.path.join(self.work_dir, "t4_moved_restored.docx")
        result = restore_revision(
            accepted_path, restored_path, rev_id,
            snapshot_path=review_snapshot_path(out_path),
        )
        self.assertEqual(result["status"], "LOCATION_LOST")
        self.assertIsNone(result["output_docx"])
        self.assertFalse(os.path.exists(restored_path))

    def test_v35_duplicate_revision_id_detected(self) -> None:
        """A revision id reused across parts must fail the integrity audit."""
        path = os.path.join(self.work_dir, "dup_id.docx")
        document = docx.Document()
        body_paragraph = document.add_paragraph("正文")
        header_paragraph = document.sections[0].header.paragraphs[0]
        header_paragraph.add_run("页眉")

        for parent in (body_paragraph._p, header_paragraph._p):
            ins = OxmlElement("w:ins")
            ins.set(qn("w:id"), "900")
            ins.set(qn("w:author"), "Tester")
            ins.set(qn("w:date"), "2026-01-01T00:00:00Z")
            run = OxmlElement("w:r")
            text = OxmlElement("w:t")
            text.text = "插入"
            run.append(text)
            ins.append(run)
            parent.append(ins)
        document.save(path)

        audit = audit_review_integrity(path)
        self.assertFalse(audit["passed"])
        details = " | ".join(item["detail"] for item in audit["issues"])
        self.assertIn("reused across parts", details)


    def test_v35_revision_action_is_transactional(self) -> None:
        """accept publishes through the M1 transaction and leaves no staged artifacts."""
        out_path = self._build_single_paragraph_review()
        rev_id = self._run_level_rpr_change_id(out_path)
        accepted_path = os.path.join(self.work_dir, "t7_accepted.docx")

        result = accept_revision(out_path, accepted_path, rev_id)
        self.assertEqual(result["status"], "APPLIED")
        transaction = result["transaction"]
        self.assertTrue(transaction["committed"])
        self.assertEqual(transaction["qa_status"], "PASSED")
        self.assertTrue(transaction["transaction_id"])
        self.assertTrue(os.path.isfile(accepted_path))
        self.assertEqual(
            [name for name in os.listdir(self.work_dir) if ".tmp-" in name or ".pending-" in name],
            [],
        )


if __name__ == "__main__":
    unittest.main()
