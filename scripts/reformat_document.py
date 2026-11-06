#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""REFORMAT CLI: build a semantic format diff plan and optionally apply it with tracked revisions.

Usage:
    python scripts/reformat_document.py --reference <template.docx> --target <draft.docx> \
        --plan-out format_plan.json [--out <formatted.docx>] [--strip-red]

Without `--out`, the command is plan-only: it prints the diff list and changes nothing.
With `--out`, only `AUTO_FIX` actions are applied; `REVIEW` / `UNSUPPORTED` / `KEEP`
entries remain in the plan for the user.
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
    QA_PENDING_HUMAN_REVIEW,
    DocumentTransaction,
    TransactionAborted,
    TransactionPreflightError,
    audit_docx_package_integrity,
    audit_format_and_text_qa,
    build_reformat_plan,
    execute_reformat_plan,
    install_auto_cleanup,
)
from template_gate.errors import TemplateGateError


def _write_json(path: str, payload: dict) -> None:
    if not path:
        return
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)


def main() -> int:
    install_auto_cleanup()
    parser = argparse.ArgumentParser(description="Build and apply a semantic REFORMAT diff plan.")
    parser.add_argument("--reference", required=True, help="Reference/template .docx path")
    parser.add_argument("--target", required=True, help="Target .docx to reformat")
    parser.add_argument("--plan-out", default="", help="Optional format_plan.json output path")
    parser.add_argument("--out", "--output", dest="out", default="", help="Output .docx path (omit for plan-only)")
    parser.add_argument("--plan-only", action="store_true", help="Only emit the diff plan")
    parser.add_argument("--strip-red", action="store_true", help="Strip red template residue in AUTO_FIX paragraphs")
    parser.add_argument("--author", default="OfficeCLI REFORMAT", help="Revision author")
    parser.add_argument("--gate-record", default="", help="Optional Template Understanding Gate record path/id")
    args = parser.parse_args()

    plan = build_reformat_plan(
        args.reference,
        args.target,
        strip_red=bool(args.strip_red),
        author=args.author,
    )
    _write_json(args.plan_out, plan)

    if args.plan_only or not args.out:
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        return 0

    if not plan["actions"]:
        report = {
            "status": "NOTHING_TO_APPLY",
            "reference_docx": plan["reference_docx"],
            "target_docx": plan["target_docx"],
            "summary": plan["summary"],
        }
        _write_json(args.plan_out, {**plan, "status": "NOTHING_TO_APPLY"})
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    tx = DocumentTransaction(args.target, args.out, task_mode="REFORMAT")
    execution = {}
    package_qa = {}
    format_qa = {}
    try:
        with tx:
            execution = execute_reformat_plan(
                plan,
                tx.stage(),
                author=args.author,
                gate_record=args.gate_record or None,
            )
            package_qa = audit_docx_package_integrity(tx.temp_path)
            format_qa = audit_format_and_text_qa(
                docx.Document(tx.temp_path),
                docx_path=tx.temp_path,
                reference_docx_path=args.reference,
                raise_on_failure=False,
                comparison_profile="STYLE_GUIDE",
            )
            pending = (
                plan["summary"]["review_required"] + plan["summary"]["unsupported"] > 0
                or bool(execution.get("unresolved_actions"))
            )
            if not package_qa.get("passed"):
                # A structurally broken package must never be published.
                tx.record_qa(package_qa, format_qa)
            elif pending:
                # The deliverable intentionally contains revision-marked proposals that
                # need a human accept/reject; package integrity is still verified.
                tx.record_qa(status=QA_PENDING_HUMAN_REVIEW)
            else:
                tx.record_qa(package_qa, format_qa)
            tx.commit()
    except TemplateGateError as exc:
        print(json.dumps({
            "reference_docx": plan.get("reference_docx"),
            "target_docx": plan.get("target_docx"),
            "output_docx": args.out,
            "error": exc.code,
            "message": exc.message,
            "details": exc.details,
            "next_action": "ASK_USER / RUN_TEMPLATE_GATE",
        }, ensure_ascii=False, indent=2))
        return 2
    except TransactionPreflightError as exc:
        print(json.dumps({
            "status": "PREFLIGHT_FAILED",
            "output": args.out,
            "error": str(exc),
            "transaction": tx.record(),
        }, ensure_ascii=False, indent=2))
        return 2
    except TransactionAborted as exc:
        print(json.dumps({
            "status": "FAILED",
            "output": args.out,
            "summary": plan["summary"],
            "execution": execution,
            "package_qa_passed": package_qa.get("passed", False),
            "format_qa_passed": format_qa.get("passed", False),
            "error": str(exc),
            "qa_status": tx.qa_status,
            "transaction": tx.record(),
        }, ensure_ascii=False, indent=2))
        return 1

    report = {
        "status": tx.qa_status,
        "reference_docx": plan["reference_docx"],
        "target_docx": plan["target_docx"],
        "output_docx": args.out,
        "summary": plan["summary"],
        "execution": execution,
        "package_qa_passed": bool(package_qa.get("passed")),
        "format_qa": format_qa,
        "transaction": tx.record(),
    }
    _write_json(args.plan_out, {**plan, "execution_report": report})
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if tx.committed else 1


if __name__ == "__main__":
    raise SystemExit(main())
