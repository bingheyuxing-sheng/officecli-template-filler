# -*- coding: utf-8 -*-
"""Legacy ``--data`` token maps execute through OfficeCLI."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import docx
import pytest
from docx.oxml import parse_xml
from docx.shared import RGBColor

from document_engine.legacy_tokens import build_legacy_token_plan
from engine.officecli_runtime import OfficecliError, OfficecliRuntime
from template_gate.analyzer import build_analysis
from template_gate.store import GateStore
from template_intelligence.spec_builder import build_document_spec_from_path

ROOT = Path(__file__).resolve().parents[1]


def _require_officecli() -> None:
    try:
        OfficecliRuntime().preflight()
    except OfficecliError as exc:
        pytest.skip("officecli is not runnable here: {}".format(exc))


def _token_template(path: Path) -> None:
    document = docx.Document()
    body = document.add_paragraph()
    body_run = body.add_run("Hello {{name}}")
    body_run.font.color.rgb = RGBColor(0xFF, 0, 0)
    table = document.add_table(rows=1, cols=1)
    table.cell(0, 0).text = "{{cell}}"
    document.sections[0].header.paragraphs[0].text = "Header {{name}}"
    document.save(str(path))


def _sdt_template(path: Path) -> None:
    document = docx.Document()
    document.add_paragraph("Body")
    sdt = parse_xml(
        '<w:sdt xmlns:w="http://schemas.openxmlformats.org/'
        'wordprocessingml/2006/main"><w:sdtContent><w:p><w:r>'
        "<w:t>{{sdt}}</w:t></w:r></w:p></w:sdtContent></w:sdt>"
    )
    document.element.body.insert(0, sdt)
    document.save(str(path))


def _confirmed_gate_record(template: Path, tmp_path: Path) -> Path:
    spec = build_document_spec_from_path(str(template))
    analysis = build_analysis(str(template), "GENERATE", spec=spec)
    store = GateStore(str(tmp_path / "gates"))
    record = store.confirm(
        analysis,
        {"quality": {"unresolved_blocking": 0}, "report_digest": "f" * 64},
        user_statement="confirmed",
    )
    path = tmp_path / "gate.json"
    path.write_text(json.dumps(record), encoding="utf-8")
    return path


def test_legacy_token_plan_maps_body_table_and_header(tmp_path):
    template = tmp_path / "template.docx"
    _token_template(template)

    plan = build_legacy_token_plan(
        str(template),
        {"{{name}}": "Alice", "{{cell}}": "42"},
        {"sec[0].header": "/header[1]"},
    )

    assert plan.unsupported == []
    assert plan.occurrences == 3
    assert {item["path"] for item in plan.commands} == {
        "/body/p[1]",
        "/body/tbl[1]/tr[1]/tc[1]/p[1]",
        "/header[1]/p[1]",
    }
    body_target = next(
        item for item in plan.affected if item["path"] == "/body/p[1]"
    )
    assert body_target["strip_red"] is True


def test_legacy_token_plan_addresses_sdt(tmp_path):
    template = tmp_path / "template.docx"
    _sdt_template(template)

    plan = build_legacy_token_plan(str(template), {"{{sdt}}": "X"})

    assert plan.unsupported == []
    assert plan.occurrences == 1
    assert [command["path"] for command in plan.commands] == [
        "/body/sdt[1]/p[1]"
    ]


def test_live_legacy_data_path_uses_officecli_and_strips_red(tmp_path):
    _require_officecli()
    template = tmp_path / "template.docx"
    _token_template(template)
    gate = _confirmed_gate_record(template, tmp_path)
    data = tmp_path / "data.json"
    data.write_text(
        json.dumps({"tokens": {"{{name}}": "Alice", "{{cell}}": "42"}}),
        encoding="utf-8",
    )
    output = tmp_path / "output.docx"

    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "generate_document.py"),
            "--template",
            str(template),
            "--data",
            str(data),
            "--out",
            str(output),
            "--gate-record",
            str(gate),
        ],
        capture_output=True,
        text=True,
        env=os.environ.copy(),
        cwd=str(ROOT),
    )
    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["writer_backend"] == "officecli"
    assert payload["replaced_occurrences"] == 3
    assert output.exists()

    rendered = docx.Document(str(output))
    assert rendered.paragraphs[0].text == "Hello Alice"
    assert rendered.tables[0].cell(0, 0).text == "42"
    assert rendered.sections[0].header.paragraphs[0].text == "Header Alice"
    assert rendered.paragraphs[0].runs[0].font.color.rgb is None


def test_legacy_data_path_explicit_python_docx_still_works(tmp_path):
    template = tmp_path / "template.docx"
    _token_template(template)
    gate = _confirmed_gate_record(template, tmp_path)
    data = tmp_path / "data.json"
    data.write_text(
        json.dumps({"tokens": {"{{name}}": "Alice", "{{cell}}": "42"}}),
        encoding="utf-8",
    )
    output = tmp_path / "output.docx"

    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "generate_document.py"),
            "--template",
            str(template),
            "--data",
            str(data),
            "--out",
            str(output),
            "--gate-record",
            str(gate),
            "--writer",
            "python-docx",
        ],
        capture_output=True,
        text=True,
        env=os.environ.copy(),
        cwd=str(ROOT),
    )
    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["writer_backend"] == "python-docx"
    assert docx.Document(str(output)).paragraphs[0].text == "Hello Alice"


def test_live_legacy_data_addresses_sdt_without_fallback(tmp_path):
    _require_officecli()
    template = tmp_path / "template.docx"
    _sdt_template(template)
    gate = _confirmed_gate_record(template, tmp_path)
    data = tmp_path / "data.json"
    data.write_text(json.dumps({"tokens": {"{{sdt}}": "X"}}), encoding="utf-8")
    output = tmp_path / "output.docx"

    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "generate_document.py"),
            "--template",
            str(template),
            "--data",
            str(data),
            "--out",
            str(output),
            "--gate-record",
            str(gate),
        ],
        capture_output=True,
        text=True,
        env=os.environ.copy(),
        cwd=str(ROOT),
    )
    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["writer_backend"] == "officecli"
    assert payload["writer_fallback"] is None
    rendered = docx.Document(str(output))
    assert "{{sdt}}" not in rendered.element.body.xml
    assert ">X<" in rendered.element.body.xml


def test_live_legacy_data_does_not_fallback_for_supported_sdt(tmp_path):
    _require_officecli()
    template = tmp_path / "template.docx"
    _sdt_template(template)
    gate = _confirmed_gate_record(template, tmp_path)
    data = tmp_path / "data.json"
    data.write_text(json.dumps({"tokens": {"{{sdt}}": "X"}}), encoding="utf-8")
    output = tmp_path / "output.docx"

    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "generate_document.py"),
            "--template",
            str(template),
            "--data",
            str(data),
            "--out",
            str(output),
            "--gate-record",
            str(gate),
            "--allow-writer-fallback",
        ],
        capture_output=True,
        text=True,
        env=os.environ.copy(),
        cwd=str(ROOT),
    )
    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["writer_backend"] == "officecli"
    assert payload["writer_fallback"] is None
    rendered = docx.Document(str(output))
    assert "{{sdt}}" not in rendered.element.body.xml
    assert ">X<" in rendered.element.body.xml
