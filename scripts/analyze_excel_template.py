#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CLI entrypoint: Analyze an Excel template (.xlsx/.xlsm) and emit its spec JSON.
Usage:
    python scripts/analyze_excel_template.py <template.xlsx> [--out spec.json]

`analyze_template.py` only handles Word; Excel inputs use this entrypoint so the agent
never has to guess which analyzer applies.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from engine import extract_excel_spec, install_auto_cleanup
from engine.cli_io import configure_stdio
from engine.package_guard import check_package, load_limits


SUPPORTED_EXCEL_SUFFIXES = (".xlsx", ".xlsm")


def _package_reject(path: str) -> "dict | None":
    verdict = check_package(path, load_limits())
    if verdict["ok"]:
        return None
    violations = verdict.get("violations") or []
    detail = "; ".join(
        str(item.get("detail") or item.get("limit"))
        for item in violations
        if isinstance(item, dict)
    )
    return {
        "error": verdict["code"],
        "message": "input package cannot be analyzed: {}".format(detail or verdict["code"]),
        "input": path,
        "next_action": "PROVIDE_VALID_XLSX_OR_XLSM",
        "package_guard": verdict,
    }


def main() -> int:
    configure_stdio()
    install_auto_cleanup()
    parser = argparse.ArgumentParser(description="Analyze an Excel template and output its structural spec.")
    parser.add_argument("template", nargs="?", default="", help="Path to .xlsx/.xlsm template")
    parser.add_argument("--input", dest="input_path", default="", help="Alias for the positional template path")
    parser.add_argument("--out", "--output", dest="out", default="", help="Optional output JSON path")
    args = parser.parse_args()

    template_path = args.input_path or args.template
    if not template_path:
        parser.error("a template path is required (positional or --input)")
    if not template_path.lower().endswith(SUPPORTED_EXCEL_SUFFIXES):
        print(
            json.dumps(
                {
                    "error": "UNSUPPORTED_CONTAINER",
                    "message": (
                        "analyze_excel_template.py only accepts .xlsx/.xlsm; "
                        "use analyze_template.py for Word"
                    ),
                    "input": template_path,
                    "supported": list(SUPPORTED_EXCEL_SUFFIXES),
                },
                ensure_ascii=False,
            )
        )
        return 2

    rejected = _package_reject(template_path)
    if rejected:
        print(json.dumps(rejected, ensure_ascii=False))
        return 2

    try:
        spec = extract_excel_spec(template_path)
    except Exception as exc:
        print(
            json.dumps(
                {
                    "error": "DOCUMENT_UNREADABLE",
                    "message": "{}: {}".format(type(exc).__name__, exc),
                    "input": template_path,
                    "next_action": "PROVIDE_VALID_XLSX_OR_XLSM",
                },
                ensure_ascii=False,
            )
        )
        return 2
    payload = json.dumps(spec, ensure_ascii=False, indent=2)
    errors = spec.get("errors") if isinstance(spec, dict) else None
    blocked = isinstance(errors, list) and bool(errors)
    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as handle:
            handle.write(payload)
        if not blocked:
            print(f"Saved Excel template analysis to: {args.out}")
    if blocked:
        envelope = {
            "error": "DOCUMENT_SPEC_BLOCKED",
            "message": "Excel template spec contains blocking errors",
            "input": template_path,
            "errors": errors,
            "next_action": "PROVIDE_VALID_XLSX_OR_XLSM",
        }
        if args.out:
            envelope["output"] = args.out
        else:
            envelope["spec"] = spec
        print(json.dumps(envelope, ensure_ascii=False, indent=2))
        return 2
    if not args.out:
        print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
