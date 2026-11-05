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
from engine.package_guard import check_package, load_limits


def main() -> int:
    install_auto_cleanup()
    parser = argparse.ArgumentParser(description="Analyze an Excel template and output its structural spec.")
    parser.add_argument("template", nargs="?", default="", help="Path to .xlsx/.xlsm template")
    parser.add_argument("--input", dest="input_path", default="", help="Alias for the positional template path")
    parser.add_argument("--out", "--output", dest="out", default="", help="Optional output JSON path")
    args = parser.parse_args()

    template_path = args.input_path or args.template
    if not template_path:
        parser.error("a template path is required (positional or --input)")
    if not template_path.lower().endswith((".xlsx", ".xlsm")):
        parser.error("analyze_excel_template.py only accepts .xlsx/.xlsm; use analyze_template.py for Word")

    verdict = check_package(template_path, load_limits())
    if not verdict["ok"]:
        print(json.dumps({"error": verdict["code"], "package_guard": verdict}, ensure_ascii=False))
        return 2

    spec = extract_excel_spec(template_path)
    payload = json.dumps(spec, ensure_ascii=False, indent=2)
    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as handle:
            handle.write(payload)
        print(f"Saved Excel template analysis to: {args.out}")
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
