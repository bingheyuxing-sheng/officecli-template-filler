# -*- coding: utf-8 -*-
"""Deterministic document-logic checks used by PROOFREAD.

These checks do not pretend to understand prose. They only flag structural facts that can
be verified mechanically:

- the same long paragraph appears more than once;
- a heading is immediately followed by a same-or-higher heading with no body;
- an Arabic-numbered list skips a number (`1.` `2.` `4.`);
- a labelled start date is later than the labelled end date.

Every finding is evidence for a human decision, never an automatic rewrite.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

from .alignment import is_heading_paragraph

_LIST_NUMBER_RE = re.compile(r"^\s*(\d{1,2})\s*[.、．)]\s+\S")
_DATE_RE = re.compile(r"(\d{4})\s*[年\-/]\s*(\d{1,2})\s*[月\-/]\s*(\d{1,2})")
_START_LABELS = ("开始日期", "起始日期", "开工日期", "起始时间", "开始时间")
_END_LABELS = ("结束日期", "截止日期", "竣工日期", "结束时间", "截止时间")

_SEVERITY_HIGH = "high"
_SEVERITY_MEDIUM = "medium"
_SEVERITY_LOW = "low"


def _issue(code: str, location: str, detail: str, severity: str) -> Dict[str, Any]:
    return {
        "code": code,
        "location": location,
        "detail": detail,
        "severity": severity,
        "source": "logic_qa",
    }


def _heading_level(paragraph) -> int:
    try:
        name = str(getattr(paragraph.style, "name", "") or "").strip().lower()
    except Exception:
        name = ""
    match = re.search(r"(?:heading|标题)\s*([1-9])", name)
    if match:
        return int(match.group(1))
    if "heading" in name or "标题" in name:
        return 1
    p_pr = paragraph._p.pPr
    if p_pr is not None:
        outline = p_pr.find("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}outlineLvl")
        if outline is not None:
            try:
                return int(outline.get("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}val") or 0) + 1
            except (TypeError, ValueError):
                return 1
    return 0


def _parse_date(text: str, labels: Tuple[str, ...]) -> Optional[date]:
    pattern = r"(?:" + "|".join(re.escape(label) for label in labels) + r")\s*[：:]\s*"
    match = re.search(pattern + _DATE_RE.pattern, text or "")
    if not match:
        return None
    try:
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None


def _duplicate_paragraph_issues(paragraphs) -> List[Dict[str, Any]]:
    issues: List[Dict[str, Any]] = []
    first_seen: Dict[str, str] = {}
    for index, paragraph in enumerate(paragraphs):
        if is_heading_paragraph(paragraph):
            continue
        text = re.sub(r"\s+", "", paragraph.text or "")
        if len(text) < 20:
            continue
        location = f"body.p[{index}]"
        if text in first_seen:
            issues.append(_issue(
                "LOGIC_DUPLICATE_PARAGRAPH",
                location,
                f"与 {first_seen[text]} 内容完全重复，请确认是否应删除",
                _SEVERITY_MEDIUM,
            ))
        else:
            first_seen[text] = location
    return issues


def _empty_section_issues(paragraphs) -> List[Dict[str, Any]]:
    issues: List[Dict[str, Any]] = []
    heading_indices = [
        index for index, paragraph in enumerate(paragraphs)
        if is_heading_paragraph(paragraph)
    ]
    for position, index in enumerate(heading_indices[:-1]):
        next_index = heading_indices[position + 1]
        level = _heading_level(paragraphs[index])
        next_level = _heading_level(paragraphs[next_index])
        has_body = any(
            (paragraphs[cursor].text or "").strip()
            for cursor in range(index + 1, next_index)
        )
        if not has_body and next_level <= level:
            issues.append(_issue(
                "LOGIC_EMPTY_SECTION",
                f"body.p[{index}]",
                f"标题“{(paragraphs[index].text or '').strip()}”下没有正文，紧接着是同级或更高级标题",
                _SEVERITY_LOW,
            ))
    return issues


def _list_gap_issues(paragraphs) -> List[Dict[str, Any]]:
    issues: List[Dict[str, Any]] = []
    previous: Optional[int] = None
    previous_location = ""
    for index, paragraph in enumerate(paragraphs):
        if is_heading_paragraph(paragraph):
            previous = None
            continue
        match = _LIST_NUMBER_RE.match(paragraph.text or "")
        if not match:
            previous = None
            continue
        number = int(match.group(1))
        location = f"body.p[{index}]"
        if previous is not None and number > previous + 1:
            issues.append(_issue(
                "LOGIC_LIST_SEQUENCE_GAP",
                location,
                f"编号从 {previous} 直接跳到 {number}（上一项在 {previous_location}）",
                _SEVERITY_LOW,
            ))
        previous = number
        previous_location = location
    return issues


def _date_range_issues(paragraphs) -> List[Dict[str, Any]]:
    issues: List[Dict[str, Any]] = []
    all_starts: List[Tuple[date, str]] = []
    all_ends: List[Tuple[date, str]] = []

    for index, paragraph in enumerate(paragraphs):
        text = paragraph.text or ""
        start = _parse_date(text, _START_LABELS)
        end = _parse_date(text, _END_LABELS)
        location = f"body.p[{index}]"
        if start:
            all_starts.append((start, location))
        if end:
            all_ends.append((end, location))
        if start and end and start > end:
            issues.append(_issue(
                "LOGIC_DATE_RANGE_INVALID",
                location,
                f"开始日期 {start.isoformat()} 晚于结束日期 {end.isoformat()}",
                _SEVERITY_HIGH,
            ))

    # Only compare document-wide when each side is unambiguous; multiple candidates are
    # separate schedules, not one broken range.
    if len(all_starts) == 1 and len(all_ends) == 1:
        start, start_location = all_starts[0]
        end, end_location = all_ends[0]
        if start > end and start_location != end_location:
            issues.append(_issue(
                "LOGIC_DATE_RANGE_INVALID",
                start_location,
                f"开始日期 {start.isoformat()}（{start_location}）晚于结束日期 {end.isoformat()}（{end_location}）",
                _SEVERITY_HIGH,
            ))
    return issues


def audit_logic(doc) -> Dict[str, Any]:
    """Run every deterministic logic check against a python-docx document."""
    paragraphs = list(doc.paragraphs)
    issues: List[Dict[str, Any]] = []
    issues.extend(_duplicate_paragraph_issues(paragraphs))
    issues.extend(_empty_section_issues(paragraphs))
    issues.extend(_list_gap_issues(paragraphs))
    issues.extend(_date_range_issues(paragraphs))
    return {
        "passed": not issues,
        "issues": issues,
        "issue_count": len(issues),
        "checked_paragraphs": len(paragraphs),
    }
