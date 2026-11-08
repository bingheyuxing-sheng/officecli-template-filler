# -*- coding: utf-8 -*-
"""POLISH mode: OfficeCLI-backed surgical wording edits on one DOCX.

Planning is read-only and happens before any mutation. Every edit is resolved
to exactly one OfficeCLI target:

* a run path (``/body/p[3]/r[2]``) when the replaced text lives entirely in one
  direct run, which preserves every sibling run and its formatting;
* a paragraph path (``/body/p[3]``) only when the span crosses runs that carry
  identical ``w:rPr``, so merging them cannot change the rendered layout.

A span that crosses differently formatted runs is refused instead of letting
officecli rebuild the paragraph and silently drop bold/italic/colour.
"""

from __future__ import annotations

import shutil
from typing import Any, Dict, List, Optional, Sequence, Tuple

import docx
from docx.oxml.ns import qn
from lxml import etree

from .officecli_writer import (
    UnsupportedLocation,
    build_set_command,
    close,
    get_text,
    location_to_path,
    restore_paragraph_identity,
    run_batch,
)
from .ooxml_utils import LogicalParagraphView, iter_all_document_paragraphs_with_Wait_context


class PolishPlanningError(ValueError):
    """An edit cannot be expressed without changing layout or formatting."""

    def __init__(self, code: str, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


class PolishExecutionError(RuntimeError):
    """OfficeCLI accepted the batch but the read-back did not confirm the edit."""

    def __init__(self, code: str, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


# ---------------------------------------------------------------------------
# input normalisation
# ---------------------------------------------------------------------------


def _as_text(value: Any) -> str:
    return "" if value is None else str(value)


def normalize_edits(edits: Any) -> List[Dict[str, Any]]:
    """Accept a list, ``{"edits": [...]}`` or a single edit object."""
    if isinstance(edits, dict):
        edits = edits.get("edits", [])
    if not isinstance(edits, list):
        raise PolishPlanningError(
            "POLISH_EDITS_INVALID",
            "edits must be a list of {old_text, new_text, ...} objects",
        )
    normalized = []
    for index, item in enumerate(edits, 1):
        if not isinstance(item, dict):
            raise PolishPlanningError(
                "POLISH_EDITS_INVALID",
                "edit %d is not an object" % index,
            )
        old_text = _as_text(item.get("old_text"))
        if not old_text:
            raise PolishPlanningError(
                "POLISH_EDITS_INVALID",
                "edit %d has an empty old_text" % index,
                {"edit_index": index},
            )
        normalized.append({
            "old_text": old_text,
            "new_text": _as_text(item.get("new_text")),
            "location_id": _as_text(item.get("location_id")),
            "occurrence": item.get("occurrence"),
            "reason": _as_text(item.get("reason")),
        })
    return normalized


def normalize_terms(terms: Any) -> List[Tuple[str, str]]:
    """Accept a ``{old: new}`` map, a list of pairs, or ``{"terms": {...}}``."""
    if terms is None:
        return []
    if isinstance(terms, dict) and "terms" in terms:
        terms = terms.get("terms")
    if isinstance(terms, dict):
        pairs = list(terms.items())
    elif isinstance(terms, list):
        pairs = []
        for item in terms:
            if isinstance(item, dict):
                pairs.append((item.get("old_text", item.get("old")), item.get("new_text", item.get("new"))))
            elif isinstance(item, (list, tuple)) and len(item) == 2:
                pairs.append((item[0], item[1]))
            else:
                raise PolishPlanningError(
                    "POLISH_TERMS_INVALID",
                    "terms must be a {old: new} map or a list of pairs",
                )
    else:
        raise PolishPlanningError(
            "POLISH_TERMS_INVALID",
            "terms must be a {old: new} map or a list of pairs",
        )
    normalized = []
    for old, new in pairs:
        old_text = _as_text(old)
        if old_text:
            normalized.append((old_text, _as_text(new)))
    return normalized


def load_polish_inputs(path: str) -> Dict[str, Any]:
    """Load one JSON file carrying either ``edits`` or ``terms``."""
    import json

    with open(path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if isinstance(payload, list):
        return {"edits": normalize_edits(payload), "terms": []}
    if not isinstance(payload, dict):
        raise PolishPlanningError("POLISH_EDITS_INVALID", "input JSON must be an object or a list")
    return {
        "edits": normalize_edits(payload.get("edits", [])),
        "terms": normalize_terms(payload.get("terms")),
    }


# ---------------------------------------------------------------------------
# paragraph / run resolution
# ---------------------------------------------------------------------------


def _collect_paragraphs(document) -> Dict[str, Any]:
    paragraphs: Dict[str, Any] = {}
    for context in iter_all_document_paragraphs_with_Wait_context(document):
        if context.get("scope") not in ("body", "table"):
            continue
        paragraphs[context["location_id"]] = context["paragraph"]
    return paragraphs


def _direct_run_index(paragraph_el, run_el) -> Optional[int]:
    runs = paragraph_el.findall(qn("w:r"))
    if run_el in runs:
        return runs.index(run_el) + 1
    return None


def _rpr_signature(run_el) -> str:
    rpr = run_el.find(qn("w:rPr"))
    return etree.tostring(rpr, encoding="unicode") if rpr is not None else ""


def _run_text(run_el) -> str:
    return "".join(node.text or "" for node in run_el.findall(qn("w:t")))


def _span_runs(view: LogicalParagraphView, start: int, end: int) -> List[Any]:
    seen: List[Any] = []
    for node in view.char_map[start:end]:
        if node.r_el not in seen:
            seen.append(node.r_el)
    return seen


def _find_spans(text: str, token: str) -> List[Tuple[int, int]]:
    spans: List[Tuple[int, int]] = []
    start = 0
    while True:
        index = text.find(token, start)
        if index < 0:
            return spans
        spans.append((index, index + len(token)))
        start = index + max(1, len(token))


def _unsupported_location(location_id: str, message: str) -> PolishPlanningError:
    return PolishPlanningError(
        "POLISH_LOCATION_UNSUPPORTED",
        message,
        {"location_id": location_id},
    )


def _officecli_path(location_id: str) -> str:
    try:
        return location_to_path(location_id)
    except UnsupportedLocation as exc:
        raise _unsupported_location(location_id, str(exc)) from exc


def _single_occurrence_command(
    paragraph,
    location_id: str,
    old_text: str,
    new_text: str,
    occurrence: Optional[int],
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Resolve one explicit edit to a command plus its plan descriptor."""
    view = LogicalParagraphView(paragraph._p)
    spans = _find_spans(view.logical_text, old_text)
    if not spans:
        raise PolishPlanningError(
            "POLISH_EDIT_NOT_FOUND",
            "old_text not found in %s" % location_id,
            {"location_id": location_id, "old_text": old_text},
        )

    if occurrence is not None:
        try:
            occurrence = int(occurrence)
        except (TypeError, ValueError):
            raise PolishPlanningError(
                "POLISH_EDITS_INVALID",
                "occurrence must be an integer",
                {"location_id": location_id, "occurrence": occurrence},
            )
        if occurrence < 1 or occurrence > len(spans):
            raise PolishPlanningError(
                "POLISH_OCCURRENCE_OUT_OF_RANGE",
                "occurrence %d is outside the %d match(es) in %s"
                % (occurrence, len(spans), location_id),
                {"location_id": location_id, "occurrence": occurrence, "matches": len(spans)},
            )
        chosen = spans[occurrence - 1]
    else:
        if len(spans) > 1:
            raise PolishPlanningError(
                "POLISH_EDIT_AMBIGUOUS",
                "old_text occurs %d times in %s; add location_id or occurrence"
                % (len(spans), location_id),
                {"location_id": location_id, "matches": len(spans)},
            )
        chosen = spans[0]

    start, end = chosen
    runs = _span_runs(view, start, end)
    paragraph_path = _officecli_path(location_id)

    if len(runs) == 1:
        run_el = runs[0]
        run_index = _direct_run_index(paragraph._p, run_el)
        if run_index is not None and _run_text(run_el).count(old_text) == 1:
            path = "%s/r[%d]" % (paragraph_path, run_index)
            return (
                build_set_command(path, old_text, new_text),
                {
                    "location_id": location_id,
                    "path": path,
                    "read_path": paragraph_path,
                    "scope": "run",
                    "run_index": run_index,
                },
            )

    if len(spans) > 1:
        raise PolishPlanningError(
            "POLISH_OCCURRENCE_UNSUPPORTED",
            "old_text occurs %d times in %s and the selected occurrence cannot be "
            "isolated in one run; officecli would replace every match"
            % (len(spans), location_id),
            {"location_id": location_id, "matches": len(spans)},
        )

    if any(run_el.getparent() is not paragraph._p for run_el in runs):
        raise PolishPlanningError(
            "POLISH_UNSUPPORTED_RUN",
            "old_text in %s sits in a hyperlink, field or nested run; "
            "officecli cannot target it without rebuilding that construct" % location_id,
            {"location_id": location_id},
        )

    signatures = {_rpr_signature(run_el) for run_el in runs}
    if len(signatures) == 1:
        return (
            build_set_command(paragraph_path, old_text, new_text),
            {
                "location_id": location_id,
                "path": paragraph_path,
                "read_path": paragraph_path,
                "scope": "paragraph",
                "run_index": None,
            },
        )

    raise PolishPlanningError(
        "POLISH_CROSS_RUN_FORMATTING",
        "old_text in %s spans runs with different formatting; officecli would "
        "rebuild the paragraph and lose that formatting" % location_id,
        {"location_id": location_id, "run_count": len(runs)},
    )


def _term_commands(paragraph, location_id: str, old_text: str, new_text: str) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """Resolve one glossary term inside one paragraph to zero or more commands."""
    view = LogicalParagraphView(paragraph._p)
    spans = _find_spans(view.logical_text, old_text)
    if not spans:
        return [], None

    paragraph_path = _officecli_path(location_id)
    run_indexes: List[int] = []
    cross_spans: List[Tuple[int, int]] = []
    for start, end in spans:
        runs = _span_runs(view, start, end)
        if len(runs) == 1:
            run_index = _direct_run_index(paragraph._p, runs[0])
            if run_index is not None:
                if run_index not in run_indexes:
                    run_indexes.append(run_index)
                continue
        cross_spans.append((start, end))

    commands: List[Dict[str, Any]] = [
        build_set_command("%s/r[%d]" % (paragraph_path, run_index), old_text, new_text)
        for run_index in run_indexes
    ]
    if not cross_spans:
        return commands, None

    if commands:
        return commands, (
            "%s: %d occurrence(s) of %r cross runs and were left unchanged"
            % (location_id, len(cross_spans), old_text)
        )

    signatures = set()
    for start, end in cross_spans:
        for run_el in _span_runs(view, start, end):
            if run_el.getparent() is not paragraph._p:
                return [], (
                    "%s: %r sits in a hyperlink, field or nested run and was left unchanged"
                    % (location_id, old_text)
                )
            signatures.add(_rpr_signature(run_el))
    if len(signatures) == 1:
        return [build_set_command(paragraph_path, old_text, new_text)], None
    return [], (
        "%s: %r crosses differently formatted runs and was left unchanged"
        % (location_id, old_text)
    )


# ---------------------------------------------------------------------------
# plan
# ---------------------------------------------------------------------------


def build_polish_plan(
    target_path: str,
    edits: Sequence[Dict[str, Any]],
    terms: Sequence[Tuple[str, str]] = (),
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Return ``(public_plan, payload)``; payload carries the officecli commands."""
    document = docx.Document(target_path)
    paragraphs = _collect_paragraphs(document)

    commands: List[Dict[str, Any]] = []
    entries: List[Dict[str, Any]] = []
    warnings: List[str] = []
    limitations: List[str] = []
    strip_red: List[Tuple[str, int]] = []

    for index, edit in enumerate(edits, 1):
        old_text = edit["old_text"]
        new_text = edit["new_text"]
        if "\n" in new_text or "\r" in new_text:
            raise PolishPlanningError(
                "POLISH_NEW_TEXT_MULTILINE",
                "edit %d would insert a paragraph break and change the layout" % index,
                {"edit_index": index},
            )
        if old_text == new_text:
            entries.append({
                "edit_id": "E%d" % index,
                "source": "explicit",
                "status": "SKIPPED",
                "reason": edit.get("reason") or "old_text equals new_text",
                "old_text": old_text,
                "new_text": new_text,
            })
            continue

        location_id = edit.get("location_id") or ""
        if location_id:
            paragraph = paragraphs.get(location_id)
            if paragraph is None:
                raise PolishPlanningError(
                    "POLISH_LOCATION_UNRESOLVED",
                    "location %r did not resolve to a body or table paragraph" % location_id,
                    {"location_id": location_id},
                )
            candidates = [(location_id, paragraph)]
        else:
            candidates = [
                (loc, paragraph)
                for loc, paragraph in paragraphs.items()
                if old_text in LogicalParagraphView(paragraph._p).logical_text
            ]
            if not candidates:
                raise PolishPlanningError(
                    "POLISH_EDIT_NOT_FOUND",
                    "old_text %r was not found in any body or table paragraph" % old_text,
                    {"old_text": old_text},
                )
            if len(candidates) > 1:
                raise PolishPlanningError(
                    "POLISH_EDIT_AMBIGUOUS",
                    "old_text %r occurs in %d paragraphs; add location_id"
                    % (old_text, len(candidates)),
                    {"old_text": old_text, "locations": [loc for loc, _ in candidates[:20]]},
                )

        loc, paragraph = candidates[0]
        command, descriptor = _single_occurrence_command(
            paragraph, loc, old_text, new_text, edit.get("occurrence")
        )
        commands.append(command)
        entry = {
            "edit_id": "E%d" % index,
            "source": "explicit",
            "status": "PLANNED",
            "reason": edit.get("reason") or "",
            "old_text": old_text,
            "new_text": new_text,
        }
        entry.update(descriptor)
        entries.append(entry)
        if descriptor["scope"] == "run" and descriptor.get("run_index"):
            strip_red.append((descriptor["location_id"], descriptor["run_index"]))

    term_index = 0
    for old_text, new_text in terms:
        if not old_text or old_text == new_text:
            continue
        if "\n" in new_text or "\r" in new_text:
            warnings.append(
                "term %r was skipped: the replacement contains a paragraph break" % old_text
            )
            limitations.append("POLISH_TERM_SKIPPED: %s (multiline replacement)" % old_text)
            continue
        applied_any = False
        for location_id, paragraph in paragraphs.items():
            term_commands, warning = _term_commands(paragraph, location_id, old_text, new_text)
            if warning:
                warnings.append(warning)
                limitations.append("POLISH_TERM_SKIPPED: %s" % warning)
            if not term_commands:
                continue
            applied_any = True
            for command in term_commands:
                term_index += 1
                commands.append(command)
                run_index = None
                path = str(command.get("path") or "")
                if "/r[" in path:
                    try:
                        run_index = int(path.rsplit("/r[", 1)[1].rstrip("]"))
                    except (TypeError, ValueError):
                        run_index = None
                entry = {
                    "edit_id": "T%d" % term_index,
                    "source": "terms",
                    "status": "PLANNED",
                    "reason": "glossary term",
                    "old_text": old_text,
                    "new_text": new_text,
                    "location_id": location_id,
                    "path": path,
                    "read_path": _officecli_path(location_id),
                    "scope": "run" if run_index else "paragraph",
                    "run_index": run_index,
                }
                entries.append(entry)
                if run_index:
                    strip_red.append((location_id, run_index))
        if not applied_any:
            limitations.append("POLISH_TERM_UNUSED: %s" % old_text)

    public_plan = {
        "schema_version": "1.0",
        "task_mode": "POLISH",
        "target_docx": target_path,
        "backend": "officecli",
        "edits": entries,
        "summary": {
            "requested_edits": len(edits),
            "term_rules": len(terms),
            "planned": sum(1 for entry in entries if entry["status"] == "PLANNED"),
            "skipped": sum(1 for entry in entries if entry["status"] != "PLANNED"),
        },
        "warnings": warnings,
        "limitations": limitations,
    }
    payload = {
        "commands": commands,
        "strip_red": strip_red,
    }
    return public_plan, payload


# ---------------------------------------------------------------------------
# execution
# ---------------------------------------------------------------------------


def execute_polish_plan(
    target_path: str,
    stage_path: str,
    plan: Dict[str, Any],
    payload: Dict[str, Any],
    *,
    strip_red: bool = False,
) -> Dict[str, Any]:
    """Apply the batch to a staged copy, read back, then normalise identity."""
    commands = list(payload.get("commands") or [])
    shutil.copyfile(target_path, stage_path)
    if commands:
        try:
            run_batch(stage_path, commands)
        finally:
            close(stage_path)

    applied = 0
    failed = 0
    verification: List[Dict[str, Any]] = []
    for entry in plan.get("edits") or []:
        if entry.get("status") != "PLANNED":
            continue
        read_path = entry.get("read_path")
        try:
            after_text = get_text(stage_path, read_path)
        except Exception as exc:  # officecli read failure is a hard failure
            entry["status"] = "FAILED"
            failed += 1
            verification.append({
                "edit_id": entry.get("edit_id"),
                "status": "FAILED",
                "path": read_path,
                "detail": "%s: %s" % (type(exc).__name__, exc),
            })
            continue
        still_present = entry.get("old_text") in after_text
        entry["status"] = "FAILED" if still_present else "APPLIED"
        entry["after_text"] = after_text
        if still_present:
            failed += 1
        else:
            applied += 1
        verification.append({
            "edit_id": entry.get("edit_id"),
            "status": entry["status"],
            "path": read_path,
        })

    close(stage_path)
    if failed:
        raise PolishExecutionError(
            "POLISH_READBACK_FAILED",
            "%d edit(s) were not confirmed by officecli read-back" % failed,
            {"verification": verification},
        )

    strip_targets = payload.get("strip_red") if strip_red else None
    restore_paragraph_identity(
        target_path,
        stage_path,
        strip_red_runs=strip_targets,
    )

    return {
        "backend": "officecli",
        "commands": len(commands),
        "applied": applied,
        "failed": failed,
        "verification": verification,
        "strip_red": bool(strip_red),
    }


__all__ = [
    "PolishExecutionError",
    "PolishPlanningError",
    "build_polish_plan",
    "execute_polish_plan",
    "load_polish_inputs",
    "normalize_edits",
    "normalize_terms",
]
