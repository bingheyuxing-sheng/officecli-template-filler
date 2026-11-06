#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CLI entrypoint: Template-Driven REVIEW Mode (v3.1).

Builds a review plan against a reference template, applies it with Word tracked changes,
native comments, and an audit report so a human can accept or reject every text change.
The reviewed document is staged and only published after review + package QA.

Usage:
    python scripts/review_document.py --reference <template.docx> --target <draft.docx> \
        --out <reviewed.docx> [--author "..."] [--revisions revisions.json] \
        [--report review_report.json] [--plan-out review_plan.json] [--plan-only]

`revisions.json` is an optional list of {"old_text": "...", "new_text": "...", "reason": "..."}.
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
    REVIEW_AUTHOR_DEFAULT,
    DocumentTransaction,
    PENDING_HUMAN_REVIEW_CODES,
    TransactionAborted,
    TransactionPreflightError,
    audit_docx_package_integrity,
    audit_review_integrity,
    build_review_plan,
    execute_review_plan,
    install_auto_cleanup,
    write_review_snapshot,
)
from template_gate.errors import TemplateGateError


def main() -> int:
    install_auto_cleanup()
    parser = argparse.ArgumentParser(description="Build and execute a tracked-changes review plan.")
    parser.add_argument("--reference", required=True, help="Reference/template .docx path")
    parser.add_argument("--target", required=True, help="Draft/target .docx to review")
    parser.add_argument("--out", "--output", dest="out", default="", help="Output reviewed .docx path")
    parser.add_argument("--author", default=REVIEW_AUTHOR_DEFAULT, help="Revision and comment author")
    parser.add_argument("--revisions", default="", help="Optional JSON list of text revisions")
    parser.add_argument("--report", default="", help="Optional review_report.json output path")
    parser.add_argument("--snapshot", default="", help="Optional review_snapshot.json output path (default: next to the deliverable)")
    parser.add_argument("--gate-record", default="", help="Optional Template Understanding Gate record path/id")
    parser.add_argument("--plan-out", default="", help="Optional review_plan.json output path")
    parser.add_argument("--plan-only", action="store_true", help="Only emit the review plan")
    parser.add_argument(
        "--no-auto-text-diff",
        action="store_true",
        help="Disable automatic template-vs-draft text diff (only --revisions become tracked edits)",
    )
    args = parser.parse_args()

    revisions = []
    if args.revisions:
        with open(args.revisions, "r", encoding="utf-8") as handle:
            revisions = json.load(handle)

    plan = build_review_plan(
        args.reference,
        args.target,
        author=args.author,
        text_revisions=revisions,
        auto_text_diff=not args.no_auto_text_diff,
    )
    if args.plan_out:
        os.makedirs(os.path.dirname(os.path.abspath(args.plan_out)), exist_ok=True)
        with open(args.plan_out, "w", encoding="utf-8") as handle:
            json.dump(plan, handle, ensure_ascii=False, indent=2)

    if args.plan_only or not args.out:
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        if not args.out:
            print(
                "REVIEW deliverable missing: pass --out <reviewed.docx>. "
                "The user must receive a Word document that opens in revision mode; a plan or report is not the delivery.",
                file=sys.stderr,
            )
        return 0

    tx = DocumentTransaction(args.target, args.out, task_mode="REVIEW")
    execution = {}
    review_qa = {}
    package_qa = {}
    snapshot_report = None
    try:
        with tx:
            # The snapshot must describe the published file, so it is written after commit.
            execution = execute_review_plan(
                plan, tx.stage(), snapshot_path="", gate_record=args.gate_record or None
            )
            review_qa = audit_review_integrity(tx.temp_path)
            package_qa = audit_docx_package_integrity(tx.temp_path)
            # Placeholders kept on purpose wait for a human decision in REVIEW mode.
            tx.record_qa(
                review_qa,
                package_qa,
                pending_codes=PENDING_HUMAN_REVIEW_CODES,
                qa_report_path=args.report or None,
            )
            tx.commit()
        snapshot_report = write_review_snapshot(tx.output_path, snapshot_path=args.snapshot or None)
    except TemplateGateError as exc:
        print(json.dumps({
            "schema_version": "3.1",
            "task_mode": "REVIEW",
            "reference_docx": args.reference,
            "target_docx": args.target,
            "output_docx": args.out,
            "error": exc.code,
            "message": exc.message,
            "details": exc.details,
            "passed": False,
            "next_action": "ASK_USER / RUN_TEMPLATE_GATE",
        }, ensure_ascii=False, indent=2))
        return 2
    except TransactionPreflightError as exc:
        report = {
            "schema_version": "3.1",
            "task_mode": "REVIEW",
            "reference_docx": args.reference,
            "target_docx": args.target,
            "output_docx": args.out,
            "error": str(exc),
            "passed": False,
            "transaction": tx.record(),
        }
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 2
    except TransactionAborted as exc:
        report = {
            "schema_version": "3.1",
            "task_mode": "REVIEW",
            "reference_docx": args.reference,
            "target_docx": args.target,
            "output_docx": args.out,
            "author": args.author,
            "summary": plan["summary"],
            "execution": execution,
            "review_qa": review_qa,
            "package_qa_passed": package_qa.get("passed", False),
            "error": str(exc),
            "qa_status": tx.qa_status,
            "passed": False,
            "transaction": tx.record(),
        }
        _write_report(args.report, report)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1

    report = {
        "schema_version": "3.1",
        "task_mode": "REVIEW",
        "reference_docx": args.reference,
        "target_docx": args.target,
        "output_docx": args.out,
        "author": args.author,
        "summary": plan["summary"],
        "execution": execution,
        "review_qa": review_qa,
        "package_qa_passed": package_qa["passed"],
        "qa_status": tx.qa_status,
        "snapshot": snapshot_report,
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
