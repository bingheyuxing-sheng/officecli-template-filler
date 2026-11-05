# -*- coding: utf-8 -*-
"""Semantic anchors for template comparison.

A generated document is not a byte-for-byte replica of its template: paragraphs are added,
removed and rewritten, and a new table may have no counterpart at all. Comparing by list
index therefore reports formatting drift for content that merely moved.

This module maps output paragraphs/tables to their template counterparts using text anchors,
heading levels, table captions and header rows. Unmatched items are reported as new/removed
content instead of being compared to an unrelated neighbour.
"""

from __future__ import annotations

import difflib
import re
from typing import Any, Dict, List, Sequence, Tuple

from docx.oxml.ns import qn
from docx.text.paragraph import Paragraph

_WHITESPACE_RE = re.compile(r"\s+")
_PUNCT_RE = re.compile(r"[，。；：、！？（）()《》〈〉“”\"'·,.;:!?\\-—_]+")
_HEADING_STYLE_RE = re.compile(r"(heading|标题)\s*([1-9])?", re.IGNORECASE)

_STYLE_SYNONYMS = {
    "normal": "body",
    "正文": "body",
    "body text": "body",
    "bodytext": "body",
    "默认": "body",
}


def normalize_text(text: str) -> str:
    value = (text or "").strip().lower()
    value = _WHITESPACE_RE.sub("", value)
    value = _PUNCT_RE.sub("", value)
    return value


def _style_name(paragraph) -> str:
    try:
        return str(getattr(paragraph.style, "name", "") or "").strip()
    except Exception:
        return ""


def _canonical_style(paragraph) -> str:
    name = _style_name(paragraph).lower()
    for synonym, canonical in _STYLE_SYNONYMS.items():
        if synonym in name:
            return canonical
    return name


def _heading_level(paragraph) -> int:
    name = _style_name(paragraph).lower()
    match = _HEADING_STYLE_RE.search(name)
    if match and match.group(2):
        return int(match.group(2))
    if match:
        return 1
    p_pr = paragraph._p.pPr
    if p_pr is not None:
        outline = p_pr.find(qn("w:outlineLvl"))
        if outline is not None:
            try:
                return int(outline.get(qn("w:val")) or 0) + 1
            except (TypeError, ValueError):
                return 1
    return 0


def is_heading_paragraph(paragraph) -> bool:
    """True for real headings; TOC and caption styles are deliberately excluded.

    Structural helper shared by alignment, workflow TOC assessment and logic QA.
    ``heading``/``标题`` styles and ``w:outlineLvl`` count; ``TOC``/``目录`` and
    ``caption``/``题注`` styles do not.
    """
    try:
        name = str(getattr(paragraph.style, "name", "") or "").strip().lower()
    except Exception:
        name = ""
    if any(marker in name for marker in ("toc", "目录", "caption", "题注")):
        return False
    if re.search(r"(heading|标题)\s*[1-9]?", name):
        return True
    p_pr = paragraph._p.pPr
    return p_pr is not None and p_pr.find(qn("w:outlineLvl")) is not None


def _paragraph_token(paragraph) -> str:
    text = normalize_text(paragraph.text)
    if text:
        return text
    return f"<empty:{_canonical_style(paragraph)}>"


def _similarity(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    if left == right:
        return 1.0
    return difflib.SequenceMatcher(None, left, right).ratio()


def _compatible_paragraphs(out_p, ref_p) -> bool:
    out_text = normalize_text(out_p.text)
    ref_text = normalize_text(ref_p.text)
    if not out_text or not ref_text:
        # Empty paragraphs are spacing, not content: never pair an empty output
        # paragraph with a populated template paragraph (that caused TOC entries to
        # be compared with blank lines).
        return not out_text and not ref_text
    out_style = _canonical_style(out_p)
    ref_style = _canonical_style(ref_p)
    if out_style and ref_style and out_style != ref_style:
        return False
    if _heading_level(out_p) and _heading_level(ref_p):
        return _heading_level(out_p) == _heading_level(ref_p)
    return True


def align_paragraphs(
    output_paragraphs: Sequence[Any],
    reference_paragraphs: Sequence[Any],
) -> Dict[str, Any]:
    """Return `{matches, unmatched_output, unmatched_reference}` map keys are indices."""
    out_tokens = [_paragraph_token(p) for p in output_paragraphs]
    ref_tokens = [_paragraph_token(p) for p in reference_paragraphs]
    matches: Dict[int, int] = {}
    used_ref = set()

    matcher = difflib.SequenceMatcher(a=out_tokens, b=ref_tokens, autojunk=False)
    for tag, out_start, out_end, ref_start, ref_end in matcher.get_opcodes():
        if tag == "equal":
            for offset in range(out_end - out_start):
                matches[out_start + offset] = ref_start + offset
                used_ref.add(ref_start + offset)
        elif tag == "replace":
            out_index = out_start
            ref_index = ref_start
            while out_index < out_end and ref_index < ref_end:
                if _compatible_paragraphs(output_paragraphs[out_index], reference_paragraphs[ref_index]):
                    matches[out_index] = ref_index
                    used_ref.add(ref_index)
                    out_index += 1
                    ref_index += 1
                else:
                    # Keep the pair unassigned instead of comparing unrelated roles.
                    break

    # Heading anchors: headings often change one word but keep their level.
    unmatched_out = [i for i in range(len(output_paragraphs)) if i not in matches]
    for out_index in list(unmatched_out):
        out_p = output_paragraphs[out_index]
        level = _heading_level(out_p)
        if not level:
            continue
        best = None
        for ref_index, ref_p in enumerate(reference_paragraphs):
            if ref_index in used_ref or _heading_level(ref_p) != level:
                continue
            score = _similarity(normalize_text(out_p.text), normalize_text(ref_p.text))
            if score >= 0.5 and (best is None or score > best[0]):
                best = (score, ref_index)
        if best is not None:
            matches[out_index] = best[1]
            used_ref.add(best[1])

    # Final pass: same role/style with a strong text match.
    for out_index in range(len(output_paragraphs)):
        if out_index in matches:
            continue
        out_p = output_paragraphs[out_index]
        out_text = normalize_text(out_p.text)
        if not out_text:
            continue
        best = None
        for ref_index, ref_p in enumerate(reference_paragraphs):
            if ref_index in used_ref or not _compatible_paragraphs(out_p, ref_p):
                continue
            score = _similarity(out_text, normalize_text(ref_p.text))
            if score >= 0.6 and (best is None or score > best[0]):
                best = (score, ref_index)
        if best is not None:
            matches[out_index] = best[1]
            used_ref.add(best[1])

    return {
        "matches": matches,
        "unmatched_output": [i for i in range(len(output_paragraphs)) if i not in matches],
        "unmatched_reference": [i for i in range(len(reference_paragraphs)) if i not in used_ref],
    }


def _table_caption(table) -> str:
    previous = table._tbl.getprevious()
    if previous is None:
        return ""
    try:
        return normalize_text(Paragraph(previous, table._parent).text)
    except Exception:
        return ""


def _table_header(table) -> str:
    if not table.rows:
        return ""
    cells = []
    try:
        from .table_engine import get_unique_row_cells

        row_cells = get_unique_row_cells(table.rows[0])
    except Exception:
        row_cells = table.rows[0].cells
    for cell in row_cells:
        cells.append(normalize_text(cell.text))
    return "|".join(cells)


def table_descriptor(table) -> Dict[str, Any]:
    grid = table._tbl.find(qn("w:tblGrid"))
    widths = []
    if grid is not None:
        for column in grid.findall(qn("w:gridCol")):
            raw = column.get(qn("w:w")) or ""
            if raw.isdigit():
                widths.append(int(raw))
    return {
        "caption": _table_caption(table),
        "header": _table_header(table),
        "column_count": len(table.columns) if table.rows else 0,
        "total_width": sum(widths),
    }


def align_tables(output_tables: Sequence[Any], reference_tables: Sequence[Any]) -> Dict[str, Any]:
    """Match tables by caption first, then by header row; never by raw index alone."""
    out_desc = [table_descriptor(t) for t in output_tables]
    ref_desc = [table_descriptor(t) for t in reference_tables]
    matches: Dict[int, int] = {}
    used_ref = set()

    def _take(out_index: int, ref_index: int) -> None:
        matches[out_index] = ref_index
        used_ref.add(ref_index)

    # 1. Exact caption match (unique on both sides).
    for out_index, out in enumerate(out_desc):
        if not out["caption"]:
            continue
        candidates = [
            i for i, ref in enumerate(ref_desc)
            if i not in used_ref and ref["caption"] == out["caption"]
        ]
        if len(candidates) == 1:
            _take(out_index, candidates[0])

    # 2. Exact header row match (unique, requires a real header).
    for out_index, out in enumerate(out_desc):
        if out_index in matches or not out["header"] or len(out["header"]) < 3:
            continue
        candidates = [
            i for i, ref in enumerate(ref_desc)
            if i not in used_ref
            and ref["header"] == out["header"]
            and ref["column_count"] == out["column_count"]
        ]
        if len(candidates) == 1:
            _take(out_index, candidates[0])

    # 3. Best caption/header similarity with the same column count.
    for out_index, out in enumerate(out_desc):
        if out_index in matches:
            continue
        best = None
        for ref_index, ref in enumerate(ref_desc):
            if ref_index in used_ref or ref["column_count"] != out["column_count"]:
                continue
            caption_score = _similarity(out["caption"], ref["caption"]) if out["caption"] and ref["caption"] else 0.0
            header_score = _similarity(out["header"], ref["header"]) if out["header"] and ref["header"] else 0.0
            score = max(caption_score, header_score * 0.8)
            if score >= 0.55 and (best is None or score > best[0]):
                best = (score, ref_index)
        if best is not None:
            _take(out_index, best[1])

    # 3b. Same ordinal slot with matching geometry: template tables whose header row
    # contains filled values still occupy the same slot. Geometry must agree, so a
    # structurally different table inserted at that slot is not silently paired.
    for out_index, out in enumerate(out_desc):
        if out_index in matches or out_index >= len(ref_desc):
            continue
        ref = ref_desc[out_index]
        if out_index in used_ref or ref["column_count"] != out["column_count"]:
            continue
        if not out["total_width"] or not ref["total_width"]:
            continue
        drift = abs(out["total_width"] - ref["total_width"]) / float(ref["total_width"])
        if drift <= 0.05 and not out["caption"] and not ref["caption"]:
            _take(out_index, out_index)

    # 4. Generic tables without captions/headers: pair by nearest index when the column
    # count is unambiguous. This preserves structural comparison for tables the template
    # does not label.
    for out_index, out in enumerate(out_desc):
        if out_index in matches:
            continue
        if out["caption"] or out["header"]:
            continue
        candidates = [
            i for i, ref in enumerate(ref_desc)
            if i not in used_ref
            and ref["column_count"] == out["column_count"]
            and not ref["caption"]
            and not ref["header"]
        ]
        if len(candidates) == 1:
            _take(out_index, candidates[0])

    # 5. Last resort: exactly one unmatched table on each side with the same column count.
    remaining_out = [i for i in range(len(out_desc)) if i not in matches]
    remaining_ref = [i for i in range(len(ref_desc)) if i not in used_ref]
    if len(remaining_out) == 1 and len(remaining_ref) == 1:
        if out_desc[remaining_out[0]]["column_count"] == ref_desc[remaining_ref[0]]["column_count"]:
            _take(remaining_out[0], remaining_ref[0])

    return {
        "matches": matches,
        "unmatched_output": [i for i in range(len(output_tables)) if i not in matches],
        "unmatched_reference": [i for i in range(len(reference_tables)) if i not in used_ref],
        "output_descriptors": out_desc,
        "reference_descriptors": ref_desc,
    }
