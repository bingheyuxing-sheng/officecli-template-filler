# -*- coding: utf-8 -*-
"""W3-6: the documented GENERATE workflow must run the v4 plan chain.

The test follows SKILL.md step by step with subprocesses and real plan
builders: analyze --spec-version 4 -> validate spec -> ContentPlan/FillPlan ->
generate_document --spec/--plan/--content-plan. It fails if the documented
default falls back to the legacy token path or emits a 3.0 spec.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import docx

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from content_intelligence import build_content_plan, build_fill_plan  # noqa: E402
from template_intelligence.spec_validator import validate_document_spec  # noqa: E402


def _make_template(path: str) -> None:
    document = docx.Document()
    document.add_paragraph("{{项目名称}}")
    table = document.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "项目"
    table.cell(0, 1).text = "金额"
    table.cell(1, 0).text = "【合计金额】"
    table.cell(1, 1).text = ""
    document.save(path)


def _find(spec: dict, text: str) -> dict:
    for slot in spec["slots"]:
        if slot.get("matched_text") == text and slot.get("protection_status") == "FILLABLE":
            return slot
    raise AssertionError("slot %r not found; got %r" % (text, [s.get("matched_text") for s in spec["slots"]]))


class SkillWorkflowV4Tests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.template = self.dir / "template.docx"
        _make_template(str(self.template))

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _run(self, args, timeout=180):
        return subprocess.run(
            [sys.executable] + args,
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )

    def test_documented_generate_workflow_is_v4(self) -> None:
        # Step 2 as documented: analyze with --spec-version 4.
        analyzed = self._run([
            str(ROOT / "scripts" / "analyze_template.py"),
            "--input", str(self.template),
            "--spec-version", "4",
        ])
        self.assertEqual(analyzed.returncode, 0, analyzed.stderr)
        spec = json.loads(analyzed.stdout)
        self.assertEqual(spec["schema_version"], "4.0")
        self.assertTrue(validate_document_spec(spec)["passed"])

        name = _find(spec, "{{项目名称}}")
        total = _find(spec, "【合计金额】")
        facts = [
            {"fact_id": "F_001", "label": "项目名称", "value": "示例项目", "unit": "none",
             "source": "USER_INPUT", "verification_status": "VERIFIED",
             "used_by_slots": [name["slot_id"]]},
            {"fact_id": "F_002", "label": "合计金额", "value": 120000, "unit": "yuan",
             "source": "budget.xlsx!Sheet1!B2", "verification_status": "VERIFIED",
             "used_by_slots": [total["slot_id"]]},
        ]
        content = build_content_plan(
            spec,
            plan_id="CP_SKILL",
            sections=[{"section_id": "SEC_001", "purpose": "项目",
                       "target_slots": [name["slot_id"], total["slot_id"]],
                       "fact_refs": ["F_001", "F_002"]}],
            facts=facts,
            required_slots=[name["slot_id"], total["slot_id"]],
        )
        fill = build_fill_plan(spec, content, task_id="TASK_SKILL_001", mode="STANDARD")

        spec_path = self.dir / "spec.json"
        content_path = self.dir / "content_plan.json"
        plan_path = self.dir / "fill_plan.json"
        spec_path.write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
        content_path.write_text(json.dumps(content, ensure_ascii=False), encoding="utf-8")
        plan_path.write_text(json.dumps(fill, ensure_ascii=False), encoding="utf-8")

        output = self.dir / "out.docx"
        generated = self._run([
            str(ROOT / "scripts" / "generate_document.py"),
            "--template", str(self.template),
            "--spec", str(spec_path),
            "--content-plan", str(content_path),
            "--plan", str(plan_path),
            "--out", str(output),
            "--mode", "STANDARD",
            "--allow-unverified",
        ])
        self.assertEqual(generated.returncode, 0, generated.stderr + generated.stdout)
        payload = json.loads(generated.stdout)
        self.assertIn(payload["status"], ("SUCCESS", "UNVERIFIED"), payload["errors"])
        self.assertEqual(payload["schema_version"], "4.0")
        self.assertTrue(payload["transaction"]["committed"])
        self.assertTrue(output.exists())
        # Plan path markers; the legacy token path prints `replaced_occurrences`.
        self.assertIn("transaction", payload)
        self.assertIn("qa_status", payload["data"])
        self.assertIsNotNone(payload["data"]["plan_validation"])
        self.assertGreater(payload["data"]["ledger"]["record_count"], 0, "fill ledger must record operations")
        self.assertTrue(payload["data"]["ledger"]["records"])
        self.assertNotIn("replaced_occurrences", payload)

        written = docx.Document(str(output))
        self.assertIn("示例项目", [p.text for p in written.paragraphs])
        self.assertEqual(written.tables[0].cell(1, 0).text, "120000")

    def test_default_analyzer_stays_legacy_for_compatibility(self) -> None:
        result = self._run([str(ROOT / "scripts" / "analyze_template.py"),
                            "--input", str(self.template)])
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(
            set(payload),
            {"file_path", "compatibility", "paragraphs_count", "candidate_hits_count",
             "candidate_hits", "table_profiles", "image_profiles"},
            "default output must stay the legacy CLI summary (compatibility boundary)",
        )

    def test_skill_documents_the_v4_chain(self) -> None:
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn('analyze_template.py --input "$INPUT_1" --spec-version 4', skill)
        self.assertIn("--content-plan", skill)
        self.assertIn("Legacy token mode", skill)
        self.assertNotIn(
            'generate_document.py --template "$INPUT_1" --payload',
            skill,
            "the documented GENERATE workflow must not use the legacy payload path",
        )


if __name__ == "__main__":
    unittest.main()
