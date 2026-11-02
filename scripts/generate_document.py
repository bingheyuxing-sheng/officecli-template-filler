#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CLI entrypoint: Generate a filled document from a template and a JSON replacement map.
Usage:
    python scripts/generate_document.py --template <template.docx> --data <data.json> --out <output.docx>

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


def main() -> int:
    install_auto_cleanup()
    parser = argparse.ArgumentParser(description="Fill a Word template non-destructively using LogicalParagraphView.")
    parser.add_argument("--template", required=True, help="Input .docx template path")
    parser.add_argument("--data", "--payload", dest="data", required=True, help="JSON file containing token->value replacement map")
    parser.add_argument("--out", "--output", dest="out", required=True, help="Output .docx path")
    args = parser.parse_args()

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


if __name__ == "__main__":
    raise SystemExit(main())
