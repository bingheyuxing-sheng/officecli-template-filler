#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CLI entrypoint: Generate a filled document from a template and a JSON replacement map.
Usage:
    python scripts/generate_document.py --template <template.docx> --data <data.json> --out <output.docx>
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
    TaskResourceGuard,
    LogicalParagraphView,
    iter_all_document_paragraphs_with_Wait_context,
    sanitize_ooxml_whitespace_and_pagination,
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

    with TaskResourceGuard() as guard:
        doc = docx.Document(args.template)
        replaced_count = 0
        for ctx in iter_all_document_paragraphs_with_Wait_context(doc):
            p_el = ctx["p_el"]
            view = LogicalParagraphView(p_el)
            for token, replacement in tokens_map.items():
                if token in view.logical_text:
                    replaced_count += view.replace_all_tokens(str(token), str(replacement), strip_red=True)

        sanitize_ooxml_whitespace_and_pagination(doc)
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        doc.save(args.out)

        qa_report = audit_format_and_text_qa(
            doc,
            docx_path=args.out,
            reference_docx_path=args.template,
            raise_on_failure=False,
        )
        release_office_file_locks(guard=guard)

    print(json.dumps({
        "output": args.out,
        "replaced_occurrences": replaced_count,
        "qa_passed": qa_report["passed"],
        "qa_issues": qa_report.get("issues", []),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
