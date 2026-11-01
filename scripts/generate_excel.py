#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CLI entrypoint: EXCEL_GENERATE mode (v3.2).

Fills an .xlsx template from a JSON payload without touching formulas or cell styles.
This exists so `EXCEL_GENERATE` no longer routes into the Word-only generator.

Usage:
    python scripts/generate_excel.py --template <template.xlsx> --payload <payload.json> --out <output.xlsx>

Payload shape:
    {"replacements": {"project": "示例项目", "leader": "张三"}, ...any extra keys...}
"""
from __future__ import annotations

import argparse
import json
import os
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

import openpyxl

from engine import audit_excel_formula_and_style_qa, install_auto_cleanup


def _replacement_map(payload: dict) -> dict:
    nested = payload.get("replacements")
    if isinstance(nested, dict):
        return {str(k): str(v) for k, v in nested.items()}
    return {str(k): str(v) for k, v in payload.items() if not isinstance(v, (dict, list))}


def _apply(cell, replacements: dict) -> bool:
    value = cell.value
    if not isinstance(value, str) or value.startswith("="):
        return False
    updated = value
    for key, replacement in replacements.items():
        updated = updated.replace("{{" + key + "}}", replacement)
        updated = updated.replace("【" + key + "】", replacement)
    if updated == value:
        return False
    cell.value = updated
    return True


def main() -> int:
    install_auto_cleanup()
    parser = argparse.ArgumentParser(description="Fill an Excel template non-destructively.")
    parser.add_argument("--template", required=True, help="Input .xlsx/.xlsm template path")
    parser.add_argument("--data", "--payload", dest="data", required=True, help="JSON payload path")
    parser.add_argument("--out", "--output", dest="out", required=True, help="Output .xlsx path")
    args = parser.parse_args()

    with open(args.data, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    replacements = _replacement_map(payload)

    is_xlsm = args.template.lower().endswith(".xlsm")
    workbook = openpyxl.load_workbook(
        args.template,
        keep_vba=is_xlsm,
        keep_links=True,
        data_only=False,
    )
    replaced = 0
    for sheet in workbook.worksheets:
        for row in sheet.iter_rows():
            for cell in row:
                if _apply(cell, replacements):
                    replaced += 1

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    if is_xlsm and not args.out.lower().endswith(".xlsm"):
        # An .xlsx container cannot hold the macro content type: silently saving
        # one would drop the VBA project, so force the .xlsm extension.
        base = args.out[:-5] if args.out.lower().endswith(".xlsx") else args.out
        args.out = base + ".xlsm"
    workbook.save(args.out)

    # QA must compare the OUTPUT against the ORIGINAL TEMPLATE — comparing the
    # output with itself proves nothing about formula or style preservation.
    qa_report = audit_excel_formula_and_style_qa(
        template_path=args.template,
        output_path=args.out,
    )
    print(json.dumps({
        "output": args.out,
        "template": args.template,
        "keep_vba": is_xlsm,
        "replaced_cells": replaced,
        "qa_passed": qa_report["passed"],
        "qa": qa_report,
    }, ensure_ascii=False, indent=2))
    return 0 if qa_report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
