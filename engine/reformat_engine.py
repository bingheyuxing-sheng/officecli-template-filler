# -*- coding: utf-8 -*-
"""REFORMAT: semantic format diff plan and tracked apply.

The plan lists every paragraph/table formatting difference between a target document and
a reference template. Each entry carries `current`, `reference_value`, `action` and a
reason, so the user can review the list before anything is changed. Applying the plan
writes native Word format revisions (`w:*PrChange`) instead of silently rewriting styles.
"""

from __future__ import annotations

import difflib
import os
import uuid
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence

import docx

from .alignment import align_paragraphs, align_tables, normalize_text
from .layout_qa import _paragraph_fingerprint
from .qa_engine import _table_dominant_font, _table_dominant_size
from .repair_engine import _extract_paragraph_format_profile
from .style_engine import resolve_run_effective_font, resolve_run_effective_sz
from .review_engine import (
    apply_paragraph_profile_tracked,
    create_revision_id_allocator,
    enable_track_changes,
    restore_table_style_tracked,
)
from .table_engine import compare_table_style, table_style_signature

_SAFE_PARAGRAPH_MARKERS = ("normal", "body text", "bodytext", "正文", "默认")


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _dominant(values: Sequence[Any]) -> Any:
    values = [value for value in values if value not in (None, "", "None")]
    if not values:
        return None
    counts = Counter(values)
    return sorted(counts.items(), key=lambda item: (-item[1], str(item[0])))[0][0]


def _style_name(paragraph) -> str:
    return str(getattr(getattr(paragraph, "style", None), "name", "") or "").strip().lower()


def _is_plain_body(paragraph) -> bool:
    name = _style_name(paragraph)
    return not name or any(marker in name for marker in _SAFE_PARAGRAPH_MARKERS)


def _style_compatible(left, right) -> bool:
    left_name = _style_name(left)
    right_name = _style_name(right)
    if not left_name or not right_name:
        return True
    if left_name == right_name:
        return True
    left_body = any(marker in left_name for marker in _SAFE_PARAGRAPH_MARKERS)
    right_body = any(marker in right_name for marker in _SAFE_PARAGRAPH_MARKERS)
    return left_body and right_body


def _is_safe_paragraph(paragraph) -> bool:
    unsafe = (
        ".//w:hyperlink",
        ".//w:fldChar",
        ".//w:drawing",
        ".//w:object",
        ".//w:sdt",
        ".//w:txbxContent",
        ".//w:commentReference",
    )
    for expression in unsafe:
        if paragraph._p.xpath(expression):
            return False
    return True


def _uniform_runs(paragraph) -> bool:
    styles = set()
    for run in paragraph.runs:
        if not (run.text or "").strip():
            continue
        ascii_font, east_asia = resolve_run_effective_font(run, paragraph)
        styles.add((
            (east_asia or ascii_font or "").strip(),
            str(resolve_run_effective_sz(run, paragraph) or ""),
            bool(run.bold),
        ))
    return len(styles) <= 1


def _reference_profile(paragraph) -> Dict[str, Any]:
    """Extract the template profile and fill inherited fonts with effective values."""
    profile = _extract_paragraph_format_profile(paragraph)
    for run in paragraph.runs:
        if not (run.text or "").strip():
            continue
        ascii_font, east_asia = resolve_run_effective_font(run, paragraph)
        profile["font_east_asia"] = profile.get("font_east_asia") or east_asia
        profile["font_ascii"] = profile.get("font_ascii") or ascii_font
        break
    return profile


def _similarity(left: str, right: str) -> float:
    left = normalize_text(left)
    right = normalize_text(right)
    if not left or not right:
        return 0.0
    if left == right:
        return 1.0
    return difflib.SequenceMatcher(None, left, right).ratio()


def _diff(
    scope: str,
    target: str,
    reference: str,
    property_name: str,
    current: Any,
    reference_value: Any,
    action: str,
    reason: str,
    confidence: float,
) -> Dict[str, Any]:
    return {
        "diff_id": uuid.uuid4().hex[:12],
        "scope": scope,
        "target": target,
        "reference": reference,
        "property": property_name,
        "current": current,
        "reference_value": reference_value,
        "action": action,
        "reason": reason,
        "confidence": round(float(confidence), 3),
    }


def _paragraph_diffs(
    out_paragraph,
    ref_paragraph,
    out_index: int,
    ref_index: int,
    similarity: float,
    auto_allowed: bool,
) -> List[Dict[str, Any]]:
    target = f"body.p[{out_index}]"
    reference = f"body.p[{ref_index}]"
    out_fp = _paragraph_fingerprint(target, out_paragraph)
    ref_fp = _paragraph_fingerprint(reference, ref_paragraph)
    diffs: List[Dict[str, Any]] = []

    for key in ("alignment", "line_spacing", "first_line_indent", "left_indent", "space_before", "space_after"):
        if ref_fp.get(key) is None or out_fp.get(key) == ref_fp.get(key):
            continue
        action = "AUTO_FIX" if auto_allowed else "REVIEW"
        reason = (
            "matched paragraph role and text are stable"
            if auto_allowed
            else "paragraph text/structure differs or contains complex runs"
        )
        diffs.append(_diff(
            "paragraph", target, reference, f"paragraph.{key}",
            out_fp.get(key), ref_fp.get(key), action, reason, similarity,
        ))

    out_font = _dominant([run.get("font") for run in out_fp.get("runs") or []])
    ref_font = _dominant([run.get("font") for run in ref_fp.get("runs") or []])
    if ref_font and out_font != ref_font:
        action = "AUTO_FIX" if auto_allowed else "REVIEW"
        diffs.append(_diff(
            "paragraph", target, reference, "run.font",
            out_font, ref_font, action,
            "matched paragraph; uniform runs" if auto_allowed else "mixed runs or changed content",
            similarity,
        ))

    out_size = _dominant([run.get("size") for run in out_fp.get("runs") or []])
    ref_size = _dominant([run.get("size") for run in ref_fp.get("runs") or []])
    if ref_size and out_size != ref_size:
        action = "AUTO_FIX" if auto_allowed else "REVIEW"
        diffs.append(_diff(
            "paragraph", target, reference, "run.size",
            out_size, ref_size, action,
            "matched paragraph; uniform runs" if auto_allowed else "mixed runs or changed content",
            similarity,
        ))

    out_bold = _dominant([run.get("bold") for run in out_fp.get("runs") or []])
    ref_bold = _dominant([run.get("bold") for run in ref_fp.get("runs") or []])
    if ref_bold is not None and out_bold != ref_bold:
        diffs.append(_diff(
            "paragraph", target, reference, "run.bold",
            out_bold, ref_bold, "REVIEW",
            "bold changes can alter emphasis; keep for human review",
            similarity,
        ))
    return diffs


def _table_property(issue: Sequence[Any]) -> str:
    kind = issue[0]
    if kind in ("table_row_height", "table_row_height_rule"):
        return f"table.row_height[{issue[2]}]"
    if kind == "table_column_ratio":
        return f"table.column_ratio[{issue[2]}]"
    if kind == "table_cell_margin":
        return f"table.cell_margin.{issue[2]}"
    if kind in ("table_border_missing", "table_border_style"):
        return f"table.border.{issue[2]}"
    if kind == "table_cell_property":
        return f"table.cell[{issue[2]},{issue[3]}].{issue[4]}"
    if kind == "table_cell_font_or_size":
        return f"table.cell[{issue[2]},{issue[3]}].font_or_size"
    return kind.replace("table_", "table.")


def _table_diffs(table_index: int, reference_index: int, issues: List[Sequence[Any]], auto_allowed: bool, row_counts_equal: bool) -> List[Dict[str, Any]]:
    target = f"body.tbl[{table_index}]"
    reference = f"body.tbl[{reference_index}]"
    diffs: List[Dict[str, Any]] = []
    for issue in issues:
        kind = issue[0]
        current = issue[-2] if len(issue) >= 3 else None
        reference_value = issue[-1] if len(issue) >= 2 else None
        if kind == "table_row_count":
            action, reason = "KEEP", "row-count change is content, not formatting"
        elif kind == "table_column_count":
            action, reason = "UNSUPPORTED", "column-count mismatch requires structural editing"
        elif kind == "table_cell_font_or_size":
            action = "AUTO_FIX" if auto_allowed else "REVIEW"
            reason = "matched table with equal rows" if auto_allowed else "row counts differ or cell content is mixed"
        else:
            action = "AUTO_FIX" if auto_allowed else "REVIEW"
            reason = "matched table geometry" if auto_allowed else (
                "row counts differ; restoring row-level style could shift new content"
                if not row_counts_equal else "table requires review"
            )
        diffs.append(_diff(
            "table", target, reference, _table_property(issue),
            current, reference_value, action, reason,
            1.0 if auto_allowed else 0.6,
        ))
    return diffs


def build_reformat_plan(
    reference_docx_path: str,
    target_docx_path: str,
    *,
    strip_red: bool = False,
    author: str = "OfficeCLI REFORMAT",
) -> Dict[str, Any]:
    ref_doc = docx.Document(reference_docx_path)
    tgt_doc = docx.Document(target_docx_path)
    paragraph_alignment = align_paragraphs(tgt_doc.paragraphs, ref_doc.paragraphs)
    table_alignment = align_tables(tgt_doc.tables, ref_doc.tables)

    diffs: List[Dict[str, Any]] = []
    actions: List[Dict[str, Any]] = []

    for out_index, ref_index in paragraph_alignment["matches"].items():
        out_p = tgt_doc.paragraphs[out_index]
        ref_p = ref_doc.paragraphs[ref_index]
        if not (out_p.text or "").strip():
            continue
        similarity = _similarity(out_p.text, ref_p.text)
        auto_allowed = (
            _is_safe_paragraph(out_p)
            and _is_plain_body(out_p)
            and _uniform_runs(out_p)
            and _style_compatible(out_p, ref_p)
            and similarity >= 0.85
        )
        paragraph_diffs = _paragraph_diffs(out_p, ref_p, out_index, ref_index, similarity, auto_allowed)
        diffs.extend(paragraph_diffs)
        if any(item["action"] == "AUTO_FIX" for item in paragraph_diffs):
            actions.append({
                "action_id": f"paragraph_{out_index}",
                "action_type": "RESTORE_PARAGRAPH_FORMAT",
                "target": f"body.p[{out_index}]",
                "paragraph_index": out_index,
                "reference_paragraph_index": ref_index,
                "target_profile": _reference_profile(ref_p),
                "strip_red": bool(strip_red),
                "diff_ids": [item["diff_id"] for item in paragraph_diffs if item["action"] == "AUTO_FIX"],
                "risk_level": "LOW",
            })

    for out_index, ref_index in table_alignment["matches"].items():
        out_tbl = tgt_doc.tables[out_index]
        ref_tbl = ref_doc.tables[ref_index]
        out_sig = table_style_signature(out_tbl)
        ref_sig = table_style_signature(ref_tbl)
        row_counts_equal = out_sig.get("row_count") == ref_sig.get("row_count")
        column_counts_equal = out_sig.get("column_count") == ref_sig.get("column_count")
        issues = compare_table_style(out_sig, ref_sig, out_index)
        auto_allowed = row_counts_equal and column_counts_equal
        table_diffs = _table_diffs(out_index, ref_index, issues, auto_allowed, row_counts_equal)

        out_size = _table_dominant_size(out_tbl)
        ref_size = _table_dominant_size(ref_tbl)
        if out_size and ref_size and out_size != ref_size:
            action = "AUTO_FIX" if auto_allowed else "REVIEW"
            table_diffs.append(_diff(
                "table", f"body.tbl[{out_index}]", f"body.tbl[{ref_index}]",
                "table.dominant_size", out_size, ref_size, action,
                "matched table geometry" if auto_allowed else "row counts differ or table needs review",
                1.0 if auto_allowed else 0.6,
            ))
        out_font = _table_dominant_font(out_tbl)
        ref_font = _table_dominant_font(ref_tbl)
        if out_font and ref_font and out_font[1] and ref_font[1] and out_font[1] != ref_font[1]:
            action = "AUTO_FIX" if auto_allowed else "REVIEW"
            table_diffs.append(_diff(
                "table", f"body.tbl[{out_index}]", f"body.tbl[{ref_index}]",
                "table.dominant_font", out_font[1], ref_font[1], action,
                "matched table geometry" if auto_allowed else "row counts differ or table needs review",
                1.0 if auto_allowed else 0.6,
            ))

        diffs.extend(table_diffs)
        if any(item["action"] == "AUTO_FIX" for item in table_diffs):
            actions.append({
                "action_id": f"table_{out_index}",
                "action_type": "RESTORE_TABLE_STYLE",
                "target": f"body.tbl[{out_index}]",
                "table_index": out_index,
                "reference_table_index": ref_index,
                "diff_ids": [item["diff_id"] for item in table_diffs if item["action"] == "AUTO_FIX"],
                "risk_level": "LOW",
            })

    # New content is surfaced, but it is never compared to an unrelated neighbour.
    for out_index in paragraph_alignment["unmatched_output"]:
        if (tgt_doc.paragraphs[out_index].text or "").strip():
            diffs.append(_diff(
                "paragraph", f"body.p[{out_index}]", "", "paragraph.new",
                None, None, "KEEP", "no template counterpart; new content", 1.0,
            ))
    for out_index in table_alignment["unmatched_output"]:
        diffs.append(_diff(
            "table", f"body.tbl[{out_index}]", "", "table.new",
            None, None, "KEEP", "no template counterpart; new table", 1.0,
        ))

    counts = Counter(item["action"] for item in diffs)
    return {
        "schema_version": "1.0",
        "task_mode": "REFORMAT",
        "author": author,
        "reference_docx": os.path.abspath(reference_docx_path),
        "target_docx": os.path.abspath(target_docx_path),
        "comparison_profile": "STYLE_GUIDE",
        "summary": {
            "total_diffs": len(diffs),
            "auto_fix": counts.get("AUTO_FIX", 0),
            "review_required": counts.get("REVIEW", 0),
            "keep": counts.get("KEEP", 0),
            "unsupported": counts.get("UNSUPPORTED", 0),
            "apply_actions": len(actions),
            "matched_paragraphs": len(paragraph_alignment["matches"]),
            "new_paragraphs": len([i for i in paragraph_alignment["unmatched_output"] if (tgt_doc.paragraphs[i].text or "").strip()]),
            "matched_tables": len(table_alignment["matches"]),
            "new_tables": len(table_alignment["unmatched_output"]),
        },
        "diffs": diffs,
        "actions": actions,
    }


def execute_reformat_plan(
    plan: Dict[str, Any],
    output_docx_path: str,
    *,
    author: Optional[str] = None,
    date: Optional[str] = None,
    gate_record=None,
) -> Dict[str, Any]:
    from template_gate.validator import require_confirmed_gate

    require_confirmed_gate(plan["reference_docx"], "REFORMAT", gate_record=gate_record)
    ref_doc = docx.Document(plan["reference_docx"])
    tgt_doc = docx.Document(plan["target_docx"])
    author = author or plan.get("author") or "OfficeCLI REFORMAT"
    date = date or _now_iso()
    enable_track_changes(tgt_doc, True)
    ids = create_revision_id_allocator(tgt_doc)

    applied = 0
    format_marks = 0
    unresolved: List[str] = []
    results: List[Dict[str, Any]] = []

    for action in plan.get("actions") or []:
        action_type = action.get("action_type")
        if action_type == "RESTORE_PARAGRAPH_FORMAT":
            index = action.get("paragraph_index")
            if index is None or index >= len(tgt_doc.paragraphs):
                unresolved.append(action.get("action_id") or "paragraph")
                results.append({"action_id": action.get("action_id"), "status": "UNRESOLVED"})
                continue
            first_id = ids._next
            marks = apply_paragraph_profile_tracked(
                tgt_doc.paragraphs[index],
                action.get("target_profile") or {},
                strip_red=bool(action.get("strip_red", False)),
                author=author,
                date=date,
                ids=ids,
            )
            applied += 1
            format_marks += marks
            results.append({
                "action_id": action.get("action_id"),
                "status": "APPLIED",
                "target": f"body.p[{index}]",
                "format_revision_ids": list(range(first_id, first_id + marks)),
            })
        elif action_type == "RESTORE_TABLE_STYLE":
            table_index = action.get("table_index")
            ref_index = action.get("reference_table_index")
            if (
                table_index is None
                or ref_index is None
                or table_index >= len(tgt_doc.tables)
                or ref_index >= len(ref_doc.tables)
            ):
                unresolved.append(action.get("action_id") or "table")
                results.append({"action_id": action.get("action_id"), "status": "UNRESOLVED"})
                continue
            first_id = ids._next
            ok, marks = restore_table_style_tracked(
                tgt_doc.tables[table_index],
                ref_doc.tables[ref_index],
                author=author,
                date=date,
                ids=ids,
            )
            if ok:
                applied += 1
                format_marks += marks
                results.append({
                    "action_id": action.get("action_id"),
                    "status": "APPLIED",
                    "target": f"body.tbl[{table_index}]",
                    "format_revision_ids": list(range(first_id, first_id + marks)),
                })
            else:
                unresolved.append(action.get("action_id") or "table")
                results.append({"action_id": action.get("action_id"), "status": "UNRESOLVED"})

    tgt_doc.save(output_docx_path)
    return {
        "output_docx": os.path.abspath(output_docx_path),
        "applied_actions": applied,
        "unresolved_actions": unresolved,
        "format_revision_count": format_marks,
        "action_results": results,
    }
