#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CLI entrypoint: Route document task & inspect template compatibility (L1-L4) + DocumentSpec.
Usage:
    python scripts/inspect_document.py <input.docx> [--intent "生成报告"] [--out spec.json]
"""

from __future__ import annotations

import argparse
import json
import os
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

import docx
from engine import route_document_task, extract_document_spec, install_auto_cleanup


def main() -> int:
    install_auto_cleanup()
    parser = argparse.ArgumentParser(description="Inspect an Office document and output DocumentSpec JSON.")
    parser.add_argument("files", nargs="*", default=[], help="Input .docx/.xlsx file path(s)")
    parser.add_argument("--inputs", nargs="+", default=[], help="Alias for the positional input file list")
    parser.add_argument("--intent", default="", help="User task intent description")
    parser.add_argument("--out", "--output", dest="out", default="", help="Optional output JSON path")
    args = parser.parse_args()

    files = args.inputs or args.files
    if not files:
        parser.error("at least one input file is required (positional or --inputs)")

    routing = route_document_task(files, user_intent=args.intent)
    result = {"routing": routing, "specs": []}

    for fpath in files:
        if fpath.lower().endswith((".docx", ".docm")) and os.path.isfile(fpath):
            doc = docx.Document(fpath)
            spec = extract_document_spec(doc, file_path=fpath)
            result["specs"].append(spec)

    payload = json.dumps(result, ensure_ascii=False, indent=2)
    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(payload)
        print(f"Saved inspection output to: {args.out}")
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
