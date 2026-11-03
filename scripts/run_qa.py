#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CLI entrypoint: Run full DOCX Package Integrity, Format-Diff & Visual QA (or Excel Formula & Style QA).
Usage:
    python scripts/run_qa.py <document.docx_or_xlsx> [--out qa_report.json]
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
    audit_docx_package_integrity,
    audit_format_and_text_qa,
    run_visual_layout_qa,
    audit_excel_formula_and_style_qa,
    audit_review_integrity,
    install_auto_cleanup,
    resolve_comparison_profile,
    split_issues,
)


SECTION_KEYS = ("package_integrity", "format_and_text_qa", "visual_qa", "review_qa", "excel_qa")

# Placeholder residue is intentional in REVIEW mode: it waits for a human decision.
PENDING_HUMAN_REVIEW_CODES = {"TEMPLATE_TEXT_RESIDUAL"}


def _collect(report: dict) -> tuple:
    issues = []
    gaps = []
    unverified = 0
    for key in SECTION_KEYS:
        section = report.get(key)
        if not isinstance(section, dict):
            continue
        for item in section.get("structured_issues") or section.get("issues") or []:
            if isinstance(item, dict) and item.get("code"):
                issues.append(item)
        gaps.extend(section.get("coverage_gaps") or [])
        unverified += int(section.get("unverified_count") or 0)
    return issues, gaps, unverified


def resolve_report_status(issues: list, coverage_gaps: list, unverified_count: int, review: bool) -> tuple:
    """Fold sections into one status; only high-severity issues are hard failures."""
    pending_codes = PENDING_HUMAN_REVIEW_CODES if review else ()
    blocking, _warnings, pending = split_issues(issues, pending_codes)
    if blocking:
        return "FAILED", blocking, pending
    if coverage_gaps or unverified_count:
        return "UNVERIFIED", blocking, pending
    if pending:
        return "PENDING_HUMAN_REVIEW", blocking, pending
    return "PASSED", blocking, pending


def main() -> int:
    install_auto_cleanup()
    parser = argparse.ArgumentParser(description="Run full QA suite on a .docx or .xlsx output file.")
    parser.add_argument("file_path", nargs="?", default="", help="Path to .docx or .xlsx file")
    parser.add_argument("--output", dest="output_alias", default="", help="Alias for the positional file path")
    parser.add_argument("--reference", default="", help="Optional reference/template .docx baseline for size and visual QA")
    parser.add_argument("--review", action="store_true", help="Also audit tracked-change and comment integrity for REVIEW outputs")
    parser.add_argument(
        "--profile",
        default="auto",
        choices=("auto", "replica", "style-guide"),
        help="Comparison semantics: replica preserves template order; style-guide treats the template as a style source",
    )
    parser.add_argument(
        "--task-mode",
        default="",
        help="Task mode that produced the file (GENERATE / REPAIR / REVIEW ...). Used when --profile=auto",
    )
    parser.add_argument("--out", "--report", dest="out", default="", help="Optional output JSON report path")
    args = parser.parse_args()

    fpath = args.output_alias or args.file_path
    if not fpath:
        parser.error("an output file path is required (positional, --output)")

    comparison_profile = resolve_comparison_profile(
        args.profile,
        task_mode=args.task_mode,
        reference_provided=bool(args.reference),
    )

    if fpath.lower().endswith((".xlsx", ".xlsm")):
        excel_qa = audit_excel_formula_and_style_qa(fpath)
        report = {"excel_qa": excel_qa}
    else:
        doc = docx.Document(fpath)
        pkg_qa = audit_docx_package_integrity(fpath)
        # Structured report instead of an exception: callers need the issue list, not a traceback.
        fmt_qa = audit_format_and_text_qa(
            doc,
            docx_path=fpath,
            reference_docx_path=args.reference or None,
            raise_on_failure=False,
            comparison_profile=comparison_profile,
        )
        vis_qa = run_visual_layout_qa(
            fpath,
            reference_docx_path=args.reference or None,
            comparison_profile=comparison_profile,
        )
        report = {
            "package_integrity": pkg_qa,
            "format_and_text_qa": fmt_qa,
            "visual_qa": vis_qa,
        }
        if args.review:
            report["review_qa"] = audit_review_integrity(fpath)

    issues, coverage_gaps, unverified_count = _collect(report)
    # Without `--review` nothing is expected to stay unresolved, so placeholders count as failures.
    status, strict_failures, pending = resolve_report_status(
        issues, coverage_gaps, unverified_count, args.review
    )
    _blocking, warnings, _pending = split_issues(
        issues, PENDING_HUMAN_REVIEW_CODES if args.review else ()
    )

    report.update({
        "status": status,
        "passed": status == "PASSED",
        "passed_or_pending": status in ("PASSED", "PENDING_HUMAN_REVIEW", "UNVERIFIED"),
        "comparison_profile": comparison_profile,
        "issues": issues,
        "warnings": warnings,
        "warning_count": len(warnings),
        "coverage_gaps": coverage_gaps,
        "unverified_count": unverified_count,
        "hard_failure_count": len(strict_failures),
        "pending_human_review_count": len(pending),
    })

    payload = json.dumps(report, ensure_ascii=False, indent=2)
    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(payload)
    print(payload)
    return 0 if report["passed_or_pending"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
