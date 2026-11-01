#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CLI entrypoint: Dual-Document REPAIR Mode (v3.0).
Compares a Reference/Template .docx and a Broken/Target .docx, emits `repair_plan.json`,
and executes the repair non-destructively.

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

from engine import build_repair_plan, execute_repair_plan, audit_docx_package_integrity, install_auto_cleanup


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

    exec_result = execute_repair_plan(plan, args.out)
    pkg_qa = audit_docx_package_integrity(args.out)

    print(json.dumps({
        "plan_total_actions": plan["total_actions"],
        "execution": exec_result,
        "package_qa_passed": pkg_qa["passed"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
