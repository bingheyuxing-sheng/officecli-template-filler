# -*- coding: utf-8 -*-
"""
v3.5 M3 — Task capability registry (single source of truth).

The router used to name seven modes while only some of them had a real handler, which
left the agent guessing which script to run. This module states, per mode, whether an
implementation exists and where it lives. Modes without a handler must be blocked in
automatic flows instead of silently falling back to `generate_document.py`.
"""

from __future__ import annotations

import os
from typing import Any, Dict, Iterable, List

SUPPORTED_INPUT_EXTENSIONS = (".docx", ".docm", ".xlsx", ".xlsm")

TASK_CAPABILITIES: Dict[str, Dict[str, Any]] = {
    "GENERATE": {"handler": "scripts/generate_document.py", "enabled": True},
    "EXCEL_GENERATE": {"handler": "scripts/generate_excel.py", "enabled": True},
    "REPAIR": {"handler": "scripts/repair_document.py", "enabled": True},
    "REVIEW": {"handler": "scripts/review_document.py", "enabled": True},
    "REFORMAT": {"handler": "scripts/reformat_document.py", "enabled": True},
    "POLISH": {"handler": "scripts/polish_document.py", "enabled": True},
    "MERGE": {"handler": "scripts/merge_documents.py", "enabled": True},
    "PROOFREAD": {"handler": "scripts/proofread_document.py", "enabled": True},
}


class CapabilityNotAvailable(RuntimeError):
    """Raised when an automatic flow reaches a task mode without an implementation."""


def get_capability(task_mode: str) -> Dict[str, Any]:
    """Describe what the given task mode can actually do."""
    entry = TASK_CAPABILITIES.get(task_mode)
    if entry is None:
        return {
            "task_mode": task_mode,
            "enabled": False,
            "handler": None,
            "reason": "UNKNOWN_TASK_MODE",
        }
    enabled = bool(entry.get("enabled"))
    return {
        "task_mode": task_mode,
        "enabled": enabled,
        "handler": entry.get("handler"),
        "reason": None if enabled else "CAPABILITY_NOT_AVAILABLE",
    }


def require_capability(task_mode: str) -> Dict[str, Any]:
    """Return the capability or raise when the mode cannot be executed yet."""
    capability = get_capability(task_mode)
    if not capability["enabled"]:
        raise CapabilityNotAvailable(
            f"{task_mode} has no implemented handler "
            f"(declared handler: {capability['handler'] or 'none'})"
        )
    return capability


def unsupported_inputs(paths: Iterable[str]) -> List[str]:
    """Files whose container this skill cannot read at all."""
    result = []
    for path in paths:
        extension = os.path.splitext(str(path))[1].lower()
        if extension not in SUPPORTED_INPUT_EXTENSIONS:
            result.append(str(path))
    return result
