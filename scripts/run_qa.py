#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CLI entrypoint: Run full DOCX Package Integrity, Format-Diff & Visual QA (or Excel Formula & Style QA).
Usage:
    python scripts/run_qa.py <document.docx_or_xlsx> [--out qa_report.json]
"""

from __future__ import annotations

import argparse
import hashlib
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
    audit_content_consistency,
    audit_image_text,
    run_visual_layout_qa,
    audit_excel_formula_and_style_qa,
    audit_review_integrity,
    install_auto_cleanup,
    resolve_comparison_profile,
    split_issues,
    validation_report,
)
from engine.package_guard import reject_first_package


SECTION_KEYS = (
    "package_integrity",
    "format_and_text_qa",
    "content_qa",
    "image_text_qa",
    "visual_qa",
    "review_qa",
    "excel_qa",
    "officecli_validation",
)

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


def _file_sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_reuse_candidate(path: str, fpath: str, args) -> tuple:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError) as exc:
        return None, "cannot read sidecar: %s: %s" % (type(exc).__name__, exc)
    if not isinstance(payload, dict):
        return None, "sidecar is not an object"
    report = payload.get("qa_report") if isinstance(payload.get("qa_report"), dict) else payload
    expected_sha = str(payload.get("output_sha256") or report.get("output_sha256") or "")
    if not expected_sha:
        return None, "sidecar has no output_sha256"
    if expected_sha != _file_sha256(fpath):
        return None, "output file hash differs from the sidecar"
    if args.task_mode and str(report.get("task_mode")) != args.task_mode.strip().upper():
        return None, "task mode differs from the sidecar"
    if args.reference:
        return None, "an explicit reference requires a fresh QA run"
    if args.profile != "auto":
        return None, "an explicit profile requires a fresh QA run"
    if args.review or args.ocr or args.no_content_qa:
        return None, "extra or disabled checks require a fresh QA run"
    from qa.gate import validate_qa_report

    validation = validate_qa_report(report)
    if not validation.get("passed"):
        return None, "stored QA report is invalid: %s" % "; ".join(validation.get("errors") or [])[:400]
    return report, ""


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
    parser.add_argument(
        "--no-content-qa",
        action="store_true",
        help="Skip numeric/term consistency checks (content_qa section)",
    )
    parser.add_argument(
        "--ocr",
        action="store_true",
        help="OCR pictures to detect placeholder text inside images (requires an OCR backend)",
    )
    parser.add_argument(
        "--allow-unverified",
        action="store_true",
        help="Exit 0 even when required checks could not run (status UNVERIFIED is disclosed in the report)",
    )
    parser.add_argument(
        "--reuse-report",
        default="",
        help="Reuse a hash-matched QAReport sidecar written by generate_document.py --qa-report",
    )
    args = parser.parse_args()

    fpath = args.output_alias or args.file_path
    if not fpath:
        parser.error("an output file path is required (positional, --output)")

    rejected = reject_first_package({"document": fpath, "reference": args.reference})
    if rejected:
        print(json.dumps(rejected, ensure_ascii=False))
        return 2

    reuse_skipped = ""
    if args.reuse_report:
        reused_report, reuse_reason = _load_reuse_candidate(args.reuse_report, fpath, args)
        if reused_report is not None:
            status = str(reused_report.get("status") or "UNVERIFIED")
            issues = list(reused_report.get("issues") or [])
            warnings = list(reused_report.get("warnings") or [])
            coverage_gaps = list(reused_report.get("coverage_gaps") or [])
            exit_ok = status in ("PASSED", "PENDING_HUMAN_REVIEW") or (
                status == "UNVERIFIED" and args.allow_unverified
            )
            payload = {
                "reused": True,
                "reused_from": os.path.abspath(args.reuse_report),
                "output_sha256": _file_sha256(fpath),
                "status": status,
                "passed": status == "PASSED",
                "passed_or_pending": status in ("PASSED", "PENDING_HUMAN_REVIEW", "UNVERIFIED"),
                "exit_ok": exit_ok,
                "issues": issues,
                "warnings": warnings,
                "coverage_gaps": coverage_gaps,
                "unverified_count": len(coverage_gaps),
                "qa_report": reused_report,
            }
            text = json.dumps(payload, ensure_ascii=False, indent=2)
            if args.out:
                os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
                with open(args.out, "w", encoding="utf-8") as handle:
                    handle.write(text)
            print(text)
            return 0 if exit_ok else 1
        reuse_skipped = reuse_reason

    comparison_profile = resolve_comparison_profile(
        args.profile,
        task_mode=args.task_mode,
        reference_provided=bool(args.reference),
    )

    if fpath.lower().endswith((".xlsx", ".xlsm")):
        excel_qa = audit_excel_formula_and_style_qa(fpath)
        report = {
            "excel_qa": excel_qa,
            "officecli_validation": validation_report(fpath),
        }
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
            "officecli_validation": validation_report(fpath),
        }
        if not args.no_content_qa:
            # Content truth: numeric conflicts, subtotal closure, term drift. A high
            # severity finding here is a content error, not a formatting opinion.
            report["content_qa"] = audit_content_consistency(doc=doc)
        if args.ocr:
            # Image-internal text is out of scope without an OCR backend; asking for it
            # explicitly turns a missing backend into OCR_UNAVAILABLE (UNVERIFIED).
            report["image_text_qa"] = audit_image_text(fpath)
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

    exit_ok = status in ("PASSED", "PENDING_HUMAN_REVIEW") or (
        status == "UNVERIFIED" and args.allow_unverified
    )
    report.update({
        "status": status,
        "passed": status == "PASSED",
        "passed_or_pending": status in ("PASSED", "PENDING_HUMAN_REVIEW", "UNVERIFIED"),
        "exit_ok": exit_ok,
        "comparison_profile": comparison_profile,
        "issues": issues,
        "warnings": warnings,
        "warning_count": len(warnings),
        "coverage_gaps": coverage_gaps,
        "unverified_count": unverified_count,
        "hard_failure_count": len(strict_failures),
        "pending_human_review_count": len(pending),
    })
    if reuse_skipped:
        report["reuse_skipped"] = reuse_skipped

    payload = json.dumps(report, ensure_ascii=False, indent=2)
    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(payload)
    print(payload)
    return 0 if exit_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
