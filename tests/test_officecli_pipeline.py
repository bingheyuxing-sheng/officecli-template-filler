# -*- coding: utf-8 -*-
"""End-to-end: gate -> plans -> OfficeCLI batch -> QA -> published DOCX."""

from __future__ import annotations

import docx
import pytest

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
