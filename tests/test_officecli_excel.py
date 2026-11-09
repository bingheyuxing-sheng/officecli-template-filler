# -*- coding: utf-8 -*-
"""EXCEL_GENERATE fills cells through OfficeCLI without touching formulas/styles."""

from __future__ import annotations

import openpyxl
import pytest
from openpyxl.styles import Font, PatternFill

from engine.excel_writer import build_excel_commands, fill_excel_template
from engine.officecli_runtime import OfficecliError, OfficecliRuntime


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
