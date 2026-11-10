# -*- coding: utf-8 -*-
"""REPLICA size QA compares each paragraph with its own template counterpart."""

from __future__ import annotations

import docx
from docx.shared import Pt

from engine.qa_engine import _document_size_inventory, audit_format_and_text_qa


def _template(path):
    document = docx.Document()
    title = document.add_paragraph()
    title.add_run("Title").font.size = Pt(36)
    body = document.add_paragraph()
    body.add_run("Body ").font.size = Pt(14)
    body.add_run("value").font.size = Pt(14)
    note = document.add_paragraph()
    note.add_run("Note").font.size = Pt(20)
    document.save(str(path))


def _audit(output, template):
    report = audit_format_and_text_qa(
        docx.Document(str(output)),
        docx_path=str(output),
        reference_docx_path=str(template),
        raise_on_failure=False,
        comparison_profile="REPLICA",
    )
    return report["size_anomalies"]


def test_matched_direct_formatted_sizes_do_not_raise_false_anomalies(tmp_path):
    template = tmp_path / "template.docx"
    output = tmp_path / "output.docx"
    _template(template)

    document = docx.Document(str(template))
    document.paragraphs[1].runs[1].text = "filled"
    document.save(str(output))

    assert _audit(output, template) == []


def test_matched_paragraph_reports_a_size_borrowed_from_elsewhere(tmp_path):
    template = tmp_path / "template.docx"
    output = tmp_path / "output.docx"
    _template(template)

    document = docx.Document(str(template))
    document.paragraphs[0].runs[0].font.size = Pt(20)
    document.save(str(output))

    anomalies = _audit(output, template)
    assert any(item[0] == "body_p" and item[1] == 0 for item in anomalies), anomalies


def test_table_size_inventory_keeps_every_cell_across_runs(tmp_path):
    template = tmp_path / "inventory.docx"
    document = docx.Document()
    table = document.add_table(rows=12, cols=6)
    for row in table.rows:
        for cell in row.cells:
            cell.paragraphs[0].add_run("cell").font.size = Pt(11)
    document.save(str(template))

    inventories = [
        _document_size_inventory(docx.Document(str(template)))
        for _ in range(20)
    ]
    assert all("22" in inventory for inventory in inventories)
    assert {tuple(sorted(item, key=int)) for item in inventories} == {("22",)}
