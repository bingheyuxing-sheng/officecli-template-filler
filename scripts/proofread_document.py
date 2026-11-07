#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CLI entrypoint: PROOFREAD mode (single document). v3.5 M8.

Proofreading is REVIEW against the document itself: no template formatting is restored,
text fixes are written as `w:ins` / `w:del`, and judgement calls stay as comments for the
human. It reuses `execute_review_plan()` and the M1 transaction + M2 snapshot.

Usage:
    python scripts/proofread_document.py --target <draft.docx> --out <proofread.docx> \
        --revisions revisions.json [--author "..."] [--report report.json] [--snapshot path]

`revisions.json` is a list of {"old_text": "...", "new_text": "...", "reason": "..."}.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from engine import (
    PENDING_HUMAN_REVIEW_CODES,
    REVIEW_AUTHOR_DEFAULT,
    DocumentTransaction,
    TransactionAborted,
    TransactionPreflightError,
    audit_docx_package_integrity,
    audit_review_integrity,
    build_proofread_plan,
    execute_review_plan,
    install_auto_cleanup,
    write_review_snapshot,
)
from engine.package_guard import reject_first_package


def main() -> int:
    install_auto_cleanup()
    parser = argparse.ArgumentParser(description="Proofread a single document into a tracked-changes deliverable.")
    parser.add_argument("--target", required=True, help="Document to proofread")
    parser.add_argument("--out", "--output", dest="out", required=True, help="Output proofread .docx")
    parser.add_argument("--author", default=REVIEW_AUTHOR_DEFAULT, help="Revision and comment author")
    parser.add_argument("--revisions", default="", help="JSON list of text revisions")
    parser.add_argument("--report", default="", help="Optional proofread_report.json path")
    parser.add_argument("--snapshot", default="", help="Optional review_snapshot.json path")
    parser.add_argument(
        "--no-auto-check",
        action="store_true",
        help="Disable automatic content/typo checks (only --revisions and placeholder comments remain)",
    )
    args = parser.parse_args()

    rejected = reject_first_package({"target": args.target})
    if rejected:
        print(json.dumps(rejected, ensure_ascii=False))
        return 2

    revisions = []
    if args.revisions:
        with open(args.revisions, "r", encoding="utf-8") as handle:
            revisions = json.load(handle)

    # Reference == target: proofreading never restores a template's formatting.
    # Automated content/typo findings become review comments, never silent edits.
    plan = build_proofread_plan(
        args.target,
        author=args.author,
        text_revisions=revisions,
        auto_check=not args.no_auto_check,
    )

    tx = DocumentTransaction(args.target, args.out, task_mode="PROOFREAD")
    execution = {}
    review_qa = {}
    package_qa = {}
    snapshot_report = None
    try:
        with tx:
            execution = execute_review_plan(plan, tx.stage(), snapshot_path="")
            review_qa = audit_review_integrity(tx.temp_path)
            package_qa = audit_docx_package_integrity(tx.temp_path)
            tx.record_qa(review_qa, package_qa, pending_codes=PENDING_HUMAN_REVIEW_CODES)
            tx.commit()
        snapshot_report = write_review_snapshot(tx.output_path, snapshot_path=args.snapshot or None)
    except TransactionPreflightError as exc:
        print(json.dumps({
            "task_mode": "PROOFREAD",
            "target_docx": args.target,
            "output_docx": args.out,
            "error": str(exc),
            "passed": False,
            "transaction": tx.record(),
        }, ensure_ascii=False, indent=2))
        return 2
    except TransactionAborted as exc:
        report = {
            "task_mode": "PROOFREAD",
            "target_docx": args.target,
            "output_docx": args.out,
            "execution": execution,
            "review_qa": review_qa,
            "package_qa": package_qa,
            "error": str(exc),
            "qa_status": tx.qa_status,
            "passed": False,
            "transaction": tx.record(),
        }
        _write_report(args.report, report)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1

    report = {
        "task_mode": "PROOFREAD",
        "target_docx": args.target,
        "output_docx": args.out,
        "author": args.author,
        "auto_check": plan.get("auto_check"),
        "execution": execution,
        "review_qa": review_qa,
        "package_qa": package_qa,
        "snapshot": snapshot_report,
        "qa_status": tx.qa_status,
        "passed": bool(review_qa["passed"] and package_qa["passed"] and tx.committed),
        "transaction": tx.record(),
    }
    _write_report(args.report, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


def _write_report(path: str, report: dict) -> None:
    if not path:
        return
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    raise SystemExit(main())
