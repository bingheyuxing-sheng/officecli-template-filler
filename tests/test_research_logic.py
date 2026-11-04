# -*- coding: utf-8 -*-
"""Tests for deterministic logic checks and research planning/provenance."""

from __future__ import annotations

import os
import tempfile
import unittest

import docx

from engine import (
    build_proofread_plan,
    build_research_plan,
    research_policy,
    validate_research_facts,
)
from engine.logic_qa import audit_logic


def _codes(document) -> set:
    return {issue["code"] for issue in audit_logic(document)["issues"]}


class LogicQaTests(unittest.TestCase):
    def test_duplicate_long_paragraph(self) -> None:
        document = docx.Document()
        text = "这是一段足够长的重复正文内容，用于验证重复段落检查是否生效。"
        document.add_paragraph(text)
        document.add_paragraph("另一段不同的正文。")
        document.add_paragraph(text)
        self.assertIn("LOGIC_DUPLICATE_PARAGRAPH", _codes(document))

    def test_empty_section(self) -> None:
        document = docx.Document()
        document.add_heading("第一章 总则", level=1)
        document.add_heading("第二章 范围", level=1)
        self.assertIn("LOGIC_EMPTY_SECTION", _codes(document))

    def test_list_sequence_gap(self) -> None:
        document = docx.Document()
        document.add_paragraph("1. 第一项")
        document.add_paragraph("2. 第二项")
        document.add_paragraph("4. 第四项")
        self.assertIn("LOGIC_LIST_SEQUENCE_GAP", _codes(document))

    def test_date_range_inversion(self) -> None:
        document = docx.Document()
        document.add_paragraph("开始日期：2026年12月1日，结束日期：2026年11月1日")
        report = audit_logic(document)
        self.assertIn("LOGIC_DATE_RANGE_INVALID", {issue["code"] for issue in report["issues"]})

    def test_proofread_plan_includes_logic_findings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "dup.docx")
            document = docx.Document()
            text = "这是一段足够长的重复正文内容，用于验证校对计划是否收集逻辑问题。"
            document.add_paragraph(text)
            document.add_paragraph("中间一段。")
            document.add_paragraph(text)
            document.save(path)

            plan = build_proofread_plan(path)
            comments = [action.get("comment", "") for action in plan["actions"]]
            self.assertTrue(any("LOGIC_DUPLICATE_PARAGRAPH" in comment for comment in comments))


class ResearchPlanTests(unittest.TestCase):
    def test_policy_by_mode(self) -> None:
        self.assertTrue(research_policy("GENERATE")["enabled"])
        self.assertEqual(
            research_policy("GENERATE")["policy"],
            "ON_DEMAND_PUBLIC_STANDARDS_ONLY",
        )
        self.assertFalse(research_policy("REPAIR")["enabled"])

    def test_plan_skips_internal_and_protected_slots(self) -> None:
        slots = [
            {"confirmation_tier": "AUTO_DERIVE_OR_BIND", "matched_text": "{{project_name}}", "location_id": "body.p[0]"},
            {"confirmation_tier": "AUTO_DERIVE_OR_BIND", "matched_text": "{{project_name}}", "location_id": "body.p[1]"},
            {"confirmation_tier": "MUST_ASK_USER", "matched_text": "项目负责人", "location_id": "body.p[2]"},
            {"confirmation_tier": "PROTECTED_DO_NOT_TOUCH", "matched_text": "field", "location_id": "body.p[3]"},
        ]
        plan = build_research_plan("智慧校园建设", slots)
        self.assertTrue(plan["enabled"])
        self.assertEqual(len(plan["queries"]), 1)
        self.assertIn("智慧校园建设", plan["queries"][0]["query"])
        self.assertEqual(plan["queries"][0]["priority"], "high")

    def test_disabled_mode_has_no_queries(self) -> None:
        plan = build_research_plan(
            "智慧校园建设",
            [{"confirmation_tier": "AUTO_DERIVE_OR_BIND", "matched_text": "{{x}}"}],
            task_mode="REPAIR",
        )
        self.assertFalse(plan["enabled"])
        self.assertEqual(plan["queries"], [])

    def test_fact_sources_are_required_and_unverified_are_reported(self) -> None:
        report = validate_research_facts([
            {"label": "缺少来源", "value": 1},
            {"label": "有来源", "value": 2, "source": "https://example.edu/standard"},
            {"label": "未核实", "value": 3, "source": "UNVERIFIED"},
        ])
        self.assertFalse(report["passed"])
        self.assertIn("FACT_SOURCE_MISSING", {issue["code"] for issue in report["issues"]})
        self.assertEqual(report["unverified_count"], 1)
        self.assertEqual(report["unverified_facts"][0]["label"], "未核实")


if __name__ == "__main__":
    unittest.main()
