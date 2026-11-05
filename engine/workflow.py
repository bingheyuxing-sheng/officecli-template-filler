# -*- coding: utf-8 -*-
"""Deterministic workflow orchestration helpers.

SKILL.md describes a P2 confirmation gate, FAST/STANDARD/FULL execution profiles,
four staged checkpoints and a TOC degradation chain. Those are agent-level decisions, but
their policy and state transitions can still be deterministic and testable. This module
implements them without adding CLI flags: the agent decides when to call a helper, and the
helper returns a stable, auditable result.

Modules:
- `resolve_confirmation_gate()` — pick SKIP / LIGHT_CONFIRM / FULL_CONFIRM / HOLD_AND_ASK.
- `resolve_execution_profile()` / `profile_requirements()` — FAST / STANDARD / FULL.
- `WorkflowCheckpointStore` — persist content/tables/images/toc stage checkpoints.
- `assess_toc()` / `toc_degradation_chain()` — detect stale or missing TOC state.
- `run_visual_qa_rounds()` — bounded multi-round visual QA with a caller-supplied mutator.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Sequence

import docx
from docx.oxml.ns import qn

from .alignment import is_heading_paragraph as _is_heading_paragraph

CONFIRMATION_SKIP = "SKIP"
CONFIRMATION_LIGHT = "LIGHT_CONFIRM"
CONFIRMATION_FULL = "FULL_CONFIRM"
CONFIRMATION_HOLD = "HOLD_AND_ASK"
CONFIRMATION_TIERS = (
    CONFIRMATION_SKIP,
    CONFIRMATION_LIGHT,
    CONFIRMATION_FULL,
    CONFIRMATION_HOLD,
)

EXECUTION_PROFILES = ("FAST", "STANDARD", "FULL")
PROFILE_REQUIREMENTS: Dict[str, Dict[str, Any]] = {
    "FAST": {
        "fill_confirmed_slots_only": True,
        "fill_all_native_tables": False,
        "redraw_placeholder_images": False,
        "visual_qa_rounds": 1,
        "requires_coverage_for_omissions": True,
    },
    "STANDARD": {
        "fill_confirmed_slots_only": False,
        "fill_all_native_tables": True,
        "redraw_placeholder_images": False,
        "visual_qa_rounds": 1,
        "requires_coverage_for_omissions": False,
    },
    "FULL": {
        "fill_confirmed_slots_only": False,
        "fill_all_native_tables": True,
        "redraw_placeholder_images": True,
        "visual_qa_rounds": 2,
        "requires_coverage_for_omissions": False,
    },
}

CHECKPOINT_STAGES = ("content", "tables", "images", "toc")
CHECKPOINT_VALID_STATUSES = ("PASSED", "PENDING_HUMAN_REVIEW")
CHECKPOINT_STATUSES = CHECKPOINT_VALID_STATUSES + ("UNVERIFIED", "FAILED")

TOC_ACTUAL = "TOC_ACTUAL"
TOC_STALE = "TOC_STALE"
TOC_MISSING = "TOC_MISSING"
TOC_UNVERIFIED = "TOC_UNVERIFIED"
TOC_STATUSES = (TOC_ACTUAL, TOC_STALE, TOC_MISSING, TOC_UNVERIFIED)

_TOC_ERROR_MARKERS = (
    "错误！未定义书签",
    "錯誤！未定義書籤",
    "Error! Bookmark not defined",
    "未找到目录项",
)
_TOC_TRAILING_PAGE_RE = re.compile(r"[\t\.·…\s]+\d+\s*$")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(path: Optional[str]) -> Optional[str]:
    if not path or not os.path.isfile(path):
        return None
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


# ---------------------------------------------------------------------------
# P2 confirmation gate
# ---------------------------------------------------------------------------


def resolve_confirmation_gate(
    *,
    slots: Optional[Sequence[Dict[str, Any]]] = None,
    compatibility_level: str = "L1",
    blocking_conflicts: Optional[Sequence[Any]] = None,
    optional_choices: Optional[Sequence[Any]] = None,
    user_requested_skip: bool = False,
) -> Dict[str, Any]:
    """Pick the confirmation tier for a task from deterministic evidence.

    Priority: blocking conflicts / L4 > MUST_ASK_USER slots > explicit user skip >
    optional choices > SKIP. `MUST_ASK_USER` always wins over "just generate": an
    unsearchable internal fact must be asked for or explicitly left blank.
    """
    slot_list = list(slots or [])
    conflicts = list(blocking_conflicts or [])
    optional = list(optional_choices or [])
    must_ask = [
        slot for slot in slot_list
        if str(slot.get("confirmation_tier") or "") == "MUST_ASK_USER"
    ]
    is_l4 = str(compatibility_level or "").strip().upper() == "L4"

    if conflicts or is_l4:
        reasons = []
        if conflicts:
            reasons.append(f"blocking_conflicts:{len(conflicts)}")
        if is_l4:
            reasons.append("template_level_L4")
        return {
            "tier": CONFIRMATION_HOLD,
            "reasons": reasons,
            "ask_items": conflicts or slot_list,
            "must_ask_count": len(must_ask),
        }
    if must_ask:
        return {
            "tier": CONFIRMATION_FULL,
            "reasons": [f"must_ask_slots:{len(must_ask)}"],
            "ask_items": must_ask,
            "must_ask_count": len(must_ask),
        }
    if user_requested_skip:
        return {
            "tier": CONFIRMATION_SKIP,
            "reasons": ["user_requested_skip"],
            "ask_items": [],
            "must_ask_count": 0,
        }
    if optional:
        return {
            "tier": CONFIRMATION_LIGHT,
            "reasons": [f"optional_choices:{len(optional)}"],
            "ask_items": optional,
            "must_ask_count": 0,
        }
    return {
        "tier": CONFIRMATION_SKIP,
        "reasons": ["no_open_decisions"],
        "ask_items": [],
        "must_ask_count": 0,
    }


# ---------------------------------------------------------------------------
# Execution profiles
# ---------------------------------------------------------------------------


def resolve_execution_profile(
    requested: Optional[str] = None,
    *,
    has_placeholder_images: bool = False,
) -> str:
    """Return the effective profile; placeholder figures force FULL."""
    profile = str(requested or "STANDARD").strip().upper()
    if profile not in EXECUTION_PROFILES:
        raise ValueError(f"unknown execution profile: {requested!r}")
    if has_placeholder_images:
        return "FULL"
    return profile


def profile_requirements(profile: str) -> Dict[str, Any]:
    """Return a copy of the requirements for one profile."""
    key = str(profile or "").strip().upper()
    if key not in PROFILE_REQUIREMENTS:
        raise ValueError(f"unknown execution profile: {profile!r}")
    return dict(PROFILE_REQUIREMENTS[key])


# ---------------------------------------------------------------------------
# Staged checkpoints
# ---------------------------------------------------------------------------


class WorkflowCheckpointStore:
    """Persist per-task stage checkpoints as one atomic JSON file.

    A checkpoint records the stage, input/output hashes, QA status, issues and coverage
    gaps. `latest_valid()` only accepts PASSED / PENDING_HUMAN_REVIEW, so a failed or
    unverified stage is never used as a resume point.
    """

    def __init__(self, work_dir: str, task_id: str = "default") -> None:
        safe = "".join(
            char if char.isalnum() or char in "-_." else "_"
            for char in str(task_id or "default")
        ) or "default"
        os.makedirs(work_dir, exist_ok=True)
        self.task_id = safe
        self.path = os.path.join(work_dir, f"officecli_checkpoints_{safe}.json")

    def load(self) -> Dict[str, Any]:
        if not os.path.isfile(self.path):
            return {"schema_version": "1.0", "task_id": self.task_id, "stages": {}}
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                state = json.load(handle)
        except (OSError, ValueError):
            return {"schema_version": "1.0", "task_id": self.task_id, "stages": {}}
        if not isinstance(state, dict):
            state = {}
        state.setdefault("schema_version", "1.0")
        state.setdefault("task_id", self.task_id)
        if not isinstance(state.get("stages"), dict):
            state["stages"] = {}
        return state

    def record(
        self,
        stage: str,
        *,
        input_path: Optional[str] = None,
        output_path: Optional[str] = None,
        qa_status: str = "PASSED",
        issues: Optional[Sequence[Any]] = None,
        coverage_gaps: Optional[Sequence[Any]] = None,
    ) -> Dict[str, Any]:
        if stage not in CHECKPOINT_STAGES:
            raise ValueError(f"unknown checkpoint stage: {stage!r}")
        status = str(qa_status or "").strip().upper()
        if status not in CHECKPOINT_STATUSES:
            raise ValueError(f"unknown QA status: {qa_status!r}")

        entry = {
            "stage": stage,
            "input_sha256": _sha256(input_path),
            "output_sha256": _sha256(output_path),
            "qa_status": status,
            "issues": list(issues or []),
            "coverage_gaps": list(coverage_gaps or []),
            "recorded_at": _now(),
        }
        state = self.load()
        state["stages"][stage] = entry
        state["updated_at"] = entry["recorded_at"]
        self._write(state)
        return dict(entry)

    def latest_valid(self) -> Optional[Dict[str, Any]]:
        state = self.load()
        for stage in reversed(CHECKPOINT_STAGES):
            entry = state["stages"].get(stage)
            if entry and entry.get("qa_status") in CHECKPOINT_VALID_STATUSES:
                return dict(entry)
        return None

    def resume_stage(self) -> str:
        """Return the next stage to run, or `deliver` when every stage is valid."""
        latest = self.latest_valid()
        if latest is None:
            return CHECKPOINT_STAGES[0]
        index = CHECKPOINT_STAGES.index(latest["stage"])
        if index + 1 >= len(CHECKPOINT_STAGES):
            return "deliver"
        return CHECKPOINT_STAGES[index + 1]

    def clear(self) -> None:
        try:
            os.remove(self.path)
        except OSError:
            pass

    def _write(self, state: Dict[str, Any]) -> None:
        staged = self.path + ".tmp"
        with open(staged, "w", encoding="utf-8") as handle:
            json.dump(state, handle, ensure_ascii=False, indent=2)
        os.replace(staged, self.path)


# ---------------------------------------------------------------------------
# TOC assessment
# ---------------------------------------------------------------------------


def is_heading_paragraph(paragraph) -> bool:
    """True for real headings; TOC and caption styles are deliberately excluded.

    Delegates to :func:`engine.alignment.is_heading_paragraph`: the structural
    helper lives there so that logic QA does not depend on workflow. Kept here
    as the public workflow API, backed by the single implementation.
    """
    return _is_heading_paragraph(paragraph)


def _toc_paragraphs(document) -> List[Any]:
    result = []
    for paragraph in document.paragraphs:
        try:
            name = str(getattr(paragraph.style, "name", "") or "").strip().upper()
        except Exception:
            name = ""
        has_field = any(
            "TOC" in (node.text or "").upper()
            for node in paragraph._p.xpath(".//w:instrText")
        )
        for field in paragraph._p.xpath(".//w:fldSimple"):
            if "TOC" in str(field.get(qn("w:instr")) or "").upper():
                has_field = True
        if name.startswith("TOC") or has_field:
            result.append(paragraph)
    return result


def _entry_text(paragraph) -> str:
    # Field results can live inside `w:fldSimple`, so `paragraph.text` (direct runs only)
    # may be empty even though the cached TOC text is present.
    text = "".join(node.text or "" for node in paragraph._p.xpath(".//w:t")).strip()
    if not text:
        text = (paragraph.text or "").strip()
    return _TOC_TRAILING_PAGE_RE.sub("", text).strip()


def assess_toc(document) -> Dict[str, Any]:
    """Classify the document's table of contents as actual / stale / missing / unverified."""
    headings = [
        (paragraph.text or "").strip()
        for paragraph in document.paragraphs
        if is_heading_paragraph(paragraph) and (paragraph.text or "").strip()
    ]
    toc_paragraphs = _toc_paragraphs(document)
    entries = [entry for entry in (_entry_text(p) for p in toc_paragraphs) if entry]

    if not toc_paragraphs:
        return {
            "status": TOC_MISSING,
            "heading_count": len(headings),
            "entry_count": 0,
            "missing_headings": headings,
            "evidence": "no TOC field or TOC-styled paragraph found",
        }

    if any(marker in entry for entry in entries for marker in _TOC_ERROR_MARKERS):
        return {
            "status": TOC_STALE,
            "heading_count": len(headings),
            "entry_count": len(entries),
            "missing_headings": [],
            "evidence": "TOC contains an undefined-bookmark error",
        }

    if not headings:
        return {
            "status": TOC_UNVERIFIED,
            "heading_count": 0,
            "entry_count": len(entries),
            "missing_headings": [],
            "evidence": "TOC exists but no heading paragraphs were found",
        }

    if not entries:
        return {
            "status": TOC_UNVERIFIED,
            "heading_count": len(headings),
            "entry_count": 0,
            "missing_headings": headings,
            "evidence": "TOC field has no cached result text",
        }

    missing = [
        heading for heading in headings
        if not any(heading[:20] in entry for entry in entries)
    ]
    if missing or len(entries) != len(headings):
        return {
            "status": TOC_STALE,
            "heading_count": len(headings),
            "entry_count": len(entries),
            "missing_headings": missing,
            "evidence": "cached TOC entries do not match current headings",
        }

    return {
        "status": TOC_ACTUAL,
        "heading_count": len(headings),
        "entry_count": len(entries),
        "missing_headings": [],
        "evidence": "cached TOC entries match current headings",
    }


def toc_degradation_chain(status: str) -> List[str]:
    """Ordered fallback actions for a TOC status."""
    key = str(status or "").strip().upper()
    if key not in TOC_STATUSES:
        raise ValueError(f"unknown TOC status: {status!r}")
    return {
        TOC_ACTUAL: [],
        TOC_STALE: ["UPDATE_FIELD", "RECOMPARE", "MANUAL_REVIEW_IF_UNCHANGED"],
        TOC_MISSING: ["GENERATE_TOC", "RECOMPARE", "MANUAL_REVIEW_IF_UNCHANGED"],
        TOC_UNVERIFIED: ["MANUAL_REVIEW"],
    }[key]


# ---------------------------------------------------------------------------
# Multi-round visual QA
# ---------------------------------------------------------------------------


def run_visual_qa_rounds(
    docx_path: str,
    reference_docx_path: Optional[str] = None,
    *,
    max_rounds: int = 1,
    mutator: Optional[Callable[[int, str], Optional[str]]] = None,
) -> Dict[str, Any]:
    """Run bounded visual QA rounds; `mutator(round, path)` returns the next file path.

    Without a mutator the function runs once and reports honestly. With one, it stops at
    the first round whose issues are all non-high, or at `max_rounds`.
    """
    from .qa_engine import run_visual_layout_qa

    rounds: List[Dict[str, Any]] = []
    current = docx_path
    limit = max(1, int(max_rounds))
    for round_index in range(limit):
        report = run_visual_layout_qa(
            current,
            reference_docx_path=reference_docx_path,
        )
        issues = list(report.get("issues") or [])
        rounds.append({
            "round": round_index + 1,
            "docx_path": current,
            "issues": issues,
            "coverage_gaps": list(report.get("coverage_gaps") or []),
            "unverified_count": int(report.get("unverified_count") or 0),
        })
        has_high = any(
            str(issue.get("severity") or "high").lower() == "high"
            for issue in issues
        )
        if not has_high or mutator is None:
            break
        updated = mutator(round_index + 1, current)
        if not updated:
            break
        current = updated

    return {
        "rounds": rounds,
        "final_path": current,
        "converged": not any(
            str(issue.get("severity") or "high").lower() == "high"
            for item in rounds
            for issue in item["issues"]
        ),
        "max_rounds": limit,
    }
