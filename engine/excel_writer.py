# -*- coding: utf-8 -*-
"""Excel fill execution on OfficeCLI.

The template is scanned read-only (openpyxl) to decide *which* cells contain
placeholders. The mutation itself is one OfficeCLI ``batch`` of ``set`` items on
``/SheetName/A1`` paths, so formulas, styles, merged ranges and drawing parts stay
in the package.
"""

from __future__ import annotations

import os
import shutil
from typing import Any, Dict, List, Mapping, Optional, Tuple

import openpyxl

from .officecli_commands import set_command
from .officecli_runtime import OfficecliError, is_available as officecli_available
from .officecli_writer import close as officecli_close, run_batch


class ExcelWriterError(RuntimeError):
    def __init__(self, code: str, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


def replacement_map(payload: Mapping[str, Any]) -> Dict[str, str]:
    nested = payload.get("replacements")
    if isinstance(nested, dict):
        return {str(key): str(value) for key, value in nested.items()}
    return {
        str(key): str(value)
        for key, value in payload.items()
        if not isinstance(value, (dict, list))
    }


def _replace_text(value: str, replacements: Mapping[str, str]) -> str:
    updated = value
    for key, replacement in replacements.items():
        updated = updated.replace("{{" + key + "}}", replacement)
        updated = updated.replace("【" + key + "】", replacement)
    return updated


def _sheet_path(name: str) -> str:
    if any(token in name for token in ("/", "[", "]")):
        raise ExcelWriterError(
            "EXCEL_SHEET_PATH_UNSUPPORTED",
            "sheet name %r cannot be addressed by an OfficeCLI path" % name,
            {"sheet": name},
        )
    return "/" + name


def build_excel_commands(
    template_path: str,
    replacements: Mapping[str, str],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Return ``(commands, replacements)`` for a template, without mutating it."""
    workbook = openpyxl.load_workbook(
        template_path,
        read_only=True,
        data_only=False,
        keep_links=True,
    )
    commands: List[Dict[str, Any]] = []
    changes: List[Dict[str, Any]] = []
    try:
        for sheet in workbook.worksheets:
            sheet_path = _sheet_path(sheet.title)
            for row in sheet.iter_rows():
                for cell in row:
                    value = cell.value
                    if not isinstance(value, str) or value.startswith("="):
                        continue
                    updated = _replace_text(value, replacements)
                    if updated == value:
                        continue
                    commands.append(
                        set_command(
                            "%s/%s" % (sheet_path, cell.coordinate),
                            {"value": updated, "type": "string"},
                        )
                    )
                    changes.append({
                        "sheet": sheet.title,
                        "cell": cell.coordinate,
                        "before": value,
                        "after": updated,
                    })
    finally:
        workbook.close()
    return commands, changes


def _openpyxl_fill(
    template_path: str,
    output_path: str,
    replacements: Mapping[str, str],
    *,
    keep_vba: bool,
) -> int:
    workbook = openpyxl.load_workbook(
        template_path,
        keep_vba=keep_vba,
        keep_links=True,
        data_only=False,
    )
    replaced = 0
    try:
        for sheet in workbook.worksheets:
            for row in sheet.iter_rows():
                for cell in row:
                    value = cell.value
                    if not isinstance(value, str) or value.startswith("="):
                        continue
                    updated = _replace_text(value, replacements)
                    if updated != value:
                        cell.value = updated
                        replaced += 1
        workbook.save(output_path)
    finally:
        workbook.close()
    return replaced


def fill_excel_template(
    template_path: str,
    output_path: str,
    replacements: Mapping[str, str],
    *,
    allow_writer_fallback: bool = False,
) -> Dict[str, Any]:
    """Fill ``template_path`` into ``output_path`` with OfficeCLI as the writer."""
    is_xlsm = template_path.lower().endswith(".xlsm")
    os.makedirs(os.path.dirname(os.path.abspath(output_path)) or ".", exist_ok=True)

    if is_xlsm or not officecli_available():
        reason = (
            "macro-enabled workbooks are not on the OfficeCLI xlsx path"
            if is_xlsm
            else "officecli is not installed"
        )
        if not allow_writer_fallback:
            raise ExcelWriterError(
                "WRITER_UNSUPPORTED",
                reason + "; pass --allow-writer-fallback to use openpyxl",
                {"template": template_path, "xlsm": is_xlsm},
            )
        replaced = _openpyxl_fill(
            template_path,
            output_path,
            replacements,
            keep_vba=is_xlsm,
        )
        return {
            "writer_backend": "openpyxl",
            "writer_fallback": reason,
            "replaced_cells": replaced,
            "commands": 0,
            "changes": [],
        }

    commands, changes = build_excel_commands(template_path, replacements)
    shutil.copyfile(template_path, output_path)
    try:
        if commands:
            run_batch(output_path, commands)
    except OfficecliError:
        officecli_close(output_path)
        if not allow_writer_fallback:
            raise
        replaced = _openpyxl_fill(
            template_path,
            output_path,
            replacements,
            keep_vba=False,
        )
        return {
            "writer_backend": "openpyxl",
            "writer_fallback": "officecli batch failed",
            "replaced_cells": replaced,
            "commands": 0,
            "changes": [],
        }
    finally:
        officecli_close(output_path)

    return {
        "writer_backend": "officecli",
        "writer_fallback": None,
        "replaced_cells": len(changes),
        "commands": len(commands),
        "changes": changes,
    }


__all__ = [
    "ExcelWriterError",
    "build_excel_commands",
    "fill_excel_template",
    "replacement_map",
]
