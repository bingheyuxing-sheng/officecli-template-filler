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
from openpyxl.utils.cell import coordinate_to_tuple, range_boundaries

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


def payload_cells(payload: Mapping[str, Any]) -> Any:
    """Return the direct cell plan from a payload, accepting both key spellings."""
    cells = payload.get("cells")
    if cells is None:
        cells = payload.get("cell_plan")
    return cells


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


def _cell_entries(cell_plan: Any) -> Tuple[List[Dict[str, Any]], List[Dict[str, str]]]:
    """Normalise both accepted cell-plan shapes into ``{sheet, cell, value, type}``."""
    entries: List[Dict[str, Any]] = []
    errors: List[Dict[str, str]] = []
    if cell_plan is None:
        return entries, errors
    if isinstance(cell_plan, Mapping):
        for raw_key, value in cell_plan.items():
            key = str(raw_key)
            if "!" not in key:
                errors.append({
                    "code": "INVALID_CELL_REFERENCE",
                    "detail": "cell key %r must use SheetName!A1" % key,
                })
                continue
            sheet_name, coordinate = key.rsplit("!", 1)
            entries.append({"sheet": sheet_name, "cell": coordinate, "value": value})
        return entries, errors
    if not isinstance(cell_plan, list):
        return [], [{
            "code": "INVALID_CELL_PLAN",
            "detail": "cells must be a list of objects or a SheetName!A1 map",
        }]
    for index, item in enumerate(cell_plan):
        if not isinstance(item, Mapping):
            errors.append({
                "code": "INVALID_CELL_PLAN",
                "detail": "cells[%d] must be an object" % index,
            })
            continue
        sheet_name = item.get("sheet")
        coordinate = item.get("cell") or item.get("ref")
        if not sheet_name or not coordinate:
            errors.append({
                "code": "INVALID_CELL_PLAN",
                "detail": "cells[%d] must declare sheet and cell" % index,
            })
            continue
        entries.append({
            "sheet": str(sheet_name),
            "cell": str(coordinate),
            "value": item.get("value"),
            "type": item.get("type"),
        })
    return entries, errors


def _cell_value_type(value: Any, explicit: Any) -> Tuple[str, str, Any]:
    """Return ``(officecli_text, officecli_type, openpyxl_value)``."""
    if explicit is not None:
        declared = str(explicit).lower()
        if declared not in ("string", "number", "boolean"):
            raise ValueError("type %r is not string, number or boolean" % explicit)
        if declared == "number":
            try:
                number = float(value)
            except (TypeError, ValueError):
                raise ValueError("number cell received non-numeric value %r" % (value,))
            raw = int(number) if number.is_integer() else number
            return ("%g" % number), "number", raw
        if declared == "boolean":
            raw = value if isinstance(value, bool) else str(value).lower() in ("1", "true", "yes")
            return ("true" if raw else "false"), "boolean", raw
        return str("" if value is None else value), "string", str("" if value is None else value)
    if isinstance(value, bool):
        return ("true" if value else "false"), "boolean", value
    if isinstance(value, (int, float)):
        return str(value), "number", value
    text = str("" if value is None else value)
    return text, "string", text


def build_cell_commands(
    template_path: str,
    cell_plan: Any,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, str]]]:
    """Validate a direct cell plan and return ``(commands, changes, errors)``.

    Literal writes only: merged non-top-left cells and formula cells are refused
    because OfficeCLI would either drop the value or destroy the formula.
    """
    entries, errors = _cell_entries(cell_plan)
    if errors or not entries:
        return [], [], errors

    workbook = openpyxl.load_workbook(
        template_path,
        read_only=False,
        data_only=False,
        keep_links=True,
    )
    commands: List[Dict[str, Any]] = []
    changes: List[Dict[str, Any]] = []
    seen = set()
    try:
        merged_by_sheet: Dict[str, Dict[str, str]] = {}
        for sheet in workbook.worksheets:
            top_left: Dict[str, str] = {}
            for merged in sheet.merged_cells.ranges:
                min_col, min_row, max_col, max_row = range_boundaries(str(merged))
                top_left[str(merged).split(":")[0]] = str(merged)
            merged_by_sheet[sheet.title] = top_left

        for index, entry in enumerate(entries):
            sheet_name = entry["sheet"]
            coordinate = entry["cell"].replace("$", "").upper()
            if sheet_name not in workbook.sheetnames:
                errors.append({
                    "code": "UNKNOWN_SHEET",
                    "detail": "sheet %r does not exist (available: %s)"
                    % (sheet_name, ", ".join(workbook.sheetnames)),
                })
                continue
            try:
                row, column = coordinate_to_tuple(coordinate)
            except ValueError:
                errors.append({
                    "code": "INVALID_CELL_REFERENCE",
                    "detail": "cells[%d] has invalid A1 reference %r" % (index, entry["cell"]),
                })
                continue
            key = "%s!%s" % (sheet_name, coordinate)
            if key in seen:
                errors.append({
                    "code": "DUPLICATE_CELL_TARGET",
                    "detail": "cell %s is declared more than once" % key,
                })
                continue
            seen.add(key)

            sheet = workbook[sheet_name]
            cell = sheet.cell(row=row, column=column)
            current = cell.value
            if isinstance(current, str) and current.startswith("="):
                errors.append({
                    "code": "FORMULA_CELL_PROTECTED",
                    "detail": "%s contains formula %r; a literal write would destroy it"
                    % (key, current),
                })
                continue

            merged_range = None
            for candidate, merged in merged_by_sheet[sheet_name].items():
                min_col, min_row, max_col, max_row = range_boundaries(merged)
                if min_row <= row <= max_row and min_col <= column <= max_col:
                    merged_range = merged
                    if coordinate != candidate:
                        errors.append({
                            "code": "MERGED_CELL_NOT_TOP_LEFT",
                            "detail": "%s is inside merged range %s; write to %s instead"
                            % (key, merged, candidate),
                        })
                    break
            if any(
                item["code"] == "MERGED_CELL_NOT_TOP_LEFT" and item["detail"].startswith(key + " ")
                for item in errors
            ):
                continue
            try:
                value_text, value_type, raw_value = _cell_value_type(entry.get("value"), entry.get("type"))
            except ValueError as exc:
                errors.append({"code": "INVALID_CELL_VALUE", "detail": "%s: %s" % (key, exc)})
                continue
            commands.append(
                set_command(
                    "%s/%s" % (_sheet_path(sheet_name), coordinate),
                    {"value": value_text, "type": value_type},
                )
            )
            changes.append({
                "sheet": sheet_name,
                "cell": coordinate,
                "before": current,
                "after": value_text,
                "type": value_type,
                "raw": raw_value,
                "merged_range": merged_range,
            })
    finally:
        workbook.close()
    return ([] if errors else commands), ([] if errors else changes), errors


def _apply_cell_changes(workbook, changes: List[Dict[str, Any]]) -> None:
    for change in changes:
        workbook[change["sheet"]][change["cell"]] = change.get("raw", change["after"])


def _openpyxl_fill(
    template_path: str,
    output_path: str,
    replacements: Mapping[str, str],
    *,
    keep_vba: bool,
    cell_changes: Optional[List[Dict[str, Any]]] = None,
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
        if cell_changes:
            _apply_cell_changes(workbook, cell_changes)
            replaced += len(cell_changes)
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
    cell_plan: Any = None,
) -> Dict[str, Any]:
    """Fill ``template_path`` into ``output_path`` with OfficeCLI as the writer."""
    is_xlsm = template_path.lower().endswith(".xlsm")
    os.makedirs(os.path.dirname(os.path.abspath(output_path)) or ".", exist_ok=True)

    cell_commands, cell_changes, cell_errors = build_cell_commands(template_path, cell_plan)
    if cell_errors:
        raise ExcelWriterError(
            "INVALID_CELL_PLAN",
            "the direct cell plan was rejected; the template was not modified",
            {"errors": cell_errors, "cells": len(cell_errors)},
        )

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
            cell_changes=cell_changes,
        )
        return {
            "writer_backend": "openpyxl",
            "writer_fallback": reason,
            "replaced_cells": replaced,
            "commands": 0,
            "changes": [],
            "cell_changes": [],
        }

    commands, changes = build_excel_commands(template_path, replacements)
    commands.extend(cell_commands)
    changes.extend(cell_changes)
    if not commands:
        raise ExcelWriterError(
            "NO_MATCHING_PLACEHOLDERS",
            "no {{...}} or 【...】 placeholders matched the payload and no cells "
            "were declared; the template was not modified",
            {
                "template": template_path,
                "replacement_keys": sorted(str(key) for key in replacements),
                "accepted_cell_plan": [
                    {"sheet": "Sheet1", "cell": "B2", "value": "text"},
                    {"sheet": "Sheet1", "cell": "B3", "value": 42, "type": "number"},
                ],
            },
        )
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
            cell_changes=cell_changes,
        )
        return {
            "writer_backend": "openpyxl",
            "writer_fallback": "officecli batch failed",
            "replaced_cells": replaced,
            "commands": 0,
            "changes": [],
            "cell_changes": [],
        }
    finally:
        officecli_close(output_path)

    return {
        "writer_backend": "officecli",
        "writer_fallback": None,
        "replaced_cells": len(changes),
        "commands": len(commands),
        "changes": changes,
        "cell_changes": cell_changes,
    }


__all__ = [
    "ExcelWriterError",
    "build_cell_commands",
    "build_excel_commands",
    "fill_excel_template",
    "payload_cells",
    "replacement_map",
]
