# -*- coding: utf-8 -*-
"""W1-F end-to-end acceptance: template -> spec -> plans -> executor -> QA -> commit.

Covers the eight W1 acceptance scenarios required by the project:
1 normal fill, 2 missing required content, 3 capacity overflow, 4 protected region,
5 QA failure, 6 mid-execution failure, 7 STRICT commit refusal, 8 rollback keeps
the original template byte-identical.
"""

from __future__ import annotations

import copy
import hashlib
import json
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

from template_intelligence import build_document_spec_from_path  # noqa: E402
from template_intelligence.spec_validator import validate_document_spec  # noqa: E402
from content_intelligence import build_content_plan, build_fill_plan  # noqa: E402
from document_engine import execute_fill_plan  # noqa: E402
from qa.report_builder import build_qa_report, check_record  # noqa: E402
from qa.gate import resolve_required_checks  # noqa: E402

TASK_ID = "TASK_E2E_001"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _make_template(directory: Path) -> Path:
    path = directory / "template.docx"
    document = docx.Document()
    document.add_paragraph("{{项目名称}}")
    document.add_paragraph("{{项目背景}}")
    table = document.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "项目"
    table.cell(0, 1).text = "金额"
    table.cell(1, 0).text = "【合计金额】"
    table.cell(1, 1).text = ""
    document.save(str(path))
    return path


def _make_header_template(directory: Path) -> Path:
    path = directory / "header_template.docx"
    document = docx.Document()
    document.add_paragraph("正文内容")
    section = document.sections[0]
    section.different_first_page_header_footer = True
    header = section.first_page_header
    header.is_linked_to_previous = False
    header.paragraphs[0].text = "{{页眉标题}}"
    header.add_paragraph("内部资料")
    document.save(str(path))
    return path


def _find_slot(spec: dict, matched_text: str) -> dict:
    matches = [
        slot for slot in spec["slots"]
        if slot.get("matched_text") == matched_text
        and slot.get("protection_status") == "FILLABLE"
    ]
    if not matches:
        raise AssertionError("slot not produced for %r: %s" % (matched_text, [s.get("matched_text") for s in spec["slots"]]))
    return matches[0]


def _bundle(template: Path, mode: str = "STANDARD") -> tuple:
    spec = build_document_spec_from_path(str(template))
    report = validate_document_spec(spec)
    if not report["passed"]:
        raise AssertionError("producer emitted an invalid DocumentSpec: %s" % report["errors"][:3])

    name = _find_slot(spec, "{{项目名称}}")
    background = _find_slot(spec, "{{项目背景}}")
    total = _find_slot(spec, "【合计金额】")

    facts = [
        {
            "fact_id": "F_001",
            "label": "项目名称",
            "value": "示例项目",
            "unit": "none",
            "source": "USER_INPUT",
            "verification_status": "VERIFIED",
            "used_by_slots": [name["slot_id"]],
        },
        {
            "fact_id": "F_002",
            "label": "项目背景",
            "value": "本项目面向区域产业升级需求。",
            "unit": "none",
            "source": "USER_INPUT",
            "verification_status": "VERIFIED",
            "used_by_slots": [background["slot_id"]],
        },
        {
            "fact_id": "F_003",
            "label": "合计金额",
            "value": 120000,
            "unit": "yuan",
            "source": "budget.xlsx!Sheet1!B2",
            "verification_status": "VERIFIED",
            "used_by_slots": [total["slot_id"]],
        },
    ]
    sections = [
        {
            "section_id": "SEC_001",
            "purpose": "项目信息",
            "target_slots": [name["slot_id"], background["slot_id"]],
            "fact_refs": ["F_001", "F_002"],
        },
        {
            "section_id": "SEC_002",
            "purpose": "预算",
            "target_slots": [total["slot_id"]],
            "fact_refs": ["F_003"],
        },
    ]
    content = build_content_plan(
        spec,
        plan_id="CP_E2E_001",
        sections=sections,
        facts=facts,
        required_slots=[name["slot_id"], background["slot_id"], total["slot_id"]],
    )
    fill = build_fill_plan(spec, content, task_id=TASK_ID, mode=mode)
    return spec, content, fill


def _overflow_bundle(spec: dict, fill: dict) -> tuple:
    """Force a consistent hard capacity limit so the overflow scenario is legal."""
    spec = copy.deepcopy(spec)
    target = _find_slot(spec, "【合计金额】")
    target["capacity"] = {
        "max_chars_per_line": 20,
        "estimated_lines": None,
        "confidence": "low",
        "method": "forced_test_limit",
        "hard_limit": {"kind": "fixed_height_cell", "value": 10},
    }
    plan = copy.deepcopy(fill)
    for operation in plan["operations"]:
        if operation["slot_id"] != target["slot_id"]:
            continue
        operation["overflow"] = {
            "measured_chars": 999,
            "limit_source": "fixed_height_cell",
            "limit_value": 10,
            "strategy": "REJECT",
        }
        if "capacity_ok" not in operation["preconditions"]:
            operation["preconditions"].append("capacity_ok")
    return spec, plan


def _report_with_all_checks(gate_mode: str, staged: str, *, fail_check: str | None = None,
                            skip_check: str | None = None) -> dict:
    policy = resolve_required_checks("GENERATE", gate_mode)
    checks = [
        check_record(check_id, "PASSED", "e2e_stub", artifact_path=staged, detail="stub evidence")
        for check_id in policy["required"]
    ]
    issues = []
    coverage_gaps = []
    if fail_check:
        for index, record in enumerate(checks):
            if record["check_id"] == fail_check:
                checks[index] = check_record(
                    fail_check, "FAILED", "e2e_stub", artifact_path=staged, detail="forced failure"
                )
        issues.append(
            {
                "code": "%s_CHECK_FAILED" % fail_check,
                "severity": "high",
                "location": fail_check,
                "detail": "forced failure for the acceptance scenario",
                "blocking": True,
                "check_id": fail_check,
            }
        )
    if skip_check:
        for index, record in enumerate(checks):
            if record["check_id"] == skip_check:
                checks[index] = check_record(
                    skip_check, "SKIPPED", "e2e_stub", artifact_path=staged, detail="forced unavailable"
                )
        coverage_gaps.append("FORCED_%s_UNAVAILABLE" % skip_check)
    return build_qa_report(
        task_id=TASK_ID,
        task_mode="GENERATE",
        gate_mode=gate_mode,
        checks=checks,
        issues=issues,
        coverage_gaps=coverage_gaps,
    )


class EndToEndTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.directory = Path(self._tmp.name)
        self.template = _make_template(self.directory)
        self.original_sha = _sha256(self.template)
        self.gate = ensure_gate(str(self.template), "GENERATE")
        self.spec, self.content, self.fill = _bundle(self.template)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _assert_rollback(self, output: Path) -> None:
        self.assertFalse(output.exists(), "failed run must not publish a deliverable")
        self.assertEqual(_sha256(self.template), self.original_sha, "template bytes must stay unchanged")
        leftovers = [
            item.name for item in self.directory.iterdir()
            if ".tmp-" in item.name or ".pending-" in item.name
        ]
        self.assertEqual(leftovers, [], "no staged artifact may survive a failed run")

    def test_01_normal_fill_commits(self) -> None:
        output = self.directory / "out.docx"
        result = execute_fill_plan(
            str(self.template), self.spec, self.fill, str(output),
            content_plan=self.content, allow_unverified=True,
        )
        self.assertIn(result["status"], ("SUCCESS", "UNVERIFIED"), result["errors"])
        self.assertTrue(result["transaction"]["committed"])
        self.assertTrue(output.exists())
        self.assertEqual(_sha256(self.template), self.original_sha)

        written = docx.Document(str(output))
        texts = [paragraph.text for paragraph in written.paragraphs]
        self.assertIn("示例项目", texts)
        self.assertIn("本项目面向区域产业升级需求。", texts)
        self.assertEqual(written.tables[0].cell(1, 0).text, "120000")

        ledger = result["data"]["ledger"]
        self.assertEqual(ledger["record_count"], len(self.fill["operations"]))
        self.assertTrue(all(record["result"]["status"] == "SUCCESS" for record in ledger["records"]))

    def test_02_missing_required_content_blocks(self) -> None:
        plan = copy.deepcopy(self.fill)
        plan["operations"] = [op for op in plan["operations"] if op["type"] != "fill_cell"]
        plan["baseline"]["allowed_slot_ids"] = [op["slot_id"] for op in plan["operations"]]
        output = self.directory / "missing.docx"
        result = execute_fill_plan(str(self.template), self.spec, plan, str(output), content_plan=self.content)
        self.assertEqual(result["status"], "BLOCKED")
        self.assertIn("REQUIRED_SLOT_MISSING", str(result["data"]["plan_validation"]))
        self._assert_rollback(output)

    def test_03_capacity_overflow_blocks(self) -> None:
        spec, plan = _overflow_bundle(self.spec, self.fill)
        output = self.directory / "overflow.docx"
        result = execute_fill_plan(str(self.template), spec, plan, str(output), content_plan=self.content)
        self.assertEqual(result["status"], "BLOCKED")
        self.assertIn("CAPACITY_EXCEEDED", str(result["data"]["plan_validation"]))
        self._assert_rollback(output)

    def test_04_protected_slot_blocks(self) -> None:
        spec = copy.deepcopy(self.spec)
        target = _find_slot(spec, "【合计金额】")
        target["protection_status"] = "PROTECTED"
        target["confirmation_tier"] = "PROTECTED_DO_NOT_TOUCH"
        plan = copy.deepcopy(self.fill)
        output = self.directory / "protected.docx"
        result = execute_fill_plan(str(self.template), spec, plan, str(output), content_plan=self.content)
        self.assertEqual(result["status"], "BLOCKED")
        self.assertIn("PROTECTED_SLOT_VIOLATION", str(result["data"]["plan_validation"]))
        self._assert_rollback(output)

    def test_05_qa_failure_prevents_commit(self) -> None:
        output = self.directory / "qa_failed.docx"

        def runner(staged: str) -> dict:
            return _report_with_all_checks("STANDARD", staged, fail_check="FORMAT")

        result = execute_fill_plan(
            str(self.template), self.spec, self.fill, str(output),
            content_plan=self.content, qa_runner=runner, allow_unverified=True,
        )
        self.assertEqual(result["status"], "FAILED")
        self._assert_rollback(output)

    def test_06_mid_execution_failure_rolls_back(self) -> None:
        output = self.directory / "mid_failure.docx"
        with mock.patch(
            "document_engine.fill_executor._apply_operation",
            side_effect=RuntimeError("simulated mid-execution failure"),
        ):
            result = execute_fill_plan(
                str(self.template), self.spec, self.fill, str(output),
                content_plan=self.content, allow_unverified=True,
            )
        self.assertEqual(result["status"], "FAILED")
        self._assert_rollback(output)
        self.assertTrue(any(record["result"]["status"] == "FAILED" for record in result["data"]["ledger"]["records"]))

    def test_07_strict_unverified_refuses_commit(self) -> None:
        plan = copy.deepcopy(self.fill)
        plan["mode"] = "STRICT"
        output = self.directory / "strict_unverified.docx"

        def runner(staged: str) -> dict:
            return _report_with_all_checks("STRICT", staged, skip_check="VISUAL_PAGE_COUNT")

        result = execute_fill_plan(
            str(self.template), self.spec, plan, str(output),
            content_plan=self.content, qa_runner=runner, allow_unverified=True,
        )
        self.assertEqual(result["status"], "FAILED")
        self._assert_rollback(output)

    def test_08_rollback_is_byte_identical(self) -> None:
        output = self.directory / "rollback.docx"
        spec, plan = _overflow_bundle(self.spec, self.fill)
        result = execute_fill_plan(str(self.template), spec, plan, str(output), content_plan=self.content)
        self.assertEqual(result["status"], "BLOCKED")
        self._assert_rollback(output)

    def test_11_first_page_header_slot_fills(self) -> None:
        template = _make_header_template(self.directory)
        ensure_gate(str(template), "GENERATE")
        original_sha = _sha256(template)
        spec = build_document_spec_from_path(str(template))
        self.assertTrue(validate_document_spec(spec)["passed"])

        slot = _find_slot(spec, "{{页眉标题}}")
        self.assertTrue(slot["location_id"].startswith("sec[0].first_page_header"), slot["location_id"])
        protected_locations = {region["location_id"] for region in spec["protected_regions"]}
        self.assertNotIn(slot["location_id"], protected_locations)
        fixed = [
            region for region in spec["protected_regions"]
            if region["location_id"] == "sec[0].first_page_header.p[1]"
        ]
        self.assertTrue(fixed, "fixed header paragraph must stay protected")
        self.assertEqual(fixed[0]["kind"], "header")
        self.assertIn("first_page_header", fixed[0]["evidence"])

        fact = {
            "fact_id": "F_HEADER",
            "label": "页眉标题",
            "value": "年度报告",
            "unit": "none",
            "source": "USER_INPUT",
            "verification_status": "VERIFIED",
            "used_by_slots": [slot["slot_id"]],
        }
        content = build_content_plan(
            spec,
            plan_id="CP_HEADER",
            sections=[{"section_id": "SEC_HEADER", "purpose": "页眉", "target_slots": [slot["slot_id"]]}],
            facts=[fact],
            required_slots=[slot["slot_id"]],
        )
        fill = build_fill_plan(spec, content, task_id="TASK_E2E_HEADER", mode="STANDARD")

        output = self.directory / "header_out.docx"
        result = execute_fill_plan(
            str(template), spec, fill, str(output),
            content_plan=content, allow_unverified=True,
        )
        self.assertIn(result["status"], ("SUCCESS", "UNVERIFIED"), result["errors"])
        self.assertTrue(result["transaction"]["committed"])
        self.assertEqual(_sha256(template), original_sha, "template bytes must stay unchanged")

        written = docx.Document(str(output))
        header = written.sections[0].first_page_header
        header_texts = [paragraph.text for paragraph in header.paragraphs]
        self.assertIn("年度报告", header_texts)
        self.assertIn("内部资料", header_texts)

    def test_09_analyze_template_emits_spec_4_cli(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "analyze_template.py"),
                "--input", str(self.template),
                "--spec-version", "4",
            ],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=120,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        spec = json.loads(result.stdout)
        report = validate_document_spec(spec)
        self.assertTrue(report["passed"], report["errors"][:5])
        self.assertEqual(spec["schema_version"], "4.0")

    def test_10_generate_document_plan_cli(self) -> None:
        spec_path = self.directory / "spec.json"
        plan_path = self.directory / "fill_plan.json"
        content_path = self.directory / "content_plan.json"
        spec_path.write_text(json.dumps(self.spec, ensure_ascii=False), encoding="utf-8")
        plan_path.write_text(json.dumps(self.fill, ensure_ascii=False), encoding="utf-8")
        content_path.write_text(json.dumps(self.content, ensure_ascii=False), encoding="utf-8")
        output = self.directory / "cli_out.docx"
        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "generate_document.py"),
                "--template", str(self.template),
                "--spec", str(spec_path),
                "--plan", str(plan_path),
                "--content-plan", str(content_path),
                "--out", str(output),
                "--mode", "STANDARD",
                "--allow-unverified",
            ],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=180,
        )
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["transaction"]["committed"])
        self.assertIn(payload["status"], ("SUCCESS", "UNVERIFIED"))
        self.assertTrue(output.exists())


if __name__ == "__main__":
    unittest.main()
