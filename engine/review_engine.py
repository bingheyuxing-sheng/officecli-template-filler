"""
Template-Driven REVIEW Mode Engine (v3.1).

Turns a template-vs-draft comparison into a human-reviewable document:

- Format drift is restored directly, because OOXML tracked changes cannot express
  font/size/spacing edits, and every direct edit is recorded in the review report.
- Text edits are written as real `<w:ins>` / `<w:del>` revisions with author and
  timestamp, and `<w:trackChanges/>` is switched on so WPS/Word opens in review mode.
- Items that need a human decision are written as native Word comments instead of
  being silently changed.

Nothing here uses global process killing; callers stay inside `TaskResourceGuard`.
"""
from __future__ import annotations

import copy
import difflib
import json
import os
import re
import zipfile
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import docx
from docx.opc.constants import CONTENT_TYPE as CT, RELATIONSHIP_TYPE as RT
from docx.opc.packuri import PackURI
from docx.opc.part import Part
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.oxml.parser import parse_xml
from lxml import etree

from .ooxml_utils import TOKEN_PATTERN, is_red_run, iter_all_document_paragraphs_with_Wait_context
from .repair_engine import (
    _apply_paragraph_profile,
    _classify_paragraph_role,
    _extract_paragraph_format_profile,
)
from .table_engine import (
    TBLPR_ORDER,
    TCPR_ORDER,
    TRPR_ORDER,
    compare_table_style,
    restore_table_style_from_reference,
    table_style_signature,
)
from .transaction import DocumentTransaction, TransactionAborted, TransactionPreflightError

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
REVIEW_AUTHOR_DEFAULT = "OfficeCLI Reviewer"
PLACEHOLDER_PATTERN = re.compile(r"(\{\{[^{}]+\}\}|【[^【】]+】|\*{3,}|_{3,})")
ISO_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

_MINIMAL_COMMENTS_XML = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    f'<w:comments xmlns:w="{W_NS}"></w:comments>'
)


# ---------------------------------------------------------------------------
# Revision identifiers and timestamps
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    """UTC timestamp in the exact shape Word writes into `w:date`."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class _RevisionIdAllocator:
    """Hands out `w:id` values that never collide with existing revisions or comments."""

    def __init__(self, start: int = 1):
        self._next = int(start)

    def take(self) -> int:
        value = self._next
        self._next += 1
        return value


def _scan_existing_revision_ids(doc) -> int:
    """Return one past the highest `w:id` already used in the main document part."""
    highest = 0
    root = doc.element.body if hasattr(doc, "element") else doc
    for el in root.iter():
        raw = el.get(qn("w:id"))
        if raw is None:
            continue
        tag = el.tag.rsplit("}", 1)[-1]
        if tag in ("ins", "del", "comment", "moveFrom", "moveTo",
                   "rPrChange", "pPrChange", "tblPrChange", "trPrChange", "tcPrChange", "sectPrChange"):
            try:
                highest = max(highest, int(raw))
            except (TypeError, ValueError):
                continue
    return highest + 1


_SETTINGS_BEFORE_TRACK_CHANGES = (
    "writeProtection", "view", "zoom", "removePersonalInformation", "removeDateAndTime",
    "doNotDisplayPageBoundaries", "displayBackgroundShape", "printPostScriptOverText",
    "printFractionalCharacterWidth", "printFormsData", "embedTrueTypeFonts", "embedSystemFonts",
    "saveSubsetFonts", "saveFormsData", "mirrorMargins", "alignBordersAndEdges",
    "bordersDoNotSurroundHeader", "bordersDoNotSurroundFooter", "gutterAtTop",
    "hideSpellingErrors", "hideGrammaticalErrors", "activeWritingStyle", "proofState",
    "formsDesign", "attachedTemplate", "linkStyles", "stylePaneFormatFilter",
    "stylePaneSortMethod", "documentType", "mailMerge", "revisionView",
)


def enable_track_changes(doc, enabled: bool = True) -> bool:
    """Add or remove `<w:trackChanges/>` so the delivered file opens in revision mode."""
    settings = doc.settings.element
    existing = settings.find(qn("w:trackChanges"))
    if enabled:
        if existing is None:
            node = OxmlElement("w:trackChanges")
            # `w:settings` is a schema sequence; insert after the last element that must precede it.
            insert_at = 0
            for idx, child in enumerate(settings):
                if child.tag.rsplit("}", 1)[-1] in _SETTINGS_BEFORE_TRACK_CHANGES:
                    insert_at = idx + 1
            settings.insert(insert_at, node)
        return True
    if existing is not None:
        settings.remove(existing)
    return False


def is_track_changes_enabled(doc) -> bool:
    return doc.settings.element.find(qn("w:trackChanges")) is not None


# ---------------------------------------------------------------------------
# Run-level tracked changes
# ---------------------------------------------------------------------------


def _run_text(r_el) -> str:
    return "".join((t.text or "") for t in r_el.findall(qn("w:t")))


# Child elements of a run that carry non-text content. A run containing any of these
# must never be cloned/split: the clone would duplicate drawings, field instructions,
# or footnotes in the document body.
_RUN_NONTEXT_TAGS = (
    "drawing", "object", "pict", "fldChar", "instrText", "footnoteReference",
    "endnoteReference", "commentReference", "noBreakHyphen", "sym",
)

# Direct children of `w:p` whose text belongs to a container (hyperlink, SmartTag,
# SDT run container, field result) rather than the paragraph itself. Rewriting the
# paragraph's direct runs while the match spans such a container would reorder it.
_P_CONTAINER_TAGS = ("hyperlink", "smartTag", "sdt", "fldSimple", "ins", "del",
                     "moveFrom", "moveTo", "bookmarkStart", "bookmarkEnd",
                     "commentRangeStart", "commentRangeEnd", "commentReference")


def _clone_run_with_text(r_el, text: str, keep_format_changes: bool = True):
    """Clone a run's formatting but replace every `<w:t>` with one new text node.

    Only safe on runs whose content is purely textual (`w:t` + optional `w:rPr`).
    A split run produces several clones; only the first may keep the source run's
    `w:*PrChange` mark, otherwise every clone repeats the same revision id.
    """
    clone = copy.deepcopy(r_el)
    for t in clone.findall(qn("w:t")):
        clone.remove(t)
    for extra in ("w:delText", "w:br", "w:tab"):
        for node in clone.findall(qn(extra)):
            clone.remove(node)
    if not keep_format_changes:
        for rpr in clone.findall(qn("w:rPr")):
            for child in list(rpr):
                if child.tag.rsplit("}", 1)[-1] in _FORMAT_CHANGE_TAGS:
                    rpr.remove(child)
    node = OxmlElement("w:t")
    node.set(qn("xml:space"), "preserve")
    node.text = text
    clone.append(node)
    return clone


def _as_deleted_run(r_el):
    """Convert a cloned text run into its deleted form (`w:t` becomes `w:delText`)."""
    for t in r_el.findall(qn("w:t")):
        t.tag = qn("w:delText")
    return r_el


def _wrap_deleted_run(run_el, rev_id: int, author: str, date: str):
    wrapper = OxmlElement("w:del")
    wrapper.set(qn("w:id"), str(rev_id))
    wrapper.set(qn("w:author"), author)
    wrapper.set(qn("w:date"), date)
    wrapper.append(_as_deleted_run(run_el))
    return wrapper


def _wrap_inserted_run(run_el, rev_id: int, author: str, date: str):
    wrapper = OxmlElement("w:ins")
    wrapper.set(qn("w:id"), str(rev_id))
    wrapper.set(qn("w:author"), author)
    wrapper.set(qn("w:date"), date)
    wrapper.append(run_el)
    return wrapper


def apply_tracked_replacement(
    paragraph,
    old_text: str,
    new_text: str,
    author: str = REVIEW_AUTHOR_DEFAULT,
    date: Optional[str] = None,
    revision_ids: Optional[_RevisionIdAllocator] = None,
) -> Optional[Dict[str, Any]]:
    """
    Replace `old_text` with `new_text` inside `paragraph` as tracked changes.

    Safety contract (v3.4.2):
    - Only direct text runs of the paragraph participate; the match must not span
      non-run children (hyperlinks, SDTs, fields, bookmarks, existing revisions).
      A spanning match returns None — the caller degrades to a comment instead of
      reordering document structure.
    - Runs carrying drawings, field codes or references are never cloned or split.
    - Untouched runs keep their original position; nothing outside the match moves.
    """
    if not old_text:
        return None
    p_el = paragraph._p

    # A match must live entirely in the paragraph's direct text runs. If the
    # paragraph contains any container/references children, a match is only safe
    # when it lies fully inside one contiguous run-group between them.
    direct_children = list(p_el)
    if any(_local_name(child.tag) in _P_CONTAINER_TAGS for child in direct_children):
        # Guard mode: require the match to be found within a single maximal
        # group of consecutive plain runs separated by the containers.
        return _replace_within_plain_run_group(p_el, old_text, new_text, author, date, revision_ids)

    runs = [r for r in p_el.findall(qn("w:r")) if _run_text(r)]
    if not runs:
        return None
    return _replace_in_run_list(p_el, runs, old_text, new_text, author, date, revision_ids)


def _replace_within_plain_run_group(p_el, old_text, new_text, author, date, revision_ids):
    """Attempt replacement inside ONE maximal group of consecutive plain text runs.

    Container children (hyperlinks, fields, ...) keep their absolute position:
    groups are processed independently, so removing/rebuilding a group's runs can
    never reorder a container. Returns None when the text spans multiple groups or
    is not found — never a structural rewrite.
    """
    group: List[Any] = []
    groups: List[List[Any]] = []
    for child in p_el:
        tag = _local_name(child.tag)
        if tag == "pPr":
            continue
        if tag == "r":
            if _run_text(child):
                group.append(child)
                continue
        if group:
            groups.append(group)
            group = []
    if group:
        groups.append(group)

    for group in groups:
        full_text = "".join(_run_text(r) for r in group)
        if old_text in full_text:
            return _replace_in_run_list(p_el, group, old_text, new_text, author, date, revision_ids)
    return None


def _replace_in_run_list(p_el, runs, old_text, new_text, author, date, revision_ids):
    """Rewrite one contiguous run list in place; runs outside the list never move."""
    # Refuse to clone/split runs carrying non-text content.
    if any(
        any(r.find(qn(f"w:{tag}")) is not None for tag in _RUN_NONTEXT_TAGS)
        for r in runs
    ):
        return None

    texts = [_run_text(r) for r in runs]
    full_text = "".join(texts)
    start = full_text.find(old_text)
    if start < 0:
        return None
    end = start + len(old_text)

    ids = revision_ids or _RevisionIdAllocator(_scan_existing_revision_ids(p_el.getroottree().getroot()))
    date = date or _now_iso()

    allocated_ids: List[int] = []
    nodes: List[Any] = []
    cursor = 0
    inserted = False
    for r_el, text in zip(runs, texts, strict=True):
        r_start, r_end = cursor, cursor + len(text)
        cursor = r_end
        overlap_start = max(start, r_start)
        overlap_end = min(end, r_end)
        if overlap_start >= overlap_end:
            nodes.append(copy.deepcopy(r_el))
            continue

        prefix = text[: overlap_start - r_start]
        removed = text[overlap_start - r_start : overlap_end - r_start]
        suffix = text[overlap_end - r_start :]

        # A source run may be split into prefix + del + ins + suffix. Keep its format
        # revision mark on the first clone only, so one w:id never appears four times.
        keep_format = True
        if prefix:
            nodes.append(_clone_run_with_text(r_el, prefix, keep_format))
            keep_format = False
        if removed:
            allocated_ids.append(ids.take())
            nodes.append(_wrap_deleted_run(_clone_run_with_text(r_el, removed, keep_format), allocated_ids[-1], author, date))
            keep_format = False
        if not inserted:
            if new_text:
                allocated_ids.append(ids.take())
                nodes.append(_wrap_inserted_run(_clone_run_with_text(r_el, new_text, keep_format), allocated_ids[-1], author, date))
                keep_format = False
            inserted = True
        if suffix:
            nodes.append(_clone_run_with_text(r_el, suffix, keep_format))

    if not inserted:
        return None

    # Replace only the participating runs, in place, at the first run's position.
    insert_at = p_el.index(runs[0])
    for r_el in runs:
        p_el.remove(r_el)
    for offset, node in enumerate(nodes):
        p_el.insert(insert_at + offset, node)

    return {
        "old_text": old_text,
        "new_text": new_text,
        "revision_id_start": allocated_ids[0],
        "revision_ids": allocated_ids,
        "tracked": True,
    }


# ---------------------------------------------------------------------------
# Tracked formatting revisions (w:*PrChange)
# ---------------------------------------------------------------------------
#
# OOXML tracked changes CAN express format edits: Word writes `w:rPrChange`,
# `w:pPrChange`, `w:tblPrChange`, `w:trPrChange`, `w:tcPrChange` holding the
# PRE-change properties, and the review pane shows them as accept/reject-able
# "Formatting: ..." revisions. REVIEW therefore must not silently rewrite
# formats: every restored property is paired with its old value in a change
# mark so the human confirms it. REPAIR stays direct (no marks).

_PPR_BASE_TAGS = (
    "pStyle", "keepNext", "keepLines", "pageBreakBefore", "framePr", "widowControl",
    "numPr", "suppressLineNumbers", "pBdr", "shd", "tabs", "suppressAutoHyphens",
    "kinsoku", "wordWrap", "overflowPunct", "topLinePunct", "autoSpaceDE",
    "autoSpaceDN", "bidi", "adjustRightInd", "snapToGrid", "spacing", "ind",
    "contextualSpacing", "mirrorIndents", "suppressOverlap", "jc", "textDirection",
    "textAlignment", "textboxTightWrap", "outlineLvl", "divId", "cnfStyle",
)

_RPR_BASE_TAGS = (
    "rStyle", "rFonts", "b", "bCs", "i", "iCs", "caps", "smallCaps", "strike",
    "dstrike", "outline", "shadow", "emboss", "imprint", "noProof", "snapToGrid",
    "vanish", "webHidden", "color", "spacing", "w", "kern", "position", "sz",
    "szCs", "highlight", "u", "effect", "bdr", "shd", "fitText", "vertAlign",
    "rtl", "cs", "em", "lang", "eastAsianLayout", "specVanish", "oMath",
)

_FORMAT_CHANGE_TAGS = (
    "rPrChange", "pPrChange", "tblPrChange", "trPrChange", "tcPrChange", "sectPrChange",
)

# OOXML requires every *PrChange mark to wrap the pre-change properties in a
# container element of the matching type: <w:rPrChange><w:rPr>...</w:rPr></w:rPrChange>.
_FORMAT_CHANGE_WRAPPERS = {
    "rPrChange": "rPr",
    "pPrChange": "pPr",
    "tblPrChange": "tblPr",
    "trPrChange": "trPr",
    "tcPrChange": "tcPr",
    "sectPrChange": "sectPr",
}

# Tracked row/cell insertion and deletion marks are revisions, not formatting: a
# reject must never strip them while rolling back a *PrChange.
_TRPR_FORMAT_TAGS = tuple(tag for tag in TRPR_ORDER if tag not in ("ins", "del", "trPrChange"))
_TCPR_FORMAT_TAGS = tuple(
    tag for tag in TCPR_ORDER if tag not in ("tcPrChange", "cellIns", "cellDel", "cellMerge")
)


def _format_change_base_tags(change_tag: str):
    """Formatting properties a `*PrChange` may restore, or None when unsupported."""
    if change_tag == "rPrChange":
        return _RPR_BASE_TAGS
    if change_tag == "pPrChange":
        return _PPR_BASE_TAGS
    if change_tag == "tblPrChange":
        return TBLPR_ORDER
    if change_tag == "trPrChange":
        return _TRPR_FORMAT_TAGS
    if change_tag == "tcPrChange":
        return _TCPR_FORMAT_TAGS
    return None


def _local_name(tag) -> str:
    return tag.rsplit("}", 1)[-1]


def _base_children(el, tags) -> List[Any]:
    """Schema-base children of `el` (the properties a *PrChange mark may carry)."""
    if el is None:
        return []
    return [child for child in el if _local_name(child.tag) in tags]


def _snapshot_nodes(nodes) -> List[Any]:
    """Detached copy of property nodes.

    `_base_children()` returns live elements, and the restore helpers mutate those
    elements in place. Without copying here the "old properties" recorded in a
    `*PrChange` mark would end up holding the NEW values, making reject a no-op.
    """
    return [copy.deepcopy(node) for node in nodes]


def _serialize_nodes(nodes) -> bytes:
    return b"|".join(etree.tostring(node) for node in nodes)


def _append_format_change(parent, change_tag: str, old_nodes, rev_id: int, author: str, date: str) -> None:
    """Append a Word formatting-revision mark carrying the pre-change properties.

    The old properties go inside the container element the OOXML schema mandates
    (`w:rPr` for `w:rPrChange`, `w:pPr` for `w:pPrChange`, ...), not directly on the
    change node — Word repairs or drops a flat `*PrChange` mark.
    """
    change = OxmlElement(change_tag)
    change.set(qn("w:id"), str(rev_id))
    change.set(qn("w:author"), author)
    change.set(qn("w:date"), date)
    wrapper_name = _FORMAT_CHANGE_WRAPPERS.get(_local_name(change_tag).split(":")[-1])
    container = change
    if wrapper_name:
        container = OxmlElement(f"w:{wrapper_name}")
        change.append(container)
    for node in old_nodes:
        container.append(copy.deepcopy(node))
    parent.append(change)


def _paragraph_mark_rpr(p_el):
    pPr = p_el.find(qn("w:pPr"))
    return pPr.find(qn("w:rPr")) if pPr is not None else None


def _apply_paragraph_profile_tracked(paragraph, profile, strip_red: bool, author: str, date: str, ids) -> int:
    """Restore paragraph formatting AND record every change as a tracked format revision."""
    p_el = paragraph._p
    old_ppr_nodes = _snapshot_nodes(_base_children(p_el.find(qn("w:pPr")), _PPR_BASE_TAGS))
    old_mark_nodes = _snapshot_nodes(_base_children(_paragraph_mark_rpr(p_el), _RPR_BASE_TAGS))
    old_run_nodes = [
        _snapshot_nodes(_base_children(run._r.find(qn("w:rPr")), _RPR_BASE_TAGS))
        for run in paragraph.runs
    ]

    _apply_paragraph_profile(paragraph, profile, strip_red=strip_red)

    added = 0
    # Paragraph-mark rPr first: schema requires w:rPr before w:pPrChange inside w:pPr.
    new_mark_nodes = _base_children(_paragraph_mark_rpr(p_el), _RPR_BASE_TAGS)
    if (new_mark_nodes or old_mark_nodes) and _serialize_nodes(new_mark_nodes) != _serialize_nodes(old_mark_nodes):
        target = p_el.get_or_add_pPr().get_or_add_rPr()
        _append_format_change(target, "w:rPrChange", old_mark_nodes, ids.take(), author, date)
        added += 1
    new_ppr = p_el.find(qn("w:pPr"))
    if new_ppr is not None:
        if _serialize_nodes(_base_children(new_ppr, _PPR_BASE_TAGS)) != _serialize_nodes(old_ppr_nodes):
            _append_format_change(new_ppr, "w:pPrChange", old_ppr_nodes, ids.take(), author, date)
            added += 1
    for run, old_nodes in zip(paragraph.runs, old_run_nodes, strict=False):
        new_nodes = _base_children(run._r.find(qn("w:rPr")), _RPR_BASE_TAGS)
        if _serialize_nodes(new_nodes) != _serialize_nodes(old_nodes):
            _append_format_change(run._r.get_or_add_rPr(), "w:rPrChange", old_nodes, ids.take(), author, date)
            added += 1
    return added


def _restore_table_style_tracked(target_tbl, reference_tbl, author: str, date: str, ids) -> Tuple[bool, int]:
    """Restore table style from the template AND record changes as tracked format revisions."""
    from .table_engine import TBLPR_ORDER, TCPR_ORDER, TRPR_ORDER, _get_or_add_trPr, get_unique_row_cells

    tcpr_tags = tuple(tag for tag in TCPR_ORDER if tag != "tcPrChange")
    tbl_el = target_tbl._tbl

    def _cell_marks(cell):
        marks = []
        for p in cell.paragraphs:
            marks.append((
                _base_children(_paragraph_mark_rpr(p._p), _RPR_BASE_TAGS),
                [_base_children(run._r.find(qn("w:rPr")), _RPR_BASE_TAGS) for run in p.runs],
            ))
        return marks

    old_tblpr = _snapshot_nodes(_base_children(tbl_el.find(qn("w:tblPr")), TBLPR_ORDER))
    old_trpr = [
        _snapshot_nodes(_base_children(row._tr.find(qn("w:trPr")), TRPR_ORDER))
        for row in target_tbl.rows
    ]
    old_tcpr = [
        [
            _snapshot_nodes(_base_children(cell._tc.find(qn("w:tcPr")), tcpr_tags))
            for cell in get_unique_row_cells(row)
        ]
        for row in target_tbl.rows
    ]
    old_marks = [
        [
            [
                (
                    _snapshot_nodes(mark_nodes),
                    [_snapshot_nodes(run_nodes) for run_nodes in run_groups],
                )
                for mark_nodes, run_groups in _cell_marks(cell)
            ]
            for cell in get_unique_row_cells(row)
        ]
        for row in target_tbl.rows
    ]

    if not restore_table_style_from_reference(target_tbl, reference_tbl):
        return False, 0

    added = 0
    tblPr = tbl_el.find(qn("w:tblPr"))
    if tblPr is not None and _serialize_nodes(_base_children(tblPr, TBLPR_ORDER)) != _serialize_nodes(old_tblpr):
        _append_format_change(tblPr, "w:tblPrChange", old_tblpr, ids.take(), author, date)
        added += 1

    for row, old_nodes in zip(target_tbl.rows, old_trpr, strict=False):
        trPr = row._tr.find(qn("w:trPr"))
        if _serialize_nodes(_base_children(trPr, TRPR_ORDER)) != _serialize_nodes(old_nodes):
            trPr = _get_or_add_trPr(row._tr)
            _append_format_change(trPr, "w:trPrChange", old_nodes, ids.take(), author, date)
            added += 1

    for row, old_row in zip(target_tbl.rows, old_tcpr, strict=False):
        for cell, old_nodes in zip(get_unique_row_cells(row), old_row, strict=False):
            tcPr = cell._tc.find(qn("w:tcPr"))
            if _serialize_nodes(_base_children(tcPr, tcpr_tags)) != _serialize_nodes(old_nodes):
                _append_format_change(cell._tc.get_or_add_tcPr(), "w:tcPrChange", old_nodes, ids.take(), author, date)
                added += 1

    for row, old_row_marks in zip(target_tbl.rows, old_marks, strict=False):
        for cell, old_cell_marks in zip(get_unique_row_cells(row), old_row_marks, strict=False):
            for p, (old_mark, old_runs) in zip(cell.paragraphs, old_cell_marks, strict=False):
                new_mark = _base_children(_paragraph_mark_rpr(p._p), _RPR_BASE_TAGS)
                if (new_mark or old_mark) and _serialize_nodes(new_mark) != _serialize_nodes(old_mark):
                    target = p._p.get_or_add_pPr().get_or_add_rPr()
                    _append_format_change(target, "w:rPrChange", old_mark, ids.take(), author, date)
                    added += 1
                for run, old_nodes in zip(p.runs, old_runs, strict=False):
                    new_nodes = _base_children(run._r.find(qn("w:rPr")), _RPR_BASE_TAGS)
                    if _serialize_nodes(new_nodes) != _serialize_nodes(old_nodes):
                        _append_format_change(run._r.get_or_add_rPr(), "w:rPrChange", old_nodes, ids.take(), author, date)
                        added += 1
    return True, added


def create_revision_id_allocator(doc):
    """Public helper for REFORMAT apply: allocate ids above every existing revision."""
    return _RevisionIdAllocator(_scan_existing_revision_ids(doc))


def apply_paragraph_profile_tracked(paragraph, profile, *, strip_red: bool, author: str, date: str, ids) -> int:
    """Public wrapper: restore a paragraph profile with native Word format revisions."""
    return _apply_paragraph_profile_tracked(
        paragraph, profile, strip_red=strip_red, author=author, date=date, ids=ids
    )


def restore_table_style_tracked(target_tbl, reference_tbl, *, author: str, date: str, ids) -> Tuple[bool, int]:
    """Public wrapper: restore table style with native Word format revisions."""
    return _restore_table_style_tracked(
        target_tbl, reference_tbl, author=author, date=date, ids=ids
    )


# ---------------------------------------------------------------------------
# Native Word comments
# ---------------------------------------------------------------------------


class _CommentsStore:
    """Read/write access to `/word/comments.xml`, creating the part when missing."""

    def __init__(self, doc):
        self.doc = doc
        self.part = self._resolve_part()
        self.element = parse_xml(self.part.blob)
        self._ids = _RevisionIdAllocator(self._highest_comment_id() + 1)

    def _resolve_part(self):
        for rel in self.doc.part.rels.values():
            if rel.reltype == RT.COMMENTS:
                return rel.target_part
        part = Part(PackURI("/word/comments.xml"), CT.WML_COMMENTS, _MINIMAL_COMMENTS_XML.encode("utf-8"), self.doc.part.package)
        self.doc.part.relate_to(part, RT.COMMENTS)
        return part

    def _highest_comment_id(self) -> int:
        highest = -1
        for node in self.element.findall(qn("w:comment")):
            try:
                highest = max(highest, int(node.get(qn("w:id"))))
            except (TypeError, ValueError):
                continue
        return highest

    def add(self, text: str, author: str, initials: str, date: str) -> int:
        comment_id = self._ids.take()
        comment = OxmlElement("w:comment")
        comment.set(qn("w:id"), str(comment_id))
        comment.set(qn("w:author"), author)
        comment.set(qn("w:date"), date)
        comment.set(qn("w:initials"), initials)
        p_el = OxmlElement("w:p")
        ref_run = OxmlElement("w:r")
        ref_run.append(OxmlElement("w:annotationRef"))
        p_el.append(ref_run)
        text_run = OxmlElement("w:r")
        t = OxmlElement("w:t")
        t.set(qn("xml:space"), "preserve")
        t.text = text
        text_run.append(t)
        p_el.append(text_run)
        comment.append(p_el)
        self.element.append(comment)
        return comment_id

    def flush(self) -> None:
        self.part._blob = etree.tostring(
            self.element,
            xml_declaration=True,
            encoding="UTF-8",
            standalone=True,
        )


def add_paragraph_comment(
    paragraph,
    text: str,
    author: str = REVIEW_AUTHOR_DEFAULT,
    initials: str = "OCR",
    date: Optional[str] = None,
    comments: Optional[_CommentsStore] = None,
) -> int:
    """Anchor a native comment over the whole paragraph and return its id."""
    store = comments or _CommentsStore(paragraph.part.document)
    date = date or _now_iso()
    comment_id = store.add(text, author, initials, date)

    p_el = paragraph._p
    start_marker = OxmlElement("w:commentRangeStart")
    start_marker.set(qn("w:id"), str(comment_id))
    end_marker = OxmlElement("w:commentRangeEnd")
    end_marker.set(qn("w:id"), str(comment_id))
    reference_run = OxmlElement("w:r")
    reference_run.append(OxmlElement("w:commentReference"))
    reference_run.find(qn("w:commentReference")).set(qn("w:id"), str(comment_id))

    insert_at = 0
    pPr = p_el.find(qn("w:pPr"))
    if pPr is not None:
        insert_at = p_el.index(pPr) + 1
    p_el.insert(insert_at, start_marker)
    p_el.append(end_marker)
    p_el.append(reference_run)
    return comment_id


# ---------------------------------------------------------------------------
# Review plan construction
# ---------------------------------------------------------------------------


def _build_auto_text_diff_actions(
    reference_doc,
    target_doc,
    existing_actions: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Propose tracked text revisions for paragraphs aligned with the template.

    Only pairs the semantic alignment treats as the same slot AND whose text is still
    similar (>= 0.6) become revisions. A paragraph rewritten from scratch is new content,
    not a wording correction, and must not be silently replaced.
    """
    from .alignment import align_paragraphs
    from .docx_parser import match_internal_fact_slots

    target_paragraphs = list(target_doc.paragraphs)
    reference_paragraphs = list(reference_doc.paragraphs)
    alignment = align_paragraphs(target_paragraphs, reference_paragraphs)
    claimed = {
        str(action.get("location_id"))
        for action in existing_actions
        if action.get("location_id")
    }

    actions: List[Dict[str, Any]] = []
    for target_index, reference_index in sorted(alignment["matches"].items()):
        location_id = f"body.p[{target_index}]"
        if location_id in claimed:
            continue
        target_paragraph = target_paragraphs[target_index]
        reference_paragraph = reference_paragraphs[reference_index]
        target_text = (target_paragraph.text or "").strip()
        reference_text = (reference_paragraph.text or "").strip()
        if not target_text or not reference_text or target_text == reference_text:
            continue
        # Template residue and protected containers are not authoritative text: restoring
        # them would replace real content with placeholders or disturb fields/hyperlinks.
        if TOKEN_PATTERN.search(target_text) or TOKEN_PATTERN.search(reference_text):
            continue
        # A blank internal-fact field is a slot, not text to restore: never revert a value
        # the draft legitimately filled in (e.g. 项目负责人：张三 → 项目负责人：).
        if match_internal_fact_slots(reference_text):
            continue
        if any(is_red_run(run) for run in reference_paragraph.runs):
            continue
        if reference_paragraph._p.xpath(
            ".//w:sdt | .//w:fldSimple | .//w:instrText | .//w:hyperlink | .//a:blip"
        ):
            continue
        if difflib.SequenceMatcher(None, target_text, reference_text).ratio() < 0.6:
            continue
        actions.append({
            "action_id": f"auto_text_diff_{target_index}",
            "action_type": "TRACK_TEXT_REVISION",
            "target": location_id,
            "location_id": location_id,
            "old_text": target_text,
            "new_text": reference_text,
            "reason": "自动比对：按模板文本修正",
            "change_mode": "TRACKED",
            "requires_human_review": True,
            "risk_level": "MEDIUM",
            "auto_generated": True,
        })
    return actions


def build_review_plan(
    reference_docx_path: str,
    target_docx_path: str,
    author: str = REVIEW_AUTHOR_DEFAULT,
    text_revisions: Optional[List[Dict[str, Any]]] = None,
    comment_unresolved_placeholders: bool = True,
    auto_text_diff: bool = False,
) -> Dict[str, Any]:
    """
    Diff the target document against the reference template and split the findings into
    three review channels: direct format restore, tracked text revisions, and comments.
    """
    ref_doc = docx.Document(reference_docx_path)
    tgt_doc = docx.Document(target_docx_path)

    role_catalog: Dict[str, Dict[str, Any]] = {}
    for idx, p in enumerate(ref_doc.paragraphs):
        if not (p.text or "").strip():
            continue
        role = _classify_paragraph_role(p, idx)
        role_catalog.setdefault(role, _extract_paragraph_format_profile(p))

    actions: List[Dict[str, Any]] = []
    format_count = 0
    comment_count = 0

    for p_idx, tgt_p in enumerate(tgt_doc.paragraphs):
        text = (tgt_p.text or "").strip()
        if not text:
            continue
        role = _classify_paragraph_role(tgt_p, p_idx)

        ref_profile = None
        if p_idx < len(ref_doc.paragraphs) and (ref_doc.paragraphs[p_idx].text or "").strip():
            if _classify_paragraph_role(ref_doc.paragraphs[p_idx], p_idx) == role:
                ref_profile = _extract_paragraph_format_profile(ref_doc.paragraphs[p_idx])
        if ref_profile is None:
            ref_profile = role_catalog.get(role) or role_catalog.get("body")

        if ref_profile is not None:
            tgt_profile = _extract_paragraph_format_profile(tgt_p)
            diffs = {}
            for key in ("jc", "spacing_line", "spacing_lineRule", "first_line_indent", "sz_val", "font_east_asia", "font_ascii"):
                if ref_profile.get(key) is not None and ref_profile.get(key) != tgt_profile.get(key):
                    diffs[key] = {"reference": ref_profile.get(key), "target": tgt_profile.get(key)}
            has_red = any(is_red_run(r, tgt_p) for r in tgt_p.runs)
            if diffs or has_red:
                actions.append({
                    "action_id": f"format_restore_{p_idx}",
                    "action_type": "RESTORE_PARAGRAPH_FORMAT",
                    "target": f"body.p[{p_idx}]",
                    "paragraph_index": p_idx,
                    "role": role,
                    "target_profile": ref_profile,
                    "strip_red": has_red,
                    "diffs": diffs,
                    "change_mode": "DIRECT",
                    "requires_human_review": False,
                    "risk_level": "LOW",
                })
                format_count += 1

        if comment_unresolved_placeholders:
            placeholder = PLACEHOLDER_PATTERN.search(text)
            if placeholder:
                actions.append({
                    "action_id": f"comment_placeholder_{p_idx}",
                    "action_type": "ADD_REVIEW_COMMENT",
                    "target": f"body.p[{p_idx}]",
                    "paragraph_index": p_idx,
                    "comment": f"待人工确认：此行仍含模板占位内容 {placeholder.group(0)}，请核对是否应替换为正式内容。",
                    "change_mode": "COMMENT",
                    "requires_human_review": True,
                    "risk_level": "MEDIUM",
                })
                comment_count += 1

    reference_tables = list(ref_doc.tables)
    for t_idx, target_tbl in enumerate(tgt_doc.tables):
        if t_idx >= len(reference_tables):
            break
        reference_tbl = reference_tables[t_idx]
        issues = compare_table_style(
            table_style_signature(target_tbl),
            table_style_signature(reference_tbl),
            t_idx,
        )
        if issues:
            actions.append({
                "action_id": f"table_style_restore_{t_idx}",
                "action_type": "RESTORE_TABLE_STYLE",
                "target": f"body.tbl[{t_idx}]",
                "table_index": t_idx,
                "issues": [list(issue) for issue in issues],
                "change_mode": "DIRECT",
                "requires_human_review": False,
                "risk_level": "LOW",
            })

    for revision_index, revision in enumerate(text_revisions or []):
        old_text = str(revision.get("old_text", ""))
        new_text = str(revision.get("new_text", ""))
        if not old_text:
            continue
        actions.append({
            "action_id": f"text_revision_{revision_index}",
            "action_type": "TRACK_TEXT_REVISION",
            "target": revision.get("location_id") or revision.get("target", "auto_locate"),
            "location_id": revision.get("location_id"),
            "occurrence": revision.get("occurrence"),
            "old_text": old_text,
            "new_text": new_text,
            "reason": revision.get("reason", "按模板规范修正文本"),
            "change_mode": "TRACKED",
            "requires_human_review": True,
            "risk_level": revision.get("risk_level", "MEDIUM"),
        })

    auto_text_actions: List[Dict[str, Any]] = []
    if auto_text_diff:
        auto_text_actions = _build_auto_text_diff_actions(ref_doc, tgt_doc, actions)
        actions.extend(auto_text_actions)

    return {
        "schema_version": "3.1",
        "task_mode": "REVIEW",
        "reference_docx": reference_docx_path,
        "target_docx": target_docx_path,
        "author": author,
        "track_changes": True,
        "summary": {
            "format_restore_actions": format_count,
            "table_style_restores": len([a for a in actions if a["action_type"] == "RESTORE_TABLE_STYLE"]),
            "tracked_text_revisions": len(text_revisions or []),
            "auto_text_diffs": len(auto_text_actions),
            "comments": comment_count,
            "total_actions": len(actions),
        },
        "actions": actions,
    }


# ---------------------------------------------------------------------------
# PROOFREAD auto-check
# ---------------------------------------------------------------------------

# Only unambiguous misspellings go in the lexicon. Judgement calls (的/地/得, 权力/权利,
# 截止/截至) are deliberately absent: flagging them would create false corrections.
_PROOFREAD_TYPO_MAP = {
    "按装": "安装",
    "帐号": "账号",
    "帐户": "账户",
    "做为": "作为",
    "侯选": "候选",
    "既使": "即使",
    "部份": "部分",
    "关健": "关键",
    "决对": "绝对",
    "以经": "已经",
    "因该": "应该",
    "在次": "再次",
}
_PROOFREAD_TYPO_RE = re.compile(
    "|".join(re.escape(word) for word in sorted(_PROOFREAD_TYPO_MAP, key=len, reverse=True))
)


def build_findings_review_plan(
    target_docx_path: str,
    findings: Any,
    author: str = REVIEW_AUTHOR_DEFAULT,
    text_revisions: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Turn external findings (Excel/JSON/consistency QA) into inline Word comments.

    This is the REVIEW path for evidence that is not a sibling DOCX. The deliverable is
    still the target document with native comments and track changes; the findings file
    and the report JSON are sidecars, never the deliverable. Every finding must resolve
    to a real paragraph or table cell, otherwise the plan is rejected instead of
    silently dropping the comment.
    """
    if isinstance(findings, dict):
        items = findings.get("findings")
        if items is None:
            items = findings.get("issues")
        if items is None:
            items = [findings]
    else:
        items = findings
    if not isinstance(items, list):
        raise ValueError("findings must be a JSON list or an object with a findings/issues list")

    doc = docx.Document(target_docx_path)
    actions: List[Dict[str, Any]] = []
    unresolved: List[Dict[str, Any]] = []

    for index, item in enumerate(items):
        if not isinstance(item, dict):
            unresolved.append({"index": index, "reason": "NOT_AN_OBJECT"})
            continue
        location = str(
            item.get("location") or item.get("location_id") or item.get("target") or ""
        ).strip()
        comment = str(
            item.get("comment") or item.get("detail") or item.get("message") or ""
        ).strip()
        if not location or not comment:
            unresolved.append({
                "index": index,
                "location": location,
                "reason": "LOCATION_OR_COMMENT_MISSING",
            })
            continue
        if _resolve_comment_paragraph(doc, location) is None:
            unresolved.append({
                "index": index,
                "location": location,
                "reason": "LOCATION_NOT_FOUND",
            })
            continue
        code = str(item.get("code") or "").strip()
        severity = str(item.get("severity") or "medium").lower()
        comment_text = comment if not code or comment.startswith("[") else f"[{code}] {comment}"
        actions.append({
            "action_id": f"finding_comment_{index}",
            "action_type": "ADD_REVIEW_COMMENT",
            "target": location,
            "location_id": location,
            "comment": comment_text,
            "change_mode": "COMMENT",
            "requires_human_review": True,
            "risk_level": severity if severity in ("high", "medium", "low") else "medium",
            "finding_code": code,
        })

    if unresolved:
        raise ValueError(
            "COMMENT_LOCATION_UNRESOLVED: "
            + json.dumps(unresolved, ensure_ascii=False)
        )

    for revision_index, revision in enumerate(text_revisions or []):
        old_text = str(revision.get("old_text", ""))
        new_text = str(revision.get("new_text", ""))
        if not old_text:
            continue
        actions.append({
            "action_id": f"text_revision_{revision_index}",
            "action_type": "TRACK_TEXT_REVISION",
            "target": revision.get("location_id") or revision.get("target", "auto_locate"),
            "location_id": revision.get("location_id"),
            "occurrence": revision.get("occurrence"),
            "old_text": old_text,
            "new_text": new_text,
            "reason": revision.get("reason", "按模板规范修正文本"),
            "change_mode": "TRACKED",
            "requires_human_review": True,
            "risk_level": revision.get("risk_level", "MEDIUM"),
        })

    return {
        "schema_version": "3.1",
        "task_mode": "REVIEW",
        "reference_docx": target_docx_path,
        "target_docx": target_docx_path,
        "author": author,
        "track_changes": True,
        "review_source": "EXTERNAL_FINDINGS",
        "summary": {
            "format_restore_actions": 0,
            "table_style_restores": 0,
            "tracked_text_revisions": len(text_revisions or []),
            "auto_text_diffs": 0,
            "comments": len([a for a in actions if a["action_type"] == "ADD_REVIEW_COMMENT"]),
            "total_actions": len(actions),
        },
        "actions": actions,
    }


def audit_proofread_candidates(docx_path: Optional[str] = None, doc=None) -> Dict[str, Any]:
    """Deterministic proofreading evidence: content contradictions plus typo candidates.

    Nothing here decides which value is correct. Every finding is a comment the human
    accepts or rejects; numeric corrections are never invented.
    """
    if doc is None:
        doc = docx.Document(docx_path)

    issues: List[Dict[str, Any]] = []
    coverage_gaps: List[str] = []

    try:
        from .consistency_qa import audit_content_consistency

        content_report = audit_content_consistency(doc=doc)
        for issue in content_report.get("issues") or []:
            issues.append({**issue, "source": "content_qa"})
    except Exception as exc:  # a failed check must be reported, never treated as a pass
        coverage_gaps.append(f"CONTENT_QA_FAILED: {exc}")

    seen = set()
    for context in iter_all_document_paragraphs_with_Wait_context(doc):
        text = context["paragraph"].text or ""
        if not text.strip():
            continue
        for match in _PROOFREAD_TYPO_RE.finditer(text):
            wrong = match.group(0)
            key = (context["location_id"], wrong)
            if key in seen:
                continue
            seen.add(key)
            issues.append({
                "code": "PROOFREAD_TYPO_CANDIDATE",
                "location": context["location_id"],
                "detail": f"“{wrong}”疑似应为“{_PROOFREAD_TYPO_MAP[wrong]}”",
                "severity": "low",
                "source": "typo_lexicon",
            })

    # Duplicate headings are a structural logic problem (two sections with the same
    # title), not a spelling issue. Only real headings participate, never TOC entries.
    from .workflow import is_heading_paragraph

    heading_locations: Dict[str, str] = {}
    for index, paragraph in enumerate(doc.paragraphs):
        if not is_heading_paragraph(paragraph):
            continue
        title = (paragraph.text or "").strip()
        if not title:
            continue
        key = re.sub(r"\s+", "", title)
        location = f"body.p[{index}]"
        if key in heading_locations:
            issues.append({
                "code": "PROOFREAD_DUPLICATE_HEADING",
                "location": location,
                "detail": f"标题“{title}”与 {heading_locations[key]} 重复，请确认是否为重复章节",
                "severity": "low",
                "source": "structure",
            })
        else:
            heading_locations[key] = location

    try:
        from .logic_qa import audit_logic

        logic_report = audit_logic(doc)
        issues.extend(logic_report.get("issues") or [])
    except Exception as exc:  # a failed logic pass is a coverage gap, never a pass
        coverage_gaps.append(f"LOGIC_QA_FAILED: {exc}")

    return {
        "passed": not issues and not coverage_gaps,
        "issues": issues,
        "issue_count": len(issues),
        "coverage_gaps": coverage_gaps,
        "unverified_count": len(coverage_gaps),
    }


def build_proofread_plan(
    target_docx_path: str,
    author: str = REVIEW_AUTHOR_DEFAULT,
    text_revisions: Optional[List[Dict[str, Any]]] = None,
    auto_check: bool = True,
) -> Dict[str, Any]:
    """PROOFREAD plan: supplied fixes are tracked edits, automated findings are comments."""
    plan = build_review_plan(
        target_docx_path,
        target_docx_path,
        author=author,
        text_revisions=text_revisions,
    )
    plan["task_mode"] = "PROOFREAD"

    auto_check_comments = 0
    if auto_check:
        audit = audit_proofread_candidates(docx_path=target_docx_path)
        existing = {
            (action.get("location_id"), action.get("comment"))
            for action in plan["actions"]
            if action.get("action_type") == "ADD_REVIEW_COMMENT"
        }
        for index, issue in enumerate(audit["issues"]):
            comment = f"[自动检查:{issue.get('code')}] {issue.get('detail')}"
            key = (issue.get("location"), comment)
            if key in existing:
                continue
            plan["actions"].append({
                "action_id": f"auto_check_{index}",
                "action_type": "ADD_REVIEW_COMMENT",
                "target": issue.get("location"),
                "location_id": issue.get("location"),
                "comment": comment,
                "change_mode": "COMMENT",
                "requires_human_review": True,
                "risk_level": "MEDIUM" if issue.get("severity") == "high" else "LOW",
                "auto_generated": True,
            })
            auto_check_comments += 1
        plan["auto_check"] = {
            "issue_count": audit["issue_count"],
            "coverage_gaps": audit.get("coverage_gaps") or [],
        }
    else:
        plan["auto_check"] = {"issue_count": 0, "coverage_gaps": [], "disabled": True}

    plan["summary"]["auto_check_comments"] = auto_check_comments
    plan["summary"]["total_actions"] = len(plan["actions"])
    return plan


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------


def _full_text_of(doc) -> str:
    return "\n".join(p.text or "" for p in doc.paragraphs)


def _find_paragraph_by_location(doc, location_id: str):
    """Resolve a `location_id` from the unified walker to its paragraph, or None."""
    for context in iter_all_document_paragraphs_with_Wait_context(doc):
        if context["location_id"] == location_id:
            return context["paragraph"]
    return None


def _resolve_comment_paragraph(doc, location_id: str):
    """Resolve a QA issue location (paragraph, header/footer or table cell) to a paragraph.

    `consistency_qa` reports table cells as `body.tbl[t].r[r].c[c]` while the walker
    addresses their paragraphs as `...c[c].p[i]`; fall back to the first paragraph in
    that cell so the finding still gets a visible comment.
    """
    exact = _find_paragraph_by_location(doc, location_id)
    if exact is not None:
        return exact
    contexts = list(iter_all_document_paragraphs_with_Wait_context(doc))
    if ".p[" not in location_id:
        for context in contexts:
            if context["location_id"].startswith(location_id + ".p["):
                return context["paragraph"]
    for context in contexts:
        if context["location_id"].startswith(location_id):
            return context["paragraph"]
    return None


def _count_occurrences(doc, needle: str) -> int:
    total = 0
    for context in iter_all_document_paragraphs_with_Wait_context(doc):
        total += (context["paragraph"].text or "").count(needle)
    return total


def _merge_diff_kind(target_tbl, reference_tbl) -> List[str]:
    """Merge-topology properties (gridSpan/hMerge/vMerge) that still differ between tables."""
    from .table_engine import compare_table_style, table_style_signature

    kinds: List[str] = []
    for issue in compare_table_style(
        table_style_signature(target_tbl), table_style_signature(reference_tbl), 0
    ):
        if issue[0] == "table_cell_property" and len(issue) > 4 and issue[4] in ("gridSpan", "hMerge", "vMerge"):
            kinds.append(str(issue[4]))
    return sorted(set(kinds))


def execute_review_plan(
    review_plan: Dict[str, Any],
    output_docx_path: str,
    snapshot_path: Optional[str] = None,
    *,
    gate_record=None,
) -> Dict[str, Any]:
    """
    Apply the review plan: restore formatting, write tracked text revisions, anchor comments,
    turn on track changes, and save the reviewable document.

    A revision snapshot is written next to the output (pass `snapshot_path=""` to skip it,
    e.g. when a caller publishes the document through a transaction first).
    """
    if str(review_plan.get("task_mode") or "").upper() == "REVIEW":
        from template_gate.validator import require_confirmed_gate

        require_confirmed_gate(review_plan["reference_docx"], "REVIEW", gate_record=gate_record)
    ref_doc = docx.Document(review_plan["reference_docx"])
    tgt_doc = docx.Document(review_plan["target_docx"])
    author = review_plan.get("author") or REVIEW_AUTHOR_DEFAULT
    date = _now_iso()

    revision_ids = _RevisionIdAllocator(_scan_existing_revision_ids(tgt_doc))
    comments: Optional[_CommentsStore] = None
    applied_format = 0
    tracked = 0
    tracked_format = 0
    added_comments = 0
    unresolved: List[str] = []
    action_results: List[Dict[str, Any]] = []

    for action in review_plan.get("actions", []):
        action_type = action.get("action_type")

        if action_type == "RESTORE_PARAGRAPH_FORMAT":
            p_idx = action.get("paragraph_index")
            if p_idx is not None and p_idx < len(tgt_doc.paragraphs):
                first_id = revision_ids._next
                marks = _apply_paragraph_profile_tracked(
                    tgt_doc.paragraphs[p_idx],
                    action.get("target_profile", {}),
                    strip_red=bool(action.get("strip_red", False)),
                    author=author,
                    date=date,
                    ids=revision_ids,
                )
                applied_format += 1
                tracked_format += marks
                action_results.append({
                    "action_id": action.get("action_id"),
                    "status": "APPLIED",
                    "target": f"body.p[{p_idx}]",
                    "revision_ids": [],
                    "format_revision_ids": list(range(first_id, first_id + marks)),
                })

        elif action_type == "RESTORE_TABLE_STYLE":
            t_idx = action.get("table_index")
            if t_idx is not None and t_idx < len(tgt_doc.tables) and t_idx < len(ref_doc.tables):
                first_id = revision_ids._next
                ok, marks = _restore_table_style_tracked(
                    tgt_doc.tables[t_idx], ref_doc.tables[t_idx],
                    author=author, date=date, ids=revision_ids,
                )
                if ok:
                    applied_format += 1
                    tracked_format += marks
                    # Merge topology (gridSpan/hMerge/vMerge) is deliberately not
                    # rewritten — a merge change can destroy business content. If it
                    # still differs from the template, the action must NOT claim
                    # full success.
                    unresolved_kinds = _merge_diff_kind(tgt_doc.tables[t_idx], ref_doc.tables[t_idx])
                    status = "PARTIALLY_APPLIED" if unresolved_kinds else "APPLIED"
                    action_results.append({
                        "action_id": action.get("action_id"),
                        "status": status,
                        "target": f"body.tbl[{t_idx}]",
                        "revision_ids": [],
                        "format_revision_ids": list(range(first_id, first_id + marks)),
                        "restored_properties": ["tblPr", "trPr", "tcW", "tcMar", "shd", "vAlign", "trHeight", "fonts"],
                        "unresolved_properties": unresolved_kinds,
                        "requires_human_review": bool(unresolved_kinds),
                    })
                else:
                    unresolved.append(f"table_style:{t_idx}")
                    action_results.append({
                        "action_id": action.get("action_id"),
                        "status": "UNRESOLVED",
                        "revision_ids": [],
                        "format_revision_ids": [],
                    })

        elif action_type == "TRACK_TEXT_REVISION":
            old_text = action.get("old_text", "")
            new_text = action.get("new_text", "")
            location_id = action.get("location_id") or ""
            occurrence = action.get("occurrence")
            located = False
            ambiguous = False

            # Safety rule: never guess when the text is ambiguous. With no explicit
            # location and multiple matches, hand the decision to a human comment
            # instead of silently editing the first hit.
            if not location_id and not isinstance(occurrence, int) and _count_occurrences(tgt_doc, old_text) > 1:
                ambiguous = True
            else:
                candidates = []
                resolved_location = location_id
                if location_id:
                    p = _find_paragraph_by_location(tgt_doc, location_id)
                    if p is not None:
                        candidates = [(p, location_id)]
                else:
                    contexts = list(iter_all_document_paragraphs_with_Wait_context(tgt_doc))
                    if isinstance(occurrence, int) and occurrence >= 1:
                        seen = 0
                        for context in contexts:
                            hits = (context["paragraph"].text or "").count(old_text)
                            if hits:
                                seen += hits
                                if seen >= occurrence:
                                    candidates = [(context["paragraph"], context["location_id"])]
                                    break
                    else:
                        candidates = [(context["paragraph"], context["location_id"]) for context in contexts]

                for p, context_location in candidates:
                    result = apply_tracked_replacement(
                        p, old_text, new_text, author=author, date=date, revision_ids=revision_ids
                    )
                    if result is not None:
                        tracked += 1
                        located = True
                        action_results.append({
                            "action_id": action.get("action_id"),
                            "status": "APPLIED",
                            "target": resolved_location if location_id else context_location,
                            "revision_ids": result["revision_ids"],
                            "format_revision_ids": [],
                        })
                        break

            if not located:
                unresolved.append(f"text_revision:{old_text[:30]}")
                action_results.append({
                    "action_id": action.get("action_id"),
                    "status": "UNRESOLVED",
                    "revision_ids": [],
                    "format_revision_ids": [],
                    **({"reason": "AMBIGUOUS_MULTIPLE_MATCHES"} if ambiguous else {}),
                })
                # Never drop an intended edit silently: show it as a comment the reviewer can act on.
                anchor_context = next((c for c in iter_all_document_paragraphs_with_Wait_context(tgt_doc) if (c["paragraph"].text or "").strip()), None)
                if anchor_context is not None:
                    comments = comments or _CommentsStore(tgt_doc)
                    if ambiguous:
                        message = (
                            f"原文“{old_text}”在文档中出现多处，未指定位置，"
                            "为避免改错位置已停止自动修改，请人工确认应修改哪一处。"
                        )
                    else:
                        message = (
                            f"未能自动定位该修订：原文“{old_text}”未在文档中找到。"
                            f"建议改为“{new_text}”，请人工确认应修改的位置。"
                        )
                    add_paragraph_comment(
                        anchor_context["paragraph"],
                        message,
                        author=author,
                        date=date,
                        comments=comments,
                    )
                    added_comments += 1

        elif action_type == "ADD_REVIEW_COMMENT":
            paragraph = None
            comment_location = str(action.get("location_id") or "")
            if comment_location:
                paragraph = _resolve_comment_paragraph(tgt_doc, comment_location)
            p_idx = action.get("paragraph_index")
            if paragraph is None and p_idx is not None and p_idx < len(tgt_doc.paragraphs):
                paragraph = tgt_doc.paragraphs[p_idx]
            if paragraph is not None:
                comments = comments or _CommentsStore(tgt_doc)
                add_paragraph_comment(
                    paragraph,
                    action.get("comment", ""),
                    author=author,
                    date=date,
                    comments=comments,
                )
                added_comments += 1
                action_results.append({
                    "action_id": action.get("action_id"),
                    "status": "APPLIED",
                    "target": comment_location or f"body.p[{p_idx}]",
                    "revision_ids": [],
                    "format_revision_ids": [],
                })

    if comments is not None:
        comments.flush()

    if review_plan.get("track_changes", True):
        enable_track_changes(tgt_doc, True)

    tgt_doc.save(output_docx_path)

    snapshot_report = None
    if snapshot_path != "":
        snapshot_report = write_review_snapshot(output_docx_path, snapshot_path=snapshot_path or None)

    return {
        "output_docx": output_docx_path,
        "format_restored": applied_format,
        "tracked_format_changes": tracked_format,
        "tracked_text_revisions": tracked,
        "comments_added": added_comments,
        "unresolved_actions": unresolved,
        "action_results": action_results,
        "revision_count": tracked,
        "track_changes_enabled": bool(review_plan.get("track_changes", True)),
        "review_mode": "TRACKED_CHANGES",
        "snapshot_path": (snapshot_report or {}).get("snapshot_path"),
        "snapshot_revision_count": (snapshot_report or {}).get("revision_count", 0),
    }


# ---------------------------------------------------------------------------
# Review integrity QA
# ---------------------------------------------------------------------------


def _part_xml_bytes(docx_path: str, part_name: str) -> Optional[bytes]:
    import zipfile

    with zipfile.ZipFile(docx_path) as zf:
        try:
            return zf.read(part_name)
        except KeyError:
            return None


def iter_revision_marks(root):
    """Yield `(node, kind)` for every revision mark; kind is `"text"` or `"format"`."""
    for node in root.iter():
        tag = _local_name(node.tag)
        if tag in ("ins", "del"):
            yield node, "text"
        elif tag in _FORMAT_CHANGE_TAGS:
            yield node, "format"


def _iter_revision_nodes(root):
    """Text revisions only (`w:ins` / `w:del`); kept for callers of the older API."""
    for node, kind in iter_revision_marks(root):
        if kind == "text":
            yield node


def _node_path(root, target) -> Optional[List[int]]:
    """Child-index path from `root` to `target`, or None when `target` is outside `root`."""
    path: List[int] = []
    node = target
    while node is not root:
        parent = node.getparent() if node is not None else None
        if parent is None:
            return None
        path.append(parent.index(node))
        node = parent
    path.reverse()
    return path


def _find_by_path(root, path):
    """Resolve a `_node_path()` result back to the element, or None when it moved."""
    node = root
    for index in path or []:
        try:
            node = node[int(index)]
        except (IndexError, TypeError, ValueError):
            return None
    return node


def _paragraph_anchor_text(node) -> str:
    """Text of the owning paragraph, excluding the revision mark itself."""
    parent = node
    while parent is not None and _local_name(parent.tag) != "p":
        parent = parent.getparent()
    if parent is None:
        return ""
    chunks: List[str] = []

    def _collect(el):
        for child in el:
            if child is node:
                continue
            if _local_name(child.tag) in ("t", "delText"):
                chunks.append(child.text or "")
            else:
                _collect(child)

    _collect(parent)
    return "".join(chunks).strip()[:120]


def _iter_revision_parts(docx_path: str):
    """Yield `(part_name, root)` for every Word part that can carry revisions."""
    with zipfile.ZipFile(docx_path) as archive:
        for name in archive.namelist():
            if not name.startswith("word/") or not name.endswith(".xml") or name.endswith("settings.xml"):
                continue
            try:
                yield name, etree.fromstring(archive.read(name))
            except etree.XMLSyntaxError:
                continue


def list_revisions(docx_path: str, include_format: bool = False) -> List[Dict[str, Any]]:
    """List Word revisions across document, headers, footers, footnotes and endnotes.

    Set `include_format=True` to also list tracked formatting revisions (`w:*PrChange`)
    in the same shape; every entry carries `kind` (`"text"` or `"format"`).
    """
    revisions: List[Dict[str, Any]] = []
    for name, root in _iter_revision_parts(docx_path):
        for node, kind in iter_revision_marks(root):
            if kind == "format":
                if include_format:
                    revisions.append(_format_revision_entry(name, node))
                continue
            revision_type = _local_name(node.tag)
            text_nodes = node.findall(".//" + qn("w:t")) if revision_type == "ins" else node.findall(".//" + qn("w:delText"))
            revisions.append({
                "part": name,
                "kind": "text",
                "revision_id": node.get(qn("w:id")),
                "type": revision_type,
                "author": node.get(qn("w:author")),
                "date": node.get(qn("w:date")),
                "text": "".join((item.text or "") for item in text_nodes),
            })
    return revisions


def _format_revision_entry(part_name: str, node) -> Dict[str, Any]:
    tag = _local_name(node.tag)
    wrapper_name = _FORMAT_CHANGE_WRAPPERS.get(tag)
    wrapper = node.find(qn(f"w:{wrapper_name}")) if wrapper_name else None
    # v3.4 wrote the old properties flat on the change node; keep reading
    # those files and say so instead of pretending they are schema-valid.
    property_nodes = list(wrapper) if wrapper is not None else list(node)
    return {
        "part": part_name,
        "kind": "format",
        "revision_id": node.get(qn("w:id")),
        "type": tag,
        "author": node.get(qn("w:author")),
        "date": node.get(qn("w:date")),
        "wrapper_tag": wrapper_name,
        "legacy_flat_mark": bool(wrapper_name and wrapper is None),
        "old_properties": [_local_name(child.tag) for child in property_nodes],
    }


def list_format_revisions(docx_path: str) -> List[Dict[str, Any]]:
    """List tracked formatting revisions (`w:*PrChange`) with their pre-change properties."""
    revisions: List[Dict[str, Any]] = []
    for name, root in _iter_revision_parts(docx_path):
        for node, kind in iter_revision_marks(root):
            if kind == "format":
                revisions.append(_format_revision_entry(name, node))
    return revisions


# ---------------------------------------------------------------------------
# Revision snapshot (restore support for accepted/rejected revisions)
# ---------------------------------------------------------------------------

REVIEW_SNAPSHOT_SCHEMA_VERSION = "1.0"


def review_snapshot_path(docx_path: str) -> str:
    """Default snapshot location: `<stem>.review_snapshot.json` next to the document."""
    base, _ext = os.path.splitext(os.path.abspath(docx_path))
    return base + ".review_snapshot.json"


def build_review_snapshot(docx_path: str) -> Dict[str, Any]:
    """Capture every revision mark with a locator and its serialized XML.

    accept/reject throws the mark away, so without this capture `restore_revision`
    would have nothing to rebuild the mark from.
    """
    revisions: List[Dict[str, Any]] = []
    for name, root in _iter_revision_parts(docx_path):
        for node, kind in iter_revision_marks(root):
            parent = node.getparent()
            if parent is None:
                continue
            entry: Dict[str, Any] = {
                "revision_id": node.get(qn("w:id")),
                "kind": kind,
                "type": _local_name(node.tag),
                "part": name,
                "author": node.get(qn("w:author")),
                "date": node.get(qn("w:date")),
                "parent_path": _node_path(root, parent) or [],
                "parent_tag": _local_name(parent.tag),
                "index_in_parent": parent.index(node),
                "anchor_text": _paragraph_anchor_text(node),
                "mark_xml": etree.tostring(node, encoding="unicode"),
            }
            if kind == "format":
                format_entry = _format_revision_entry(name, node)
                entry["wrapper_tag"] = format_entry["wrapper_tag"]
                entry["old_properties"] = format_entry["old_properties"]
                entry["legacy_flat_mark"] = format_entry["legacy_flat_mark"]
            revisions.append(entry)
    return {
        "schema_version": REVIEW_SNAPSHOT_SCHEMA_VERSION,
        "source_docx": os.path.abspath(docx_path),
        "generated_at": _now_iso(),
        "revision_count": len(revisions),
        "revisions": revisions,
    }


def write_review_snapshot(docx_path: str, snapshot_path: Optional[str] = None) -> Dict[str, Any]:
    """Write the revision snapshot for `docx_path` and report where it went."""
    target = snapshot_path or review_snapshot_path(docx_path)
    snapshot = build_review_snapshot(docx_path)
    os.makedirs(os.path.dirname(os.path.abspath(target)) or ".", exist_ok=True)
    with open(target, "w", encoding="utf-8") as handle:
        json.dump(snapshot, handle, ensure_ascii=False, indent=2)
    return {
        "snapshot_path": os.path.abspath(target),
        "revision_count": snapshot["revision_count"],
    }


def _restore_revision_from_snapshot(
    docx_path: str,
    output_docx_path: str,
    revision_id: str,
    snapshot_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Rebuild one revision mark from `review_snapshot.json`, verifying the location."""
    snapshot_file = snapshot_path or review_snapshot_path(docx_path)
    result: Dict[str, Any] = {
        "output_docx": None,
        "revision_id": str(revision_id),
        "action": "restore",
        "kind": None,
        "type": None,
        "changed": 0,
        "snapshot_path": snapshot_file,
        "transaction": None,
    }
    if not os.path.isfile(snapshot_file):
        result["status"] = "SNAPSHOT_MISSING"
        return result
    with open(snapshot_file, "r", encoding="utf-8") as handle:
        snapshot = json.load(handle)
    entry = next(
        (item for item in snapshot.get("revisions", [])
         if str(item.get("revision_id")) == str(revision_id)),
        None,
    )
    if entry is None:
        result["status"] = "SNAPSHOT_MISSING"
        return result
    result["kind"] = entry.get("kind")
    result["type"] = entry.get("type")

    with zipfile.ZipFile(docx_path) as source:
        payloads = {name: source.read(name) for name in source.namelist()}
        infos = {name: source.getinfo(name) for name in source.namelist()}
    part = entry.get("part")
    if part not in payloads:
        result["status"] = "LOCATION_LOST"
        return result
    try:
        root = etree.fromstring(payloads[part])
        mark = etree.fromstring(entry["mark_xml"].encode("utf-8"))
    except (etree.XMLSyntaxError, KeyError):
        result["status"] = "SNAPSHOT_INVALID"
        return result

    parent = _find_by_path(root, entry.get("parent_path") or [])
    if parent is None or _local_name(parent.tag) != entry.get("parent_tag"):
        result["status"] = "LOCATION_LOST"
        return result
    index = int(entry.get("index_in_parent") or 0)
    parent.insert(min(max(index, 0), len(parent)), mark)
    payloads[part] = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)

    tx = DocumentTransaction(docx_path, output_docx_path, task_mode="REVISION_RESTORE")
    audit: Dict[str, Any] = {}
    try:
        with tx:
            with zipfile.ZipFile(tx.stage(), "w") as target:
                for name, payload in payloads.items():
                    target.writestr(infos[name], payload)
            restored_ids = {
                str(item["revision_id"])
                for item in list_revisions(tx.temp_path, include_format=True)
            }
            if str(revision_id) not in restored_ids:
                tx.abort("RESTORE_FAILED")
                result["status"] = "RESTORE_FAILED"
                result["transaction"] = tx.record()
                return result
            audit = audit_review_integrity(tx.temp_path)
            tx.record_qa(audit)
            tx.commit()
    except (TransactionPreflightError, TransactionAborted) as exc:
        result["status"] = "RESTORE_FAILED"
        result["error"] = str(exc)
        result["issues"] = [item["detail"] for item in audit.get("issues", [])]
        result["transaction"] = tx.record()
        return result

    result.update(
        status="RESTORED",
        changed=1,
        output_docx=output_docx_path,
        transaction=tx.record(),
    )
    return result



def _apply_text_revision(node, action: str) -> None:
    """Accept, reject or revert one `w:ins` / `w:del` mark in place."""
    revision_type = _local_name(node.tag)
    parent = node.getparent()
    if action == "accept":
        if revision_type == "ins":
            index = parent.index(node)
            for child in list(node):
                parent.insert(index, child)
                index += 1
        parent.remove(node)
    elif action in ("reject", "restore"):
        if revision_type == "ins":
            parent.remove(node)
        else:
            index = parent.index(node)
            for child in list(node):
                for text_node in child.iter(qn("w:delText")):
                    text_node.tag = qn("w:t")
                parent.insert(index, child)
                index += 1
            parent.remove(node)
    else:
        raise ValueError(f"Unsupported revision action: {action}")


def _insert_property_in_order(parent, node, base_tags) -> None:
    """Insert one property node at its schema position (before any tag that sorts later)."""
    name = _local_name(node.tag)
    rank = base_tags.index(name) if name in base_tags else len(base_tags)
    for child in list(parent):
        child_name = _local_name(child.tag)
        child_rank = base_tags.index(child_name) if child_name in base_tags else len(base_tags)
        if child_rank > rank:
            parent.insert(parent.index(child), node)
            return
    parent.append(node)


def _apply_format_revision(node, action: str) -> bool:
    """Accept, reject or revert one `w:*PrChange` mark in place.

    accept keeps the properties currently in effect and drops the mark.
    reject / restore rebuilds the pre-change properties stored inside the mark, then
    drops it. `sectPrChange` is reported as unsupported instead of being half-applied.
    """
    tag = _local_name(node.tag)
    base_tags = _format_change_base_tags(tag)
    if base_tags is None:
        return False
    if action not in ("accept", "reject", "restore"):
        raise ValueError(f"Unsupported revision action: {action}")

    parent = node.getparent()
    if action == "accept":
        parent.remove(node)
        return True

    wrapper_name = _FORMAT_CHANGE_WRAPPERS.get(tag)
    wrapper = node.find(qn(f"w:{wrapper_name}")) if wrapper_name else None
    # Flat marks written before v3.5 keep the old properties directly on the mark.
    old_nodes = list(wrapper) if wrapper is not None else [
        child for child in node if _local_name(child.tag) in base_tags
    ]

    for child in list(parent):
        if _local_name(child.tag) in base_tags:
            parent.remove(child)
    for old_node in old_nodes:
        _insert_property_in_order(parent, copy.deepcopy(old_node), base_tags)
    parent.remove(node)
    return True


def _rewrite_revision(docx_path: str, output_docx_path: str, revision_id: str, action: str) -> Dict[str, Any]:
    changed = 0
    matched_kind: Optional[str] = None
    matched_type: Optional[str] = None
    format_unsupported = 0
    with zipfile.ZipFile(docx_path) as source:
        payloads = {name: source.read(name) for name in source.namelist()}
        infos = {name: source.getinfo(name) for name in source.namelist()}
    for name, payload in payloads.items():
        if not name.startswith("word/") or not name.endswith(".xml"):
            continue
        try:
            root = etree.fromstring(payload)
        except etree.XMLSyntaxError:
            continue
        for node, kind in list(iter_revision_marks(root)):
            if node.get(qn("w:id")) != str(revision_id):
                continue
            matched_kind = kind
            matched_type = _local_name(node.tag)
            if kind == "format":
                if _apply_format_revision(node, action):
                    changed += 1
                else:
                    format_unsupported += 1
                continue
            _apply_text_revision(node, action)
            changed += 1
        if changed:
            payloads[name] = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)
    if changed == 0:
        # Nothing was rewritten, so no output file is produced: a copy at the requested
        # path would be indistinguishable from a successful revision action.
        return {
            "output_docx": None,
            "revision_id": str(revision_id),
            "action": action,
            "kind": matched_kind,
            "type": matched_type,
            "status": "UNSUPPORTED_REVISION_TYPE" if format_unsupported else "NOT_FOUND",
            "changed": 0,
            "transaction": None,
        }

    tx = DocumentTransaction(docx_path, output_docx_path, task_mode=f"REVISION_{action.upper()}")
    try:
        with tx:
            with zipfile.ZipFile(tx.stage(), "w") as target:
                for name, payload in payloads.items():
                    target.writestr(infos[name], payload)
            tx.record_qa(audit_review_integrity(tx.temp_path))
            tx.commit()
    except TransactionPreflightError as exc:
        return {
            "output_docx": None,
            "revision_id": str(revision_id),
            "action": action,
            "kind": matched_kind,
            "type": matched_type,
            "status": "PREFLIGHT_FAILED",
            "changed": 0,
            "error": str(exc),
            "transaction": tx.record(),
        }
    except TransactionAborted as exc:
        return {
            "output_docx": None,
            "revision_id": str(revision_id),
            "action": action,
            "kind": matched_kind,
            "type": matched_type,
            "status": "QA_FAILED",
            "changed": 0,
            "error": str(exc),
            "transaction": tx.record(),
        }

    return {
        "output_docx": output_docx_path,
        "revision_id": str(revision_id),
        "action": action,
        "kind": matched_kind,
        "type": matched_type,
        "status": "APPLIED",
        "changed": changed,
        "transaction": tx.record(),
    }


def accept_revision(docx_path: str, output_docx_path: str, revision_id: str) -> Dict[str, Any]:
    return _rewrite_revision(docx_path, output_docx_path, revision_id, "accept")


def reject_revision(docx_path: str, output_docx_path: str, revision_id: str) -> Dict[str, Any]:
    return _rewrite_revision(docx_path, output_docx_path, revision_id, "reject")


def restore_revision(
    docx_path: str,
    output_docx_path: str,
    revision_id: str,
    snapshot_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Undo a review decision for one revision.

    While the mark still exists in the document this reverts it in place (the pre-v3.5
    behaviour). Once accept/reject has removed the mark, the mark is rebuilt from
    `review_snapshot.json`; without a snapshot the call reports `SNAPSHOT_MISSING` and
    writes nothing instead of guessing.
    """
    present = {str(item["revision_id"]) for item in list_revisions(docx_path, include_format=True)}
    if str(revision_id) in present:
        result = _rewrite_revision(docx_path, output_docx_path, revision_id, "restore")
        if result["changed"]:
            result["status"] = "REVERTED_PENDING"
        return result
    return _restore_revision_from_snapshot(docx_path, output_docx_path, revision_id, snapshot_path)


def audit_review_integrity(docx_path: str) -> Dict[str, Any]:
    """
    Verify that every revision and comment is internally consistent so Word/WPS can open
    the file in review mode without repair prompts.
    """
    issues: List[str] = []

    document_xml = _part_xml_bytes(docx_path, "word/document.xml")
    if document_xml is None:
        raise ValueError(f"word/document.xml missing in {docx_path}")
    root = etree.fromstring(document_xml)

    settings_xml = _part_xml_bytes(docx_path, "word/settings.xml")
    track_changes = settings_xml is not None and b"trackChanges" in settings_xml

    seen_ids: Dict[str, int] = {}
    revision_count = 0
    format_revision_count = 0
    for el in root.iter():
        tag = el.tag.rsplit("}", 1)[-1]
        if tag not in ("ins", "del") and tag not in _FORMAT_CHANGE_TAGS:
            continue
        raw_id = el.get(qn("w:id"))
        if not raw_id or not raw_id.isdigit():
            issues.append(f"{tag} has invalid w:id={raw_id!r}")
            continue
        seen_ids[raw_id] = seen_ids.get(raw_id, 0) + 1
        if not (el.get(qn("w:author")) or "").strip():
            issues.append(f"{tag}[{raw_id}] missing w:author")
        if not ISO_DATE_PATTERN.match(el.get(qn("w:date")) or ""):
            issues.append(f"{tag}[{raw_id}] invalid w:date")
        if tag in _FORMAT_CHANGE_TAGS:
            format_revision_count += 1
            continue
        revision_count += 1
        if tag == "del" and el.find(qn("w:delText")) is None and el.find(".//" + qn("w:delText")) is None:
            issues.append(f"del[{raw_id}] contains no w:delText")
        if tag == "ins" and el.find(".//" + qn("w:t")) is None:
            issues.append(f"ins[{raw_id}] contains no w:t")

    duplicate_ids = [rid for rid, count in seen_ids.items() if count > 1]
    if duplicate_ids:
        issues.append(f"duplicate revision ids: {duplicate_ids}")

    # Package-wide checks: every *PrChange must carry its schema container, and a
    # revision id may not be reused across parts (accept/reject matches by id only,
    # so a reused id silently rewrites more than one revision).
    revision_parts: Dict[str, set] = {}
    for part_name, part_root in _iter_revision_parts(docx_path):
        for el in part_root.iter():
            tag = _local_name(el.tag)
            if tag not in ("ins", "del") and tag not in _FORMAT_CHANGE_TAGS:
                continue
            raw_id = el.get(qn("w:id"))
            if not raw_id:
                continue
            revision_parts.setdefault(raw_id, set()).add(part_name)
            if tag in _FORMAT_CHANGE_TAGS:
                wrapper_name = _FORMAT_CHANGE_WRAPPERS.get(tag)
                containers = [child for child in el if _local_name(child.tag) == wrapper_name]
                if len(containers) != 1:
                    issues.append(
                        f"{tag}[{raw_id}] in {part_name} must contain exactly one "
                        f"<w:{wrapper_name}>, found {len(containers)}"
                    )
    cross_part_ids = {rid: sorted(parts) for rid, parts in revision_parts.items() if len(parts) > 1}
    if cross_part_ids:
        issues.append(f"revision ids reused across parts: {sorted(cross_part_ids)}")

    referenced_comment_ids = {
        el.get(qn("w:id"))
        for el in root.iter()
        if el.tag.rsplit("}", 1)[-1] == "commentReference"
    }

    comments_xml = _part_xml_bytes(docx_path, "word/comments.xml")
    defined_comment_ids = set()
    if comments_xml is not None:
        comments_root = etree.fromstring(comments_xml)
        defined_comment_ids = {
            node.get(qn("w:id")) for node in comments_root.findall(qn("w:comment"))
        }
        for node in comments_root.findall(qn("w:comment")):
            if not (node.get(qn("w:author")) or "").strip():
                issues.append(f"comment[{node.get(qn('w:id'))}] missing w:author")
        dangling = referenced_comment_ids - defined_comment_ids
        if dangling:
            issues.append(f"commentReference ids without definitions: {sorted(dangling)}")
        orphans = defined_comment_ids - referenced_comment_ids
        if orphans:
            issues.append(f"comments never referenced in document.xml: {sorted(orphans)}")
    elif referenced_comment_ids:
        issues.append("document.xml references comments but word/comments.xml is missing")

    structured_issues = [
        {"code": "REVIEW_INTEGRITY", "location": "revisions_comments", "detail": item, "severity": "high"}
        for item in issues
    ]

    return {
        "passed": not issues,
        "track_changes_enabled": track_changes,
        "revision_count": revision_count,
        "format_revision_count": format_revision_count,
        "comment_count": len(defined_comment_ids),
        "issues": structured_issues,
        "structured_issues": structured_issues,
        "coverage_gaps": [] if track_changes else ["TRACK_CHANGES_DISABLED"],
        "unverified_count": 0,
    }
