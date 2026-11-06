# -*- coding: utf-8 -*-
"""W4-9 end-to-end: block -> resolve -> report -> confirm -> generate."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import docx

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from content_intelligence import build_content_plan, build_fill_plan  # noqa: E402
from document_engine import execute_fill_plan  # noqa: E402
from template_gate import build_analysis, validate_gate  # noqa: E402
from template_gate.report import build_report  # noqa: E402
from template_gate.store import GateStore  # noqa: E402
from template_gate.supplements import resolve_evidence  # noqa: E402
from template_intelligence import build_document_spec_from_path  # noqa: E402


def _passing_qa(_staged):
    return {"status": "PASSED", "passed": True, "issues": [], "coverage_gaps": []}


def _template(directory: str) -> str:
    path = os.path.join(directory, "template.docx")
    document = docx.Document()
    document.add_paragraph("{{项目名称}}")
    table = document.add_table(rows=2, cols=2)
    table.cell(1, 0).text = "一段未标注用途的说明"
    document.save(path)
    return path


class TemplateGateEndToEndTests(unittest.TestCase):
    def test_block_resolve_confirm_generate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            template = _template(directory)
            gate_home = os.path.join(directory, "gates")
            analysis = build_analysis(template, "GENERATE")
            self.assertGreaterEqual(analysis["summary"]["blocking"], 1)

            report = build_report(analysis)
            self.assertTrue(report["blocking_items"])
            store = GateStore(gate_home)
            store.review_token(report["analysis_id"], report["report_digest"])
            with self.assertRaises(ValueError):
                store.confirm(analysis, report, user_statement="未解决就确认")

            purpose = next(item for item in analysis["evidence"] if item["property"] == "table.purpose")
            analysis = resolve_evidence(
                analysis,
                purpose["evidence_id"],
                resolution_type="PROVIDE_VALUE",
                value="fixed_or_reference",
                user_statement="这个表格是固定说明，不需要填写",
            )
            report = build_report(analysis)
            self.assertEqual(report["blocking_items"], [])
            record = store.confirm(
                analysis,
                report,
                user_statement="确认按该模板生成",
                ttl_seconds=3600,
            )

            verdict = validate_gate(template, "GENERATE", gate_record=record, gate_home=gate_home)
            self.assertTrue(verdict["passed"], verdict["checks"])

            spec = build_document_spec_from_path(template)
            slot = next(item for item in spec["slots"] if item.get("matched_text") == "{{项目名称}}")
            content = build_content_plan(
                spec,
                plan_id="CP_E2E_GATE",
                sections=[{"section_id": "SEC_001", "purpose": "项目名称", "target_slots": [slot["slot_id"]]}],
                facts=[],
                required_slots=[slot["slot_id"]],
            )
            plan = build_fill_plan(
                spec, content, task_id="TASK_E2E_GATE", values_by_slot={slot["slot_id"]: "示例项目"}
            )
            output = os.path.join(directory, "out.docx")
            with mock.patch.dict(os.environ, {"OFFICECLI_GATE_HOME": gate_home}):
                result = execute_fill_plan(
                    template,
                    spec,
                    plan,
                    output,
                    content_plan=content,
                    qa_runner=_passing_qa,
                    allow_unverified=True,
                    gate_record=record,
                )
            self.assertIn(result["status"], ("SUCCESS", "UNVERIFIED"), result["errors"])
            self.assertTrue(os.path.isfile(output))

    def test_template_change_after_confirmation_is_stale(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            template = _template(directory)
            analysis = build_analysis(template, "GENERATE")
            purpose = next(item for item in analysis["evidence"] if item["property"] == "table.purpose")
            analysis = resolve_evidence(
                analysis,
                purpose["evidence_id"],
                resolution_type="PROVIDE_VALUE",
                value="fixed_or_reference",
                user_statement="固定说明",
            )
            report = build_report(analysis)
            store = GateStore(os.path.join(directory, "gates"))
            record = store.confirm(analysis, report, user_statement="确认", ttl_seconds=3600)

            document = docx.Document(template)
            document.add_paragraph("追加内容")
            document.save(template)
            verdict = validate_gate(
                template, "GENERATE", gate_record=record, gate_home=os.path.join(directory, "gates")
            )
            self.assertFalse(verdict["passed"])
            self.assertEqual(verdict["code"], "TEMPLATE_GATE_STALE")


if __name__ == "__main__":
    unittest.main()
