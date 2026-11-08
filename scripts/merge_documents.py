#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CLI entrypoint: MERGE mode — consolidate 2+ same-format Office files with OfficeCLI.

The first input is the base package. Every later input is dumped to a replayable
OfficeCLI batch and applied to a staged copy, so the base styles, theme, headers
and media survive while the appended bodies keep runs, tables, pictures and
hyperlinks. Writes are transactional and verified before publication.

Usage:
    python scripts/merge_documents.py --inputs a.docx b.docx c.docx --out merged.docx
    python scripts/merge_documents.py --inputs a.xlsx b.xlsx --out merged.xlsx
    python scripts/merge_documents.py a.docx b.docx --out merged.docx --plan-only
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
from engine.merge_engine import (
    MergeExecutionError,
    MergePlanningError,
    container_family,
    execute_merge,
    normalize_inputs,
    plan_docx_merge,
    plan_xlsx_merge,
    verify_merge,
)
from engine.package_guard import check_package, load_limits


def _write_json(path: str, payload: dict) -> None:
    if not path:
        return
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)


def main() -> int:
    install_auto_cleanup()
    parser = argparse.ArgumentParser(description="Merge multiple Office files through the officecli backend.")
    parser.add_argument("files", nargs="*", default=[], help="Input .docx/.xlsx paths")
    parser.add_argument("--inputs", nargs="+", default=[], help="Alias for the input path list")
    parser.add_argument("--out", "--output", dest="out", default="", help="Merged output path")
    parser.add_argument("--separator", choices=("page", "none"), default="page",
                        help="DOCX only: insert a page break before each appended document")
    parser.add_argument("--plan-out", default="", help="Optional merge_plan.json output path")
    parser.add_argument("--report", default="", help="Optional merge_report.json output path")
    parser.add_argument("--plan-only", action="store_true", help="Only emit the plan; write nothing")
    args = parser.parse_args()

    paths = args.inputs or args.files
    if not paths:
        parser.error("at least two input files are required (positional or --inputs)")

    if officecli_writer.find_officecli() is None:
        print(json.dumps({
            "task_mode": "MERGE",
            "inputs": paths,
            "output": args.out,
            "error": "OFFICECLI_UNAVAILABLE",
            "message": "MERGE is implemented on the officecli backend; install OfficeCLI or set OFFICECLI_BINARY",
            "passed": False,
        }, ensure_ascii=False, indent=2))
        return 2

    try:
        inputs = normalize_inputs(paths)
        family = container_family(inputs[0])
    except MergePlanningError as exc:
        print(json.dumps({
            "task_mode": "MERGE",
            "inputs": paths,
            "output": args.out,
            "error": exc.code,
            "message": exc.message,
            "details": exc.details,
            "passed": False,
        }, ensure_ascii=False, indent=2))
        return 2

    for path in inputs:
        verdict = check_package(path, load_limits())
        if not verdict["ok"]:
            print(json.dumps({"error": verdict["code"], "input": path,
                              "package_guard": verdict}, ensure_ascii=False))
            return 2

    try:
        if family == "docx":
            plan, payload = plan_docx_merge(
                inputs, output_path=args.out, separator=args.separator
            )
        else:
            plan, payload = plan_xlsx_merge(inputs, output_path=args.out)
    except MergePlanningError as exc:
        print(json.dumps({
            "task_mode": "MERGE",
            "inputs": inputs,
            "output": args.out,
            "error": exc.code,
            "message": exc.message,
            "details": exc.details,
            "passed": False,
        }, ensure_ascii=False, indent=2))
        return 2
    except Exception as exc:
        print(json.dumps({
            "task_mode": "MERGE",
            "inputs": inputs,
            "output": args.out,
            "error": "MERGE_PLANNING_FAILED",
            "message": "%s: %s" % (type(exc).__name__, exc),
            "passed": False,
        }, ensure_ascii=False, indent=2))
        return 2

    _write_json(args.plan_out, plan)
    if args.plan_only or not args.out:
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        if not args.out:
            print(
                "MERGE deliverable missing: pass --out <merged file>. A plan is not the delivery.",
                file=sys.stderr,
            )
        return 0

    tx = DocumentTransaction(inputs[0], args.out, task_mode="MERGE")
    execution = {}
    merge_qa = {}
    package_qa = {}
    format_qa = {}
    try:
        with tx:
            execution = execute_merge(plan, payload, tx.stage())
            merge_qa = verify_merge(plan, payload, tx.temp_path)
            reports = [merge_qa]
            if family == "docx":
                package_qa = audit_docx_package_integrity(tx.temp_path)
                format_qa = audit_format_and_text_qa(
                    docx.Document(tx.temp_path),
                    docx_path=tx.temp_path,
                    reference_docx_path=inputs[0],
                    raise_on_failure=False,
                    comparison_profile="STYLE_GUIDE",
                )
                reports.extend([package_qa, format_qa])
            tx.record_qa(*reports)
            tx.commit()
    except TransactionPreflightError as exc:
        report = {
            "task_mode": "MERGE",
            "format": family,
            "inputs": inputs,
            "output": args.out,
            "error": str(exc),
            "passed": False,
            "transaction": tx.record(),
        }
        _write_json(args.report, report)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 2
    except (TransactionAborted, MergeExecutionError) as exc:
        report = {
            "task_mode": "MERGE",
            "format": family,
            "inputs": inputs,
            "output": args.out,
            "summary": plan["summary"],
            "execution": execution,
            "merge_qa": merge_qa,
            "package_qa": package_qa,
            "format_qa": format_qa,
            "error": getattr(exc, "code", str(exc)),
            "message": str(exc),
            "qa_status": tx.qa_status,
            "passed": False,
            "limitations": plan.get("limitations", []),
            "transaction": tx.record(),
        }
        _write_json(args.report, report)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1

    report = {
        "task_mode": "MERGE",
        "format": family,
        "inputs": inputs,
        "output": args.out,
        "summary": plan["summary"],
        "documents": plan["documents"],
        "execution": execution,
        "merge_qa": merge_qa,
        "package_qa_passed": bool(package_qa.get("passed")) if package_qa else None,
        "format_qa_passed": bool(format_qa.get("passed")) if format_qa else None,
        "qa_status": tx.qa_status,
        "warnings": plan.get("warnings", []),
        "limitations": plan.get("limitations", []),
        "passed": bool(
            merge_qa.get("passed")
            and (not package_qa or package_qa.get("passed"))
            and (not format_qa or format_qa.get("passed"))
            and tx.committed
        ),
        "transaction": tx.record(),
    }
    _write_json(args.report, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
