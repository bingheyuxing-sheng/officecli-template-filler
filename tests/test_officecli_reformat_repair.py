# -*- coding: utf-8 -*-
"""REFORMAT and REPAIR execute their mutations through OfficeCLI."""

from __future__ import annotations

import docx
import pytest
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import parse_xml
from docx.shared import Cm, Pt

from engine.officecli_commands import (
    section_setup_commands,
    table_format_commands,
)
from engine.officecli_runtime import OfficecliError, OfficecliRuntime
from engine.reformat_engine import build_reformat_plan, execute_reformat_plan
from engine.repair_engine import build_repair_plan, execute_repair_plan


def _require_officecli() -> None:
    try:
        OfficecliRuntime().preflight()
    except OfficecliError as exc:
        pytest.skip("officecli is not runnable here: {}".format(exc))


def test_section_setup_maps_emu_to_twips_and_orientation():
    commands = section_setup_commands(
        "/section[2]",
        {
            "page_width": 7772400,
            "page_height": 10058400,
            "orientation": 1,
            "top_margin": 914400,
            "bottom_margin": 914400,
            "left_margin": 1143000,
            "right_margin": 1143000,
            "header_distance": 457200,
            "footer_distance": 457200,
        },
    )
    props = commands[0]["props"]
    assert props["pageWidth"] == 12240
    assert props["pageHeight"] == 15840
    assert props["orientation"] == "landscape"
    assert props["marginTop"] == 1440


def test_table_format_commands_address_table_row_and_cell_paths():
    document = docx.Document()
    table = document.add_table(rows=1, cols=2)
    table.cell(0, 0).text = "A"
    table.cell(0, 1).text = "B"
    table.style = "Table Grid"
    table.cell(0, 0)._tc.get_or_add_tcPr().append(
        parse_xml(
            '<w:shd xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
            'w:val="clear" w:fill="FFFF00"/>'
        )
    )

    commands = table_format_commands("/body/tbl[1]", table, table)
    paths = {command["path"] for command in commands}
    assert "/body/tbl[1]" in paths
    assert "/body/tbl[1]/tr[1]/tc[1]" in paths
    cell = next(
        command
        for command in commands
        if command["path"] == "/body/tbl[1]/tr[1]/tc[1]"
    )
    assert cell["props"]["fill"] == "FFFF00"


def _paragraph_document(path, *, alignment, size, text="Body text"):
    document = docx.Document()
    paragraph = document.add_paragraph(text)
    paragraph.alignment = alignment
    run = paragraph.runs[0]
    run.font.size = Pt(size)
    document.save(str(path))


def test_live_reformat_applies_tracked_paragraph_format(tmp_path, monkeypatch):
    _require_officecli()
    monkeypatch.setattr(
        "template_gate.validator.require_confirmed_gate",
        lambda *args, **kwargs: None,
    )
    reference = tmp_path / "reference.docx"
    target = tmp_path / "target.docx"
    output = tmp_path / "formatted.docx"
    _paragraph_document(reference, alignment=WD_ALIGN_PARAGRAPH.CENTER, size=14)
    _paragraph_document(target, alignment=WD_ALIGN_PARAGRAPH.LEFT, size=11)

    plan = build_reformat_plan(str(reference), str(target))
    assert plan["actions"], plan
    result = execute_reformat_plan(plan, str(output), author="Tester")
    assert result["writer_backend"] == "officecli"
    assert result["applied_actions"] >= 1

    rendered = docx.Document(str(output))
    assert rendered.paragraphs[0].text == "Body text"
    assert rendered.paragraphs[0].alignment == WD_ALIGN_PARAGRAPH.CENTER
    assert rendered.paragraphs[0].runs[0].font.size == Pt(14)

    from engine.review_engine import audit_review_integrity, list_revisions

    revisions = list_revisions(str(output), include_format=True)
    assert any(item["kind"] == "format" for item in revisions)
    assert audit_review_integrity(str(output))["track_changes_enabled"] is True


def test_live_repair_restores_paragraph_and_section_format(tmp_path, monkeypatch):
    _require_officecli()
    monkeypatch.setattr(
        "template_gate.validator.require_confirmed_gate",
        lambda *args, **kwargs: None,
    )
    reference = tmp_path / "reference.docx"
    broken = tmp_path / "broken.docx"
    output = tmp_path / "repaired.docx"

    ref_doc = docx.Document()
    ref_p = ref_doc.add_paragraph("Body text")
    ref_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    ref_p.runs[0].font.size = Pt(14)
    ref_doc.sections[0].left_margin = Cm(3)
    ref_doc.save(str(reference))

    brk_doc = docx.Document()
    brk_p = brk_doc.add_paragraph("Body text")
    brk_p.alignment = WD_ALIGN_PARAGRAPH.LEFT
    brk_p.runs[0].font.size = Pt(10)
    brk_doc.sections[0].left_margin = Cm(1)
    brk_doc.save(str(broken))

    plan = build_repair_plan(str(reference), str(broken))
    assert any(
        action["action_type"] == "SYNC_PARAGRAPH_FORMAT"
        for action in plan["actions"]
    )
    result = execute_repair_plan(plan, str(output))
    assert result["writer_backend"] == "officecli"
    assert result["hygiene_backend"] == "python-ooxml"

    rendered = docx.Document(str(output))
    assert rendered.paragraphs[0].text == "Body text"
    assert rendered.paragraphs[0].alignment == WD_ALIGN_PARAGRAPH.CENTER
    assert rendered.paragraphs[0].runs[0].font.size == Pt(14)
    assert abs(rendered.sections[0].left_margin - Cm(3)) <= 1000
