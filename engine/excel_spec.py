# -*- coding: utf-8 -*-
"""
v3.5 M3 — Excel template understanding (.xlsx / .xlsm).

`analyze_template.py` only understands Word, so Excel inputs used to fall through to an
empty spec. This module gives Excel the same first-class analysis: sheets, structure,
formulas, placeholders and macro state.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List

import openpyxl

from .ooxml_utils import TOKEN_PATTERN

# Full-mode openpyxl parses drawings/charts and style-heavy workbooks; a large
# real-world workbook can take tens of seconds or hit openpyxl extension bugs
# (PageItem/Nested chart parsing). Above this size we scan read-only, which
# reads values/formulas without drawings, and disclose what was not inspected.
_FULL_SCAN_MAX_BYTES = 2 * 1024 * 1024


def _open_excel_workbook(file_path: str, is_xlsm: bool, read_only: bool):
    return openpyxl.load_workbook(
        file_path,
        data_only=False,
        keep_vba=is_xlsm,
        keep_links=True,
        read_only=read_only,
    )


def _scan_sheets(workbook) -> Dict[str, Any]:
    sheets: List[Dict[str, Any]] = []
    all_tokens: List[str] = []
    formula_count = 0
    for worksheet in workbook.worksheets:
        formula_cells = 0
        formula_samples: List[str] = []
        tokens: List[str] = []
        for row in worksheet.iter_rows():
            for cell in row:
                value = cell.value
                if not isinstance(value, str):
                    continue
                if value.startswith("="):
                    formula_cells += 1
                    if len(formula_samples) < 5:
                        formula_samples.append(f"{cell.coordinate}: {value}")
                    continue
                tokens.extend(TOKEN_PATTERN.findall(value))
        try:
            merged = [str(item) for item in worksheet.merged_cells.ranges]
        except Exception:
            merged = []
        validations = getattr(worksheet, "data_validations", None)
        try:
            validation_count = len(validations.dataValidation)
        except Exception:
            validation_count = 0
        formula_count += formula_cells
        all_tokens.extend(tokens)
        sheets.append({
            "name": worksheet.title,
            "max_row": worksheet.max_row,
            "max_column": worksheet.max_column,
            "merged_ranges": merged,
            "formula_cells": formula_cells,
            "formula_samples": formula_samples,
            "placeholder_tokens": sorted(set(tokens)),
            "data_validation_count": validation_count,
            "image_count": len(getattr(worksheet, "_images", []) or []),
        })
    return {"sheets": sheets, "tokens": all_tokens, "formula_count": formula_count}


def _error_spec(file_path: str, is_xlsm: bool, scan_mode: str, degraded: List[str],
                detail: str) -> Dict[str, Any]:
    return {
        "file_path": file_path,
        "file_type": "xlsm" if is_xlsm else "xlsx",
        "macro_enabled": is_xlsm,
        "sheet_count": 0,
        "sheets": [],
        "formula_count": 0,
        "placeholder_tokens": [],
        "placeholder_count": 0,
        "scan_mode": scan_mode,
        "degraded": degraded,
        "errors": [{"code": "EXCEL_PARSE_FAILED", "detail": detail}],
        "compatibility": {"level": "L4", "macro_enabled": is_xlsm,
                          "notes": degraded + ["Workbook could not be parsed; no fill is safe."]},
    }


def extract_excel_spec(file_path: str) -> Dict[str, Any]:
    """Describe an Excel template well enough to plan a fill without opening it twice."""
    is_xlsm = file_path.lower().endswith(".xlsm")
    degraded: List[str] = []
    scan_mode = "full"
    try:
        size = os.path.getsize(file_path)
    except OSError:
        size = 0

    workbook = None
    if size > _FULL_SCAN_MAX_BYTES:
        scan_mode = "read_only_large"
        degraded.append(
            "LARGE_WORKBOOK_READ_ONLY_SCAN: %.1f MB exceeds the %.1f MB full-scan budget; "
            "merged ranges, data validations and images were not inspected"
            % (size / (1024 * 1024), _FULL_SCAN_MAX_BYTES / (1024 * 1024))
        )
        try:
            workbook = _open_excel_workbook(file_path, is_xlsm, read_only=True)
        except Exception as exc:
            return _error_spec(file_path, is_xlsm, scan_mode, degraded,
                               "%s: %s" % (type(exc).__name__, exc))
    else:
        try:
            workbook = _open_excel_workbook(file_path, is_xlsm, read_only=False)
        except Exception as exc:
            scan_mode = "read_only_fallback"
            degraded.append(
                "FULL_SCAN_FAILED: %s: %s; reopened read-only (drawings/charts skipped)"
                % (type(exc).__name__, exc)
            )
            try:
                workbook = _open_excel_workbook(file_path, is_xlsm, read_only=True)
            except Exception as exc2:
                return _error_spec(file_path, is_xlsm, scan_mode, degraded,
                                   "%s: %s" % (type(exc2).__name__, exc2))

    try:
        scanned = _scan_sheets(workbook)
    except Exception as exc:
        return _error_spec(file_path, is_xlsm, scan_mode, degraded,
                           "%s: %s" % (type(exc).__name__, exc))
    finally:
        workbook.close()

    sheets = scanned["sheets"]
    all_tokens = scanned["tokens"]
    unique_tokens = sorted(set(all_tokens))
    has_structure = any(item["merged_ranges"] or item["data_validation_count"] for item in sheets)
    notes = (["Macro-enabled workbook: object preflight is required before generating."]
             if is_xlsm else []) + degraded
    return {
        "file_path": file_path,
        "file_type": "xlsm" if is_xlsm else "xlsx",
        "macro_enabled": is_xlsm,
        "sheet_count": len(sheets),
        "sheets": sheets,
        "formula_count": scanned["formula_count"],
        "placeholder_tokens": unique_tokens,
        "placeholder_count": len(unique_tokens),
        "scan_mode": scan_mode,
        "degraded": degraded,
        "errors": [],
        "compatibility": {
            "level": "L4" if is_xlsm else ("L2" if has_structure else "L1"),
            "macro_enabled": is_xlsm,
            "notes": notes,
        },
    }
