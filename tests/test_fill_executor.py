# -*- coding: utf-8 -*-
"""W1-D tests: deterministic FillPlan execution, fill ledger and transaction boundary.

Every fixture is a real DOCX produced with python-docx, described by the real
DocumentSpec producer (W1-A) and the real ContentPlan/FillPlan builders (W1-C),
so the executor is exercised end-to-end rather than against hand-written JSON.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import docx
from docx.oxml import OxmlElement, parse_xml
from docx.oxml.ns import nsdecls, qn
from docx.shared import Cm, RGBColor
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gate_helpers import ensure_gate, gate_home  # noqa: E402

from content_intelligence import build_content_plan, build_fill_plan  # noqa: E402
from document_engine import FillLedger, execute_fill_plan  # noqa: E402
from template_intelligence import build_document_spec_from_path  # noqa: E402

SCRIPT = ROOT / "scripts" / "generate_document.py"
TABLE_LOCATION = "body.tbl[0].r[1].c[0].p[0]"
NAME_LOCATION = "body.p[0]"


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


def _tr_pr(row):
    tr_pr = row._tr.find(qn("w:trPr"))
    if tr_pr is None:
        tr_pr = OxmlElement("w:trPr")
        row._tr.insert(0, tr_pr)
    return tr_pr


def _mark_repeating_header(row) -> None:
    tr_pr = _tr_pr(row)
    tr_pr.append(OxmlElement("w:tblHeader"))


def _mark_exact_row_height(row, twips: int = 40) -> None:
    tr_pr = _tr_pr(row)
    height = OxmlElement("w:trHeight")
    height.set(qn("w:hRule"), "exact")
    height.set(qn("w:val"), str(twips))
    tr_pr.append(height)


def make_template(directory: Path, name: str = "template.docx") -> Path:
    """Body token + table token; row 0 repeats (a 'warning' protected region)."""
    path = directory / name
    document = docx.Document()
    document.add_paragraph("{{项目名称}}")

    table = document.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "项目"
    table.cell(0, 1).text = "金额"
    table.cell(1, 0).text = "【合计金额】"
    table.cell(1, 1).text = ""
    _mark_repeating_header(table.rows[0])
    _mark_exact_row_height(table.rows[1], 40)

    document.save(str(path))
    return path


def make_control_template(directory: Path) -> Path:
    """A content-control paragraph is reported as PROTECTED by the spec producer."""
    path = directory / "control.docx"
    document = docx.Document()
    paragraph = document.add_paragraph()
    sdt = (
        f"<w:sdt {nsdecls('w')}><w:sdtPr/><w:sdtContent>"
        "<w:r><w:t>项目负责人</w:t></w:r></w:sdtContent></w:sdt>"
    )
    paragraph._p.append(parse_xml(sdt))
    document.save(str(path))
    return path


def make_image_template(directory: Path) -> Path:
    path = directory / "image.docx"
    pixel = directory / "pixel.png"
    Image.new("RGB", (8, 8), (200, 30, 30)).save(pixel)
    document = docx.Document()
    paragraph = document.add_paragraph()
    run = paragraph.add_run("***")
    run.font.color.rgb = RGBColor(0xFF, 0x00, 0x00)
    run.add_picture(str(pixel), width=Cm(2))
    document.save(str(path))
    return path


def slot_for(spec: dict, location: str) -> dict:
    return next(item for item in spec["slots"] if item["location_id"] == location)


def two_slot_plan(spec: dict, mode: str = "STRICT"):
    name_slot = slot_for(spec, NAME_LOCATION)
    table_slot = slot_for(spec, TABLE_LOCATION)
    content = build_content_plan(
        spec,
        plan_id="CP_001",
        sections=[
            {"section_id": "SEC_001", "purpose": "项目名称", "target_slots": [name_slot["slot_id"]]},
            {"section_id": "SEC_002", "purpose": "合计金额", "target_slots": [table_slot["slot_id"]]},
        ],
        facts=[],
        required_slots=[name_slot["slot_id"], table_slot["slot_id"]],
    )
    values = {
        name_slot["slot_id"]: "示例项目",
        table_slot["slot_id"]: "120000",
    }
    plan = build_fill_plan(
        spec,
        content,
        task_id="TASK_FILL_001",
        mode=mode,
        values_by_slot=values,
    )
    return content, plan, name_slot, table_slot


def operation_of_type(plan: dict, op_type: str) -> dict:
    return next(op for op in plan["operations"] if op["type"] == op_type)


def passing_qa(_staged_path):
    return {
        "schema_version": "4.0",
        "task_id": "TASK_FILL_001",
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


def sha256_file(path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def staged_leftovers(directory: Path) -> list:
    return sorted(
        item.name for item in directory.iterdir()
        if ".tmp-" in item.name or ".pending-" in item.name
    )


class _ExecutorCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="w1d_fill_")
        self.directory = Path(self._tmp.name)
        self.template = make_template(self.directory)
        self.gate = ensure_gate(str(self.template), "GENERATE")
        self.spec = build_document_spec_from_path(str(self.template))
        self.content, self.plan, self.name_slot, self.table_slot = two_slot_plan(self.spec)
        self.output = self.directory / "out.docx"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def execute(self, **kwargs):
        fill_plan = kwargs.pop("fill_plan_override", self.plan)
        return execute_fill_plan(
            str(self.template), self.spec, fill_plan, str(self.output),
            content_plan=kwargs.pop("content_plan", self.content),
            gate_record=self.gate,
            **kwargs,
        )


# ---------------------------------------------------------------------------
# success path
# ---------------------------------------------------------------------------


class SuccessTests(_ExecutorCase):
    def test_success_fills_body_and_table_and_commits(self) -> None:
        before_sha = sha256_file(self.template)
        result = self.execute(qa_runner=passing_qa)

        self.assertEqual(result["status"], "SUCCESS")
        self.assertEqual(result["next_action"], "NONE")
        self.assertEqual(result["errors"], [])
        self.assertTrue(Path(self.output).is_file())

        output_doc = docx.Document(str(self.output))
        self.assertEqual(output_doc.paragraphs[0].text, "示例项目")
        self.assertEqual(output_doc.tables[0].cell(1, 0).text, "120000")

        # The template itself must never be modified.
        self.assertEqual(sha256_file(self.template), before_sha)

        transaction = result["transaction"]
        self.assertTrue(transaction["committed"])
        self.assertIsNone(transaction["staged_path"])
        self.assertEqual(transaction["qa_status"], "PASSED")
        self.assertEqual(staged_leftovers(self.directory), [])

        artifacts = result["artifacts"]
        self.assertEqual(len(artifacts), 1)
        self.assertEqual(Path(artifacts[0]["path"]), Path(self.output).resolve())
        self.assertEqual(artifacts[0]["kind"], "docx")
        self.assertTrue(artifacts[0]["required"])
        self.assertRegex(artifacts[0]["sha256"], r"^[0-9a-f]{64}$")

        # Contract 05: an artifact must never be a staging path.
        self.assertNotIn(".tmp-", artifacts[0]["path"])
        self.assertNotIn(".pending-", artifacts[0]["path"])

    def test_ledger_has_one_record_per_operation_with_hashes_only(self) -> None:
        result = self.execute(qa_runner=passing_qa)
        records = result["data"]["ledger"]["records"]

        self.assertEqual(len(records), len(self.plan["operations"]))
        self.assertEqual([record["op_id"] for record in records],
                         [op["op_id"] for op in self.plan["operations"]])
        for record in records:
            self.assertEqual(record["result"]["status"], "SUCCESS")
            self.assertNotIn("value", record)
            self.assertIsNotNone(record["before_text_sha256"])
            self.assertIsNotNone(record["after_text_sha256"])
            self.assertFalse(record["before_text_sha256"] == record["after_text_sha256"])

        name_record = next(record for record in records if record["slot_id"] == self.name_slot["slot_id"])
        expected = hashlib.sha256("示例项目".encode("utf-8")).hexdigest()
        self.assertEqual(name_record["value_sha256"], expected)
        self.assertEqual(name_record["location_id"], NAME_LOCATION)
        self.assertEqual(name_record["source_ref"], "USER_INPUT")

    def test_warning_protected_region_continues_and_is_recorded(self) -> None:
        result = self.execute(qa_runner=passing_qa)

        self.assertEqual(result["status"], "SUCCESS")
        warnings = result["data"]["region_warnings"]
        self.assertTrue(warnings, "the repeating-header region must be recorded")
        self.assertEqual(warnings[0]["code"], "PROTECTED_REGION_WARNING")
        self.assertEqual(warnings[0]["location_id"], "body.tbl[0]")
        self.assertEqual(warnings[0]["op_id"], "OP_002")

    def test_qa_runner_receives_the_staged_path(self) -> None:
        seen = {}

        def stub(staged_path):
            seen["path"] = staged_path
            seen["existed"] = os.path.isfile(staged_path)
            return passing_qa(staged_path)

        result = execute_fill_plan(
            str(self.template), self.spec, self.plan, str(self.output),
            content_plan=self.content, qa_runner=stub,
        )
        self.assertEqual(result["status"], "SUCCESS")
        self.assertTrue(seen["existed"], "QA must read an existing staged artifact")
        self.assertIn(".tmp-", os.path.basename(seen["path"]))
        self.assertNotEqual(Path(seen["path"]), Path(self.output).resolve())


# ---------------------------------------------------------------------------
# blocked paths (no mutation, no artifact)
# ---------------------------------------------------------------------------


class BlockedTests(_ExecutorCase):
    def test_template_byte_change_blocks_before_mutation(self) -> None:
        changed = docx.Document(str(self.template))
        changed.add_paragraph("附加内容")
        changed.save(str(self.template))
        self.assertNotEqual(sha256_file(self.template), self.spec["template"]["template_sha256"])

        result = self.execute(qa_runner=passing_qa)

        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(result["artifacts"], [])
        self.assertFalse(Path(self.output).exists())
        self.assertIn("TEMPLATE_SHA_MISMATCH", [item["code"] for item in result["errors"]])
        self.assertEqual(staged_leftovers(self.directory), [])

    def test_protected_slot_blocks_without_output(self) -> None:
        control_template = make_control_template(self.directory)
        control_spec = build_document_spec_from_path(str(control_template))
        control_slot = control_spec["slots"][0]
        content = build_content_plan(
            control_spec,
            plan_id="CP_002",
            sections=[{"section_id": "SEC_001", "purpose": "负责人", "target_slots": [control_slot["slot_id"]]}],
            facts=[],
            required_slots=[control_slot["slot_id"]],
        )
        plan = build_fill_plan(
            control_spec, content, task_id="TASK_FILL_002",
            values_by_slot={control_slot["slot_id"]: "张三"},
        )
        output = self.directory / "control-out.docx"

        result = execute_fill_plan(
            str(control_template), control_spec, plan, str(output),
            content_plan=content, qa_runner=passing_qa,
        )

        self.assertEqual(result["status"], "BLOCKED")
        self.assertFalse(output.exists())
        self.assertIn("PROTECTED_SLOT_VIOLATION", [item["code"] for item in result["errors"]])
        self.assertEqual(result["artifacts"], [])

    def test_overflow_is_rejected_not_shrunk(self) -> None:
        plan = copy.deepcopy(self.plan)
        table_op = operation_of_type(plan, "fill_cell")
        table_op["value"] = "超长金额" * 20
        table_op["overflow"]["measured_chars"] = len(table_op["value"])

        result = self.execute(fill_plan_override=plan)

        self.assertEqual(result["status"], "BLOCKED")
        self.assertFalse(Path(self.output).exists())
        codes = [item["code"] for item in result["errors"]]
        self.assertIn("CAPACITY_EXCEEDED", codes)
        self.assertEqual(staged_leftovers(self.directory), [])

    def test_unknown_slot_blocks(self) -> None:
        plan = copy.deepcopy(self.plan)
        plan["operations"][0]["slot_id"] = "S_deadbeefdead"

        result = self.execute(fill_plan_override=plan)

        self.assertEqual(result["status"], "BLOCKED")
        self.assertFalse(Path(self.output).exists())
        self.assertIn("UNKNOWN_SLOT", [item["code"] for item in result["errors"]])

    def test_invalid_content_plan_blocks(self) -> None:
        content = copy.deepcopy(self.content)
        content["sections"][0]["target_slots"] = ["S_deadbeef12ab"]

        result = execute_fill_plan(
            str(self.template), self.spec, self.plan, str(self.output),
            content_plan=content, qa_runner=passing_qa,
        )

        self.assertEqual(result["status"], "BLOCKED")
        self.assertFalse(Path(self.output).exists())

    def test_missing_image_file_blocks(self) -> None:
        image_template = make_image_template(self.directory)
        image_spec = build_document_spec_from_path(str(image_template))
        image_slot = image_spec["slots"][0]
        self.assertEqual(image_slot["matched_text"], "***")

        content = build_content_plan(
            image_spec,
            plan_id="CP_003",
            sections=[{"section_id": "SEC_001", "purpose": "配图", "target_slots": [image_slot["slot_id"]]}],
            facts=[],
            required_slots=[image_slot["slot_id"]],
        )
        plan = build_fill_plan(
            image_spec, content, task_id="TASK_FILL_003",
            images_by_slot={image_slot["slot_id"]: str(self.directory / "missing.png")},
        )
        self.assertEqual(operation_of_type(plan, "replace_image")["type"], "replace_image")
        output = self.directory / "image-out.docx"

        result = execute_fill_plan(
            str(image_template), image_spec, plan, str(output),
            content_plan=content, qa_runner=passing_qa,
        )

        self.assertEqual(result["status"], "BLOCKED")
        self.assertFalse(output.exists())
        self.assertEqual(result["artifacts"], [])


# ---------------------------------------------------------------------------
# QA gate
# ---------------------------------------------------------------------------


class QaGateTests(_ExecutorCase):
    def test_qa_failure_prevents_commit_and_output(self) -> None:
        def failing_qa(_staged_path):
            return {
                "schema_version": "4.0",
                "task_id": "TASK_FILL_001",
                "status": "FAILED",
                "missing_checks": [],
                "coverage_gaps": [],
                "issues": [{
                    "code": "QA_FALSE_PASS",
                    "severity": "blocking",
                    "blocking": True,
                    "location": "FORMAT",
                    "detail": "format gate failed",
                }],
                "checks": [],
            }

        result = self.execute(qa_runner=failing_qa)

        self.assertEqual(result["status"], "FAILED")
        self.assertFalse(Path(self.output).exists())
        self.assertEqual(result["artifacts"], [])
        self.assertFalse(result["transaction"]["committed"])
        self.assertEqual(result["transaction"]["abort_reason"], "QA_FAILED")
        self.assertEqual(staged_leftovers(self.directory), [])

    def test_strict_mode_refuses_unverified_report(self) -> None:
        def unverified_qa(_staged_path):
            return {
                "schema_version": "4.0",
                "task_id": "TASK_FILL_001",
                "status": "UNVERIFIED",
                "missing_checks": ["FIDELITY", "VISUAL_PAGE_COUNT"],
                "coverage_gaps": [],
                "issues": [],
                "checks": [],
            }

        result = self.execute(qa_runner=unverified_qa)

        self.assertEqual(result["status"], "FAILED")
        self.assertFalse(Path(self.output).exists())
        self.assertEqual(result["transaction"]["abort_reason"], "QA_NOT_ELIGIBLE")
        self.assertIn("QA_ELIGIBILITY_CONTRADICTION",
                      [item["code"] for item in result["errors"]])

    def test_standard_mode_commits_unverified_only_with_disclosure(self) -> None:
        content, plan, _name, _table = two_slot_plan(self.spec, mode="STANDARD")
        output = self.directory / "standard-out.docx"

        def unverified_qa(_staged_path):
            return {
                "schema_version": "4.0",
                "task_id": "TASK_FILL_001",
                "status": "UNVERIFIED",
                "missing_checks": ["FIDELITY", "DATA"],
                "coverage_gaps": [],
                "issues": [],
                "checks": [],
            }

        result = execute_fill_plan(
            str(self.template), self.spec, plan, str(output),
            content_plan=content, qa_runner=unverified_qa, allow_unverified=True,
        )

        self.assertEqual(result["status"], "UNVERIFIED")
        self.assertEqual(result["next_action"], "COMMIT")
        self.assertTrue(output.is_file())
        self.assertTrue(result["data"]["qa_eligible"])
        self.assertEqual(result["data"]["missing_checks"], ["FIDELITY", "DATA"])
        self.assertTrue(result["transaction"]["committed"])


# ---------------------------------------------------------------------------
# ledger persistence + CLI compatibility
# ---------------------------------------------------------------------------


class LedgerAndCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="w1d_cli_")
        self.directory = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_fill_ledger_write_is_atomic(self) -> None:
        ledger = FillLedger(task_id="TASK_FILL_010")
        ledger.record("OP_001", "S_000000000001", "body.p[0]", "USER_INPUT", "秘密值",
                      {"status": "SUCCESS"}, before_text="{{项目名称}}", after_text="秘密值")
        target = self.directory / "ledger.json"
        written = ledger.write(str(target))

        self.assertEqual(Path(written), target.resolve())
        self.assertFalse((self.directory / "ledger.json.tmp").exists())
        payload = json.loads(target.read_text(encoding="utf-8"))
        self.assertEqual(payload["record_count"], 1)
        self.assertEqual(payload["records"][0]["result"]["status"], "SUCCESS")
        self.assertNotIn("秘密值", target.read_text(encoding="utf-8"))

    def test_legacy_data_cli_is_unchanged(self) -> None:
        template = self.directory / "legacy.docx"
        document = docx.Document()
        document.add_paragraph("{{项目名称}}")
        document.save(str(template))
        ensure_gate(str(template), "GENERATE")
        payload = self.directory / "payload.json"
        payload.write_text(json.dumps({"tokens": {"{{项目名称}}": "老接口"}}, ensure_ascii=False),
                           encoding="utf-8")
        output = self.directory / "legacy-out.docx"

        completed = subprocess.run(
            [sys.executable, str(SCRIPT), "--template", str(template),
             "--data", str(payload), "--out", str(output)],
            cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8",
            errors="replace", check=False,
            env={**os.environ, "OFFICECLI_GATE_HOME": gate_home()},
        )
        self.assertEqual(completed.returncode, 0, completed.stderr or completed.stdout)
        result = json.loads(completed.stdout)
        self.assertEqual(
            set(result.keys()),
            {"output", "replaced_occurrences", "package_qa_passed", "qa_passed",
             "qa_status", "transaction"},
        )
        self.assertEqual(result["replaced_occurrences"], 1)
        self.assertTrue(output.is_file())

    def test_plan_cli_standard_commits_unverified_with_disclosure(self) -> None:
        template = make_template(self.directory)
        ensure_gate(str(template), "GENERATE")
        spec = build_document_spec_from_path(str(template))
        _content, plan, _name, _table = two_slot_plan(spec, mode="STANDARD")
        plan_path = self.directory / "fill_plan.json"
        spec_path = self.directory / "spec.json"
        spec_path.write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
        plan_path.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
        output = self.directory / "cli-plan-out.docx"

        completed = subprocess.run(
            [sys.executable, str(SCRIPT), "--template", str(template),
             "--spec", str(spec_path), "--plan", str(plan_path),
             "--out", str(output), "--mode", "STANDARD", "--allow-unverified"],
            cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8",
            errors="replace", check=False,
            env={**os.environ, "OFFICECLI_GATE_HOME": gate_home()},
        )
        self.assertEqual(completed.returncode, 0, completed.stderr or completed.stdout)
        result = json.loads(completed.stdout)
        self.assertEqual(result["schema_version"], "4.0")
        self.assertEqual(result["status"], "UNVERIFIED")
        self.assertEqual(result["next_action"], "COMMIT")
        self.assertTrue(output.is_file())
        self.assertTrue(result["data"]["qa_eligible"])


if __name__ == "__main__":
    unittest.main()
