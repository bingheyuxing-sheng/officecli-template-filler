# -*- coding: utf-8 -*-
"""EXCEL_GENERATE fills cells through OfficeCLI without touching formulas/styles."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import openpyxl
import pytest
from openpyxl.styles import Font, PatternFill

from engine.excel_engine import recalculate_and_verify_excel_formulas
from engine.excel_writer import (
    ExcelWriterError,
    build_cell_commands,
    build_excel_commands,
    fill_excel_template,
)
from engine.officecli_runtime import OfficecliError, OfficecliRuntime

ROOT = Path(__file__).resolve().parents[1]


def _require_officecli() -> None:
    try:
        OfficecliRuntime().preflight()
    except OfficecliError as exc:
        pytest.skip("officecli is not runnable here: {}".format(exc))


def _template(path):
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Report"
    sheet["A1"] = "Project: {{project}}"
    sheet["A1"].font = Font(bold=True, size=14)
    sheet["A1"].fill = PatternFill("solid", fgColor="FFFF00")
    sheet["B1"] = "=SUM(B2:B3)"
    sheet["A2"] = "【owner】"
    sheet["A2"].font = Font(italic=True)
    sheet["B2"] = 1
    sheet["B3"] = 2
    workbook.save(path)
    workbook.close()


def test_build_commands_skips_formulas_and_keeps_text_type(tmp_path):
    template = tmp_path / "template.xlsx"
    _template(template)
    commands, changes = build_excel_commands(
        str(template), {"project": "Apollo", "owner": "Alice"}
    )
    assert [item["path"] for item in commands] == ["/Report/A1", "/Report/A2"]
    assert all(item["props"]["type"] == "string" for item in commands)
    assert {item["cell"] for item in changes} == {"A1", "A2"}


def test_live_excel_fill_preserves_formula_and_style(tmp_path):
    _require_officecli()
    template = tmp_path / "template.xlsx"
    output = tmp_path / "output.xlsx"
    _template(template)

    result = fill_excel_template(
        str(template),
        str(output),
        {"project": "Apollo", "owner": "Alice"},
    )
    assert result["writer_backend"] == "officecli"
    assert result["writer_fallback"] is None
    assert result["replaced_cells"] == 2

    rendered = openpyxl.load_workbook(str(output), data_only=False)
    sheet = rendered["Report"]
    assert sheet["A1"].value == "Project: Apollo"
    assert sheet["A2"].value == "Alice"
    assert sheet["B1"].value == "=SUM(B2:B3)"
    assert sheet["A1"].font.bold is True
    assert sheet["A1"].font.size == 14
    assert sheet["A1"].fill.fgColor.rgb in ("FFFFFF00", "00FFFF00")
    rendered.close()


def test_formula_evaluator_supports_arithmetic_inside_sum(tmp_path):
    template = tmp_path / "formula.xlsx"
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet["A1"] = 2
    sheet["A2"] = 3
    sheet["A3"] = 5
    sheet["A4"] = "=SUM(A1+A2+A3)"
    sheet["A5"] = "=A4+1"
    workbook.save(template)
    workbook.close()

    report = recalculate_and_verify_excel_formulas(str(template))
    assert report["formula_errors"] == []
    assert report["formula_status"]["Sheet!A4"] == "VERIFIED"
    assert report["formula_status"]["Sheet!A5"] == "VERIFIED"


def test_fill_rejects_a_template_without_matching_tokens(tmp_path, monkeypatch):
    template = tmp_path / "plain.xlsx"
    output = tmp_path / "output.xlsx"
    workbook = openpyxl.Workbook()
    workbook.active["A1"] = "Plain text, not a token"
    workbook.save(template)
    workbook.close()
    monkeypatch.setattr("engine.excel_writer.officecli_available", lambda: True)

    with pytest.raises(ExcelWriterError) as excinfo:
        fill_excel_template(str(template), str(output), {"project": "Apollo"})
    assert excinfo.value.code == "NO_MATCHING_PLACEHOLDERS"
    assert excinfo.value.details["accepted_cell_plan"]
    assert not output.exists()


def _cell_template(path):
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Report"
    sheet.merge_cells("A1:B1")
    sheet["A1"] = "Quarterly report"
    sheet["A1"].font = Font(bold=True, size=14)
    sheet["B2"] = "=SUM(B3:B4)"
    sheet["B3"] = 1
    sheet["B4"] = 2
    sheet["C2"] = 0
    sheet["C2"].font = Font(italic=True, size=11)
    sheet["C2"].number_format = "0.00"
    workbook.save(path)
    workbook.close()


def test_build_cell_commands_accepts_list_and_map(tmp_path):
    template = tmp_path / "template.xlsx"
    _cell_template(template)

    commands, changes, errors = build_cell_commands(
        str(template),
        [
            {"sheet": "Report", "cell": "A1", "value": "Title"},
            {"sheet": "Report", "cell": "C2", "value": 7, "type": "number"},
        ],
    )
    assert errors == []
    assert [item["path"] for item in commands] == ["/Report/A1", "/Report/C2"]
    assert commands[0]["props"] == {"value": "Title", "type": "string"}
    assert commands[1]["props"] == {"value": "7", "type": "number"}
    assert [item["raw"] for item in changes] == ["Title", 7]

    map_commands, map_changes, map_errors = build_cell_commands(
        str(template), {"Report!A1": "Title", "Report!C2": 7}
    )
    assert map_errors == []
    assert [item["path"] for item in map_commands] == ["/Report/A1", "/Report/C2"]
    assert [item["raw"] for item in map_changes] == ["Title", 7]


def test_build_cell_commands_rejects_merged_non_top_left(tmp_path):
    template = tmp_path / "template.xlsx"
    _cell_template(template)

    commands, changes, errors = build_cell_commands(
        str(template), [{"sheet": "Report", "cell": "B1", "value": "x"}]
    )
    assert commands == []
    assert changes == []
    assert errors[0]["code"] == "MERGED_CELL_NOT_TOP_LEFT"
    assert "A1" in errors[0]["detail"]


def test_build_cell_commands_rejects_formula_overwrite(tmp_path):
    template = tmp_path / "template.xlsx"
    _cell_template(template)

    commands, changes, errors = build_cell_commands(
        str(template), [{"sheet": "Report", "cell": "B2", "value": 99}]
    )
    assert commands == []
    assert errors[0]["code"] == "FORMULA_CELL_PROTECTED"
    assert "=SUM(B3:B4)" in errors[0]["detail"]


def test_build_cell_commands_rejects_unknown_sheet_and_bad_values(tmp_path):
    template = tmp_path / "template.xlsx"
    _cell_template(template)

    _, _, errors = build_cell_commands(
        str(template),
        [
            {"sheet": "Missing", "cell": "A1", "value": "x"},
            {"sheet": "Report", "cell": "C3", "value": "abc", "type": "number"},
            {"sheet": "Report", "cell": "C3", "value": "x"},
            {"sheet": "Report", "cell": "C3", "value": "y"},
        ],
    )
    codes = [item["code"] for item in errors]
    assert "UNKNOWN_SHEET" in codes
    assert "INVALID_CELL_VALUE" in codes
    assert "DUPLICATE_CELL_TARGET" in codes


def test_live_cell_fill_preserves_formula_style_and_merge(tmp_path):
    _require_officecli()
    template = tmp_path / "template.xlsx"
    output = tmp_path / "output.xlsx"
    _cell_template(template)

    result = fill_excel_template(
        str(template),
        str(output),
        {},
        cell_plan=[
            {"sheet": "Report", "cell": "A1", "value": "Filled title"},
            {"sheet": "Report", "cell": "C2", "value": 7, "type": "number"},
        ],
    )
    assert result["writer_backend"] == "officecli"
    assert result["replaced_cells"] == 2

    rendered = openpyxl.load_workbook(str(output), data_only=False)
    sheet = rendered["Report"]
    assert sheet["A1"].value == "Filled title"
    assert sheet["C2"].value == 7
    assert sheet["B2"].value == "=SUM(B3:B4)"
    assert str(sorted(sheet.merged_cells.ranges)[0]) == "A1:B1"
    assert sheet["C2"].font.italic is True
    assert sheet["C2"].number_format == "0.00"
    rendered.close()


def test_cell_plan_openpyxl_fallback_keeps_numeric_type(tmp_path, monkeypatch):
    template = tmp_path / "template.xlsx"
    output = tmp_path / "output.xlsx"
    _cell_template(template)
    monkeypatch.setattr("engine.excel_writer.officecli_available", lambda: False)

    result = fill_excel_template(
        str(template),
        str(output),
        {},
        cell_plan=[
            {"sheet": "Report", "cell": "A1", "value": "Fallback title"},
            {"sheet": "Report", "cell": "C2", "value": 7, "type": "number"},
        ],
        allow_writer_fallback=True,
    )
    assert result["writer_backend"] == "openpyxl"
    rendered = openpyxl.load_workbook(str(output), data_only=False)
    assert rendered["Report"]["A1"].value == "Fallback title"
    assert rendered["Report"]["C2"].value == 7
    assert rendered["Report"]["B2"].value == "=SUM(B3:B4)"
    rendered.close()


def test_generate_excel_cli_writes_cells_without_placeholders(tmp_path):
    _require_officecli()
    template = tmp_path / "template.xlsx"
    output = tmp_path / "output.xlsx"
    payload = tmp_path / "payload.json"
    _cell_template(template)
    payload.write_text(
        json.dumps(
            {"cells": [{"sheet": "Report", "cell": "A1", "value": "CLI title"}]},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "generate_excel.py"),
            "--template",
            str(template),
            "--payload",
            str(payload),
            "--out",
            str(output),
        ],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert output.exists()
    rendered = openpyxl.load_workbook(str(output))
    assert rendered["Report"]["A1"].value == "CLI title"
    rendered.close()


def test_generate_excel_cli_rejects_invalid_cell_plan(tmp_path):
    template = tmp_path / "template.xlsx"
    output = tmp_path / "output.xlsx"
    payload = tmp_path / "payload.json"
    _cell_template(template)
    payload.write_text(
        json.dumps({"cells": [{"sheet": "Report", "cell": "B2", "value": 9}]}),
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "generate_excel.py"),
            "--template",
            str(template),
            "--payload",
            str(payload),
            "--out",
            str(output),
        ],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
    )
    assert completed.returncode == 2
    assert not output.exists()
    body = json.loads(completed.stdout)
    assert body["error"] == "INVALID_CELL_PLAN"
    assert body["next_action"] == "FIX_CELL_PLAN"
    assert body["details"]["errors"][0]["code"] == "FORMULA_CELL_PROTECTED"
