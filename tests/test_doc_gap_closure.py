# -*- coding: utf-8 -*-
"""Regression tests for the capabilities the process document describes.

Covers the six engine-level gaps closed in this change:
1. MUST_ASK_USER slots for blank internal-fact fields;
2. REVIEW automatic template-vs-draft text diff;
3. PROOFREAD automatic content/typo checks surfaced as comments;
4. SSOT errors carrying metric/locations/values;
5. w:proofErr balance auditing in package QA;
6. NEEDS_REDRAW on failed chart rendering.
"""

from __future__ import annotations

import os
import tempfile
import unittest
import zipfile
from unittest import mock

import docx

from engine import (
    QA_PASSED,
    SSOTValidationError,
    DocumentTransaction,
    TransactionAborted,
    audit_docx_package_integrity,
    build_proofread_plan,
    build_review_plan,
    build_ssot_master_data,
    execute_review_plan,
    extract_document_spec,
    render_chart_image,
)
from engine.docx_parser import match_internal_fact_slots

from gate_helpers import ensure_gate  # noqa: E402

_real_execute_review_plan = execute_review_plan


def execute_review_plan(plan, output_docx_path, *args, **kwargs):
    if str(plan.get("task_mode") or "").upper() == "REVIEW":
        ensure_gate(plan["reference_docx"], "REVIEW")
    return _real_execute_review_plan(plan, output_docx_path, *args, **kwargs)


def _write_docx(path: str, paragraphs) -> str:
    document = docx.Document()
    for text in paragraphs:
        document.add_paragraph(text)
    document.save(path)
    return path


class _DocxTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmpdir = self._tmp.name

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def path(self, name: str) -> str:
        return os.path.join(self.tmpdir, name)


class InternalFactSlotTests(_DocxTestCase):
    def test_blank_internal_fields_are_must_ask_user(self) -> None:
        template = _write_docx(self.path("t.docx"), [
            "项目负责人：",
            "联系电话：________",
            "审核人：待填写",
            "项目负责人：张三",
        ])
        spec = extract_document_spec(docx.Document(template), file_path=template)
        internal = [
            hit for hit in spec["candidate_hits"]
            if hit["candidate_type"] == "internal_fact"
        ]

        self.assertEqual(len(internal), 3)
        self.assertTrue(all(hit["confirmation_tier"] == "MUST_ASK_USER" for hit in internal))
        self.assertEqual(
            {hit["matched_text"] for hit in internal},
            {"项目负责人", "联系电话", "审核人"},
        )
        # A filled value is content, not a slot that still needs a decision.
        self.assertNotIn("body.p[3]", {hit["location_id"] for hit in internal})

    def test_regex_does_not_match_filled_or_unrelated_text(self) -> None:
        self.assertEqual(match_internal_fact_slots("项目负责人：张三"), [])
        self.assertEqual(match_internal_fact_slots("本项目共有 3 个部门"), [])
        self.assertEqual(match_internal_fact_slots("负责人："), ["负责人"])


class ReviewAutoTextDiffTests(_DocxTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.reference = _write_docx(self.path("ref.docx"), [
            "项目总投资为100万元。",
            "本项目建设周期为两年。",
        ])
        self.target = _write_docx(self.path("target.docx"), [
            "项目总投资为120万元。",
            "本项目建设周期为两年。",
            "补充说明：本段为新增内容。",
        ])

    def test_auto_text_diff_creates_tracked_revision(self) -> None:
        plan = build_review_plan(self.reference, self.target, auto_text_diff=True)
        auto = [a for a in plan["actions"] if a.get("auto_generated")]
        self.assertEqual(len(auto), 1)
        self.assertEqual(auto[0]["action_type"], "TRACK_TEXT_REVISION")
        self.assertEqual(auto[0]["old_text"], "项目总投资为120万元。")
        self.assertEqual(auto[0]["new_text"], "项目总投资为100万元。")
        self.assertEqual(plan["summary"]["auto_text_diffs"], 1)

        out_path = self.path("reviewed.docx")
        execution = execute_review_plan(plan, out_path, snapshot_path="")
        self.assertEqual(execution["tracked_text_revisions"], 1)
        self.assertTrue(os.path.isfile(out_path))

    def test_auto_text_diff_is_opt_in(self) -> None:
        plan = build_review_plan(self.reference, self.target)
        self.assertFalse([a for a in plan["actions"] if a.get("auto_generated")])
        self.assertEqual(plan["summary"]["auto_text_diffs"], 0)

    def test_placeholder_reference_is_not_restored(self) -> None:
        reference = _write_docx(self.path("ref_placeholder.docx"), ["项目负责人：{{name}}"])
        target = _write_docx(self.path("target_filled.docx"), ["项目负责人：张三"])

        plan = build_review_plan(reference, target, auto_text_diff=True)
        self.assertFalse([a for a in plan["actions"] if a.get("auto_generated")])

    def test_blank_internal_fact_is_not_restored(self) -> None:
        reference = _write_docx(self.path("ref_internal.docx"), ["项目负责人："])
        target = _write_docx(self.path("target_internal.docx"), ["项目负责人：张三"])

        plan = build_review_plan(reference, target, auto_text_diff=True)
        self.assertFalse([a for a in plan["actions"] if a.get("auto_generated")])


class ProofreadAutoCheckTests(_DocxTestCase):
    def test_content_and_typo_findings_become_comments(self) -> None:
        target = _write_docx(self.path("draft.docx"), [
            "项目总投资为100万元。",
            "项目总投资为120万元。",
            "本项目的以经完成全部建设内容。",
        ])

        plan = build_proofread_plan(target)
        codes = {action["comment"].split("]")[0].strip("[自动检查:") for action in plan["actions"]
                 if action.get("action_type") == "ADD_REVIEW_COMMENT"}
        self.assertIn("CONTENT_VALUE_CONFLICT", codes)
        self.assertIn("PROOFREAD_TYPO_CANDIDATE", codes)
        self.assertGreaterEqual(plan["summary"]["auto_check_comments"], 2)

        out_path = self.path("proofread.docx")
        execution = execute_review_plan(plan, out_path, snapshot_path="")
        self.assertGreaterEqual(execution["comments_added"], 2)
        self.assertTrue(os.path.isfile(out_path))

    def test_auto_check_can_be_disabled(self) -> None:
        target = _write_docx(self.path("clean.docx"), ["本项目的以经完成。"])
        plan = build_proofread_plan(target, auto_check=False)
        self.assertEqual(plan["summary"]["auto_check_comments"], 0)
        self.assertTrue(plan["auto_check"]["disabled"])

    def test_table_subtotal_with_header_row_is_checked(self) -> None:
        path = self.path("table.docx")
        document = docx.Document()
        document.add_paragraph("项目数据如下。")
        table = document.add_table(rows=4, cols=2)
        table.cell(0, 0).text = "指标"
        table.cell(0, 1).text = "数值"
        table.cell(1, 0).text = "分项甲"
        table.cell(1, 1).text = "40"
        table.cell(2, 0).text = "分项乙"
        table.cell(2, 1).text = "50"
        table.cell(3, 0).text = "合计"
        table.cell(3, 1).text = "80"
        document.save(path)

        plan = build_proofread_plan(path)
        subtotal = [
            action for action in plan["actions"]
            if "CONTENT_SUBTOTAL_MISMATCH" in str(action.get("comment"))
        ]
        self.assertEqual(len(subtotal), 1)
        self.assertTrue(subtotal[0]["location_id"].startswith("body.tbl[0]"))

        out_path = self.path("table_proofread.docx")
        execution = execute_review_plan(plan, out_path, snapshot_path="")
        self.assertTrue(
            any("tbl[" in str(result.get("target")) for result in execution["action_results"])
        )


class SSOTStructuredErrorTests(unittest.TestCase):
    def test_part_sum_error_carries_metric_locations_and_values(self) -> None:
        records = [{
            "name": "项目A",
            "total": 100,
            "part_a": 40,
            "part_b": 50,
            "location": "body.tbl[0].r[1]",
        }]
        with self.assertRaises(SSOTValidationError) as caught:
            build_ssot_master_data(
                records,
                numeric_fields=["total"],
                part_sum_rules=[("total", ["part_a", "part_b"])],
            )

        error = caught.exception
        self.assertEqual(error.code, "SSOT_PART_SUM_MISMATCH")
        self.assertEqual(error.metric, "total")
        self.assertEqual(error.values["actual"], "100")
        self.assertEqual(error.values["expected"], "90")
        self.assertIn("total@body.tbl[0].r[1]", error.locations)
        self.assertEqual(error.as_dict()["metric"], "total")


class ProofErrQATests(_DocxTestCase):
    def _inject_unbalanced_proof_err(self, path: str) -> str:
        staged = path + ".unbalanced.docx"
        with zipfile.ZipFile(path) as source, zipfile.ZipFile(staged, "w", zipfile.ZIP_DEFLATED) as dest:
            for item in source.infolist():
                data = source.read(item.filename)
                if item.filename == "word/document.xml":
                    xml = data.decode("utf-8")
                    marker = '<w:p><w:proofErr w:type="spellStart"/><w:r><w:t>marker</w:t></w:r></w:p>'
                    xml = xml.replace("<w:body>", "<w:body>" + marker, 1)
                    data = xml.encode("utf-8")
                dest.writestr(item, data)
        return staged

    def test_unbalanced_proof_err_is_reported(self) -> None:
        path = _write_docx(self.path("proof.docx"), ["正文内容"])
        self.assertEqual(
            audit_docx_package_integrity(path)["proof_err_unbalanced"],
            [],
        )

        broken = self._inject_unbalanced_proof_err(path)
        report = audit_docx_package_integrity(broken)
        self.assertTrue(report["proof_err_unbalanced"])
        self.assertIn(
            "PACKAGE_PROOFERR_UNBALANCED",
            {issue["code"] for issue in report["issues"]},
        )


class ChartRedrawStatusTests(unittest.TestCase):
    def test_invalid_spec_requires_redraw(self) -> None:
        result = render_chart_image({"kind": "unknown"}, os.path.join(tempfile.gettempdir(), "x.png"))
        self.assertEqual(result["status"], "INVALID_SPEC")
        self.assertTrue(result["needs_redraw"])


class LockEvidenceTests(_DocxTestCase):
    def test_locked_output_reports_cleanup_log(self) -> None:
        source = _write_docx(self.path("source.docx"), ["正文"])
        tx = DocumentTransaction(source, self.path("out.docx"), task_mode="GENERATE")
        tx.preflight_report = {"passed": True, "checks": []}
        tx.qa_status = QA_PASSED
        with open(tx.temp_path, "wb") as handle:
            handle.write(b"staged")

        with mock.patch("engine.transaction.os.replace", side_effect=PermissionError("locked")):
            with self.assertRaises(TransactionAborted):
                tx.commit()

        self.assertEqual(tx.lock_info["code"], "OUTPUT_FILE_LOCKED")
        self.assertTrue(str(tx.lock_info["cleanup_log"]).endswith(".json"))


if __name__ == "__main__":
    unittest.main()
