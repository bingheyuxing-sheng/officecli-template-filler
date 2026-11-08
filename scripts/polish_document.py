#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CLI entrypoint: POLISH mode — OfficeCLI-backed wording refinement on one DOCX.

The document keeps its layout: every edit is applied through the officecli
``set`` command on a run or paragraph path, never by rebuilding the body.
Writes are staged and only published after package + format QA.

Usage:
    python scripts/polish_document.py --target draft.docx --edits edits.json --out polished.docx
    python scripts/polish_document.py --target draft.docx --terms terms.json --plan-out polish_plan.json --plan-only

`edits.json`:
    [{"old_text": "utilize", "new_text": "use", "reason": "plain wording",
      "location_id": "body.p[3]", "occurrence": 1}, ...]
`terms.json` (glossary, applied everywhere it is safe):
    {"utilize": "use", "in order to": "to"}
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
    install_auto_cleanup,
)
from engine import officecli_writer
from engine.package_guard import check_package, load_limits
from engine.polish_engine import (
    PolishExecutionError,
    PolishPlanningError,
    build_polish_plan,
    execute_polish_plan,
    load_polish_inputs,
    normalize_terms,
)


def _write_json(path: str, payload: dict) -> None:
    if not path:
        return
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)


def main() -> int:
    install_auto_cleanup()
    parser = argparse.ArgumentParser(description="Refine wording without changing the document layout.")
    parser.add_argument("--target", required=True, help="Draft .docx to polish")
    parser.add_argument("--edits", default="", help="JSON list/object of explicit text edits")
    parser.add_argument("--terms", default="", help="JSON glossary {old: new} applied across the document")
    parser.add_argument("--out", "--output", dest="out", default="", help="Output polished .docx path")
    parser.add_argument("--plan-out", default="", help="Optional polish_plan.json output path")
    parser.add_argument("--report", default="", help="Optional polish_report.json output path")
    parser.add_argument("--plan-only", action="store_true", help="Only emit the plan; write nothing")
    parser.add_argument("--strip-red", action="store_true",
                        help="Strip red placeholder colour from the runs this run replaces")
    args = parser.parse_args()

    if not args.edits and not args.terms:
        parser.error("at least one of --edits / --terms is required")

    if officecli_writer.find_officecli() is None:
        print(json.dumps({
            "task_mode": "POLISH",
            "target_docx": args.target,
            "output_docx": args.out,
            "error": "OFFICECLI_UNAVAILABLE",
            "message": "POLISH is implemented on the officecli backend; install OfficeCLI or set OFFICECLI_BINARY",
            "passed": False,
        }, ensure_ascii=False, indent=2))
        return 2

    verdict = check_package(args.target, load_limits())
    if not verdict["ok"]:
        print(json.dumps({"error": verdict["code"], "input": args.target,
                          "package_guard": verdict}, ensure_ascii=False))
        return 2

    edits = []
    terms = []
    try:
        if args.edits:
            loaded = load_polish_inputs(args.edits)
            edits.extend(loaded["edits"])
            terms.extend(loaded["terms"])
        if args.terms:
            with open(args.terms, "r", encoding="utf-8") as handle:
                terms.extend(normalize_terms(json.load(handle)))
        plan, payload = build_polish_plan(args.target, edits, terms)
    except PolishPlanningError as exc:
        print(json.dumps({
            "task_mode": "POLISH",
            "target_docx": args.target,
            "output_docx": args.out,
            "error": exc.code,
            "message": exc.message,
            "details": exc.details,
            "passed": False,
            "next_action": "FIX_EDITS",
        }, ensure_ascii=False, indent=2))
        return 2

    _write_json(args.plan_out, plan)
    if args.plan_only or not args.out:
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        if not args.out:
            print(
                "POLISH deliverable missing: pass --out <polished.docx>. A plan is not the delivery.",
                file=sys.stderr,
            )
        return 0

    tx = DocumentTransaction(args.target, args.out, task_mode="POLISH")
    execution = {}
    package_qa = {}
    format_qa = {}
    try:
        with tx:
            execution = execute_polish_plan(
                args.target,
                tx.stage(),
                plan,
                payload,
                strip_red=args.strip_red,
            )
            package_qa = audit_docx_package_integrity(tx.temp_path)
            format_qa = audit_format_and_text_qa(
                docx.Document(tx.temp_path),
                docx_path=tx.temp_path,
                reference_docx_path=args.target,
                raise_on_failure=False,
                comparison_profile="REPLICA",
            )
            tx.record_qa(package_qa, format_qa)
            tx.commit()
    except TransactionPreflightError as exc:
        report = {
            "task_mode": "POLISH",
            "target_docx": args.target,
            "output_docx": args.out,
            "error": str(exc),
            "passed": False,
            "transaction": tx.record(),
        }
        _write_json(args.report, report)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 2
    except (TransactionAborted, PolishExecutionError) as exc:
        report = {
            "task_mode": "POLISH",
            "target_docx": args.target,
            "output_docx": args.out,
            "execution": execution,
            "package_qa": package_qa,
            "format_qa": format_qa,
            "error": getattr(exc, "code", str(exc)),
            "message": str(exc),
            "qa_status": tx.qa_status,
            "passed": False,
            "transaction": tx.record(),
        }
        _write_json(args.report, report)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1

    report = {
        "task_mode": "POLISH",
        "target_docx": args.target,
        "output_docx": args.out,
        "summary": plan["summary"],
        "execution": execution,
        "package_qa_passed": bool(package_qa.get("passed")),
        "format_qa_passed": bool(format_qa.get("passed")),
        "qa_status": tx.qa_status,
        "warnings": plan.get("warnings", []),
        "limitations": plan.get("limitations", []),
        "passed": bool(package_qa.get("passed") and format_qa.get("passed") and tx.committed),
        "transaction": tx.record(),
    }
    _write_json(args.report, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
