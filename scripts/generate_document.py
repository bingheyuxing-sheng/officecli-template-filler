#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CLI entrypoint: Generate a filled document from a template and a JSON replacement map.
Usage:
    python scripts/generate_document.py --template <template.docx> --data <data.json> --out <output.docx>
    python scripts/generate_document.py --template <template.docx> --spec <spec.json> --plan <fill_plan.json> --out <output.docx> [--mode STRICT|STANDARD] [--allow-unverified]

The output is staged in a sibling temp file and only published after QA passes.
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
from engine import (
    DocumentTransaction,
    TaskResourceGuard,
    TransactionAborted,
    TransactionPreflightError,
    LogicalParagraphView,
    iter_all_document_paragraphs_with_Wait_context,
    sanitize_ooxml_whitespace_and_pagination,
    audit_docx_package_integrity,
    audit_format_and_text_qa,
    release_office_file_locks,
    install_auto_cleanup,
)


def _run_legacy_data_path(args) -> int:
    """v3.5.9 token replacement path; behavior is unchanged."""
    with open(args.data, "r", encoding="utf-8") as f:
        data_map = json.load(f)

    tokens_map = data_map.get("tokens", data_map)
    replaced_count = 0
    package_qa = None
    qa_report = None
    tx = DocumentTransaction(args.template, args.out, task_mode="GENERATE")

    try:
        with tx:
            with TaskResourceGuard() as guard:
                doc = docx.Document(args.template)
                for ctx in iter_all_document_paragraphs_with_Wait_context(doc):
                    p_el = ctx["p_el"]
                    view = LogicalParagraphView(p_el)
                    for token, replacement in tokens_map.items():
                        if token in view.logical_text:
                            replaced_count += view.replace_all_tokens(str(token), str(replacement), strip_red=True)

                sanitize_ooxml_whitespace_and_pagination(doc)
                doc.save(tx.stage())

                # Transaction QA must cover both the package and the rendered content:
                # a format-only gate would publish a structurally broken DOCX as PASSED.
                package_qa = audit_docx_package_integrity(tx.temp_path)
                qa_report = audit_format_and_text_qa(
                    doc,
                    docx_path=tx.temp_path,
                    reference_docx_path=args.template,
                    raise_on_failure=False,
                    comparison_profile="STYLE_GUIDE",
                )
                tx.record_qa(package_qa, qa_report)
                release_office_file_locks(guard=guard)
            tx.commit()
    except TransactionPreflightError as exc:
        print(json.dumps({
            "output": args.out,
            "error": str(exc),
            "transaction": tx.record(),
        }, ensure_ascii=False, indent=2))
        return 2
    except TransactionAborted as exc:
        print(json.dumps({
            "output": args.out,
            "replaced_occurrences": replaced_count,
            "error": str(exc),
            "qa_status": tx.qa_status,
            "qa_issues": list((package_qa or {}).get("issues", []))
                         + list((qa_report or {}).get("issues", [])),
            "transaction": tx.record(),
        }, ensure_ascii=False, indent=2))
        return 1

    print(json.dumps({
        "output": args.out,
        "replaced_occurrences": replaced_count,
        "package_qa_passed": bool((package_qa or {}).get("passed")),
        "qa_passed": tx.qa_status == "PASSED",
        "qa_status": tx.qa_status,
        "transaction": tx.record(),
    }, ensure_ascii=False, indent=2))
    return 0


def _run_plan_path(args) -> int:
    """v4.0 FillPlan path: delegate all work to the deterministic executor."""
    from document_engine import generate_document_v4

    with open(args.spec, "r", encoding="utf-8") as f:
        spec = json.load(f)
    with open(args.plan, "r", encoding="utf-8") as f:
        fill_plan = json.load(f)

    content_plan = None
    if getattr(args, "content_plan", None):
        with open(args.content_plan, "r", encoding="utf-8") as f:
            content_plan = json.load(f)

    if args.mode:
        fill_plan = dict(fill_plan)
        fill_plan["mode"] = args.mode

    result = generate_document_v4(
        args.template,
        spec,
        content_plan,
        fill_plan,
        args.out,
        allow_unverified=args.allow_unverified,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result.get("status") in ("SUCCESS", "UNVERIFIED"):
        return 0
    return 2 if result.get("status") == "BLOCKED" else 1


def main() -> int:
    install_auto_cleanup()
    parser = argparse.ArgumentParser(description="Fill a Word template non-destructively using LogicalParagraphView.")
    parser.add_argument("--template", required=True, help="Input .docx template path")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--data", "--payload", dest="data", help="JSON file containing token->value replacement map")
    source.add_argument("--plan", help="FillPlan 4.0 JSON file (requires --spec)")
    parser.add_argument("--out", "--output", dest="out", required=True, help="Output .docx path")
    parser.add_argument("--spec", help="DocumentSpec 4.0 JSON file used with --plan")
    parser.add_argument("--content-plan", dest="content_plan",
                        help="Optional ContentPlan 4.0 JSON file used with --plan")
    parser.add_argument("--mode", choices=("STRICT", "STANDARD"), help="Override the FillPlan gate mode")
    parser.add_argument("--allow-unverified", dest="allow_unverified", action="store_true",
                        help="STANDARD only: commit a QA UNVERIFIED report that discloses missing checks")
    args = parser.parse_args()

    if args.plan:
        if not args.spec:
            parser.error("--plan requires --spec")
        return _run_plan_path(args)
    return _run_legacy_data_path(args)


if __name__ == "__main__":
    raise SystemExit(main())
