#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CLI entrypoint: Dual-Document REPAIR Mode (v3.0).
Compares a Reference/Template .docx and a Broken/Target .docx, emits `repair_plan.json`,
and executes the repair non-destructively into a staged file that is published only
after package QA passes.

Usage:
    python scripts/repair_document.py --reference <ref.docx> --broken <broken.docx> --out <repaired.docx> [--plan-out repair_plan.json]
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
    TransactionAborted,
    TransactionPreflightError,
    audit_docx_package_integrity,
    audit_format_and_text_qa,
    build_repair_plan,
    execute_repair_plan,
    install_auto_cleanup,
)


def main() -> int:
    install_auto_cleanup()
    parser = argparse.ArgumentParser(description="Build and execute a dual-document repair plan.")
    parser.add_argument("--reference", required=True, help="Reference/template .docx path")
    parser.add_argument("--broken", required=True, help="Broken/target .docx path")
    parser.add_argument("--out", "--output", dest="out", default="", help="Output repaired .docx path (omit if --plan-only)")
    parser.add_argument("--plan-out", default="", help="Optional path to save repair_plan.json")
    parser.add_argument("--plan-only", action="store_true", help="Only generate repair_plan.json without executing")
    args = parser.parse_args()

    plan = build_repair_plan(args.reference, args.broken)
    if args.plan_out:
        os.makedirs(os.path.dirname(os.path.abspath(args.plan_out)), exist_ok=True)
        with open(args.plan_out, "w", encoding="utf-8") as f:
            json.dump(plan, f, ensure_ascii=False, indent=2)

    if args.plan_only or not args.out:
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        return 0

    tx = DocumentTransaction(args.broken, args.out, task_mode="REPAIR")
    exec_result = {}
    pkg_qa = {}
    fmt_qa = {}
    try:
        with tx:
            exec_result = execute_repair_plan(plan, tx.stage())
            # Package QA alone would publish a doc whose format still drifts from the template:
            # REPAIR's deliverable contract is the reference formatting, so verify it too.
            pkg_qa = audit_docx_package_integrity(tx.temp_path)
            fmt_qa = audit_format_and_text_qa(
                docx.Document(tx.temp_path),
                docx_path=tx.temp_path,
                reference_docx_path=args.reference,
                raise_on_failure=False,
                comparison_profile="REPLICA",
            )
            tx.record_qa(pkg_qa, fmt_qa)
            tx.commit()
    except TransactionPreflightError as exc:
        print(json.dumps({
            "plan_total_actions": plan["total_actions"],
            "output": args.out,
            "error": str(exc),
            "transaction": tx.record(),
        }, ensure_ascii=False, indent=2))
        return 2
    except TransactionAborted as exc:
        print(json.dumps({
            "plan_total_actions": plan["total_actions"],
            "output": args.out,
            "execution": exec_result,
            "error": str(exc),
            "qa_status": tx.qa_status,
            "qa_issues": list(pkg_qa.get("issues", [])) + list(fmt_qa.get("issues", [])),
            "transaction": tx.record(),
        }, ensure_ascii=False, indent=2))
        return 1

    print(json.dumps({
        "plan_total_actions": plan["total_actions"],
        "execution": exec_result,
        "package_qa_passed": bool(pkg_qa.get("passed")),
        "format_qa_passed": bool(fmt_qa.get("passed")),
        "qa_status": tx.qa_status,
        "transaction": tx.record(),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
