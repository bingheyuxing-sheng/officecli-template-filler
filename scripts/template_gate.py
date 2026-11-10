#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CLI for the Template Understanding Gate.

Usage:
    python scripts/template_gate.py analyze --template template.docx --task-type GENERATE [--out analysis.json]
    python scripts/template_gate.py report --analysis analysis.json [--format markdown|json] [--out report.md]
    python scripts/template_gate.py status --analysis analysis.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from engine.cli_io import configure_stdio  # noqa: E402
from engine.package_guard import reject_first_package  # noqa: E402
from template_gate import build_analysis  # noqa: E402
from template_gate.report import build_report, render_markdown  # noqa: E402
from template_gate.store import GateStore  # noqa: E402
from template_gate.supplements import resolve_evidence  # noqa: E402
from template_gate.supplements import analyze_supplements  # noqa: E402
from template_intelligence import build_document_spec_from_path  # noqa: E402

SUPPORTED_WORD_SUFFIXES = (".docx", ".docm")


def _write_text(path: str, text: str) -> None:
    if not path:
        return
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)


def _write_json(path: str, payload: dict) -> None:
    _write_text(path, json.dumps(payload, ensure_ascii=False, indent=2))


def _load_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError("JSON object expected: %s" % path)
    return payload


def _unsupported_template(path: str) -> "dict | None":
    if path.lower().endswith(SUPPORTED_WORD_SUFFIXES):
        return None
    return {
        "error": "UNSUPPORTED_CONTAINER",
        "message": (
            "template_gate.py only accepts .docx/.docm; "
            "use analyze_excel_template.py for .xlsx/.xlsm"
        ),
        "input": path,
        "supported": list(SUPPORTED_WORD_SUFFIXES),
    }


def _render_report(analysis: dict, gate_home: str, fmt: str) -> tuple:
    report = build_report(analysis)
    store = GateStore(gate_home)
    token = store.review_token(str(report.get("analysis_id")), str(report.get("report_digest")))
    report.setdefault("confirmation", {})["review_token"] = token
    if fmt == "json":
        text = json.dumps(report, ensure_ascii=False, indent=2)
    else:
        text = render_markdown(report) + "\n确认令牌（用于 confirm）：`%s`\n" % token
    return report, text


def _cmd_analyze(args) -> int:
    unsupported = _unsupported_template(args.template)
    if unsupported:
        print(json.dumps(unsupported, ensure_ascii=False))
        return 2

    rejected = reject_first_package({"template": args.template})
    if rejected:
        print(json.dumps(rejected, ensure_ascii=False))
        return 2

    try:
        spec = build_document_spec_from_path(args.template)
    except Exception as exc:
        print(
            json.dumps(
                {
                    "error": "DOCUMENT_UNREADABLE",
                    "message": "{}: {}".format(type(exc).__name__, exc),
                    "input": args.template,
                    "next_action": "PROVIDE_VALID_DOCX_OR_DOCM",
                },
                ensure_ascii=False,
            )
        )
        return 2
    try:
        analysis = build_analysis(
            args.template,
            args.task_type,
            spec=spec,
            supplements=args.supplement or None,
        )
    except Exception as exc:
        code = "SEMANTIC_SUPPLEMENT_INVALID" if args.supplement else "TEMPLATE_ANALYSIS_FAILED"
        print(
            json.dumps(
                {
                    "error": code,
                    "message": "{}: {}".format(type(exc).__name__, exc),
                    "input": args.template,
                    "supplements": args.supplement or [],
                    "next_action": (
                        "FIX_SEMANTIC_SUPPLEMENT"
                        if args.supplement
                        else "CHECK_TEMPLATE_OR_RETRY"
                    ),
                },
                ensure_ascii=False,
            )
        )
        return 2
    text = json.dumps(analysis, ensure_ascii=False, indent=2)
    if args.out:
        _write_text(args.out, text)
        print("Saved template analysis to: %s" % args.out)
    else:
        print(text)
    if args.spec_out:
        _write_json(args.spec_out, spec)
        print("Saved document spec to: %s" % args.spec_out)
    if args.report_out:
        report, report_text = _render_report(analysis, args.gate_home, args.report_format)
        _write_text(args.report_out, report_text)
        print("Saved template analysis report to: %s" % args.report_out)
        print("review_token: %s" % report["confirmation"]["review_token"])
    return 2 if analysis.get("summary", {}).get("blocking") else 0


def _cmd_report(args) -> int:
    analysis = _load_json(args.analysis)
    report, text = _render_report(analysis, args.gate_home, args.format)
    if args.out:
        _write_text(args.out, text)
        print("Saved template analysis report to: %s" % args.out)
    else:
        print(text)
    return 2 if report.get("blocking_items") else 0


def _cmd_confirm(args) -> int:
    analysis = _load_json(args.analysis)
    report = build_report(analysis)
    store = GateStore(args.gate_home)
    if not store.verify_review_token(
        str(report.get("analysis_id")),
        str(report.get("report_digest")),
        args.review_token,
    ):
        print(
            json.dumps(
                {"error": "TEMPLATE_GATE_CONFIRMATION_REQUIRED", "detail": "review token mismatch"},
                ensure_ascii=False,
                indent=2,
            )
        )
        return 2
    if report.get("blocking_items"):
        print(
            json.dumps(
                {"error": "TEMPLATE_EVIDENCE_INCOMPLETE", "blocking_items": report.get("blocking_items")},
                ensure_ascii=False,
                indent=2,
            )
        )
        return 2
    record = store.confirm(
        analysis,
        report,
        user_statement=args.user_statement,
        confirmed_by=args.confirmed_by,
        ttl_seconds=args.ttl_seconds,
    )
    text = json.dumps(record, ensure_ascii=False, indent=2)
    if args.out_record:
        _write_json(args.out_record, record)
        print("Saved gate record to: %s" % args.out_record)
    else:
        print(text)
    return 0


def _cmd_reject(args) -> int:
    analysis = _load_json(args.analysis)
    store = GateStore(args.gate_home)
    record = store.reject(analysis, user_statement=args.user_statement)
    text = json.dumps(record, ensure_ascii=False, indent=2)
    if args.out_record:
        _write_json(args.out_record, record)
        print("Saved rejected gate record to: %s" % args.out_record)
    else:
        print(text)
    return 0


def _cmd_resolve(args) -> int:
    analysis = _load_json(args.analysis)
    updated = resolve_evidence(
        analysis,
        args.evidence_id,
        resolution_type=args.resolution,
        value=args.value,
        user_statement=args.user_statement,
        source=args.source,
    )
    text = json.dumps(updated, ensure_ascii=False, indent=2)
    if args.out:
        _write_text(args.out, text)
        print("Saved updated template analysis to: %s" % args.out)
    else:
        print(text)
    return 2 if updated.get("summary", {}).get("blocking") else 0


def _cmd_apply_supplement(args) -> int:
    unsupported = _unsupported_template(args.template)
    if unsupported:
        print(json.dumps(unsupported, ensure_ascii=False))
        return 2

    analysis = _load_json(args.analysis)
    try:
        updated = analyze_supplements(
            args.template,
            analysis,
            [args.supplement],
        )
    except Exception as exc:
        print(
            json.dumps(
                {
                    "error": "SEMANTIC_SUPPLEMENT_INVALID",
                    "message": "{}: {}".format(type(exc).__name__, exc),
                    "template": args.template,
                    "supplement": args.supplement,
                    "next_action": "FIX_SEMANTIC_SUPPLEMENT",
                },
                ensure_ascii=False,
            )
        )
        return 2
    text = json.dumps(updated, ensure_ascii=False, indent=2)
    if args.out:
        _write_text(args.out, text)
        print("Saved updated template analysis to: %s" % args.out)
    else:
        print(text)
    return 2 if updated.get("summary", {}).get("blocking") else 0


def _cmd_status(args) -> int:
    if args.gate:
        record = GateStore(args.gate_home).load(args.gate)
        if record is None:
            print(json.dumps({"error": "TEMPLATE_GATE_REQUIRED", "gate_id": args.gate}, ensure_ascii=False, indent=2))
            return 2
        print(json.dumps(record, ensure_ascii=False, indent=2))
        return 0
    analysis = _load_json(args.analysis)
    payload = {
        "analysis_id": analysis.get("analysis_id"),
        "template_name": analysis.get("template_name"),
        "template_sha256": analysis.get("template_sha256"),
        "task_type": analysis.get("task_type"),
        "summary": analysis.get("summary"),
        "evidence_digest": analysis.get("evidence_digest"),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    configure_stdio()
    parser = argparse.ArgumentParser(description="Template Understanding Gate CLI.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    analyze = subparsers.add_parser("analyze", help="Analyze a template and emit evidence JSON.")
    analyze.add_argument("--template", required=True, help="Template .docx path")
    analyze.add_argument("--task-type", required=True, help="GENERATE / REPAIR / REFORMAT / REVIEW")
    analyze.add_argument("--out", default="", help="Optional analysis JSON output path")
    analyze.add_argument("--spec-out", default="", help="Optional DocumentSpec 4.0 output path")
    analyze.add_argument("--report-out", default="", help="Optional rendered report output path")
    analyze.add_argument("--report-format", choices=("markdown", "json"), default="markdown")
    analyze.add_argument("--gate-home", default="", help="Optional gate store directory")
    analyze.add_argument("--supplement", action="append", default=[], help="Reference material path (repeatable)")
    analyze.set_defaults(func=_cmd_analyze)

    report = subparsers.add_parser("report", help="Render the user-facing template analysis report.")
    report.add_argument("--analysis", required=True, help="Analysis JSON path")
    report.add_argument("--format", choices=("markdown", "json"), default="markdown")
    report.add_argument("--out", default="", help="Optional report output path")
    report.add_argument("--gate-home", default="", help="Optional gate store directory")
    report.set_defaults(func=_cmd_report)

    resolve = subparsers.add_parser("resolve", help="Resolve one evidence item with a user answer or reference.")
    resolve.add_argument("--analysis", required=True, help="Analysis JSON path")
    resolve.add_argument("--evidence-id", required=True, help="Evidence id to resolve")
    resolve.add_argument(
        "--resolution",
        required=True,
        choices=("PROVIDE_VALUE", "USE_REFERENCE", "PRESERVE_AS_IS", "USER_STATEMENT"),
    )
    resolve.add_argument("--value", default=None, help="Resolved value (JSON scalar/string)")
    resolve.add_argument("--user-statement", default="", help="User's exact statement")
    resolve.add_argument("--source", default="user_answer", help="Evidence source label")
    resolve.add_argument("--out", default="", help="Optional updated analysis path")
    resolve.set_defaults(func=_cmd_resolve)

    supplement = subparsers.add_parser(
        "apply-supplement",
        help="Apply a TemplateSemanticSupplement 1.0 batch to an analysis.",
    )
    supplement.add_argument("--analysis", required=True, help="Analysis JSON path")
    supplement.add_argument("--template", required=True, help="Template .docx path")
    supplement.add_argument("--supplement", required=True, help="Supplement JSON path")
    supplement.add_argument("--out", default="", help="Optional updated analysis path")
    supplement.set_defaults(func=_cmd_apply_supplement)

    confirm = subparsers.add_parser("confirm", help="Confirm a reviewed analysis and persist a Gate Record.")
    confirm.add_argument("--analysis", required=True, help="Analysis JSON path")
    confirm.add_argument("--review-token", required=True, help="Token printed by the report command")
    confirm.add_argument("--user-statement", required=True, help="User's exact confirmation statement")
    confirm.add_argument("--confirmed-by", default="USER", help="USER or USER_CLI")
    confirm.add_argument("--ttl-seconds", type=int, default=None, help="Gate record lifetime")
    confirm.add_argument("--gate-home", default="", help="Optional gate store directory")
    confirm.add_argument("--out-record", default="", help="Optional gate record JSON path")
    confirm.set_defaults(func=_cmd_confirm)

    reject = subparsers.add_parser("reject", help="Record an explicit user rejection.")
    reject.add_argument("--analysis", required=True, help="Analysis JSON path")
    reject.add_argument("--user-statement", default="", help="User's rejection statement")
    reject.add_argument("--gate-home", default="", help="Optional gate store directory")
    reject.add_argument("--out-record", default="", help="Optional gate record JSON path")
    reject.set_defaults(func=_cmd_reject)

    status = subparsers.add_parser("status", help="Print an analysis summary or a gate record.")
    status.add_argument("--analysis", default="", help="Analysis JSON path")
    status.add_argument("--gate", default="", help="Gate record id")
    status.add_argument("--gate-home", default="", help="Optional gate store directory")
    status.set_defaults(func=_cmd_status)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
