# -*- coding: utf-8 -*-
"""Regression tests for template semantics and editable OfficeCLI controls."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import docx
import pytest
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt, RGBColor
from docx.text.paragraph import Paragraph

from content_intelligence import build_content_plan, build_fill_plan, validate_fill_plan
from document_engine.fill_executor import (
    _control_operation_batch,
    _officecli_control_plan,
    _snapshot_controls,
    _verify_control_snapshot,
    _verify_update_fields_on_open,
)
from document_engine.fill_ledger import FillLedger
from engine.ooxml_utils import iter_all_document_paragraphs_with_Wait_context
from template_gate import build_analysis
from template_gate.report import build_report, render_markdown
from template_intelligence import build_document_spec_from_path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _add_complex_field(paragraph: Paragraph, instruction: str, result: str) -> None:
    for kind, text in (
        ("begin", None),
        ("instr", instruction),
        ("separate", None),
        ("result", result),
        ("end", None),
    ):
        run = OxmlElement("w:r")
        if kind in ("begin", "separate", "end"):
            field = OxmlElement("w:fldChar")
            field.set(qn("w:fldCharType"), kind)
            run.append(field)
        elif kind == "instr":
            node = OxmlElement("w:instrText")
            node.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
            node.text = text
            run.append(node)
        else:
            node = OxmlElement("w:t")
            node.text = text
            run.append(node)
        paragraph._p.append(run)


def _add_footer_sdt_with_field(document, sdt_id: int = 42) -> None:
    footer = document.sections[0].footer
    sdt = OxmlElement("w:sdt")
    sdt_pr = OxmlElement("w:sdtPr")
    id_node = OxmlElement("w:id")
    id_node.set(qn("w:val"), str(sdt_id))
    sdt_pr.append(id_node)
    tag = OxmlElement("w:tag")
    tag.set(qn("w:val"), "PageNumber")
    sdt_pr.append(tag)
    sdt.append(sdt_pr)
    content = OxmlElement("w:sdtContent")
    paragraph_el = OxmlElement("w:p")
    content.append(paragraph_el)
    sdt.append(content)
    footer._element.append(sdt)
    paragraph = Paragraph(paragraph_el, footer)
    _add_complex_field(paragraph, " PAGE   \\* MERGEFORMAT ", "2")


def _make_control_template(path: Path) -> Path:
    document = docx.Document()
    document.add_paragraph("正文")
    _add_complex_field(document.add_paragraph("目录项："), " PAGEREF _Toc1 \\h ", "3")
    _add_footer_sdt_with_field(document)
    document.save(path)
    return path


def test_control_inventory_resolves_fields_and_footer_sdt(tmp_path):
    template = _make_control_template(tmp_path / "controls.docx")
    spec = build_document_spec_from_path(str(template))
    fields = spec["controls"]["fields"]
    sdts = spec["controls"]["sdts"]

    assert [field["field_type"] for field in fields] == ["PAGEREF", "PAGE"]
    assert all(field["address_status"] == "RESOLVED" for field in fields)
    assert all(field["editable"] for field in fields)
    assert len(sdts) == 1
    assert sdts[0]["contains_fields"] is True
    assert sdts[0]["requires_confirmation"] is True
    assert sdts[0]["default_action"] == "REFRESH_FIELDS"
    assert fields[-1]["parent_sdt_id"] == sdts[0]["sdt_id"]
    assert fields[-1]["raw_locator"]["part"].startswith("/footer[")


def test_adjacent_red_runs_merge_to_one_instruction(tmp_path):
    template = tmp_path / "red.docx"
    document = docx.Document()
    paragraph = document.add_paragraph()
    fragments = ["（备注：", "各专业", "可适当", "删减、", "修改和补充", "培养规格，", "以体现", "专业特色", "。）"]
    for fragment in fragments:
        run = paragraph.add_run(fragment)
        run.font.color.rgb = RGBColor(0xFF, 0, 0)
        run.font.size = Pt(16)
    document.save(template)

    spec = build_document_spec_from_path(str(template))
    red_slots = [
        slot for slot in spec["slots"]
        if isinstance(slot.get("red_text"), dict)
    ]
    instructions = [
        slot for slot in red_slots
        if slot["red_text"]["semantic"] == "INSTRUCTION"
    ]

    assert len(instructions) == 1
    assert instructions[0]["red_text"]["action"] == "REMOVE_IN_FINAL"
    assert len(instructions[0]["red_text"]["run_ranges"]) == len(fragments)
    assert instructions[0]["red_text"]["original_text"].startswith("（备注：")


def test_empty_table_cells_are_user_confirmed_anchors(tmp_path):
    template = tmp_path / "empty-anchors.docx"
    document = docx.Document()
    table = document.add_table(rows=3, cols=2)
    table.cell(0, 0).text = "标签"
    table.cell(0, 1).text = "值"
    table.cell(1, 0).text = "课程名称"
    table.cell(1, 1).text = ""
    table.cell(2, 0).text = "…"
    table.cell(2, 1).text = ""
    document.save(template)

    spec = build_document_spec_from_path(str(template))
    anchors = [
        slot for slot in spec["slots"]
        if slot["candidate_type"] == "empty_anchor"
    ]

    assert sorted(
        (slot["matched_text"], slot["confirmation_tier"]) for slot in anchors
    ) == [("", "MUST_ASK_USER"), ("", "MUST_ASK_USER"), ("…", "MUST_ASK_USER")]
    assert all(slot["protection_status"] == "CONDITIONAL" for slot in anchors)
    assert all(slot["scope"] == "table" for slot in anchors)


def test_fill_plan_clears_instruction_without_writing_a_value(tmp_path):
    template = tmp_path / "instruction-clear.docx"
    document = docx.Document()
    document.add_paragraph("正文")
    paragraph = document.add_paragraph("课程：")
    run = paragraph.add_run("**")
    run.font.color.rgb = RGBColor(0xFF, 0, 0)
    instruction = document.add_paragraph()
    for fragment in ("（备注：", "请按专业实际", "修改。）"):
        red = instruction.add_run(fragment)
        red.font.color.rgb = RGBColor(0xFF, 0, 0)
    document.save(template)

    spec = build_document_spec_from_path(str(template))
    instruction_slot = next(
        slot for slot in spec["slots"]
        if isinstance(slot.get("red_text"), dict)
        and slot["red_text"]["semantic"] == "INSTRUCTION"
    )
    content_plan = build_content_plan(
        spec,
        plan_id="CP_INSTRUCTION_CLEAR",
        sections=[
            {
                "section_id": "SEC_001",
                "purpose": "remove instructions",
                "target_slots": [instruction_slot["slot_id"]],
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
        task_id="TASK_INSTRUCTION_CLEAR",
        values_by_slot={instruction_slot["slot_id"]: "不应写入"},
    )

    assert len(fill_plan["operations"]) == 1
    operation = fill_plan["operations"][0]
    assert operation["type"] == "clear_red_text"
    assert operation["slot_id"] == instruction_slot["slot_id"]
    assert "value" not in operation
    assert validate_fill_plan(fill_plan, spec, content_plan)["passed"]


def test_font_rule_is_ambiguous_until_supplement_confirms_it(tmp_path):
    template = tmp_path / "font-rule.docx"
    document = docx.Document()
    document.add_paragraph("模板")
    paragraph = document.add_paragraph()
    label = paragraph.add_run("姓名：")
    label.font.size = Pt(14)
    slot = paragraph.add_run("**")
    slot.font.size = Pt(16)
    slot.font.color.rgb = RGBColor(0xFF, 0, 0)
    document.save(template)

    analysis = build_analysis(str(template), "GENERATE")
    rule_records = [
        item for item in analysis["evidence"]
        if item["property"] == "font_rule"
    ]
    assert len(rule_records) == 1
    assert rule_records[0]["verification_status"] == "AMBIGUOUS"
    assert rule_records[0]["value"]["label_size_pt"] == 14.0
    assert rule_records[0]["value"]["slot_size_pt"] == 16.0
    assert not [
        item for item in analysis["evidence"]
        if item["location"] == rule_records[0]["location"]
        and item["property"] == "font_size"
        and item["verification_status"] == "CONFLICT"
    ]

    supplement = {
        "schema_version": "1.0",
        "kind": "TemplateSemanticSupplement",
        "supplement_id": "SUP_TEST_FONT_001",
        "template_sha256": _sha256(template),
        "font_rules": [
            {
                "evidence_id": rule_records[0]["evidence_id"],
                "label_size_pt": 14,
                "slot_size_pt": 16,
                "intentional": True,
                "user_statement": "确认标签14磅、占位符16磅。",
            }
        ],
    }
    supplement_path = tmp_path / "supplement.json"
    supplement_path.write_text(
        json.dumps(supplement, ensure_ascii=False), encoding="utf-8"
    )
    resolved = build_analysis(
        str(template), "GENERATE", supplements=[str(supplement_path)]
    )
    resolved_rules = [
        item for item in resolved["evidence"]
        if item["property"] == "font_rule"
    ]
    assert resolved_rules[0]["verification_status"] == "VERIFIED"
    assert resolved_rules[0]["blocking"] is False


def test_gate_report_does_not_claim_blocking_items_are_resolved():
    analysis = {
        "analysis_id": "analysis_test",
        "template_name": "template.docx",
        "template_sha256": "a" * 64,
        "task_type": "GENERATE",
        "summary": {
            "verified": 1,
            "unverified": 0,
            "ambiguous": 1,
            "conflict": 0,
            "blocking": 1,
            "coverage": 1.0,
        },
        "evidence": [
            {
                "evidence_id": "ev_test_1",
                "location": "body.p[0]",
                "property": "font_rule",
                "value": {"label_size_pt": 14, "slot_size_pt": 16},
                "verification_status": "AMBIGUOUS",
                "blocking": True,
                "detail": "confirm the mixed-size rule",
                "required_materials": ["font rule"],
            }
        ],
    }

    report = build_report(analysis)
    markdown = render_markdown(report)

    assert report["quality"]["unresolved_blocking"] == 1
    assert "尚未通过" in report["confirmation"]["prompt"]
    assert "1 个阻断性问题未解决" in report["confirmation"]["prompt"]
    assert "均已解决" not in markdown
    assert "尚未通过" in markdown


def test_supplement_rejects_sha_mismatch_and_duplicate_declarations(tmp_path):
    template = _make_control_template(tmp_path / "controls.docx")
    spec = build_document_spec_from_path(str(template))
    field = spec["controls"]["fields"][-1]
    analysis = build_analysis(str(template), "GENERATE", spec=spec)
    field_evidence = next(
        item for item in analysis["evidence"]
        if item["property"] == "field" and item["object_id"] == field["field_id"]
    )
    base = {
        "schema_version": "1.0",
        "kind": "TemplateSemanticSupplement",
        "supplement_id": "SUP_TEST_FIELD_001",
        "template_sha256": _sha256(template),
        "fields": [
            {
                "evidence_id": field_evidence["evidence_id"],
                "values": {"editable": True},
            }
        ],
    }
    bad_sha = dict(base)
    bad_sha["template_sha256"] = "0" * 64
    bad_path = tmp_path / "bad-sha.json"
    bad_path.write_text(json.dumps(bad_sha), encoding="utf-8")
    with pytest.raises(ValueError, match="template_sha256 mismatch"):
        build_analysis(str(template), "GENERATE", supplements=[str(bad_path)])

    duplicate = dict(base)
    duplicate["fields"] = base["fields"] + base["fields"]
    duplicate_path = tmp_path / "duplicate.json"
    duplicate_path.write_text(json.dumps(duplicate), encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate semantic supplement declaration"):
        build_analysis(str(template), "GENERATE", supplements=[str(duplicate_path)])


def _control_plan(spec, field):
    return {
        "schema_version": "4.0",
        "task_id": "TASK_TEST_0001",
        "template_id": spec["template"]["template_id"],
        "mode": "STRICT",
        "baseline": {
            "template_sha256": spec["template"]["template_sha256"],
            "spec_schema_version": "4.0",
            "fingerprint_id": spec["fingerprint_ref"]["fingerprint_id"],
            "allowed_slot_ids": [],
            "allowed_control_ids": [field["field_id"]],
        },
        "operations": [
            {
                "op_id": "OP_001",
                "sequence": 1,
                "type": "edit_field",
                "field_id": field["field_id"],
                "target": {"location_id": field["location_id"]},
                "source_ref": "USER_INPUT",
                "policy": "STRICT",
                "preconditions": ["template_sha_match"],
                "instruction": "PAGE \\* ARABIC",
                "cached_result": "9",
            }
        ],
        "global_policy": {
            "allow_structure_change": False,
            "deny_operations": [],
            "styles": "DENY",
            "page_setup": "DENY",
            "update_fields_on_open": True,
        },
    }


def test_fill_plan_control_operations_and_execution(tmp_path):
    template = _make_control_template(tmp_path / "controls.docx")
    spec = build_document_spec_from_path(str(template))
    field = spec["controls"]["fields"][-1]
    plan = _control_plan(spec, field)
    report = validate_fill_plan(plan, spec)
    assert report["passed"], report

    stage = tmp_path / "stage.docx"
    stage.write_bytes(template.read_bytes())
    document = docx.Document(stage)
    paragraphs = {
        context["location_id"]: context["paragraph"]
        for context in iter_all_document_paragraphs_with_Wait_context(document)
    }
    operation = plan["operations"][0]
    commands, descriptors, fallback = _officecli_control_plan(
        [operation], spec, {}, paragraphs
    )
    assert fallback is None
    before = _snapshot_controls(stage)
    results = {"OP_001": {"status": "PENDING"}}
    errors, abort = _control_operation_batch(
        str(template),
        str(stage),
        commands,
        [operation],
        descriptors,
        results,
        FillLedger(task_id="TASK_TEST_0001"),
        update_fields_on_open=True,
    )
    assert errors == []
    assert abort is None
    assert results["OP_001"]["status"] == "SUCCESS"
    after = _snapshot_controls(stage)
    assert _verify_control_snapshot(before, after, [operation], spec)["passed"]
    assert _verify_update_fields_on_open(str(stage))

    updated = build_document_spec_from_path(str(stage))
    edited = next(
        item for item in updated["controls"]["fields"]
        if item["location_id"] == field["location_id"]
    )
    assert "ARABIC" in edited["instruction"]
    assert edited["cached_result"] == "9"


def test_edit_sdt_text_requires_explicit_field_loss(tmp_path):
    template = _make_control_template(tmp_path / "controls.docx")
    spec = build_document_spec_from_path(str(template))
    sdt = spec["controls"]["sdts"][0]
    plan = _control_plan(spec, spec["controls"]["fields"][-1])
    plan["baseline"]["allowed_control_ids"] = [sdt["sdt_id"]]
    plan["operations"] = [
        {
            "op_id": "OP_001",
            "sequence": 1,
            "type": "edit_sdt",
            "sdt_id": sdt["sdt_id"],
            "target": {"location_id": sdt["location_id"]},
            "source_ref": "USER_INPUT",
            "policy": "STRICT",
            "preconditions": ["template_sha_match"],
            "control": {"text": "替换文本"},
        }
    ]
    report = validate_fill_plan(plan, spec)
    assert not report["passed"]
    assert any(
        "allow_field_loss=true" in item["detail"] for item in report["errors"]
    )

    plan["operations"][0]["allow_field_loss"] = True
    report = validate_fill_plan(plan, spec)
    assert report["passed"], report
