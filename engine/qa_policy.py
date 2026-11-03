# -*- coding: utf-8 -*-
"""Shared QA severity and comparison-profile policy.

The QA engine reports useful advisory findings (layout drift on content that moved,
font availability, row-count changes). A report is only a hard failure when it contains
a `high` severity issue; medium/low findings stay visible as warnings instead of turning
every deliverable into `FAILED`.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

BLOCKING_SEVERITIES = frozenset({"high"})
COMPARISON_PROFILE_REPLICA = "REPLICA"
COMPARISON_PROFILE_STYLE_GUIDE = "STYLE_GUIDE"
COMPARISON_PROFILES = (COMPARISON_PROFILE_REPLICA, COMPARISON_PROFILE_STYLE_GUIDE)


def normalize_comparison_profile(value: Optional[str]) -> str:
    """Accept CLI spellings such as `style-guide` / `replica`."""
    normalized = str(value or "").strip().upper().replace("-", "_")
    if normalized in COMPARISON_PROFILES:
        return normalized
    if normalized in ("", "AUTO"):
        return ""
    raise ValueError(f"unknown comparison profile: {value}")


def resolve_comparison_profile(
    profile: Optional[str] = None,
    task_mode: Optional[str] = None,
    reference_provided: bool = False,
) -> str:
    """
    Pick REPLICA vs STYLE_GUIDE.

    - explicit `--profile` wins
    - REPAIR / REVIEW preserve the template order and compare as a replica
    - GENERATE / EXCEL_GENERATE treat the template as a style guide, because content volume
      and order are expected to change
    - when no task mode is supplied, a reference baseline means "style guide" (the common
      post-generation QA call); otherwise REPLICA keeps the legacy behaviour
    """
    explicit = normalize_comparison_profile(profile)
    if explicit:
        return explicit
    mode = str(task_mode or "").strip().upper()
    if mode in ("REPAIR", "REVIEW"):
        return COMPARISON_PROFILE_REPLICA
    if mode:
        return COMPARISON_PROFILE_STYLE_GUIDE
    return COMPARISON_PROFILE_STYLE_GUIDE if reference_provided else COMPARISON_PROFILE_REPLICA


def severity_of(issue: Dict[str, Any]) -> str:
    return str(issue.get("severity") or "high").strip().lower() or "high"


def split_issues(
    issues: Iterable[Dict[str, Any]],
    pending_codes: Sequence[str] = (),
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Return `(blocking, warnings, pending)` without dropping any finding."""
    pending_set = set(pending_codes)
    blocking: List[Dict[str, Any]] = []
    warnings: List[Dict[str, Any]] = []
    pending: List[Dict[str, Any]] = []
    for issue in issues:
        if not isinstance(issue, dict) or not issue.get("code"):
            continue
        if issue["code"] in pending_set:
            pending.append(issue)
        elif severity_of(issue) in BLOCKING_SEVERITIES:
            blocking.append(issue)
        else:
            warnings.append(issue)
    return blocking, warnings, pending


def has_blocking_issues(issues: Iterable[Dict[str, Any]], pending_codes: Sequence[str] = ()) -> bool:
    blocking, _warnings, _pending = split_issues(issues, pending_codes)
    return bool(blocking)


def warning_count(issues: Iterable[Dict[str, Any]], pending_codes: Sequence[str] = ()) -> int:
    _blocking, warnings, _pending = split_issues(issues, pending_codes)
    return len(warnings)
