# -*- coding: utf-8 -*-
"""W4-7 tests: every formal execution entry refuses an unconfirmed template."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import docx

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gate_helpers import ensure_gate  # noqa: E402

from content_intelligence import build_content_plan, build_fill_plan  # noqa: E402
from document_engine import execute_fill_plan  # noqa: E402
from engine import (  # noqa: E402
    build_proofread_plan,
    build_repair_plan,
    build_review_plan,
    execute_repair_plan,
    execute_review_plan,
)
from template_gate.errors import TemplateGateError  # noqa: E402
from template_intelligence import build_document_spec_from_path  # noqa: E402


def _template(directory: str) -> str:
    path = os.path.join(directory, "template.docx")
    document = docx.Document()
    document.add_paragraph("{{项目名称}}")
    document.save(path)
    return path


def _passing_qa(_staged_path):
    return {"status": "PASSED", "passed": True, "issues": [], "coverage_gaps": []}


def _bundle(template: str) -> tuple:
    spec = build_document_spec_from_path(template)
    slot = next(item for item in spec["slots"] if item.get("matched_text") == "{{项目名称}}")
    content = build_content_plan(
        spec,
        plan_id="CP_GATE_ENF",
        sections=[
            {"section_id": "SEC_001", "purpose": "项目名称", "target_slots": [slot["slot_id"]]}
        ],
        facts=[],
        required_slots=[slot["slot_id"]],
    )
    plan = build_fill_plan(
        spec, content, task_id="TASK_GATE_ENF", values_by_slot={slot["slot_id"]: "示例项目"}
    )
    return spec, content, plan


class GateEnforcementTests(unittest.TestCase):
    def test_execute_fill_plan_requires_confirmation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            template = _template(directory)
            spec, content, plan = _bundle(template)
            output = os.path.join(directory, "out.docx")
            empty_home = os.path.join(directory, "empty-gates")
            with mock.patch.dict(os.environ, {"OFFICECLI_GATE_HOME": empty_home}):
                result = execute_fill_plan(
                    template, spec, plan, output, content_plan=content, allow_unverified=True
                )
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(result["errors"][0]["code"], "TEMPLATE_GATE_REQUIRED")
        self.assertFalse(os.path.exists(output))

    def test_execute_fill_plan_succeeds_with_confirmed_record(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            template = _template(directory)
            record = ensure_gate(template, "GENERATE")
            spec, content, plan = _bundle(template)
            output = os.path.join(directory, "out.docx")
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

    def test_direct_repair_api_raises_without_record(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            reference = os.path.join(directory, "ref.docx")
            broken = os.path.join(directory, "broken.docx")
            ref_doc = docx.Document()
            ref_doc.add_paragraph().add_run("正文")
            ref_doc.save(reference)
            brk_doc = docx.Document()
            brk_doc.add_paragraph().add_run("正文")
            brk_doc.save(broken)
            plan = build_repair_plan(reference, broken)
            empty_home = os.path.join(directory, "empty-gates")
            with mock.patch.dict(os.environ, {"OFFICECLI_GATE_HOME": empty_home}):
                with self.assertRaises(TemplateGateError) as raised:
                    execute_repair_plan(plan, os.path.join(directory, "out.docx"))
        self.assertEqual(raised.exception.code, "TEMPLATE_GATE_REQUIRED")

    def test_direct_review_api_raises_without_record(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            reference = os.path.join(directory, "ref.docx")
            target = os.path.join(directory, "target.docx")
            ref_doc = docx.Document()
            ref_doc.add_paragraph("模板正文")
            ref_doc.save(reference)
            tgt_doc = docx.Document()
            tgt_doc.add_paragraph("草稿正文")
            tgt_doc.save(target)
            plan = build_review_plan(reference, target)
            empty_home = os.path.join(directory, "empty-gates")
            with mock.patch.dict(os.environ, {"OFFICECLI_GATE_HOME": empty_home}):
                with self.assertRaises(TemplateGateError) as raised:
                    execute_review_plan(plan, os.path.join(directory, "out.docx"), snapshot_path="")
        self.assertEqual(raised.exception.code, "TEMPLATE_GATE_REQUIRED")

    def test_proofread_does_not_trigger_template_gate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = os.path.join(directory, "target.docx")
            document = docx.Document()
            document.add_paragraph("正文内容")
            document.save(target)
            plan = build_proofread_plan(target)
            output = os.path.join(directory, "proofread.docx")
            empty_home = os.path.join(directory, "empty-gates")
            with mock.patch.dict(os.environ, {"OFFICECLI_GATE_HOME": empty_home}):
                execution = execute_review_plan(plan, output, snapshot_path="")
            self.assertIn("review_mode", execution)
            self.assertTrue(os.path.isfile(output))

    def test_legacy_cli_cannot_bypass_gate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            template = _template(directory)
            payload = os.path.join(directory, "payload.json")
            with open(payload, "w", encoding="utf-8") as handle:
                json.dump({"tokens": {"{{项目名称}}": "老接口"}}, handle, ensure_ascii=False)
            output = os.path.join(directory, "out.docx")
            empty_home = os.path.join(directory, "empty-gates")
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "generate_document.py"),
                    "--template",
                    template,
                    "--data",
                    payload,
                    "--out",
                    output,
                ],
                cwd=str(ROOT),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
                env={**os.environ, "OFFICECLI_GATE_HOME": empty_home},
            )
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        payload_result = json.loads(result.stdout)
        self.assertEqual(payload_result["error"], "TEMPLATE_GATE_REQUIRED")
        self.assertFalse(os.path.exists(output))


if __name__ == "__main__":
    unittest.main()
