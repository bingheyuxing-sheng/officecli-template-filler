#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CLI entrypoint: Render a .docx document for Visual QA (structural layout checks + optional PDF conversion).
Usage:
    python scripts/render_document.py <input.docx> [--reference <ref.docx>] [--outdir <dir>]

With --outdir the rendered PDF is a deliverable: it is produced in a staging directory
and only moved into --outdir after QA. Without --outdir nothing is published.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from engine import (
    DocumentTransaction,
    TransactionAborted,
    TransactionPreflightError,
    install_auto_cleanup,
    run_visual_layout_qa,
)
from engine.package_guard import reject_first_package


def main() -> int:
    install_auto_cleanup()
    parser = argparse.ArgumentParser(description="Run Visual Layout QA and optional PDF rendering.")
    parser.add_argument("docx_path", help="Path to .docx file")
    parser.add_argument("--reference", default=None, help="Optional reference .docx path")
    parser.add_argument("--outdir", default=None, help="Optional output directory for PDF")
    args = parser.parse_args()

    rejected = reject_first_package({"document": args.docx_path, "reference": args.reference})
    if rejected:
        print(json.dumps(rejected, ensure_ascii=False))
        return 2

    outdir = os.path.abspath(args.outdir) if args.outdir else None
    final_pdf = None
    if outdir:
        os.makedirs(outdir, exist_ok=True)
        stem = os.path.splitext(os.path.basename(args.docx_path))[0]
        final_pdf = os.path.join(outdir, stem + ".pdf")

    tx = DocumentTransaction(args.docx_path, final_pdf, task_mode="RENDER")
    staging_dir = tempfile.mkdtemp(prefix=".render-tx-", dir=outdir) if outdir else None
    report = {}
    try:
        with tx:
            report = run_visual_layout_qa(
                args.docx_path,
                reference_docx_path=args.reference,
                output_dir=staging_dir,
            )
            if staging_dir:
                produced = report.get("pdf_path")
                if produced and os.path.isfile(produced):
                    os.replace(produced, tx.stage())
            tx.record_qa(report)
            tx.commit()
    except (TransactionPreflightError, TransactionAborted) as exc:
        report["pdf_path"] = None
        report["error"] = str(exc)
        report["transaction"] = tx.record()
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 2 if isinstance(exc, TransactionPreflightError) else 1
    finally:
        if staging_dir:
            shutil.rmtree(staging_dir, ignore_errors=True)

    if outdir:
        report["pdf_path"] = tx.output_path
    report["transaction"] = tx.record()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if (tx.committed or not outdir) and tx.qa_status != "FAILED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
