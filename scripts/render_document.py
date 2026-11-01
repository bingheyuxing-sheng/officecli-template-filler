#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CLI entrypoint: Render a .docx document for Visual QA (structural layout checks + optional PDF conversion).
Usage:
    python scripts/render_document.py <input.docx> [--reference <ref.docx>] [--outdir <dir>]
"""

from __future__ import annotations

import argparse
import json
import os
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from engine import run_visual_layout_qa, install_auto_cleanup


def main() -> int:
    install_auto_cleanup()
    parser = argparse.ArgumentParser(description="Run Visual Layout QA and optional PDF rendering.")
    parser.add_argument("docx_path", help="Path to .docx file")
    parser.add_argument("--reference", default=None, help="Optional reference .docx path")
    parser.add_argument("--outdir", default=None, help="Optional output directory for PDF")
    args = parser.parse_args()

    report = run_visual_layout_qa(
        args.docx_path,
        reference_docx_path=args.reference,
        output_dir=args.outdir,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
