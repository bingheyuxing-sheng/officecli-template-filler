#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CLI entrypoint: inspect `editor_sdk.exe` ownership evidence for a task.

WorkBuddy's sandbox keeps `editor_sdk.exe` alive after an agent turn ends, which leaves the
DOCX locked in WPS. Automatic cleanup in every entrypoint terminates only PIDs recorded as
spawned by that task. This diagnostic tool records a baseline and reports PIDs that appeared
afterwards; those PIDs are NOT terminated because a concurrent task may own them.

Usage:
    python scripts/cleanup_editor_sdk.py --start          # record baseline before the task
    python scripts/cleanup_editor_sdk.py --stop           # report new SDKs without terminating them
    python scripts/cleanup_editor_sdk.py --list           # just show current SDK PIDs
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from engine import EditorSdkSession, list_process_pids


def _default_state_path() -> str:
    """Task-scoped snapshot path so concurrent tasks cannot overwrite each other's baseline."""
    task_id = os.environ.get("OFFICECLI_TASK_ID", "default")
    safe_id = "".join(ch for ch in task_id if ch.isalnum() or ch in "-_") or "default"
    return os.path.join(tempfile.gettempdir(), f"officecli_editor_sdk_baseline_{safe_id}.json")


DEFAULT_STATE = _default_state_path()


def main() -> int:
    parser = argparse.ArgumentParser(description="Stop editor_sdk instances spawned by this task.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--start", action="store_true", help="Record the pre-task SDK PID snapshot")
    group.add_argument("--stop", action="store_true", help="Terminate SDKs spawned after the snapshot")
    group.add_argument("--list", action="store_true", help="List current editor_sdk PIDs")
    parser.add_argument("--state", default=DEFAULT_STATE, help="Snapshot file shared by --start and --stop")
    args = parser.parse_args()

    if args.list:
        print(json.dumps({"editor_sdk_pids": list_process_pids("editor_sdk.exe")}, ensure_ascii=False))
        return 0

    if args.start:
        baseline = list_process_pids("editor_sdk.exe")
        os.makedirs(os.path.dirname(os.path.abspath(args.state)), exist_ok=True)
        with open(args.state, "w", encoding="utf-8") as handle:
            json.dump({"baseline_pids": baseline}, handle)
        print(json.dumps({"baseline_pids": baseline, "state": args.state}, ensure_ascii=False))
        return 0

    if not os.path.exists(args.state):
        print(json.dumps({
            "error": "no baseline snapshot; run --start before the task",
            "state": args.state,
            "current_pids": list_process_pids("editor_sdk.exe"),
        }, ensure_ascii=False))
        return 2

    with open(args.state, "r", encoding="utf-8") as handle:
        baseline = json.load(handle).get("baseline_pids", [])

    session = EditorSdkSession(baseline_pids=baseline)
    result = session.stop_new_instances()
    try:
        os.remove(args.state)
    except OSError:
        pass

    if result.get("unowned_pids"):
        print(
            "NOTICE: unowned_pids are not proven to be spawned by this task and were left running: "
            + ", ".join(str(pid) for pid in result["unowned_pids"]),
            file=sys.stderr,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["verified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
