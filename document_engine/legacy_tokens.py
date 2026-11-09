# -*- coding: utf-8 -*-
"""OfficeCLI planning for the legacy ``--data`` token replacement path.

The legacy path predates FillPlan and accepts a flat ``{token: value}`` map.
Discovery stays read-only: a python-docx walker identifies the paragraphs that
contain tokens, then every mutation is expressed as an OfficeCLI ``set`` on a
DOM path. Paragraphs the runtime cannot address (text boxes, SDTs, individual
footnote/endnote paragraphs) are reported instead of being silently skipped.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence

import docx
from docx.oxml.ns import qn

from engine.officecli_runtime import UnsupportedLocation, location_to_path
from engine.ooxml_utils import (
    LogicalParagraphView,
    is_red_run,
    iter_all_document_paragraphs_with_Wait_context,
)


@dataclass
class LegacyTokenPlan:
    commands: List[Dict[str, Any]] = field(default_factory=list)
    occurrences: int = 0
    affected: List[Dict[str, Any]] = field(default_factory=list)
    unsupported: List[Dict[str, Any]] = field(default_factory=list)


def _token_items(tokens_map: Mapping[str, Any]) -> List[tuple[str, str]]:
    items: List[tuple[str, str]] = []
    for key, value in (tokens_map or {}).items():
        token = str(key)
        if token:
            items.append((token, "" if value is None else str(value)))
    return items


def _token_anchor(
    paragraph,
    view: LogicalParagraphView,
    token: str,
) -> tuple[bool, str]:
    index = view.logical_text.find(token)
    if index < 0 or index >= len(view.char_map):
        return False, ""
    run = view.char_map[index].r_el
    text = "".join(node.text or "" for node in run.findall(qn("w:t")))
    return is_red_run(run, paragraph), text


def build_legacy_token_plan(
    template_path: str,
    tokens_map: Mapping[str, Any],
    story_map: Optional[Mapping[str, str]] = None,
) -> LegacyTokenPlan:
    """Translate one legacy token map into an atomic OfficeCLI batch plan."""
    document = docx.Document(template_path)
    plan = LegacyTokenPlan()
    tokens = _token_items(tokens_map)
    if not tokens:
        return plan

    for context in iter_all_document_paragraphs_with_Wait_context(document):
        paragraph = context["paragraph"]
        view = LogicalParagraphView(context["p_el"])
        text = view.logical_text
        if not text:
            continue

        pending: List[Dict[str, Any]] = []
        for token, replacement in tokens:
            count = text.count(token)
            if not count:
                continue
            strip_red, anchor_text = _token_anchor(paragraph, view, token)
            pending.append({
                "token": token,
                "replacement": replacement,
                "count": count,
                "strip_red": strip_red,
                "anchor_text": anchor_text,
            })
            text = text.replace(token, replacement)
        if not pending:
            continue

        location_id = context["location_id"]
        try:
            path = location_to_path(location_id, story_map)
        except UnsupportedLocation as exc:
            plan.unsupported.append({
                "location_id": location_id,
                "tokens": [item["token"] for item in pending],
                "message": str(exc),
            })
            continue

        for item in pending:
            plan.commands.append({
                "command": "set",
                "path": path,
                "props": {
                    "find": item["token"],
                    "replace": item["replacement"],
                },
            })
            plan.occurrences += int(item["count"])
            plan.affected.append({
                "location_id": location_id,
                "path": path,
                "token": item["token"],
                "replacement": item["replacement"],
                "count": item["count"],
                "strip_red": item["strip_red"],
                "anchor_text": item["anchor_text"],
            })

    return plan


def red_targets_after_batch(
    staged_path: str,
    affected: Sequence[Mapping[str, Any]],
) -> List[tuple[str, int]]:
    """Find replacement runs that kept the template's red placeholder colour.

    OfficeCLI moves the replacement text into the anchor run and preserves that
    run's ``rPr``. Only runs whose source anchor was red are returned, so a
    legitimate red run elsewhere in the paragraph is never touched.
    """
    candidates = [
        item
        for item in affected
        if item.get("strip_red") and str(item.get("replacement") or "")
    ]
    if not candidates:
        return []

    document = docx.Document(staged_path)
    paragraphs: Dict[str, Any] = {}
    for context in iter_all_document_paragraphs_with_Wait_context(document):
        paragraphs.setdefault(context["location_id"], context["paragraph"])

    targets: List[tuple[str, int]] = []
    seen = set()
    for item in candidates:
        location_id = str(item.get("location_id") or "")
        replacement = str(item.get("replacement") or "")
        anchor_text = str(item.get("anchor_text") or "")
        paragraph = paragraphs.get(location_id)
        if paragraph is None:
            continue
        for index, run in enumerate(paragraph._p.findall(qn("w:r")), start=1):
            text = "".join(node.text or "" for node in run.findall(qn("w:t")))
            if not text:
                continue
            if replacement and replacement in text:
                matched = True
            elif anchor_text and text in anchor_text:
                matched = True
            else:
                matched = False
            if not matched:
                continue
            key = (location_id, index)
            if key not in seen:
                seen.add(key)
                targets.append(key)
            break
    return targets
