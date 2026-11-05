#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CLI entrypoint: Analyze template placeholders, cell capacities, and 4-tier confirmation items.
Usage:
    python scripts/analyze_template.py <template.docx> [--out analysis.json] [--spec-version 4]
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
from engine import extract_document_spec, install_auto_cleanup
from engine.package_guard import check_package, load_limits


def _quota_reject(path: str) -> "str | None":
    """W3-7: refuse oversized/hostile containers before any parser runs."""
    verdict = check_package(path, load_limits())
    if verdict["ok"]:
        return None
    return json.dumps({"error": verdict["code"], "package_guard": verdict}, ensure_ascii=False)


def main() -> int:
    install_auto_cleanup()
    parser = argparse.ArgumentParser(description="Analyze a Word template and output 4-tier confirmation analysis.")
    parser.add_argument("template", nargs="?", default="", help="Path to reference .docx template")
    parser.add_argument("--input", dest="input_path", default="", help="Alias for the positional template path")
    parser.add_argument("--out", "--output", dest="out", default="", help="Optional output JSON path")
    parser.add_argument(
        "--spec-version",
        dest="spec_version",
        type=int,
        choices=(3, 4),
        default=3,
        help="DocumentSpec version to emit: 3 (legacy CLI summary, default) or 4 (DocumentSpec 4.0)",
    )
    args = parser.parse_args()

    template_path = args.input_path or args.template
    if not template_path:
        parser.error("a template path is required (positional or --input)")

    rejected = _quota_reject(template_path)
    if rejected:
        print(rejected)
        return 2

    if args.spec_version == 4:
        from template_intelligence import build_document_spec_from_path

        payload = build_document_spec_from_path(template_path)
        text = json.dumps(payload, ensure_ascii=False, indent=2)
        if args.out:
            os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
            with open(args.out, "w", encoding="utf-8") as f:
                f.write(text)
            print(f"Saved template analysis to: {args.out}")
        else:
            print(text)
        return 0

    doc = docx.Document(template_path)
    spec = extract_document_spec(doc, file_path=template_path)

    summary = {
        "file_path": template_path,
        "compatibility": spec["compatibility"],
        "paragraphs_count": spec["paragraphs_count"],
        "candidate_hits_count": len(spec["candidate_hits"]),
        "candidate_hits": spec["candidate_hits"],
        "table_profiles": spec["table_profiles"],
        "image_profiles": spec["image_profiles"],
    }
    payload_text = json.dumps(summary, ensure_ascii=False, indent=2)
    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(payload_text)
        print(f"Saved template analysis to: {args.out}")
    else:
        print(payload_text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
