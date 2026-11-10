# -*- coding: utf-8 -*-
"""End-to-end: gate -> plans -> OfficeCLI batch -> QA -> published DOCX."""

from __future__ import annotations

import docx
import pytest
from docx.shared import RGBColor

from content_intelligence import build_content_plan, build_fill_plan
from document_engine import generate_document_v4
from engine.officecli_runtime import OfficecliError, OfficecliRuntime
from template_gate.analyzer import build_analysis
from template_gate.store import GateStore
from template_intelligence.spec_builder import build_document_spec_from_path


def _require_officecli() -> None:
    try:
        OfficecliRuntime().preflight()
    except OfficecliError as exc:
        pytest.skip("officecli is not runnable here: {}".format(exc))


def test_generate_pipeline_writes_body_table_and_header_through_officecli(tmp_path):
    _require_officecli()

    template = tmp_path / "template.docx"
    output = tmp_path / "output.docx"

    document = docx.Document()
    document.add_heading("Quarterly Report", level=0)
    paragraph = document.add_paragraph("Client: ")
    paragraph.add_run("{{client}}")
    table = document.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "Item"
    table.cell(0, 1).text = "Amount"
    table.cell(1, 0).text = "{{item}}"
    table.cell(1, 1).text = "{{amount}}"
    document.sections[0].header.paragraphs[0].text = "Confidential - {{client}}"
    document.save(str(template))

    spec = build_document_spec_from_path(str(template))
    analysis = build_analysis(str(template), "GENERATE", spec=spec)
    record = GateStore().confirm(
        analysis,
        {"quality": {"unresolved_blocking": 0}, "report_digest": "f" * 64},
        user_statement="confirmed",
    )

    slots = [slot for slot in spec.get("slots", []) if isinstance(slot, dict)]
    content_plan = build_content_plan(
        spec,
        plan_id="CP_TEST",
        sections=[
            {
                "section_id": "SEC_001",
                "purpose": "fill every template slot",
                "target_slots": [slot["slot_id"] for slot in slots],
            }
        ],
        approval={
            "approved": True,
            "approved_by": "pytest",
            "approved_at": "2026-11-10T00:00:00Z",
        },
    )
    fill_plan = build_fill_plan(
        spec,
        content_plan,
        task_id="TASK_TEST",
        mode="STANDARD",
        values_by_slot={slot["slot_id"]: "ACME" for slot in slots},
    )

    result = generate_document_v4(
        str(template),
        spec,
        content_plan,
        fill_plan,
        str(output),
        allow_unverified=True,
        gate_record=record,
        writer="officecli",
    )

    assert result["data"]["writer_backend"] == "officecli"
    assert result["data"]["writer_fallback"] is None
    assert output.exists()

    rendered = docx.Document(str(output))
    assert rendered.paragraphs[1].text == "Client: ACME"
    cells = [cell.text for row in rendered.tables[0].rows for cell in row.cells]
    assert cells == ["Item", "Amount", "ACME", "ACME"]
    assert rendered.sections[0].header.paragraphs[0].text == "Confidential - ACME"


def test_repeated_placeholder_tokens_fill_distinct_runs(tmp_path):
    _require_officecli()

    template = tmp_path / "repeated-tokens.docx"
    output = tmp_path / "repeated-tokens-filled.docx"

    document = docx.Document()
    paragraph = document.add_paragraph("A ")
    for chunk in ("**", " B ", "**", " C ", "**"):
        run = paragraph.add_run(chunk)
        if chunk == "**":
            run.font.color.rgb = RGBColor(0xFF, 0, 0)
    document.save(str(template))

    spec = build_document_spec_from_path(str(template))
    slots = [
        slot for slot in spec.get("slots", [])
        if slot.get("candidate_type") == "red_run_clue"
    ]
    assert [(slot["matched_text"], slot["occurrence"]) for slot in slots] == [
        ("**", 1),
        ("**", 2),
        ("**", 3),
    ]

    analysis = build_analysis(str(template), "GENERATE", spec=spec)
    record = GateStore().confirm(
        analysis,
        {"quality": {"unresolved_blocking": 0}, "report_digest": "f" * 64},
        user_statement="confirmed",
    )
    content_plan = build_content_plan(
        spec,
        plan_id="CP_REPEATED_TOKENS",
        sections=[
            {
                "section_id": "SEC_001",
                "purpose": "fill repeated placeholders",
                "target_slots": [slot["slot_id"] for slot in slots],
            }
        ],
        approval={
            "approved": True,
            "approved_by": "pytest",
            "approved_at": "2026-11-10T00:00:00Z",
        },
    )
    fill_plan = build_fill_plan(
        spec,
        content_plan,
        task_id="TASK_TEST_REPEATED",
        mode="STANDARD",
        values_by_slot={
            slots[0]["slot_id"]: "一",
            slots[1]["slot_id"]: "二",
            slots[2]["slot_id"]: "三",
        },
    )

    result = generate_document_v4(
        str(template),
        spec,
        content_plan,
        fill_plan,
        str(output),
        allow_unverified=True,
        gate_record=record,
        writer="officecli",
    )

    assert result["status"] in ("SUCCESS", "UNVERIFIED"), result
    rendered = docx.Document(str(output))
    assert rendered.paragraphs[0].text == "A 一 B 二 C 三"


def test_content_plan_without_approval_blocks_before_writing(tmp_path):
    template = tmp_path / "approval-required.docx"
    output = tmp_path / "approval-required-out.docx"

    document = docx.Document()
    document.add_paragraph("Client: {{client}}")
    document.save(str(template))

    spec = build_document_spec_from_path(str(template))
    slots = [slot for slot in spec.get("slots", []) if isinstance(slot, dict)]
    content_plan = build_content_plan(
        spec,
        plan_id="CP_APPROVAL_REQUIRED",
        sections=[
            {
                "section_id": "SEC_001",
                "purpose": "fill every template slot",
                "target_slots": [slot["slot_id"] for slot in slots],
            }
        ],
    )
    fill_plan = build_fill_plan(
        spec,
        content_plan,
        task_id="TASK_APPROVAL_REQUIRED",
        mode="STANDARD",
        values_by_slot={slot["slot_id"]: "ACME" for slot in slots},
    )

    result = generate_document_v4(
        str(template),
        spec,
        content_plan,
        fill_plan,
        str(output),
        allow_unverified=True,
    )

    assert result["status"] == "BLOCKED"
    assert any(
        item["code"] == "CONTENT_PLAN_APPROVAL_REQUIRED"
        for item in result["errors"]
    ), result["errors"]
    assert not output.exists()


def test_empty_table_anchors_fill_through_officecli(tmp_path):
    _require_officecli()

    template = tmp_path / "empty-anchors.docx"
    output = tmp_path / "empty-anchors-filled.docx"
    document = docx.Document()
    table = document.add_table(rows=3, cols=2)
    table.cell(0, 0).text = "标签"
    table.cell(0, 1).text = "值"
    table.cell(1, 0).text = "课程名称"
    table.cell(2, 0).text = "…"
    document.save(str(template))

    spec = build_document_spec_from_path(str(template))
    anchors = sorted(
        [
            slot for slot in spec["slots"]
            if slot["candidate_type"] == "empty_anchor"
        ],
        key=lambda slot: slot["location_id"],
    )
    assert len(anchors) == 3

    analysis = build_analysis(str(template), "GENERATE", spec=spec)
    record = GateStore().confirm(
        analysis,
        {"quality": {"unresolved_blocking": 0}, "report_digest": "f" * 64},
        user_statement="confirmed",
    )
    content_plan = build_content_plan(
        spec,
        plan_id="CP_EMPTY_ANCHORS",
        sections=[
            {
                "section_id": "SEC_001",
                "purpose": "fill empty table anchors",
                "target_slots": [slot["slot_id"] for slot in anchors],
            }
        ],
        approval={
            "approved": True,
            "approved_by": "pytest",
            "approved_at": "2026-11-10T00:00:00Z",
        },
    )
    fill_plan = build_fill_plan(
        spec,
        content_plan,
        task_id="TASK_EMPTY_ANCHORS",
        mode="STANDARD",
        values_by_slot={
            slot["slot_id"]: value
            for slot, value in zip(anchors, ("信息安全技术应用", "示例课程", "完成"), strict=True)
        },
    )

    result = generate_document_v4(
        str(template),
        spec,
        content_plan,
        fill_plan,
        str(output),
        allow_unverified=True,
        gate_record=record,
        writer="officecli",
    )

    assert result["status"] in ("SUCCESS", "UNVERIFIED"), result
    rendered = docx.Document(str(output))
    assert rendered.tables[0].cell(1, 1).text == "信息安全技术应用"
    assert rendered.tables[0].cell(2, 0).text == "示例课程"
    assert rendered.tables[0].cell(2, 1).text == "完成"


def test_instruction_is_cleared_in_final_output(tmp_path):
    _require_officecli()

    template = tmp_path / "instruction.docx"
    output = tmp_path / "instruction-filled.docx"
    document = docx.Document()
    paragraph = document.add_paragraph("课程：")
    slot_run = paragraph.add_run("**")
    slot_run.font.color.rgb = RGBColor(0xFF, 0, 0)
    instruction = document.add_paragraph()
    for fragment in ("（备注：", "请按专业实际", "修改。）"):
        red = instruction.add_run(fragment)
        red.font.color.rgb = RGBColor(0xFF, 0, 0)
    document.save(str(template))

    spec = build_document_spec_from_path(str(template))
    slot = next(
        item for item in spec["slots"]
        if item["candidate_type"] == "red_run_clue"
        and item["red_text"]["semantic"] == "PLACEHOLDER"
    )
    instruction_slot = next(
        item for item in spec["slots"]
        if isinstance(item.get("red_text"), dict)
        and item["red_text"]["semantic"] == "INSTRUCTION"
    )
    analysis = build_analysis(str(template), "GENERATE", spec=spec)
    record = GateStore().confirm(
        analysis,
        {"quality": {"unresolved_blocking": 0}, "report_digest": "f" * 64},
        user_statement="confirmed",
    )
    content_plan = build_content_plan(
        spec,
        plan_id="CP_INSTRUCTION",
        sections=[
            {
                "section_id": "SEC_001",
                "purpose": "fill slot and remove instruction",
                "target_slots": [slot["slot_id"], instruction_slot["slot_id"]],
            }
        ],
        approval={
            "approved": True,
            "approved_by": "pytest",
            "approved_at": "2026-11-10T00:00:00Z",
        },
    )
    fill_plan = build_fill_plan(
        spec,
        content_plan,
        task_id="TASK_INSTRUCTION",
        mode="STANDARD",
        values_by_slot={slot["slot_id"]: "信息安全技术应用"},
    )

    result = generate_document_v4(
        str(template),
        spec,
        content_plan,
        fill_plan,
        str(output),
        allow_unverified=True,
        gate_record=record,
        writer="officecli",
    )

    assert result["status"] in ("SUCCESS", "UNVERIFIED"), result
    rendered = docx.Document(str(output))
    assert rendered.paragraphs[0].text == "课程：信息安全技术应用"
    assert rendered.paragraphs[1].text == ""
