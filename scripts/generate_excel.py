#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CLI entrypoint: EXCEL_GENERATE mode (v3.2).

Fills an .xlsx template from a JSON payload without touching formulas or cell styles.
The workbook is staged in a sibling temp file and only published after QA passes.

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

from engine import (
    DocumentTransaction,
    TransactionAborted,
    TransactionPreflightError,
    audit_excel_formula_and_style_qa,
    inspect_excel_objects,
    install_auto_cleanup,
)


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
    parser.add_argument(
        "--allow-object-loss",
        action="store_true",
        help="Proceed even when the template contains parts openpyxl cannot preserve (ActiveX, pivots, slicers, ...)",
    )
    args = parser.parse_args()

    with open(args.data, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    replacements = _replacement_map(payload)

    is_xlsm = args.template.lower().endswith(".xlsm")
    if is_xlsm and not args.out.lower().endswith(".xlsm"):
        # An .xlsx container cannot hold the macro content type: silently saving
        # one would drop the VBA project, so force the .xlsm extension.
        base = args.out[:-5] if args.out.lower().endswith(".xlsx") else args.out
        args.out = base + ".xlsm"

    object_preflight = inspect_excel_objects(args.template)
    if object_preflight["object_loss_risk"] and not args.allow_object_loss:
        print(json.dumps({
            "output": args.out,
            "template": args.template,
            "error": "OBJECT_LOSS_RISK",
            "objects": object_preflight["loss_risk_objects"],
            "hint": "openpyxl cannot preserve these parts; re-run with --allow-object-loss to accept the loss",
        }, ensure_ascii=False, indent=2))
        return 3

    replaced = 0
    qa_report = None
    tx = DocumentTransaction(args.template, args.out, task_mode="EXCEL_GENERATE")

    try:
        with tx:
            workbook = openpyxl.load_workbook(
                args.template,
                keep_vba=is_xlsm,
                keep_links=True,
                data_only=False,
            )
            for sheet in workbook.worksheets:
                for row in sheet.iter_rows():
                    for cell in row:
                        if _apply(cell, replacements):
                            replaced += 1

            workbook.save(tx.stage())
            workbook.close()

            # QA must compare the OUTPUT against the ORIGINAL TEMPLATE — comparing the
            # output with itself proves nothing about formula or style preservation.
            qa_report = audit_excel_formula_and_style_qa(
                template_path=args.template,
                output_path=tx.temp_path,
            )
            tx.record_qa(qa_report)
            tx.commit()
    except TransactionPreflightError as exc:
        print(json.dumps({
            "output": args.out,
            "template": args.template,
            "error": str(exc),
            "transaction": tx.record(),
        }, ensure_ascii=False, indent=2))
        return 2
    except TransactionAborted as exc:
        print(json.dumps({
            "output": args.out,
            "template": args.template,
            "keep_vba": is_xlsm,
            "replaced_cells": replaced,
            "error": str(exc),
            "qa_status": tx.qa_status,
            "qa": qa_report or {},
            "transaction": tx.record(),
        }, ensure_ascii=False, indent=2))
        return 1

    print(json.dumps({
        "output": args.out,
        "template": args.template,
        "keep_vba": is_xlsm,
        "replaced_cells": replaced,
        "object_preflight": object_preflight,
        "qa_passed": tx.qa_status == "PASSED",
        "qa_status": tx.qa_status,
        "qa": qa_report,
        "transaction": tx.record(),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
