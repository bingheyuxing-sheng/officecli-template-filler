# -*- coding: utf-8 -*-
"""
v3.5 M3 — Excel template understanding (.xlsx / .xlsm).

`analyze_template.py` only understands Word, so Excel inputs used to fall through to an
empty spec. This module gives Excel the same first-class analysis: sheets, structure,
formulas, placeholders and macro state.
"""

from __future__ import annotations

from typing import Any, Dict, List

import openpyxl

from .ooxml_utils import TOKEN_PATTERN


def extract_excel_spec(file_path: str) -> Dict[str, Any]:
    """Describe an Excel template well enough to plan a fill without opening it twice."""
    is_xlsm = file_path.lower().endswith(".xlsm")
    workbook = openpyxl.load_workbook(
        file_path,
        data_only=False,
        keep_vba=is_xlsm,
        keep_links=True,
    )

    sheets: List[Dict[str, Any]] = []
    all_tokens: List[str] = []
    formula_count = 0
    try:
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

            formula_count += formula_cells
            all_tokens.extend(tokens)
            sheets.append({
                "name": worksheet.title,
                "max_row": worksheet.max_row,
                "max_column": worksheet.max_column,
                "merged_ranges": [str(item) for item in worksheet.merged_cells.ranges],
                "formula_cells": formula_cells,
                "formula_samples": formula_samples,
                "placeholder_tokens": sorted(set(tokens)),
                "data_validation_count": len(worksheet.data_validations.dataValidation),
                "image_count": len(getattr(worksheet, "_images", []) or []),
            })
    finally:
        workbook.close()

    unique_tokens = sorted(set(all_tokens))
    has_structure = any(item["merged_ranges"] or item["data_validation_count"] for item in sheets)
    return {
        "file_path": file_path,
        "file_type": "xlsm" if is_xlsm else "xlsx",
        "macro_enabled": is_xlsm,
        "sheet_count": len(sheets),
        "sheets": sheets,
        "formula_count": formula_count,
        "placeholder_tokens": unique_tokens,
        "placeholder_count": len(unique_tokens),
        "compatibility": {
            "level": "L4" if is_xlsm else ("L2" if has_structure else "L1"),
            "macro_enabled": is_xlsm,
            "notes": (
                ["Macro-enabled workbook: object preflight is required before generating."]
                if is_xlsm
                else []
            ),
        },
    }
