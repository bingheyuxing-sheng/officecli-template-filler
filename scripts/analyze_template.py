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
from engine.cli_io import configure_stdio
from engine.package_guard import check_package, load_limits

SUPPORTED_WORD_SUFFIXES = (".docx", ".docm")


def _package_reject(path: str) -> "dict | None":
    """W3-7: refuse oversized/hostile containers before any parser runs."""
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
        "next_action": "PROVIDE_VALID_DOCX_OR_DOCM",
        "package_guard": verdict,
    }


def main() -> int:
    configure_stdio()
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
    if not template_path.lower().endswith(SUPPORTED_WORD_SUFFIXES):
        print(
            json.dumps(
                {
                    "error": "UNSUPPORTED_CONTAINER",
                    "message": (
                        "analyze_template.py only accepts .docx/.docm; "
                        "use analyze_excel_template.py for .xlsx/.xlsm"
                    ),
                    "input": template_path,
                    "supported": list(SUPPORTED_WORD_SUFFIXES),
                },
                ensure_ascii=False,
            )
        )
        return 2

    rejected = _package_reject(template_path)
    if rejected:
        print(json.dumps(rejected, ensure_ascii=False))
        return 2

    if args.spec_version == 4:
        from template_intelligence import build_document_spec_from_path

        try:
            payload = build_document_spec_from_path(template_path)
        except Exception as exc:
            print(
                json.dumps(
                    {
                        "error": "DOCUMENT_UNREADABLE",
                        "message": "{}: {}".format(type(exc).__name__, exc),
                        "input": template_path,
                    },
                    ensure_ascii=False,
                )
            )
            return 2
        errors = payload.get("errors") if isinstance(payload, dict) else None
        blocked = isinstance(errors, list) and bool(errors)
        text = json.dumps(payload, ensure_ascii=False, indent=2)
        if args.out:
            os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
            with open(args.out, "w", encoding="utf-8") as f:
                f.write(text)
            if not blocked:
                print(f"Saved template analysis to: {args.out}")
        if blocked:
            envelope = {
                "error": "DOCUMENT_SPEC_BLOCKED",
                "message": "template spec contains blocking errors",
                "input": template_path,
                "errors": errors,
                "next_action": "FIX_TEMPLATE_OR_PROVIDE_READABLE_DOCX",
            }
            if args.out:
                envelope["output"] = args.out
            else:
                envelope["spec"] = payload
            print(json.dumps(envelope, ensure_ascii=False, indent=2))
            return 2
        if not args.out:
            print(text)
        return 0

    try:
        doc = docx.Document(template_path)
        spec = extract_document_spec(doc, file_path=template_path)
    except Exception as exc:
        print(
            json.dumps(
                {
                    "error": "DOCUMENT_UNREADABLE",
                    "message": "{}: {}".format(type(exc).__name__, exc),
                    "input": template_path,
                },
                ensure_ascii=False,
            )
        )
        return 2

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
