#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CLI entrypoint: Generate a filled document from a template and a JSON replacement map.
Usage:
    python scripts/generate_document.py --template <template.docx> --data <data.json> --out <output.docx>
        [--writer officecli|python-docx] [--allow-writer-fallback]
    python scripts/generate_document.py --template <template.docx> --spec <spec.json> --plan <fill_plan.json> --out <output.docx> [--mode STRICT|STANDARD] [--allow-unverified]

The output is staged in a sibling temp file and only published after QA passes.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

import docx
from engine import (
    DocumentTransaction,
    TaskResourceGuard,
    TransactionAborted,
    TransactionPreflightError,
    LogicalParagraphView,
    iter_all_document_paragraphs_with_Wait_context,
    sanitize_ooxml_whitespace_and_pagination,
    audit_docx_package_integrity,
    audit_format_and_text_qa,
    release_office_file_locks,
    install_auto_cleanup,
)
from engine.cli_io import configure_stdio


def _same_path(left: str, right: str) -> bool:
    return os.path.normcase(os.path.abspath(left)) == os.path.normcase(
        os.path.abspath(right)
    )


def _check_legacy_gate(args) -> int:
    from template_gate.errors import TemplateGateError
    from template_gate.validator import require_confirmed_gate

    try:
        require_confirmed_gate(args.template, "GENERATE", gate_record=args.gate_record or None)
    except TemplateGateError as exc:
        print(json.dumps({
            "output": args.out,
            "error": exc.code,
            "message": exc.message,
            "details": exc.details,
            "next_action": "ASK_USER / RUN_TEMPLATE_GATE",
        }, ensure_ascii=False, indent=2))
        return 2
    return 0


def _run_legacy_data_path_python_docx(args, *, fallback_reason=None) -> int:
    """v3.5.9 token replacement path; now an explicit compatibility backend."""
    gate_status = _check_legacy_gate(args)
    if gate_status:
        return gate_status

    with open(args.data, "r", encoding="utf-8") as f:
        data_map = json.load(f)

    tokens_map = data_map.get("tokens", data_map)
    replaced_count = 0
    package_qa = None
    qa_report = None
    tx = DocumentTransaction(args.template, args.out, task_mode="GENERATE")

    try:
        with tx:
            with TaskResourceGuard() as guard:
                doc = docx.Document(args.template)
                for ctx in iter_all_document_paragraphs_with_Wait_context(doc):
                    p_el = ctx["p_el"]
                    view = LogicalParagraphView(p_el)
                    for token, replacement in tokens_map.items():
                        if token in view.logical_text:
                            replaced_count += view.replace_all_tokens(str(token), str(replacement), strip_red=True)

                sanitize_ooxml_whitespace_and_pagination(doc)
                doc.save(tx.stage())

                # Transaction QA must cover both the package and the rendered content:
                # a format-only gate would publish a structurally broken DOCX as PASSED.
                package_qa = audit_docx_package_integrity(tx.temp_path)
                qa_report = audit_format_and_text_qa(
                    doc,
                    docx_path=tx.temp_path,
                    reference_docx_path=args.template,
                    raise_on_failure=False,
                    comparison_profile="STYLE_GUIDE",
                )
                tx.record_qa(package_qa, qa_report)
                release_office_file_locks(guard=guard)
            tx.commit()
    except TransactionPreflightError as exc:
        print(json.dumps({
            "output": args.out,
            "error": str(exc),
            "transaction": tx.record(),
        }, ensure_ascii=False, indent=2))
        return 2
    except TransactionAborted as exc:
        print(json.dumps({
            "output": args.out,
            "replaced_occurrences": replaced_count,
            "error": str(exc),
            "qa_status": tx.qa_status,
            "qa_issues": list((package_qa or {}).get("issues", []))
                         + list((qa_report or {}).get("issues", [])),
            "transaction": tx.record(),
        }, ensure_ascii=False, indent=2))
        return 1

    print(json.dumps({
        "output": args.out,
        "replaced_occurrences": replaced_count,
        "writer_backend": "python-docx",
        "writer_fallback": fallback_reason,
        "package_qa_passed": bool((package_qa or {}).get("passed")),
        "qa_passed": tx.qa_status == "PASSED",
        "qa_status": tx.qa_status,
        "transaction": tx.record(),
    }, ensure_ascii=False, indent=2))
    return 0


def _run_legacy_data_path_officecli(args) -> int:
    """Legacy token map, executed as one atomic OfficeCLI batch."""
    from document_engine.legacy_tokens import (
        build_legacy_token_plan,
        red_targets_after_batch,
    )
    from engine import officecli_writer
    from engine.officecli_runtime import OfficecliError

    gate_status = _check_legacy_gate(args)
    if gate_status:
        return gate_status

    with open(args.data, "r", encoding="utf-8") as f:
        data_map = json.load(f)
    tokens_map = data_map.get("tokens", data_map)

    try:
        officecli_writer.preflight()
    except OfficecliError as exc:
        if getattr(args, "allow_writer_fallback", False):
            return _run_legacy_data_path_python_docx(
                args,
                fallback_reason={
                    "code": getattr(exc, "code", "OFFICECLI_UNAVAILABLE"),
                    "message": str(exc),
                },
            )
        print(json.dumps({
            "output": args.out,
            "error": getattr(exc, "code", "OFFICECLI_UNAVAILABLE"),
            "message": str(exc),
            "writer_backend": "officecli",
            "next_action": "INSTALL_OFFICECLI_OR_PASS_WRITER_PYTHON_DOCX",
        }, ensure_ascii=False, indent=2))
        return 2

    try:
        story_map = officecli_writer.build_story_map(args.template)
    except OfficecliError as exc:
        print(json.dumps({
            "output": args.out,
            "error": getattr(exc, "code", "OFFICECLI_READ_FAILED"),
            "message": str(exc),
            "writer_backend": "officecli",
        }, ensure_ascii=False, indent=2))
        return 2

    plan = build_legacy_token_plan(args.template, tokens_map, story_map)
    if plan.unsupported:
        if getattr(args, "allow_writer_fallback", False):
            return _run_legacy_data_path_python_docx(
                args,
                fallback_reason={
                    "code": "WRITER_LOCATION_UNSUPPORTED",
                    "message": "OfficeCLI cannot address every token paragraph",
                    "locations": plan.unsupported,
                },
            )
        print(json.dumps({
            "output": args.out,
            "error": "WRITER_LOCATION_UNSUPPORTED",
            "message": (
                "OfficeCLI cannot address every paragraph that contains a token; "
                "pass --writer python-docx or --allow-writer-fallback"
            ),
            "writer_backend": "officecli",
            "details": {"locations": plan.unsupported},
            "next_action": "PASS_WRITER_PYTHON_DOCX_OR_ALLOW_WRITER_FALLBACK",
        }, ensure_ascii=False, indent=2))
        return 2

    replaced_count = plan.occurrences
    package_qa = None
    qa_report = None
    tx = DocumentTransaction(args.template, args.out, task_mode="GENERATE")

    try:
        with tx:
            with TaskResourceGuard() as guard:
                try:
                    shutil.copy2(args.template, tx.stage())
                    if plan.commands:
                        officecli_writer.run_batch(tx.stage(), plan.commands)
                except (OSError, OfficecliError) as exc:
                    print(json.dumps({
                        "output": args.out,
                        "error": getattr(exc, "code", "OFFICECLI_WRITE_FAILED"),
                        "message": str(exc),
                        "writer_backend": "officecli",
                        "transaction": tx.record(),
                    }, ensure_ascii=False, indent=2))
                    return 2
                finally:
                    officecli_writer.close(tx.stage())

                try:
                    red_targets = red_targets_after_batch(
                        tx.stage(), plan.affected
                    )
                    officecli_writer.restore_paragraph_identity(
                        args.template, tx.stage(), strip_red_runs=red_targets
                    )
                except Exception as exc:
                    print(json.dumps({
                        "output": args.out,
                        "error": "OFFICECLI_NORMALIZE_FAILED",
                        "message": "officecli output could not be normalised: "
                                   "{}: {}".format(type(exc).__name__, exc),
                        "writer_backend": "officecli",
                        "transaction": tx.record(),
                    }, ensure_ascii=False, indent=2))
                    return 2

                try:
                    doc = docx.Document(tx.stage())
                    package_qa = audit_docx_package_integrity(tx.temp_path)
                    qa_report = audit_format_and_text_qa(
                        doc,
                        docx_path=tx.temp_path,
                        reference_docx_path=args.template,
                        raise_on_failure=False,
                        comparison_profile="STYLE_GUIDE",
                    )
                    tx.record_qa(package_qa, qa_report)
                    release_office_file_locks(guard=guard)
                except Exception as exc:
                    print(json.dumps({
                        "output": args.out,
                        "error": "EXECUTION_FAILED",
                        "message": "{}: {}".format(type(exc).__name__, exc),
                        "writer_backend": "officecli",
                        "transaction": tx.record(),
                    }, ensure_ascii=False, indent=2))
                    return 2
            tx.commit()
    except TransactionPreflightError as exc:
        print(json.dumps({
            "output": args.out,
            "error": str(exc),
            "transaction": tx.record(),
        }, ensure_ascii=False, indent=2))
        return 2
    except TransactionAborted as exc:
        print(json.dumps({
            "output": args.out,
            "replaced_occurrences": replaced_count,
            "error": str(exc),
            "writer_backend": "officecli",
            "qa_status": tx.qa_status,
            "qa_issues": list((package_qa or {}).get("issues", []))
                         + list((qa_report or {}).get("issues", [])),
            "transaction": tx.record(),
        }, ensure_ascii=False, indent=2))
        return 1

    print(json.dumps({
        "output": args.out,
        "replaced_occurrences": replaced_count,
        "writer_backend": "officecli",
        "writer_fallback": None,
        "package_qa_passed": bool((package_qa or {}).get("passed")),
        "qa_passed": tx.qa_status == "PASSED",
        "qa_status": tx.qa_status,
        "transaction": tx.record(),
    }, ensure_ascii=False, indent=2))
    return 0


def _run_legacy_data_path(args) -> int:
    if getattr(args, "writer", "officecli") == "python-docx":
        return _run_legacy_data_path_python_docx(args)
    return _run_legacy_data_path_officecli(args)


def _run_plan_path(args) -> int:
    """v4.0 FillPlan path: delegate all work to the deterministic executor."""
    from document_engine import generate_document_v4

    with open(args.spec, "r", encoding="utf-8") as f:
        spec = json.load(f)
    with open(args.plan, "r", encoding="utf-8") as f:
        fill_plan = json.load(f)

    content_plan = None
    if getattr(args, "content_plan", None):
        with open(args.content_plan, "r", encoding="utf-8") as f:
            content_plan = json.load(f)

    if args.mode:
        fill_plan = dict(fill_plan)
        fill_plan["mode"] = args.mode

    result = generate_document_v4(
        args.template,
        spec,
        content_plan,
        fill_plan,
        args.out,
        allow_unverified=args.allow_unverified,
        gate_record=args.gate_record or None,
        writer=args.writer,
        allow_writer_fallback=args.allow_writer_fallback,
        qa_report_path=args.qa_report or None,
        require_content_approval=bool(content_plan is not None),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result.get("status") in ("SUCCESS", "UNVERIFIED"):
        return 0
    return 2 if result.get("status") == "BLOCKED" else 1


def main() -> int:
    configure_stdio()
    install_auto_cleanup()
    parser = argparse.ArgumentParser(description="Fill a Word template non-destructively using LogicalParagraphView.")
    parser.add_argument("--template", required=True, help="Input .docx template path")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--data", "--payload", dest="data", help="JSON file containing token->value replacement map")
    source.add_argument("--plan", help="FillPlan 4.0 JSON file (requires --spec)")
    parser.add_argument("--out", "--output", dest="out", required=True, help="Output .docx path")
    parser.add_argument("--spec", help="DocumentSpec 4.0 JSON file used with --plan")
    parser.add_argument("--content-plan", dest="content_plan",
                        help="Optional ContentPlan 4.0 JSON file used with --plan")
    parser.add_argument("--mode", choices=("STRICT", "STANDARD"), help="Override the FillPlan gate mode")
    parser.add_argument("--gate-record", default="", help="Optional Template Understanding Gate record path/id")
    parser.add_argument("--allow-unverified", dest="allow_unverified", action="store_true",
                        help="STANDARD only: commit a QA UNVERIFIED report that discloses missing checks")
    parser.add_argument("--writer", choices=("python-docx", "officecli"), default="officecli",
                        help="Mutation backend for --plan and --data (default: officecli). "
                             "The OfficeCLI path applies the whole mutation as one atomic "
                             "batch and blocks when a location or token cannot be expressed "
                             "faithfully; python-docx is the explicit legacy backend")
    parser.add_argument("--allow-writer-fallback", dest="allow_writer_fallback",
                        action="store_true",
                        help="Explicitly allow a whole-document python-docx fallback when "
                             "OfficeCLI cannot express the plan or token map "
                             "(recorded in writer_fallback)")
    parser.add_argument("--qa-report", default="",
                        help="Optional QAReport sidecar path for later run_qa.py --reuse-report "
                             "(requires --plan)")
    args = parser.parse_args()

    if args.data and args.qa_report:
        parser.error(
            "--qa-report requires --plan; the legacy --data path does not produce "
            "a QAReport 4.0 sidecar"
        )
    if args.qa_report and (
        _same_path(args.qa_report, args.template) or _same_path(args.qa_report, args.out)
    ):
        parser.error("--qa-report must not overwrite --template or --out")

    # W3-7: the user template passes the pre-parse quota on BOTH paths
    # (--data legacy and --plan v4) before any parser touches the file.
    from engine.package_guard import check_package, load_limits

    verdict = check_package(args.template, load_limits())
    if not verdict["ok"]:
        print(json.dumps({"output": args.out, "error": verdict["code"],
                          "package_guard": verdict}, ensure_ascii=False))
        return 2

    if args.plan:
        if not args.spec:
            parser.error("--plan requires --spec")
        if args.writer == "officecli":
            from engine.officecli_runtime import OfficecliError
            from engine import officecli_writer

            try:
                officecli_writer.preflight()
            except OfficecliError as exc:
                print(json.dumps({
                    "output": args.out,
                    "error": getattr(exc, "code", "OFFICECLI_UNAVAILABLE"),
                    "message": str(exc),
                    "next_action": "INSTALL_OFFICECLI_OR_PASS_WRITER_PYTHON_DOCX",
                }, ensure_ascii=False, indent=2))
                return 2
        return _run_plan_path(args)
    return _run_legacy_data_path(args)


if __name__ == "__main__":
    raise SystemExit(main())
