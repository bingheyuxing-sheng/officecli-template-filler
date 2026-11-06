# -*- coding: utf-8 -*-
"""Deterministic FillPlan 4.0 executor (W1-D).

The executor is the only component allowed to apply a FillPlan to a DOCX. It
follows the frozen pipeline:

    validate -> template SHA preflight -> preconditions -> locate -> mutate
    (staged) -> QA (staged) -> commit or abort

Nothing is written to the final delivery path directly: the document is saved
to ``DocumentTransaction.stage()`` and only published by ``tx.commit()`` after
QA produced an eligible report. Every operation, successful or not, is written
to a :class:`document_engine.fill_ledger.FillLedger`.

Status semantics follow Contract 05:

* ``BLOCKED`` — validation/precondition/locate failure before any mutation.
* ``FAILED``  — mutation attempted and discarded, or QA did not authorize delivery.
* ``SUCCESS`` — every operation applied and QA ``PASSED``; artifact published.
* ``UNVERIFIED`` — every operation applied, QA could not run all required checks,
  and STANDARD mode explicitly allowed the disclosed commit.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import docx

from engine import (
    DocumentTransaction,
    LogicalParagraphView,
    TransactionAborted,
    audit_docx_package_integrity,
    audit_format_and_text_qa,
    fill_cell_strict_style,
    fill_paragraph_strict_style,
    iter_all_document_paragraphs_with_Wait_context,
    iter_all_document_tables_with_context,
    replace_image_by_role,
    replace_inline_image_in_paragraph,
)
from content_intelligence import validate_content_plan, validate_fill_plan
from template_intelligence.spec_validator import validate_document_spec

from .fill_ledger import FillLedger

SCHEMA_VERSION = "4.0"
TASK_MODE = "GENERATE"
ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = ROOT / "config"

QA_PASSED = "PASSED"
QA_PENDING_HUMAN_REVIEW = "PENDING_HUMAN_REVIEW"
QA_UNVERIFIED = "UNVERIFIED"
QA_FAILED = "FAILED"

VALID_STATUSES = frozenset({QA_PASSED, QA_PENDING_HUMAN_REVIEW, QA_UNVERIFIED, QA_FAILED})
SEVERITIES = frozenset({"low", "medium", "high", "blocking"})

TASK_ID_RE = re.compile(r"^TASK_[0-9A-Za-z_-]{1,64}$")

USER_SOURCES = frozenset({"USER_INPUT", "IMAGE_INPUT"})

_EXECUTION_ERROR_CODE = "SLOT_LOCATION_UNRESOLVED"

# Abort reasons produced by the transaction-level QAReport gate (W2).
_GATE_ABORT_REASONS = frozenset({
    "QA_GATE_REJECTED",
    "QA_REPORT_STALE",
    "QA_TASK_BINDING_MISMATCH",
})

_REGISTRY_CACHE: Optional[Dict[str, Dict[str, Any]]] = None


# ---------------------------------------------------------------------------
# registry / envelope helpers
# ---------------------------------------------------------------------------


def _registry() -> Dict[str, Dict[str, Any]]:
    global _REGISTRY_CACHE
    if _REGISTRY_CACHE is None:
        try:
            with open(CONFIG_DIR / "error-codes.json", "r", encoding="utf-8") as handle:
                payload = json.load(handle)
            _REGISTRY_CACHE = {
                entry["code"]: entry
                for entry in payload.get("codes", [])
                if isinstance(entry, dict) and isinstance(entry.get("code"), str)
            }
        except (OSError, ValueError):
            _REGISTRY_CACHE = {}
    return _REGISTRY_CACHE


def _error_record(
    code: str,
    message: str,
    *,
    details: Optional[Dict[str, Any]] = None,
    severity: Optional[str] = None,
    retryable: Optional[bool] = None,
    rollback_required: Optional[bool] = None,
    human_intervention: Optional[bool] = None,
) -> Dict[str, Any]:
    """Build an envelope error record from the normative registry entry."""
    registry = _registry()
    if code not in registry:
        details = dict(details or {})
        details.setdefault("original_code", code)
        code = "INVALID_FILL_PLAN"
    entry = registry.get(code, {})
    resolved_severity = severity if severity in SEVERITIES else entry.get("severity", "high")
    if resolved_severity not in SEVERITIES:
        resolved_severity = "high"
    record: Dict[str, Any] = {
        "code": code,
        "message": str(message) if message else code,
        "severity": resolved_severity,
        "retryable": bool(entry.get("retryable", False)) if retryable is None else bool(retryable),
        "rollback_required": (
            bool(entry.get("rollback_required", False))
            if rollback_required is None
            else bool(rollback_required)
        ),
        "human_intervention": (
            bool(entry.get("human_intervention", False))
            if human_intervention is None
            else bool(human_intervention)
        ),
    }
    if details:
        record["details"] = details
    return record


def _validation_errors(report: Dict[str, Any], default_code: str) -> List[Dict[str, Any]]:
    """Map validator errors onto registered envelope codes.

    The frozen registry does not contain every validator rule name, so an
    unregistered rule collapses to the report-level code while its original
    identifier stays in ``details.validator_code``.
    """
    records: List[Dict[str, Any]] = []
    registry = _registry()
    for item in report.get("errors", []) or []:
        if not isinstance(item, dict):
            continue
        raw_code = item.get("code")
        code = raw_code if isinstance(raw_code, str) and raw_code in registry else default_code
        severity = item.get("severity")
        records.append(
            _error_record(
                code,
                item.get("detail") or code,
                details={"location": item.get("location"), "validator_code": raw_code},
                severity=severity if severity in SEVERITIES else None,
                rollback_required=False,
            )
        )
    return records


def _task_id(fill_plan: Any) -> str:
    if isinstance(fill_plan, dict):
        candidate = fill_plan.get("task_id")
        if isinstance(candidate, str) and TASK_ID_RE.match(candidate):
            return candidate
    return "TASK_INVALID_INPUT"


def _mode(fill_plan: Any) -> str:
    if isinstance(fill_plan, dict) and fill_plan.get("mode") in ("STRICT", "STANDARD"):
        return fill_plan["mode"]
    return "STRICT"


def _sha256_file(path: Any) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


# ---------------------------------------------------------------------------
# OOXML localisation helpers (reuse the v3.5.9 iterators)
# ---------------------------------------------------------------------------


def _paragraph_map(doc) -> Dict[str, Any]:
    paragraphs: Dict[str, Any] = {}
    for context in iter_all_document_paragraphs_with_Wait_context(doc):
        paragraphs.setdefault(context["location_id"], context["paragraph"])
    return paragraphs


def _table_map(doc) -> Dict[str, Any]:
    tables: Dict[str, Any] = {}
    for context in iter_all_document_tables_with_context(doc):
        tables.setdefault(context["table_id"], context["table"])
    return tables


_HEADER_FOOTER_NAMES = (
    "header", "first_page_header", "even_page_header",
    "footer", "first_page_footer", "even_page_footer",
)


def _header_footer_snapshot(doc) -> List[Tuple[Any, str, Optional[bool]]]:
    """Record linked/defined state without touching the parts themselves."""
    snapshot: List[Tuple[Any, str, Optional[bool]]] = []
    for section in doc.sections:
        for name in _HEADER_FOOTER_NAMES:
            header_footer = getattr(section, name, None)
            linked: Optional[bool] = None
            if header_footer is not None:
                try:
                    linked = bool(header_footer.is_linked_to_previous)
                except Exception:
                    linked = None
            snapshot.append((section, name, linked))
    return snapshot


def _restore_header_footer_state(snapshot: Sequence[Tuple[Any, str, Optional[bool]]]) -> None:
    """Re-link header/footer definitions that python-docx lazily created.

    The v3.5.9 story iterators read ``header.paragraphs``/``header.tables`` for
    every section, which makes python-docx materialize an empty header/footer
    part for a template that never had one. That part would otherwise be saved
    into the output and break the structural fidelity fingerprint, so any
    definition that did not exist before traversal is dropped again.
    """
    for section, name, linked in snapshot:
        if linked is None:
            continue
        header_footer = getattr(section, name, None)
        if header_footer is None:
            continue
        try:
            if linked and not header_footer.is_linked_to_previous:
                header_footer.is_linked_to_previous = True
        except Exception:
            continue


def _resolve_cell(table_map: Dict[str, Any], target: Dict[str, Any]):
    """Resolve a ``r[row].c[col]`` target against the physical grid.

    Slot locations use physical column numbers (``body.tbl[0].r[0].c[2]``), not
    dense indexes over unique cells: ``get_unique_row_cells`` collapses the
    duplicates a horizontal merge produces and shifts every later column.  A
    physical lookup returns the cell that actually covers the requested column
    (python-docx repeats a merged cell for every grid column it spans) and
    refuses a column outside the row instead of silently addressing a neighbour.
    ``row.cells`` is the exact mapping the location iterator uses, including
    vertical-merge continuations and rows that start late (``w:gridBefore``).
    """
    table = table_map.get(target.get("table_id"))
    if table is None:
        return None
    row_index = target.get("row")
    col_index = target.get("col")
    if not isinstance(row_index, int) or isinstance(row_index, bool):
        return None
    if not isinstance(col_index, int) or isinstance(col_index, bool):
        return None
    if row_index < 0 or row_index >= len(table.rows):
        return None
    cells = table.rows[row_index].cells
    if col_index < 0 or col_index >= len(cells):
        return None
    return cells[col_index]


def _region_matches(location: Any, region_location: Any) -> bool:
    if not isinstance(location, str) or not isinstance(region_location, str):
        return False
    return location == region_location or location.startswith(region_location + ".")


def _find_occurrence(text: str, token: Any, occurrence: Any) -> Optional[int]:
    """Offset of the ``occurrence``-th literal ``token`` in ``text`` (None when absent)."""
    if not isinstance(token, str) or not token:
        return None
    try:
        wanted = max(1, int(occurrence))
    except (TypeError, ValueError):
        wanted = 1
    cursor = 0
    last = -1
    for _ in range(wanted):
        last = text.find(token, cursor)
        if last == -1:
            return None
        cursor = last + len(token)
    return last


# ---------------------------------------------------------------------------
# preconditions
# ---------------------------------------------------------------------------


def _source_verified_failure(
    operation: Dict[str, Any], content_plan: Any
) -> Optional[Tuple[str, str, Dict[str, Any]]]:
    if not isinstance(content_plan, dict):
        return None
    source_ref = operation.get("source_ref")
    if not isinstance(source_ref, str) or not source_ref.strip():
        return None
    source_ref = source_ref.strip()
    if source_ref in USER_SOURCES:
        return None
    facts = [
        fact for fact in content_plan.get("facts", []) or []
        if isinstance(fact, dict) and fact.get("fact_id") == source_ref
    ]
    if not facts:
        return (
            "SOURCE_REF_MISSING",
            "source_ref {} is not declared in ContentPlan facts[]".format(source_ref),
            {"source_ref": source_ref, "op_id": operation.get("op_id")},
        )
    fact = facts[0]
    if fact.get("verification_status") != "VERIFIED":
        return (
            "SSOT_VALIDATION_FAILED",
            "source {} has verification_status {}; it is not VERIFIED".format(
                source_ref, fact.get("verification_status")
            ),
            {"source_ref": source_ref, "verification_status": fact.get("verification_status")},
        )
    return None


def _evaluate_preconditions(
    operation: Dict[str, Any],
    slot: Optional[Dict[str, Any]],
    spec: Dict[str, Any],
    actual_sha: str,
    declared_sha: str,
    content_plan: Any,
    region_warnings: List[Dict[str, Any]],
) -> Optional[Tuple[str, str, Dict[str, Any]]]:
    """Return ``(code, message, details)`` for the first unmet precondition."""
    target = operation.get("target") if isinstance(operation.get("target"), dict) else {}
    location_id = target.get("location_id")
    op_id = operation.get("op_id")
    checks = [item for item in (operation.get("preconditions") or []) if isinstance(item, str)]

    for check in checks:
        if check == "slot_exists":
            if slot is None:
                return (
                    "UNKNOWN_SLOT",
                    "Slot {} does not exist in DocumentSpec".format(operation.get("slot_id")),
                    {"slot_id": operation.get("slot_id"), "op_id": op_id},
                )
        elif check == "not_protected":
            if slot is not None and slot.get("protection_status") == "PROTECTED":
                return (
                    "PROTECTED_SLOT_VIOLATION",
                    "Operation {} targets protected slot {}".format(op_id, operation.get("slot_id")),
                    {"op_id": op_id, "slot_id": operation.get("slot_id")},
                )
            for region in spec.get("protected_regions", []) or []:
                if not isinstance(region, dict):
                    continue
                if not _region_matches(location_id, region.get("location_id")):
                    continue
                if region.get("severity") == "warning":
                    region_warnings.append(
                        {
                            "code": "PROTECTED_REGION_WARNING",
                            "region_id": region.get("region_id"),
                            "kind": region.get("kind"),
                            "location_id": region.get("location_id"),
                            "op_id": op_id,
                            "message": (
                                "Operation {} falls inside protected region {} ({}) "
                                "marked warning; filling continues".format(
                                    op_id, region.get("region_id"), region.get("location_id")
                                )
                            ),
                        }
                    )
                    continue
                return (
                    "PROTECTED_SLOT_VIOLATION",
                    "Operation {} falls inside blocking protected region {} ({})".format(
                        op_id, region.get("region_id"), region.get("location_id")
                    ),
                    {
                        "op_id": op_id,
                        "region_id": region.get("region_id"),
                        "location_id": region.get("location_id"),
                    },
                )
        elif check == "capacity_ok":
            hard_limit = None
            if slot is not None:
                capacity = slot.get("capacity")
                if isinstance(capacity, dict):
                    hard_limit = capacity.get("hard_limit")
            if isinstance(hard_limit, dict):
                measured = (operation.get("overflow") or {}).get("measured_chars")
                limit = hard_limit.get("value")
                if isinstance(measured, int) and isinstance(limit, int) and measured > limit:
                    return (
                        "CAPACITY_EXCEEDED",
                        "Operation {} measured {} > limit {}".format(op_id, measured, limit),
                        {"op_id": op_id, "measured": measured, "limit": limit},
                    )
        elif check == "source_verified":
            failure = _source_verified_failure(operation, content_plan)
            if failure is not None:
                return failure
        elif check == "template_sha_match":
            if actual_sha != declared_sha:
                return (
                    "TEMPLATE_SHA_MISMATCH",
                    "Declared {} does not match actual {}".format(declared_sha, actual_sha),
                    {"expected": declared_sha, "actual": actual_sha},
                )
    return None


def _overflow_failure(operation: Dict[str, Any]) -> Optional[Tuple[str, str, Dict[str, Any]]]:
    """Overflow is decided before mutation; the only strategy is REJECT."""
    overflow = operation.get("overflow") if isinstance(operation.get("overflow"), dict) else {}
    if overflow.get("limit_source") == "none":
        return None
    measured = overflow.get("measured_chars")
    limit = overflow.get("limit_value")
    if isinstance(measured, int) and isinstance(limit, int) and measured > limit:
        return (
            "CAPACITY_EXCEEDED",
            "Operation {} measured {} > limit {} (overflow strategy REJECT)".format(
                operation.get("op_id"), measured, limit
            ),
            {"op_id": operation.get("op_id"), "measured": measured, "limit": limit},
        )
    return None


# ---------------------------------------------------------------------------
# mutation
# ---------------------------------------------------------------------------


def _replace_span_in_place(
    view,
    start_idx: int,
    end_idx: int,
    value: str,
) -> bool:
    """Authorized text fill that never rewrites run formatting.

    ``replace_span`` places the value in the anchor ``w:t`` and only strips the red
    placeholder colour; every other ``rPr`` child (fonts, size, bold) is left byte
    identical and emptied runs are kept. That keeps ``structural_hash`` stable so
    FIDELITY does not report an authorized fill as an unauthorized template change.
    """
    return view.replace_span(
        start_idx,
        end_idx,
        value,
        strip_red_color=True,
        preserve_empty_runs=True,
    )


def _apply_operation(
    doc,
    operation: Dict[str, Any],
    slot: Dict[str, Any],
    paragraphs: Dict[str, Any],
    tables: Dict[str, Any],
    cell,
    *,
    remove_image_token: bool = True,
) -> Tuple[str, str]:
    """Apply one operation in place; return ``(before_text, after_text)``."""
    op_type = operation.get("type")
    target = operation.get("target") or {}
    location_id = target.get("location_id")
    value = str(operation.get("value"))
    placeholder_token = slot.get("matched_text")

    if op_type == "fill_cell":
        before = cell.text
        fill_cell_strict_style(cell, value, placeholder_token=placeholder_token)
        return before, cell.text

    paragraph = paragraphs.get(location_id)
    if paragraph is None:
        raise KeyError("location {} does not resolve".format(location_id))

    if op_type == "replace_text":
        view = LogicalParagraphView(paragraph._p)
        before = view.logical_text
        offset = _find_occurrence(before, placeholder_token, slot.get("occurrence"))
        if offset is not None:
            _replace_span_in_place(view, offset, offset + len(placeholder_token), value)
        elif before:
            # The slot token no longer exists in this paragraph: replace the
            # whole paragraph text in place instead of rebuilding it through the
            # v3 strict-style path, which would rewrite every run's ``rPr``.
            _replace_span_in_place(view, 0, len(before), value)
        else:
            fill_paragraph_strict_style(paragraph, value)
        after = LogicalParagraphView(paragraph._p).logical_text
        return before, after

    if op_type == "fill_paragraph":
        view = LogicalParagraphView(paragraph._p)
        before = view.logical_text
        if before:
            token = placeholder_token if placeholder_token and placeholder_token in before else before
            offset = _find_occurrence(before, token, slot.get("occurrence"))
            if offset is None:
                token = before
                offset = 0
            _replace_span_in_place(view, offset, offset + len(token), value)
        else:
            # An empty paragraph has no ``w:t`` to anchor the value; the strict-style
            # path is the only route that can create the run.
            fill_paragraph_strict_style(paragraph, value)
        after = LogicalParagraphView(paragraph._p).logical_text
        return before, after

    if op_type == "replace_image":
        before = paragraph.text
        role = target.get("image_role")
        try:
            replace_image_by_role(doc, role, value, fit_mode="fit_image")
        except ValueError as exc:
            # Several images share the role: fall back to the located paragraph.
            if "matched role" not in str(exc):
                raise
            replace_inline_image_in_paragraph(doc, paragraph, value, fit_mode="fit_image")
        # A token that marks an image slot ("{{图1}}" / "***") survives the image
        # swap and QA FORMAT reports it as TEMPLATE_TEXT_RESIDUAL.  Remove only
        # this slot's occurrence, surgically, so other runs and text stay intact.
        # A later text operation on the same slot consumes the token itself, so
        # removing it here would only turn that operation into a destructive
        # paragraph fill; defer to it instead.
        view = LogicalParagraphView(paragraph._p)
        if remove_image_token:
            offset = _find_occurrence(view.logical_text, placeholder_token, slot.get("occurrence"))
            if offset is not None:
                view.replace_span(offset, offset + len(placeholder_token), "",
                                  preserve_empty_runs=True)
        return before, view.logical_text

    raise ValueError("unsupported operation type {!r}".format(op_type))


# ---------------------------------------------------------------------------
# writer backends
# ---------------------------------------------------------------------------

_OFFICECLI_OPERATION_TYPES = ("replace_text", "fill_paragraph", "fill_cell")


def _officecli_operation_plan(
    pending: Sequence[Dict[str, Any]],
    slots: Dict[str, Any],
    paragraphs: Dict[str, Any],
    cells: Dict[str, Any],
) -> Tuple[List[Dict[str, Any]], Dict[str, Dict[str, Any]], Optional[str]]:
    """Translate operations into one atomic officecli batch.

    Returns ``(commands, plan_by_op, fallback_reason)``. A non-None
    ``fallback_reason`` means officecli cannot express this document faithfully
    and the caller must keep the python-docx writer for the whole document.

    officecli replaces text by rebuilding the target node. A paragraph-scoped
    ``set`` merges the paragraph's runs, which changes the structural tree; a
    run-scoped ``set`` (verified on 1.0.160) keeps every run, its order and its
    formatting. The plan therefore resolves the token to exactly one direct
    ``w:r`` and refuses the backend whenever the token spans runs, sits in a
    nested run, or appears more than once.
    """
    from docx.oxml.ns import qn

    from engine.officecli_writer import (  # noqa: PLC0415 - optional backend
        UnsupportedLocation,
        build_set_command,
        location_to_path,
    )

    commands: List[Dict[str, Any]] = []
    plan_by_op: Dict[str, Dict[str, Any]] = {}

    for operation in pending:
        op_id = operation.get("op_id")
        op_type = operation.get("type")
        if op_type not in _OFFICECLI_OPERATION_TYPES:
            return [], {}, (
                "operation type {!r} is not supported by the officecli writer".format(op_type)
            )

        target = operation.get("target") if isinstance(operation.get("target"), dict) else {}
        location_id = target.get("location_id")
        try:
            path = location_to_path(location_id)
        except UnsupportedLocation as exc:
            return [], {}, str(exc)

        slot = slots.get(operation.get("slot_id")) or {}
        token = slot.get("matched_text")
        if not isinstance(token, str) or not token:
            return [], {}, "slot {} has no literal matched_text".format(
                operation.get("slot_id")
            )

        paragraph = paragraphs.get(location_id)
        if paragraph is None:
            return [], {}, "location {} did not resolve".format(location_id)
        if op_type == "fill_cell":
            cell = cells.get(op_id)
            if cell is None:
                return [], {}, "cell target for {} did not resolve".format(op_id)
            # The python-docx writer fills the whole cell; a multi-paragraph
            # cell would make the two backends disagree.
            if len(cell.paragraphs) != 1:
                return [], {}, (
                    "cell at {} has {} paragraphs; officecli targets one paragraph".format(
                        location_id, len(cell.paragraphs)
                    )
                )

        view = LogicalParagraphView(paragraph._p)
        before_text = view.logical_text
        try:
            occurrence = max(1, int(slot.get("occurrence") or 1))
        except (TypeError, ValueError):
            occurrence = 1
        if occurrence != 1 or before_text.count(token) != 1:
            return [], {}, (
                "token {!r} is not unique in {}; officecli replaces every match".format(
                    token, location_id
                )
            )

        offset = _find_occurrence(before_text, token, occurrence)
        if offset is None:
            return [], {}, "token {!r} is not found in {}".format(token, location_id)
        last = offset + len(token) - 1
        if last >= len(view.char_map):
            return [], {}, "token {!r} exceeds the addressable run map".format(token)
        start_run = view.char_map[offset].r_el
        end_run = view.char_map[last].r_el
        if start_run is not end_run:
            return [], {}, (
                "token {!r} spans multiple runs in {}; officecli would merge them".format(
                    token, location_id
                )
            )
        if start_run.getparent() is not paragraph._p:
            return [], {}, (
                "token {!r} sits in a nested run in {}; officecli cannot target it".format(
                    token, location_id
                )
            )
        direct_runs = paragraph._p.findall(qn("w:r"))
        if start_run not in direct_runs:
            return [], {}, "token {!r} is not in a direct run of {}".format(token, location_id)
        run_index = direct_runs.index(start_run) + 1
        run_text = "".join(elm.text or "" for elm in start_run.findall(qn("w:t")))
        if run_text.count(token) != 1:
            return [], {}, (
                "token {!r} is not unique inside the target run of {}".format(token, location_id)
            )

        commands.append(
            build_set_command("{0}/r[{1}]".format(path, run_index), token,
                              str(operation.get("value")))
        )
        plan_by_op[op_id] = {
            "path": "{0}/r[{1}]".format(path, run_index),
            "read_path": path,
            "before": before_text,
            "token": token,
            "run_index": run_index,
        }

    return commands, plan_by_op, None


def _apply_operations_in_memory(
    document,
    pending: Sequence[Dict[str, Any]],
    slots: Dict[str, Any],
    paragraphs: Dict[str, Any],
    tables: Dict[str, Any],
    cells: Dict[str, Any],
    results_by_id: Dict[str, Dict[str, Any]],
    ledger: FillLedger,
) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """Apply operations through python-docx; returns ``(errors, abort_reason)``."""
    errors: List[Dict[str, Any]] = []
    # Slots that also get a dedicated text operation do not need the image
    # operation to strip their placeholder token.
    text_consumers = {
        (operation.get("slot_id"), (operation.get("target") or {}).get("location_id"))
        for operation in pending
        if operation.get("type") in ("replace_text", "fill_paragraph")
    }
    for index, operation in enumerate(pending):
        target = operation.get("target") if isinstance(operation.get("target"), dict) else {}
        entry = results_by_id[operation.get("op_id")]
        try:
            before_text, after_text = _apply_operation(
                document,
                operation,
                slots[operation.get("slot_id")],
                paragraphs,
                tables,
                cells.get(operation.get("op_id")),
                remove_image_token=(
                    (operation.get("slot_id"), target.get("location_id"))
                    not in text_consumers
                ),
            )
        except Exception as exc:
            code, message, details = _operation_error(exc)
            details.update({"op_id": operation.get("op_id"),
                            "location_id": target.get("location_id")})
            errors.append(_error_record(code, message, details=details, rollback_required=True))
            ledger.record(
                operation.get("op_id"),
                operation.get("slot_id"),
                target.get("location_id"),
                operation.get("source_ref"),
                operation.get("value"),
                {"status": "FAILED", "error_code": code, "detail": message},
            )
            entry.update({"status": "FAILED", "error_code": code, "detail": message})
            for remaining in pending[index + 1:]:
                remaining_target = (
                    remaining.get("target")
                    if isinstance(remaining.get("target"), dict) else {}
                )
                remaining_entry = results_by_id[remaining.get("op_id")]
                remaining_message = "not executed: an earlier operation failed"
                ledger.record(
                    remaining.get("op_id"),
                    remaining.get("slot_id"),
                    remaining_target.get("location_id"),
                    remaining.get("source_ref"),
                    remaining.get("value"),
                    {"status": "FAILED", "error_code": code, "detail": remaining_message},
                )
                remaining_entry.update(
                    {"status": "FAILED", "error_code": code, "detail": remaining_message}
                )
            return errors, "EXECUTION_FAILED"

        ledger.record(
            operation.get("op_id"),
            operation.get("slot_id"),
            target.get("location_id"),
            operation.get("source_ref"),
            operation.get("value"),
            {"status": "SUCCESS"},
            before_text=before_text,
            after_text=after_text,
        )
        entry.update({"status": "SUCCESS"})
    return errors, None


def _apply_operations_via_officecli(
    template_path: str,
    stage_path: str,
    commands: Sequence[Dict[str, Any]],
    pending: Sequence[Dict[str, Any]],
    plan_by_op: Dict[str, Dict[str, Any]],
    results_by_id: Dict[str, Dict[str, Any]],
    ledger: FillLedger,
) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """Apply the batch atomically, read back the targets, then normalise.

    officecli writes the staged copy only; the caller keeps the transaction and
    QA boundary. A batch failure proves the file is unchanged (officecli rolls
    the whole batch back). Two post-steps are mandatory before QA:

    * the resident must be closed after the reads, or the file stays locked;
    * officecli's ``w14:paraId``/``w14:textId`` stamping must be undone, or the
      template fingerprint reports an unauthorised structural change.
    """
    from engine import officecli_writer  # noqa: PLC0415 - optional backend

    errors: List[Dict[str, Any]] = []

    def fail_remaining(code: str, message: str, remaining: Sequence[Dict[str, Any]]) -> None:
        for operation in remaining:
            target = operation.get("target") if isinstance(operation.get("target"), dict) else {}
            ledger.record(
                operation.get("op_id"),
                operation.get("slot_id"),
                target.get("location_id"),
                operation.get("source_ref"),
                operation.get("value"),
                {"status": "FAILED", "error_code": code, "detail": message},
            )
            results_by_id[operation.get("op_id")].update(
                {"status": "FAILED", "error_code": code, "detail": message}
            )

    try:
        shutil.copyfile(template_path, stage_path)
        officecli_writer.run_batch(stage_path, list(commands))
    except Exception as exc:
        code = "EXECUTION_FAILED"
        message = "officecli could not apply the batch: {}: {}".format(
            type(exc).__name__, exc
        )
        errors.append(_error_record(
            code, message,
            details={"writer": "officecli", "phase": "BATCH"},
            rollback_required=True,
        ))
        fail_remaining(code, message, pending)
        return errors, "OFFICECLI_WRITE_FAILED"
    finally:
        officecli_writer.close(stage_path)

    try:
        for index, operation in enumerate(pending):
            op_id = operation.get("op_id")
            target = operation.get("target") if isinstance(operation.get("target"), dict) else {}
            entry = results_by_id[op_id]
            descriptor = plan_by_op[op_id]
            try:
                after_text = officecli_writer.get_text(stage_path, descriptor["read_path"])
                if descriptor["token"] in after_text:
                    raise ValueError(
                        "placeholder token survived the batch at {}".format(
                            descriptor["read_path"]
                        )
                    )
            except Exception as exc:
                code = "EXECUTION_FAILED"
                message = "officecli read-back failed for {}: {}: {}".format(
                    op_id, type(exc).__name__, exc
                )
                errors.append(_error_record(
                    code, message,
                    details={"op_id": op_id, "path": descriptor["read_path"],
                             "phase": "READBACK"},
                    rollback_required=True,
                ))
                ledger.record(
                    op_id,
                    operation.get("slot_id"),
                    target.get("location_id"),
                    operation.get("source_ref"),
                    operation.get("value"),
                    {"status": "FAILED", "error_code": code, "detail": message},
                )
                entry.update({"status": "FAILED", "error_code": code, "detail": message})
                fail_remaining(code, message, pending[index + 1:])
                return errors, "OFFICECLI_READBACK_FAILED"

            ledger.record(
                op_id,
                operation.get("slot_id"),
                target.get("location_id"),
                operation.get("source_ref"),
                operation.get("value"),
                {"status": "SUCCESS"},
                before_text=descriptor["before"],
                after_text=after_text,
            )
            entry.update({"status": "SUCCESS"})
    finally:
        # The reads above start a fresh resident, so the file is locked again.
        officecli_writer.close(stage_path)

    try:
        red_targets: List[Tuple[str, int]] = []
        for operation in pending:
            descriptor = plan_by_op.get(operation.get("op_id")) or {}
            target = operation.get("target") if isinstance(operation.get("target"), dict) else {}
            run_index = descriptor.get("run_index")
            location_id = target.get("location_id")
            if isinstance(run_index, int) and isinstance(location_id, str):
                red_targets.append((location_id, run_index))
        officecli_writer.restore_paragraph_identity(
            template_path, stage_path, strip_red_runs=red_targets
        )
    except Exception as exc:
        code = "EXECUTION_FAILED"
        message = "officecli output could not be normalised: {}: {}".format(
            type(exc).__name__, exc
        )
        errors.append(_error_record(
            code, message,
            details={"writer": "officecli", "phase": "NORMALIZE"},
            rollback_required=True,
        ))
        fail_remaining(code, message, pending)
        return errors, "OFFICECLI_NORMALIZE_FAILED"

    return errors, None


def _operation_error(exc: Exception) -> Tuple[str, str, Dict[str, Any]]:
    return (
        _EXECUTION_ERROR_CODE,
        "Operation could not be applied: {}: {}".format(type(exc).__name__, exc),
        {"exception": type(exc).__name__},
    )


# ---------------------------------------------------------------------------
# QA
# ---------------------------------------------------------------------------


def _qa_policy(mode: str) -> Tuple[List[str], List[str]]:
    try:
        with open(CONFIG_DIR / "qa-policy.json", "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        policy = payload["policies"]["{}/{}".format(TASK_MODE, mode)]
        return list(policy.get("required") or []), list(policy.get("optional") or [])
    except (OSError, ValueError, KeyError, TypeError):
        return (
            ["PACKAGE", "FORMAT", "FIDELITY", "CONTENT", "DATA", "VISUAL_PAGE_COUNT"],
            ["VISUAL_PIXEL", "OCR"],
        )


def _fallback_qa_report(staged_path: str, template_path: str, task_id: str, mode: str) -> Dict[str, Any]:
    """QA without the v4 pipeline: PACKAGE + FORMAT only, everything else UNVERIFIED."""
    package = audit_docx_package_integrity(staged_path)
    qa_document = docx.Document(staged_path)
    format_report = audit_format_and_text_qa(
        qa_document,
        docx_path=staged_path,
        reference_docx_path=template_path,
        raise_on_failure=False,
        comparison_profile="STYLE_GUIDE",
    )

    required, _optional = _qa_policy(mode)
    executed = ["PACKAGE", "FORMAT"]
    missing = [check_id for check_id in required if check_id not in executed]

    issues: List[Dict[str, Any]] = []
    for check_id, report in (("PACKAGE", package), ("FORMAT", format_report)):
        for item in report.get("issues", []) or []:
            if not isinstance(item, dict):
                continue
            entry = dict(item)
            entry["check_id"] = check_id
            entry.setdefault(
                "blocking",
                str(entry.get("severity", "")).lower() in ("high", "blocking"),
            )
            issues.append(entry)

    checks: List[Dict[str, Any]] = []
    for check_id, report, method in (
        ("PACKAGE", package, "engine.qa_engine.audit_docx_package_integrity"),
        ("FORMAT", format_report, "engine.qa_engine.audit_format_and_text_qa"),
    ):
        checks.append(
            {
                "check_id": check_id,
                "required": check_id in required,
                "status": "PASSED" if report.get("passed") else "FAILED",
                "evidence": {"method": method, "artifact_path": staged_path},
                "issues": [item for item in issues if item.get("check_id") == check_id],
            }
        )
    for check_id in missing:
        checks.append(
            {
                "check_id": check_id,
                "required": True,
                "status": "SKIPPED",
                "evidence": {
                    "method": "NOT_IMPLEMENTED",
                    "detail": "check {} has no implementation available in this build".format(check_id),
                },
            }
        )

    failed = any(
        check.get("status") == "FAILED" for check in checks if check.get("required")
    )
    status = QA_FAILED if failed else QA_UNVERIFIED
    coverage_gaps = ["CHECK_NOT_IMPLEMENTED:{}".format(check_id) for check_id in missing]
    reasons = (
        ["required check {} failed".format(check["check_id"]) for check in checks
         if check.get("status") == "FAILED" and check.get("required")]
        if failed
        else ["required checks not executed: {}".format(", ".join(missing))]
    )

    return {
        "schema_version": SCHEMA_VERSION,
        "task_id": task_id,
        "status": status,
        "task_mode": TASK_MODE,
        "gate_mode": mode,
        "policy_source": "{}/{}".format(TASK_MODE, mode),
        "required_checks": required,
        "executed_checks": executed,
        "missing_checks": missing,
        "checks": checks,
        "issues": issues,
        "warnings": [],
        "coverage_gaps": coverage_gaps,
        "repairs": [],
        "final": {"eligible_for_commit": False, "reasons": reasons},
    }


def _run_qa(
    qa_runner,
    staged_path: str,
    template_path: str,
    task_id: str,
    mode: str,
    content_plan: Any,
    fill_plan: Any,
    spec: Any,
) -> Any:
    if qa_runner is not None:
        return qa_runner(staged_path)
    try:
        from qa.pipeline import run_full_qa  # noqa: PLC0415 - qa/ is optional in this build
    except Exception:
        return _fallback_qa_report(staged_path, template_path, task_id, mode)
    return run_full_qa(
        staged_path,
        template_path=template_path,
        task_id=task_id,
        task_mode=TASK_MODE,
        gate_mode=mode,
        content_plan=content_plan,
        fill_plan=fill_plan,
        spec=spec,
    )


def _normalize_qa_report(report: Any) -> Dict[str, Any]:
    """Fold a QAReport 4.0 dict into a status the executor can act on."""
    normalized: Dict[str, Any] = {
        "status": QA_FAILED,
        "missing_checks": [],
        "coverage_gaps": [],
        "issues": [],
        "blocking_issues": [],
        "false_pass": False,
    }
    if not isinstance(report, dict):
        return normalized

    status = report.get("status")
    status = status.strip().upper() if isinstance(status, str) else ""
    missing = [str(item) for item in (report.get("missing_checks") or [])]
    gaps = [str(item) for item in (report.get("coverage_gaps") or [])]
    issues = [item for item in (report.get("issues") or []) if isinstance(item, dict)]
    blocking = [
        item for item in issues
        if item.get("blocking") is True
        or str(item.get("severity", "")).strip().lower() in ("high", "blocking")
    ]

    if status not in VALID_STATUSES:
        if report.get("passed") is False or blocking:
            status = QA_FAILED
        elif report.get("passed") is True and not missing and not gaps:
            status = QA_PASSED
        else:
            status = QA_UNVERIFIED

    false_pass = False
    if status == QA_PASSED and (missing or gaps or blocking):
        status = QA_FAILED
        false_pass = True
    elif blocking and status != QA_FAILED:
        # A report that claims a pass while carrying blocking evidence must not
        # authorize delivery.
        false_pass = status == QA_PASSED
        status = QA_FAILED

    normalized.update(
        {
            "status": status,
            "missing_checks": missing,
            "coverage_gaps": gaps,
            "issues": issues,
            "blocking_issues": blocking,
            "false_pass": false_pass,
        }
    )
    return normalized


def _qa_error_records(normalized: Dict[str, Any]) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    registry = _registry()
    for issue in normalized.get("blocking_issues", []) or []:
        raw_code = issue.get("code")
        code = raw_code if isinstance(raw_code, str) and raw_code in registry else "QA_EVIDENCE_MISSING"
        severity = issue.get("severity")
        records.append(
            _error_record(
                code,
                issue.get("detail") or issue.get("message") or "QA reported a blocking issue",
                details={
                    "qa_code": raw_code,
                    "location": issue.get("location"),
                    "check_id": issue.get("check_id"),
                },
                severity=severity if severity in SEVERITIES else None,
                rollback_required=True,
            )
        )
    return records


# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------


def execute_fill_plan(
    template_path: str,
    spec: Dict[str, Any],
    fill_plan: Dict[str, Any],
    output_path: str,
    *,
    content_plan: Optional[Dict[str, Any]] = None,
    qa_runner=None,
    allow_unverified: bool = False,
    gate_record=None,
    writer: str = "python-docx",
) -> Dict[str, Any]:
    """Execute a FillPlan 4.0 deterministically and return a ToolEnvelope 4.0 dict.

    ``writer`` selects the mutation backend. ``python-docx`` (default) keeps the
    v4 behaviour unchanged. ``officecli`` delegates the writes to the officecli
    binary and silently falls back to python-docx for any operation, location or
    token pattern it cannot express faithfully; ``data.writer_fallback`` records
    why. The default is deliberately not flipped until conformance is proven.
    """
    if writer not in ("python-docx", "officecli"):
        raise ValueError("unknown writer backend {!r}".format(writer))
    task_id = _task_id(fill_plan)
    mode = _mode(fill_plan)
    ledger = FillLedger(task_id=task_id)

    warnings: List[Dict[str, Any]] = []
    errors: List[Dict[str, Any]] = []
    region_warnings: List[Dict[str, Any]] = []
    data: Dict[str, Any] = {
        "spec_validation": None,
        "plan_validation": None,
        "content_plan_validation": None,
        "operation_results": [],
        "ledger": ledger.to_dict(),
        "artifact_path": None,
        "qa_status": None,
        "qa_eligible": False,
        "missing_checks": [],
        "region_warnings": region_warnings,
        "writer_backend": None,
        "writer_fallback": None,
    }

    tx: Optional[DocumentTransaction] = None

    def envelope(
        status: str,
        next_action: str,
        *,
        artifacts: Optional[List[Dict[str, Any]]] = None,
        transaction: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        data["ledger"] = ledger.to_dict()
        return {
            "schema_version": SCHEMA_VERSION,
            "task_id": task_id,
            "status": status,
            "data": data,
            "warnings": warnings,
            "errors": errors,
            "artifacts": artifacts or [],
            "next_action": next_action,
            "transaction": transaction if transaction is not None else (tx.record() if tx else {}),
        }

    try:
        # -- 0. pre-parse package quota (W3-7): reject hostile/oversized input
        # before python-docx reads any part of it.
        from engine.package_guard import check_package, load_limits

        guard_verdict = check_package(str(template_path), load_limits())
        if not guard_verdict["ok"]:
            errors.append(
                _error_record(
                    guard_verdict["code"],
                    "Template package rejected before parsing: "
                    + str(guard_verdict["violations"])[:300],
                    details={"violations": guard_verdict["violations"]},
                    rollback_required=False,
                )
            )
            return envelope("BLOCKED", "STOP")

        # -- 1. load + validate ------------------------------------------------
        try:
            document = docx.Document(template_path)
        except Exception as exc:
            errors.append(
                _error_record(
                    "TEMPLATE_SHA_MISMATCH",
                    "Template could not be opened: {}: {}".format(type(exc).__name__, exc),
                    details={"template_path": str(template_path)},
                    rollback_required=False,
                )
            )
            return envelope("BLOCKED", "STOP")

        spec_report = validate_document_spec(spec)
        data["spec_validation"] = spec_report

        if not isinstance(spec, dict) or not isinstance(fill_plan, dict):
            errors.append(
                _error_record(
                    "INVALID_FILL_PLAN",
                    "DocumentSpec and FillPlan must both be JSON objects",
                    details={
                        "spec_type": type(spec).__name__,
                        "fill_plan_type": type(fill_plan).__name__,
                    },
                    rollback_required=False,
                )
            )
            return envelope("BLOCKED", "STOP")

        if content_plan is not None and not isinstance(content_plan, dict):
            errors.append(
                _error_record(
                    "INVALID_CONTENT_PLAN",
                    "ContentPlan must be a JSON object, got {}".format(type(content_plan).__name__),
                    rollback_required=False,
                )
            )
            return envelope("BLOCKED", "STOP")

        plan_report = validate_fill_plan(fill_plan, spec, content_plan)
        data["plan_validation"] = plan_report

        if content_plan is not None:
            content_report = validate_content_plan(content_plan, spec)
            data["content_plan_validation"] = content_report
            errors.extend(_validation_errors(content_report, "INVALID_CONTENT_PLAN"))
        errors.extend(_validation_errors(spec_report, "INVALID_FILL_PLAN"))
        errors.extend(_validation_errors(plan_report, "INVALID_FILL_PLAN"))
        if errors:
            return envelope("BLOCKED", "STOP")

        if not isinstance(output_path, str) or not output_path:
            errors.append(
                _error_record(
                    "INVALID_FILL_PLAN",
                    "The final delivery path is missing; the executor never writes directly",
                    rollback_required=False,
                )
            )
            return envelope("BLOCKED", "STOP")

        # -- 2. template SHA preflight ---------------------------------------
        try:
            actual_sha = _sha256_file(template_path)
        except OSError as exc:
            errors.append(
                _error_record(
                    "TEMPLATE_SHA_MISMATCH",
                    "Template bytes could not be read: {}".format(exc),
                    details={"template_path": str(template_path)},
                    rollback_required=False,
                )
            )
            return envelope("BLOCKED", "STOP")

        declared_sha = fill_plan["baseline"]["template_sha256"]
        spec_sha = spec["template"]["template_sha256"]
        if actual_sha != declared_sha or actual_sha != spec_sha:
            errors.append(
                _error_record(
                    "TEMPLATE_SHA_MISMATCH",
                    "Declared {} does not match actual {}".format(declared_sha, actual_sha),
                    details={
                        "expected": declared_sha,
                        "actual": actual_sha,
                        "spec_template_sha256": spec_sha,
                    },
                    rollback_required=False,
                )
            )
            return envelope("BLOCKED", "STOP")

        # -- 2b. Template Understanding Gate ---------------------------------
        # A valid DocumentSpec + FillPlan is not authorization to touch a
        # template. The gate binds the template SHA, spec, evidence and an
        # explicit user confirmation before any mutation is attempted.
        try:
            from template_gate.errors import TemplateGateError
            from template_gate.validator import require_confirmed_gate

            require_confirmed_gate(template_path, TASK_MODE, spec=spec, gate_record=gate_record)
        except TemplateGateError as exc:
            errors.append(
                _error_record(
                    exc.code,
                    exc.message,
                    details=exc.details,
                    rollback_required=False,
                )
            )
            return envelope("BLOCKED", "STOP")

        tx = DocumentTransaction(template_path, output_path, task_mode=TASK_MODE, task_id=task_id)
        preflight = tx.preflight()
        if not preflight.get("passed"):
            failed_checks = [
                check["name"] for check in preflight.get("checks", [])
                if check.get("required") and not check.get("ok")
            ]
            code = (
                "OUTPUT_FILE_LOCKED"
                if any(name.startswith("output") for name in failed_checks)
                else "INVALID_FILL_PLAN"
            )
            details = {"failed_checks": failed_checks}
            if code == "OUTPUT_FILE_LOCKED":
                details["output_path"] = tx.output_path
            errors.append(
                _error_record(
                    code,
                    "Transaction preflight failed: {}".format(", ".join(failed_checks)),
                    details=details,
                    rollback_required=False,
                )
            )
            tx.abort("PREFLIGHT_FAILED")
            return envelope("BLOCKED", "STOP")

        # -- 3. preconditions before any mutation ----------------------------
        operations = sorted(
            [item for item in fill_plan.get("operations", []) if isinstance(item, dict)],
            key=lambda item: item.get("sequence", 0),
        )
        slots = {
            item["slot_id"]: item
            for item in spec.get("slots", [])
            if isinstance(item, dict) and isinstance(item.get("slot_id"), str)
        }

        results_by_id: Dict[str, Dict[str, Any]] = {}
        pending: List[Dict[str, Any]] = []
        failed_op_ids: set = set()

        for operation in operations:
            target = operation.get("target") if isinstance(operation.get("target"), dict) else {}
            entry: Dict[str, Any] = {
                "op_id": operation.get("op_id"),
                "sequence": operation.get("sequence"),
                "type": operation.get("type"),
                "slot_id": operation.get("slot_id"),
                "location_id": target.get("location_id"),
                "status": "PENDING",
            }
            data["operation_results"].append(entry)
            results_by_id[operation.get("op_id")] = entry

            slot = slots.get(operation.get("slot_id"))
            failure: Optional[Tuple[str, str, Dict[str, Any]]] = None

            blocking_dependencies = [
                dependency for dependency in (operation.get("depends_on") or [])
                if dependency in failed_op_ids
            ]
            if blocking_dependencies:
                failure = (
                    "INVALID_FILL_PLAN",
                    "Operation {} depends on failed operation(s): {}".format(
                        operation.get("op_id"), ", ".join(blocking_dependencies)
                    ),
                    {"op_id": operation.get("op_id"), "depends_on": blocking_dependencies},
                )
            else:
                failure = _evaluate_preconditions(
                    operation, slot, spec, actual_sha, declared_sha,
                    content_plan, region_warnings,
                )
                if failure is None:
                    failure = _overflow_failure(operation)

            if failure is not None:
                code, message, details = failure
                errors.append(
                    _error_record(code, message, details=details, rollback_required=False)
                )
                ledger.record(
                    operation.get("op_id"),
                    operation.get("slot_id"),
                    target.get("location_id"),
                    operation.get("source_ref"),
                    operation.get("value"),
                    {"status": "FAILED", "error_code": code, "detail": message},
                )
                entry.update({"status": "FAILED", "error_code": code, "detail": message})
                failed_op_ids.add(operation.get("op_id"))
            else:
                pending.append(operation)

        if errors:
            # Nothing was mutated: record the not-executed operations so the
            # ledger never omits an operation of a rejected plan.
            for operation in pending:
                target = operation.get("target") if isinstance(operation.get("target"), dict) else {}
                entry = results_by_id[operation.get("op_id")]
                message = "not executed: the plan was blocked before mutation"
                ledger.record(
                    operation.get("op_id"),
                    operation.get("slot_id"),
                    target.get("location_id"),
                    operation.get("source_ref"),
                    operation.get("value"),
                    {"status": "FAILED", "error_code": "INVALID_FILL_PLAN", "detail": message},
                )
                entry.update({"status": "FAILED", "error_code": "INVALID_FILL_PLAN", "detail": message})
            tx.abort("PRECONDITION_BLOCKED")
            return envelope("BLOCKED", "STOP")

        # -- 4. locate every target before mutating --------------------------
        header_footer_state = _header_footer_snapshot(document)
        paragraphs = _paragraph_map(document)
        tables = _table_map(document)
        _restore_header_footer_state(header_footer_state)
        cells: Dict[str, Any] = {}
        locate_failures: Dict[str, Tuple[str, str, Dict[str, Any]]] = {}
        for operation in pending:
            target = operation.get("target") if isinstance(operation.get("target"), dict) else {}
            location_id = target.get("location_id")
            op_type = operation.get("type")
            if op_type == "fill_cell":
                cell = _resolve_cell(tables, target)
                if cell is None:
                    locate_failures[operation.get("op_id")] = (
                        "SLOT_LOCATION_UNRESOLVED",
                        "Cell target does not resolve: table {} row {} col {}".format(
                            target.get("table_id"), target.get("row"), target.get("col")
                        ),
                        {"op_id": operation.get("op_id"), "location_id": location_id},
                    )
                else:
                    cells[operation.get("op_id")] = cell
            elif location_id not in paragraphs:
                locate_failures[operation.get("op_id")] = (
                    "SLOT_LOCATION_UNRESOLVED",
                    "Slot location {} no longer resolves".format(location_id),
                    {"op_id": operation.get("op_id"), "location_id": location_id},
                )
            elif op_type == "replace_image":
                image_path = operation.get("value")
                if not isinstance(image_path, str) or not os.path.isfile(image_path):
                    locate_failures[operation.get("op_id")] = (
                        "FACT_SOURCE_MISSING",
                        "Image file {} does not exist".format(image_path),
                        {"op_id": operation.get("op_id"), "image_path": image_path},
                    )

        if locate_failures:
            for operation in pending:
                target = operation.get("target") if isinstance(operation.get("target"), dict) else {}
                entry = results_by_id[operation.get("op_id")]
                failure = locate_failures.get(operation.get("op_id"))
                if failure is None:
                    code = "INVALID_FILL_PLAN"
                    message = "not executed: the plan was blocked before mutation"
                    details = {"op_id": operation.get("op_id")}
                else:
                    code, message, details = failure
                    errors.append(
                        _error_record(code, message, details=details, rollback_required=False)
                    )
                ledger.record(
                    operation.get("op_id"),
                    operation.get("slot_id"),
                    target.get("location_id"),
                    operation.get("source_ref"),
                    operation.get("value"),
                    {"status": "FAILED", "error_code": code, "detail": message},
                )
                entry.update({"status": "FAILED", "error_code": code, "detail": message})
            tx.abort("LOCATE_BLOCKED")
            return envelope("BLOCKED", "STOP")

        # -- 4b. writer backend selection -------------------------------------
        backend = "python-docx"
        backend_fallback: Optional[str] = None
        officecli_commands: List[Dict[str, Any]] = []
        officecli_plan: Dict[str, Dict[str, Any]] = {}

        if writer == "officecli" and pending:
            commands, plan_by_op, fallback = _officecli_operation_plan(
                pending, slots, paragraphs, cells
            )
            if fallback is None:
                backend = "officecli"
                officecli_commands = commands
                officecli_plan = plan_by_op
            else:
                backend_fallback = fallback
        data["writer_backend"] = backend
        data["writer_fallback"] = backend_fallback

        # -- 5. mutate the staged copy through the selected writer ------------
        if backend == "officecli":
            operation_errors, abort_reason = _apply_operations_via_officecli(
                template_path,
                tx.stage(),
                officecli_commands,
                pending,
                officecli_plan,
                results_by_id,
                ledger,
            )
        else:
            operation_errors, abort_reason = _apply_operations_in_memory(
                document,
                pending,
                slots,
                paragraphs,
                tables,
                cells,
                results_by_id,
                ledger,
            )
        errors.extend(operation_errors)
        if abort_reason:
            tx.abort(abort_reason)
            return envelope("FAILED", "STOP")

        try:
            if backend == "python-docx":
                document.save(tx.stage())
        except Exception as exc:
            errors.append(
                _error_record(
                    "OUTPUT_FILE_LOCKED",
                    "Staged write failed: {}: {}".format(type(exc).__name__, exc),
                    details={"output_path": tx.output_path},
                    rollback_required=True,
                )
            )
            tx.abort("STAGED_WRITE_FAILED")
            return envelope("FAILED", "STOP")

        # -- 6. QA against the staged artifact -------------------------------
        try:
            qa_report = _run_qa(
                qa_runner, tx.temp_path, template_path, task_id, mode,
                content_plan, fill_plan, spec
            )
        except Exception as exc:
            errors.append(
                _error_record(
                    "QA_EVIDENCE_MISSING",
                    "QA could not run against the staged artifact: {}: {}".format(
                        type(exc).__name__, exc
                    ),
                    details={"phase": "QA"},
                    rollback_required=True,
                )
            )
            tx.abort("QA_ERROR")
            return envelope("FAILED", "STOP")

        normalized = _normalize_qa_report(qa_report)
        qa_status = normalized["status"]
        missing_checks = normalized["missing_checks"]
        data["qa_status"] = qa_status
        data["missing_checks"] = missing_checks
        data["coverage_gaps"] = list(normalized["coverage_gaps"])

        # -- 7. commit only when the QA report is eligible --------------------
        if qa_status == QA_FAILED:
            if normalized["false_pass"]:
                errors.append(
                    _error_record(
                        "QA_FALSE_PASS",
                        "QAReport claimed PASSED while {} required check(s) are missing "
                        "or blocking evidence exists".format(
                            max(len(missing_checks), 1)
                        ),
                        details={
                            "missing_checks": missing_checks,
                            "coverage_gaps": normalized["coverage_gaps"],
                        },
                        rollback_required=True,
                    )
                )
            errors.extend(_qa_error_records(normalized))
            if not errors:
                errors.append(
                    _error_record(
                        "QA_EVIDENCE_MISSING",
                        "QAReport status FAILED without a blocking issue record",
                        details={"qa_status": qa_status, "phase": "QA"},
                        rollback_required=True,
                    )
                )
            tx.record_qa(qa_report, status=QA_FAILED)
            tx.abort("QA_FAILED")
            return envelope("FAILED", "STOP")

        if qa_status == QA_PASSED:
            eligible = True
        elif qa_status == QA_UNVERIFIED:
            # Contract 04 §7: under STANDARD an UNVERIFIED report stays committable
            # when the caller allows it. Missing checks and coverage gaps must be
            # disclosed, which the QAReport gate validates, not a per-checker count.
            eligible = bool(mode == "STANDARD" and allow_unverified)
        else:
            eligible = False

        tx.record_qa(qa_report, status=qa_status)
        if not eligible:
            data["qa_eligible"] = False
            errors.append(
                _error_record(
                    "QA_ELIGIBILITY_CONTRADICTION",
                    "QA status {} is not eligible for commit under {}/{} "
                    "(missing checks: {})".format(
                        qa_status, TASK_MODE, mode,
                        ", ".join(missing_checks) if missing_checks else "none declared",
                    ),
                    details={
                        "qa_status": qa_status,
                        "gate_mode": mode,
                        "allow_unverified": bool(allow_unverified),
                        "missing_checks": missing_checks,
                    },
                    rollback_required=True,
                )
            )
            tx.abort("QA_NOT_ELIGIBLE")
            return envelope("FAILED", "STOP")

        # -- 7b. second gate: the transaction re-validates the QAReport itself ---
        # An injected ``qa_runner`` is a DI seam used with partial QA payloads; the
        # executor's eligibility check above stays authoritative for it. Reports
        # from the real pipeline are full QAReport 4.0 objects, so the transaction
        # validates them again against the policy gate before it publishes.
        if qa_runner is None:
            try:
                tx.record_gate(qa_report)
            except TransactionAborted as exc:
                errors.append(
                    _error_record(
                        "QA_ELIGIBILITY_CONTRADICTION",
                        "Transaction gate refused the QAReport: {}".format(
                            getattr(exc, "reason", exc)
                        ),
                        details={
                            "gate_reason": getattr(exc, "reason", None),
                            "qa_status": qa_status,
                            "gate_mode": mode,
                        },
                        rollback_required=True,
                    )
                )
                return envelope("FAILED", "STOP")
            except Exception as exc:
                errors.append(
                    _error_record(
                        "QA_ELIGIBILITY_CONTRADICTION",
                        "Transaction gate could not validate the QAReport: {}: {}".format(
                            type(exc).__name__, exc
                        ),
                        details={"qa_status": qa_status, "gate_mode": mode},
                        rollback_required=True,
                    )
                )
                tx.abort("QA_GATE_REJECTED")
                return envelope("FAILED", "STOP")

        try:
            tx.commit()
        except TransactionAborted as exc:
            reason = str(getattr(exc, "reason", exc))
            code = (
                "QA_ELIGIBILITY_CONTRADICTION"
                if reason in _GATE_ABORT_REASONS
                else "OUTPUT_FILE_LOCKED"
            )
            errors.append(
                _error_record(
                    code,
                    "Commit failed: {}".format(reason),
                    details={"output_path": tx.output_path, "abort_reason": reason},
                    rollback_required=True,
                )
            )
            return envelope("FAILED", "STOP")
        except Exception as exc:
            errors.append(
                _error_record(
                    "OUTPUT_FILE_LOCKED",
                    "Commit failed: {}: {}".format(type(exc).__name__, exc),
                    details={"output_path": tx.output_path},
                    rollback_required=True,
                )
            )
            return envelope("FAILED", "STOP")

        # -- 8. publish the envelope ----------------------------------------
        final_status = "SUCCESS" if qa_status == QA_PASSED else "UNVERIFIED"
        data["artifact_path"] = tx.output_path
        data["qa_eligible"] = True
        artifacts = [
            {
                "path": tx.output_path,
                "kind": "docx",
                "sha256": tx.output_sha256,
                "required": True,
            }
        ]
        next_action = "NONE" if final_status == "SUCCESS" else "COMMIT"
        return envelope(final_status, next_action, artifacts=artifacts)

    except Exception as exc:  # pragma: no cover - defensive guard
        if tx is not None:
            tx.abort("UNEXPECTED_ERROR")
        errors.append(
            _error_record(
                "SLOT_LOCATION_UNRESOLVED",
                "Fill execution failed: {}: {}".format(type(exc).__name__, exc),
                details={"phase": "EXECUTION"},
                rollback_required=tx is not None,
            )
        )
        return envelope("FAILED", "STOP")


__all__ = ["execute_fill_plan"]
