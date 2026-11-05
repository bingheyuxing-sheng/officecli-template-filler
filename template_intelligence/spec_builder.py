# -*- coding: utf-8 -*-
"""DocumentSpec 4.0 producer (W1-A).

`build_document_spec(doc)` / `build_document_spec_from_path(path)` emit the complete
`document_spec-4.0.schema.json` shape. The producer describes the template only: it never
generates content, never mutates the document and never uses capacity to shrink text.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

import docx
from docx.oxml.ns import qn

from engine.docx_parser import (
    _has_ole_object,
    assess_template_compatibility_level,
    match_internal_fact_slots,
)
from engine.image_engine import VECTOR_MIME_TYPES, count_image_part_references, find_images
from engine.ooxml_utils import (
    TOKEN_PATTERN,
    LogicalParagraphView,
    is_red_run,
    iter_all_document_paragraphs_with_Wait_context,
    iter_all_document_tables_with_context,
)
from engine.pdf_backend import find_pdf_backend
from engine.style_engine import resolve_style_sz_and_font
from engine.table_engine import classify_cell_structure

from .fingerprint import compute_four_hashes
from .slot_id import (
    LOCATION_RE,
    make_slot_id,
    make_slot_key,
    normalize_text,
    resolve_slot_id_collisions,
)

_HF_NAMES = (
    "header", "first_page_header", "even_page_header",
    "footer", "first_page_footer", "even_page_footer",
)

_PAGE_SIZES = (
    ("A4", 11906, 16838),
    ("A3", 16838, 23811),
    ("A5", 8391, 11906),
    ("Letter", 12240, 15840),
    ("Legal", 12240, 20160),
)

_L4_CODES = {
    "chart": "CHART_EDIT_UNSUPPORTED",
    "smartart": "SMARTART_EDIT_UNSUPPORTED",
    "ole_object": "OLE_EDIT_UNSUPPORTED",
    "floating_anchor_drawing": "FLOATING_ANCHOR_LAYOUT_UNSUPPORTED",
    "macro_enabled_docm": "MACRO_DOCM_READ_ONLY",
}
_L4_DETAILS = {
    "chart": "chart objects are preserved read-only; chart data is not editable",
    "smartart": "SmartArt is preserved read-only; diagram content is not editable",
    "ole_object": "embedded OLE objects are preserved read-only",
    "floating_anchor_drawing": "floating drawing anchor found; its layout cannot be verified after filling",
    "macro_enabled_docm": "macro-enabled document; the package must stay read-only for shape edits",
}
_L3_CODES = {
    "sdt_control": "SDT_EDIT_UNSUPPORTED",
    "field_code": "FIELD_UPDATE_UNSUPPORTED",
}
_L3_DETAILS = {
    "sdt_control": "content control (w:sdt) present; SDT editing has no verified handler",
    "field_code": "field code present; field result updates have no verified handler",
}


# ---------------------------------------------------------------------------
# small OOXML helpers
# ---------------------------------------------------------------------------


def _local_name(el) -> str:
    tag = el.tag if isinstance(el.tag, str) else ""
    return tag.split("}")[-1] if "}" in tag else tag


def _twips(length) -> Optional[int]:
    try:
        return int(length.twips) if length is not None else None
    except Exception:
        return None


def _is_location(value: Optional[str]) -> bool:
    return bool(value) and bool(LOCATION_RE.match(value or ""))


def _story_prefix(location: str) -> str:
    return re.sub(r"\.(p|tbl|txbx_p)\[[0-9]+\].*$", "", location or "")


def _context_has_content(ctx: Dict[str, Any]) -> bool:
    """Only report an unsupported story when it actually carries something."""
    p_el = ctx["p_el"]
    if any((node.text or "").strip() for node in p_el.iter(qn("w:t"))):
        return True
    return bool(p_el.xpath(".//w:drawing | .//w:pict | .//w:sdt"))


def _table_has_content(table) -> bool:
    for row in table.rows:
        for cell in row.cells:
            if cell.text.strip():
                return True
            if cell._tc.xpath(".//w:drawing | .//w:pict"):
                return True
    return False


def _ancestor(p_el, tag: str):
    node = p_el
    while node is not None:
        if node.tag == qn(tag):
            return node
        node = node.getparent()
    return None


def _cell_width_twips(p_el) -> Optional[int]:
    """Width of the enclosing table cell from `w:tcW`, or None when unavailable."""
    tc = _ancestor(p_el, "w:tc")
    if tc is None:
        return None
    tc_pr = tc.find(qn("w:tcPr"))
    if tc_pr is None:
        return None
    tc_w = tc_pr.find(qn("w:tcW"))
    if tc_w is None:
        return None
    if (tc_w.get(qn("w:type")) or "dxa") != "dxa":
        return None
    raw = tc_w.get(qn("w:w")) or ""
    return int(raw) if raw.lstrip("-").isdigit() else None


def _fixed_row_height_twips(p_el) -> Optional[int]:
    """Row height only when it is declared `exact`; `atLeast` is not a hard limit."""
    tr = _ancestor(p_el, "w:tr")
    if tr is None:
        return None
    tr_pr = tr.find(qn("w:trPr"))
    height = tr_pr.find(qn("w:trHeight")) if tr_pr is not None else None
    if height is None or (height.get(qn("w:hRule")) or "") != "exact":
        return None
    raw = height.get(qn("w:val")) or ""
    if not raw.isdigit():
        return None
    value = int(raw)
    return value if value >= 1 else None


def _paragraph_style(paragraph) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """Return `(style_name, effective_sz_half_pt, font_east_asia)`."""
    name = None
    if paragraph is not None:
        try:
            name = getattr(getattr(paragraph, "style", None), "name", None)
        except Exception:
            name = None
    font = None
    size = None
    if paragraph is not None:
        try:
            font, size = resolve_style_sz_and_font(paragraph)
        except Exception:
            font, size = None, None
    return name, size, font


def _is_anchored_blip(blip) -> bool:
    node = blip.getparent()
    while node is not None:
        name = _local_name(node)
        if name == "anchor":
            return True
        if name == "inline":
            return False
        node = node.getparent()
    return False


def _svg_blips(blip) -> List[Any]:
    return [node for node in blip.iter() if _local_name(node) == "svgBlip"]


def _vml_images(p_el) -> List[Any]:
    return [node for node in p_el.iter() if _local_name(node) == "imagedata"]


def _extent_cm(p_el) -> Tuple[float, float]:
    extents = p_el.xpath(".//wp:extent")
    if not extents:
        return 0.0, 0.0
    try:
        return round(int(extents[0].get("cx") or 0) / 360000.0, 2), round(
            int(extents[0].get("cy") or 0) / 360000.0, 2
        )
    except (TypeError, ValueError):
        return 0.0, 0.0


# ---------------------------------------------------------------------------
# template identity, sections, structure
# ---------------------------------------------------------------------------


def _package_digest(doc) -> str:
    """Deterministic digest used only when no file path is available."""
    package = getattr(doc.part, "package", None)
    entries: List[List[str]] = []
    if package is not None and hasattr(package, "iter_parts"):
        for part in package.iter_parts():
            partname = str(getattr(part, "partname", ""))
            try:
                blob = part.blob
            except Exception:
                blob = b""
            entries.append([partname, hashlib.sha256(blob or b"").hexdigest()])
    return hashlib.sha256(
        json.dumps(sorted(entries), ensure_ascii=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _template_sha256(doc, file_path: str) -> Tuple[str, str]:
    if file_path and os.path.isfile(file_path):
        with open(file_path, "rb") as handle:
            return hashlib.sha256(handle.read()).hexdigest(), "file"
    return _package_digest(doc), "package"


def _section_specs(doc) -> List[Dict[str, Any]]:
    specs: List[Dict[str, Any]] = []
    for index, section in enumerate(doc.sections):
        orientation = None
        if section.orientation is not None:
            try:
                orientation = int(section.orientation)
            except (TypeError, ValueError):
                orientation = None
        specs.append({
            "section_index": index,
            "page_width_twips": _twips(section.page_width),
            "page_height_twips": _twips(section.page_height),
            "orientation": orientation,
            "margins": {
                "top": _twips(section.top_margin),
                "bottom": _twips(section.bottom_margin),
                "left": _twips(section.left_margin),
                "right": _twips(section.right_margin),
            },
            "header_distance_twips": _twips(section.header_distance),
            "footer_distance_twips": _twips(section.footer_distance),
        })
    return specs


def _page_size_name(width: Optional[int], height: Optional[int]) -> Optional[str]:
    if not width or not height:
        return None
    for name, expected_w, expected_h in _PAGE_SIZES:
        if abs(width - expected_w) <= 120 and abs(height - expected_h) <= 120:
            return name
    return None


def _document_block(sections: List[Dict[str, Any]]) -> Dict[str, Any]:
    widths = {s.get("page_width_twips") for s in sections}
    heights = {s.get("page_height_twips") for s in sections}
    page_size = None
    if len(widths) == 1 and len(heights) == 1:
        page_size = _page_size_name(widths.pop(), heights.pop())

    orientations = {s.get("orientation") for s in sections}
    if len(orientations) == 1 and None not in orientations:
        orientation = "landscape" if orientations.pop() == 1 else "portrait"
    elif len(orientations) > 1:
        orientation = "mixed"
    else:
        orientation = None

    return {"page_size": page_size, "orientation": orientation, "sections": sections}


def _structure_paragraphs(contexts: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    result: List[Dict[str, Any]] = []
    for ctx in contexts:
        paragraph = ctx["paragraph"]
        style_name, size, font = _paragraph_style(paragraph)
        view = LogicalParagraphView(ctx["p_el"])
        result.append({
            "location_id": ctx["location_id"],
            "scope": ctx["scope"],
            "style_name": style_name,
            "effective_sz_half_pt": size,
            "font_east_asia": font,
            "text_preview": view.logical_text[:120],
        })
    return result


def _structure_tables(table_contexts: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    result: List[Dict[str, Any]] = []
    for ctx in table_contexts:
        table = ctx["table"]
        counts: Dict[str, int] = {}
        seen_ids: set = set()
        seen_refs: List[Any] = []
        for row in table.rows:
            for cell in row.cells:
                if id(cell._tc) in seen_ids:
                    continue
                seen_ids.add(id(cell._tc))
                seen_refs.append(cell._tc)
                kind = str(classify_cell_structure(cell))
                counts[kind] = counts.get(kind, 0) + 1
        headers: List[str] = []
        if table.rows:
            headers = [cell.text.strip().replace("\n", "") for cell in table.rows[0].cells]
        result.append({
            "table_id": ctx["table_id"],
            "scope": ctx["scope"],
            "depth": int(ctx["depth"]),
            "rows": len(table.rows),
            "cols": len(table.columns),
            "headers": headers,
            "cell_type_counts": counts,
        })
    return result


def _image_ref_counts(doc) -> Dict[str, int]:
    """Partname -> package-wide reference count, computed once per analysis."""
    counts: Dict[str, int] = {}
    try:
        for info in count_image_part_references(doc).values():
            partname = info.get("partname")
            if partname:
                counts[str(partname)] = int(info.get("ref_count", 1))
    except Exception:
        pass
    return counts


def _structure_images(
    contexts: Sequence[Dict[str, Any]],
    ref_cache: Dict[str, int],
) -> List[Dict[str, Any]]:
    images: List[Dict[str, Any]] = []

    def _part_info(paragraph, r_id: Optional[str]) -> Dict[str, Any]:
        if not r_id:
            return {}
        part = getattr(paragraph, "part", None)
        if part is None:
            return {}
        try:
            rel = part.rels[r_id]
            if rel.is_external:
                return {}
            target = rel.target_part
        except (KeyError, AttributeError):
            return {}
        return {
            "partname": str(getattr(target, "partname", "")),
            "content_type": str(getattr(target, "content_type", "") or ""),
        }

    for ctx in contexts:
        p_el = ctx["p_el"]
        paragraph = ctx["paragraph"]
        location = ctx["location_id"]
        width_cm, height_cm = _extent_cm(p_el)

        for blip in p_el.xpath(".//a:blip"):
            r_id = blip.get(qn("r:embed"))
            info = _part_info(paragraph, r_id)
            object_type = "anchored_blip" if _is_anchored_blip(blip) else "inline_blip"
            images.append({
                "location_id": location,
                "object_type": object_type,
                "rId": r_id,
                "width_cm": width_cm,
                "height_cm": height_cm,
                "partname": info.get("partname", ""),
                "content_type": info.get("content_type", ""),
                "ref_count": ref_cache.get(info.get("partname", ""), 0),
            })
            for svg_blip in _svg_blips(blip):
                svg_rid = svg_blip.get(qn("r:embed"))
                svg_info = _part_info(paragraph, svg_rid)
                images.append({
                    "location_id": location,
                    "object_type": "svg",
                    "rId": svg_rid,
                    "width_cm": width_cm,
                    "height_cm": height_cm,
                    "partname": svg_info.get("partname", ""),
                    "content_type": svg_info.get("content_type", ""),
                    "ref_count": ref_cache.get(svg_info.get("partname", ""), 0),
                })

        for imagedata in _vml_images(p_el):
            r_id = imagedata.get(qn("r:id")) or imagedata.get(qn("r:embed"))
            info = _part_info(paragraph, r_id)
            images.append({
                "location_id": location,
                "object_type": "vml",
                "rId": r_id,
                "width_cm": 0.0,
                "height_cm": 0.0,
                "partname": info.get("partname", ""),
                "content_type": info.get("content_type", ""),
                "ref_count": ref_cache.get(info.get("partname", ""), 0),
            })

        for check, object_type in (
            (lambda el: bool(el.xpath(".//c:chart")), "chart"),
            (lambda el: bool(el.xpath(".//dgm:relIds")), "smartart"),
            (_has_ole_object, "ole_object"),
        ):
            if check(p_el):
                images.append({
                    "location_id": location,
                    "object_type": object_type,
                    "rId": None,
                    "width_cm": 0.0,
                    "height_cm": 0.0,
                    "partname": "",
                    "content_type": "",
                    "ref_count": 0,
                })
    return images


# ---------------------------------------------------------------------------
# slots
# ---------------------------------------------------------------------------


def _only_blank_marker(token: str) -> bool:
    return token.strip("_*").strip() == ""


def _locate_labels(text: str, labels: Sequence[str]) -> List[Tuple[str, int, int]]:
    spans: List[Tuple[str, int, int]] = []
    cursor = 0
    for label in labels:
        index = text.find(label, cursor)
        if index == -1:
            index = text.find(label)
        if index == -1:
            continue
        spans.append((label, index, index + len(label)))
        cursor = index + len(label)
    return spans


def _within(span: Tuple[int, int], others: Sequence[Tuple[int, int]]) -> bool:
    start, end = span
    return any(start < other_end and other_start < end for other_start, other_end in others)


def _collect_candidates(contexts: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    candidates: List[Dict[str, Any]] = []
    order = 0

    for ctx in contexts:
        paragraph = ctx["paragraph"]
        p_el = ctx["p_el"]
        location = ctx["location_id"]
        scope = ctx["scope"]
        view = LogicalParagraphView(p_el)
        text = view.logical_text
        style_name, size, font = _paragraph_style(paragraph)
        base = {
            "location_id": location,
            "scope": scope,
            "style_name": style_name,
            "effective_sz_half_pt": size,
            "font_east_asia": font,
        }

        has_sdt = bool(p_el.xpath(".//w:sdt"))
        has_field = bool(p_el.xpath(".//w:fldSimple | .//w:fldChar | .//w:instrText"))
        # `.sdt[` covers addressable container content; the ancestor test also covers
        # textbox paragraphs whose stable `txbx_p[i]` location hides the enclosing SDT.
        inside_sdt = ".sdt[" in location or bool(p_el.xpath("ancestor::w:sdt"))
        if has_sdt or has_field or inside_sdt:
            # A control/field paragraph is a protected unit. Tokens inside it are not offered
            # as fill targets; the whole paragraph is reported as `control_or_field`.
            # CP-W2-002: any paragraph discovered inside a `w:sdt` container is protected
            # as a whole, so no FILLABLE token is ever emitted inside SDT content.
            start = len(text) - len(text.lstrip())
            end = len(text.rstrip())
            if end > start:
                candidate = dict(base)
                candidate.update({
                    "candidate_type": "control_or_field",
                    "matched_text": text[start:end],
                    "span": {"start": start, "end": end},
                    "protection_status": "PROTECTED",
                    "confirmation_tier": "PROTECTED_DO_NOT_TOUCH",
                    "_order": order,
                })
                candidates.append(candidate)
                order += 1
            continue

        fact_spans = _locate_labels(text, match_internal_fact_slots(text))
        fact_ranges = [(start, end) for _label, start, end in fact_spans]

        explicit_ranges: List[Tuple[int, int]] = []
        for start, end, token in view.find_spans(TOKEN_PATTERN):
            # `____` / `***` next to a blank internal-fact label is the value box of that
            # label, which is already reported as the internal_fact slot.
            if fact_ranges and _only_blank_marker(token):
                continue
            candidate = dict(base)
            candidate.update({
                "candidate_type": "explicit_token",
                "matched_text": token,
                "span": {"start": start, "end": end},
                "protection_status": "FILLABLE",
                "confirmation_tier": "AUTO_DERIVE_OR_BIND",
                "_order": order,
            })
            candidates.append(candidate)
            order += 1
            explicit_ranges.append((start, end))

        red_cursor = 0
        if paragraph is not None:
            for run in paragraph.runs:
                try:
                    if not is_red_run(run, paragraph) or not run.text.strip():
                        continue
                except Exception:
                    continue
                run_text = run.text
                index = text.find(run_text, red_cursor)
                if index == -1:
                    continue
                start, end = index, index + len(run_text)
                red_cursor = end
                if _within((start, end), explicit_ranges) or _within((start, end), fact_ranges):
                    continue
                candidate = dict(base)
                candidate.update({
                    "candidate_type": "red_run_clue",
                    "matched_text": run_text,
                    "span": {"start": start, "end": end},
                    "protection_status": "FILLABLE",
                    "confirmation_tier": "DEFAULT_FILL_WITH_NOTICE",
                    "_order": order,
                })
                candidates.append(candidate)
                order += 1

        for label, start, end in fact_spans:
            candidate = dict(base)
            candidate.update({
                "candidate_type": "internal_fact",
                "matched_text": label,
                "span": {"start": start, "end": end},
                "protection_status": "CONDITIONAL",
                "confirmation_tier": "MUST_ASK_USER",
                "_order": order,
            })
            candidates.append(candidate)
            order += 1

    return candidates


def _assign_slot_identities(
    candidates: List[Dict[str, Any]], template_sha256: str
) -> Tuple[List[str], List[str]]:
    """Assign occurrence + slot_id/slot_key. Returns `(collision_warnings, conflict)`."""
    groups: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
    for candidate in candidates:
        key = (candidate["location_id"], normalize_text(candidate["matched_text"]))
        groups.setdefault(key, []).append(candidate)

    items: List[Tuple[str, str]] = []
    for (location, normalized), group in groups.items():
        group.sort(key=lambda c: (c["span"]["start"], c["span"]["end"], c["_order"]))
        for occurrence, candidate in enumerate(group, start=1):
            candidate["occurrence"] = occurrence
            canonical = f"v1|{template_sha256}|{location}|{normalized}|{occurrence}"
            base_id = make_slot_id(
                template_sha256, location, candidate["matched_text"], occurrence
            )
            candidate["_canonical"] = canonical
            candidate["_base_id"] = base_id
            items.append((canonical, base_id))

    resolved = resolve_slot_id_collisions(items)
    by_canonical = {canonical: slot_id for canonical, slot_id in zip(sorted(c for c, _ in items), resolved, strict=True)}
    for candidate in candidates:
        candidate["slot_id"] = by_canonical[candidate["_canonical"]]

    base_counts: Dict[str, int] = {}
    for _canonical, base_id in items:
        base_counts[base_id] = base_counts.get(base_id, 0) + 1
    collisions = sorted({base for base, count in base_counts.items() if count > 1})

    slot_ids = [candidate["slot_id"] for candidate in candidates]
    conflict = [] if len(slot_ids) == len(set(slot_ids)) else ["SLOT_ID_CONFLICT"]
    return collisions, conflict


def _capacity_for_paragraph(
    p_el, printable_width: Optional[int], size: Optional[str]
) -> Optional[Dict[str, Any]]:
    cell_width = _cell_width_twips(p_el)
    if cell_width and cell_width > 0:
        width = cell_width
        method = "cell_width_twips_over_effective_sz"
    elif printable_width and printable_width > 0:
        width = printable_width
        method = "page_width_minus_margins_over_effective_sz"
    else:
        return None

    max_chars: Optional[int] = None
    if size is not None:
        try:
            half_points = int(str(size).strip())
            if half_points > 0:
                max_chars = int((width / 20.0) // (half_points / 2.0))
        except (TypeError, ValueError):
            max_chars = None

    hard_limit = None
    fixed_height = _fixed_row_height_twips(p_el)
    if fixed_height:
        hard_limit = {"kind": "fixed_height_cell", "value": fixed_height}

    return {
        "max_chars_per_line": max_chars,
        "estimated_lines": None,
        "confidence": "medium" if max_chars is not None else "low",
        "method": method,
        "hard_limit": hard_limit,
    }


def _build_slots(
    candidates: List[Dict[str, Any]],
    template_sha256: str,
) -> Tuple[List[Dict[str, Any]], List[str], List[str]]:
    collisions, conflicts = _assign_slot_identities(candidates, template_sha256)
    if conflicts:
        return [], collisions, conflicts

    slots: List[Dict[str, Any]] = []
    for candidate in candidates:
        location = candidate["location_id"]
        slot = {
            "slot_id": candidate["slot_id"],
            "slot_key": make_slot_key(
                location, candidate["matched_text"], candidate["occurrence"]
            ),
            "location_id": location,
            "scope": candidate["scope"],
            "candidate_type": candidate["candidate_type"],
            "matched_text": candidate["matched_text"],
            "span": dict(candidate["span"]),
            "occurrence": int(candidate["occurrence"]),
            "semantic_role": None,
            "style_reference": {
                "style_name": candidate["style_name"],
                "effective_sz_half_pt": candidate["effective_sz_half_pt"],
                "font_east_asia": candidate["font_east_asia"],
            },
            "protection_status": candidate["protection_status"],
            "confirmation_tier": candidate["confirmation_tier"],
        }
        slots.append(slot)
    return slots, collisions, conflicts


def _build_capacity_profiles(
    candidates: List[Dict[str, Any]],
    contexts_by_location: Dict[str, Dict[str, Any]],
    printable_width: Optional[int],
) -> List[Dict[str, Any]]:
    profiles: List[Dict[str, Any]] = []
    seen: List[str] = []
    for candidate in candidates:
        location = candidate["location_id"]
        if location in seen:
            continue
        seen.append(location)
        ctx = contexts_by_location.get(location)
        if ctx is None:
            continue
        capacity = _capacity_for_paragraph(
            ctx["p_el"], printable_width, candidate["effective_sz_half_pt"]
        )
        if capacity is None:
            continue
        width = _cell_width_twips(ctx["p_el"]) or printable_width
        if not width:
            continue
        profiles.append({
            "profile_id": f"CAP_{len(profiles) + 1:03d}",
            "location_id": location,
            "available_width_twips": int(width),
            "available_height_twips": None,
            "effective_sz_half_pt": candidate["effective_sz_half_pt"],
            "confidence": capacity["confidence"],
            "method": capacity["method"],
        })
    return profiles


# ---------------------------------------------------------------------------
# protected regions, layout constraints, unsupported features
# ---------------------------------------------------------------------------


def _first_location_for_prefix(contexts: Sequence[Dict[str, Any]], prefix: str) -> Optional[str]:
    for ctx in contexts:
        if ctx["location_id"].startswith(prefix + "."):
            return ctx["location_id"]
    return None


def _build_protected_regions(
    doc,
    contexts: Sequence[Dict[str, Any]],
    table_contexts: Sequence[Dict[str, Any]],
    slots: Sequence[Dict[str, Any]] = (),
    sdt_containers: Sequence[Dict[str, Any]] = (),
) -> List[Dict[str, Any]]:
    regions: List[Dict[str, Any]] = []
    slot_locations = {slot["location_id"] for slot in slots}

    def _add(kind: str, location: str, evidence: str, severity: str = "blocking") -> None:
        if not _is_location(location):
            return
        regions.append({
            "region_id": f"PR_{len(regions) + 1:03d}",
            "kind": kind,
            "location_id": location,
            "evidence": evidence,
            "severity": severity,
        })

    for ctx in contexts:
        p_el = ctx["p_el"]
        location = ctx["location_id"]
        if p_el.xpath(".//w:sdt"):
            _add("sdt", location, "content control (w:sdt) found; SDT content is read-only")
        if p_el.xpath(".//w:fldSimple | .//w:fldChar | .//w:instrText"):
            _add("field", location, "field code found; field result must not be overwritten")

    for index, section in enumerate(doc.sections):
        for name in _HF_NAMES:
            hf = getattr(section, name, None)
            if hf is None:
                continue
            try:
                if hf.is_linked_to_previous:
                    continue
                paragraphs = hf.paragraphs
                text = "".join(p.text for p in paragraphs).strip()
                has_objects = bool(hf.tables) or bool(hf._element.xpath(".//w:drawing | .//w:pict"))
            except Exception:
                continue
            for paragraph_index, paragraph in enumerate(paragraphs):
                location = f"sec[{index}].{name}.p[{paragraph_index}]"
                if location in slot_locations:
                    # A paragraph that carries a fillable slot is not itself protected;
                    # only its fixed neighbours are.
                    continue
                paragraph_text = (paragraph.text or "").strip()
                has_paragraph_object = bool(
                    paragraph._p.xpath(".//w:drawing | .//w:pict")
                )
                if not paragraph_text and not has_paragraph_object:
                    continue
                kind = "header" if name.endswith("header") else "footer"
                evidence = (
                    f"{name}.p[{paragraph_index}]: non-empty text: {paragraph_text[:80]}"
                    if paragraph_text
                    else f"{name}.p[{paragraph_index}]: contains pictures"
                )
                _add(kind, location, evidence)
            if not text and has_objects:
                # No printable paragraph carries the object (for example a header table).
                fallback = _first_location_for_prefix(contexts, f"sec[{index}].{name}")
                if fallback is not None:
                    _add(
                        "header" if name.endswith("header") else "footer",
                        fallback,
                        f"{name}: contains pictures or tables without text paragraphs",
                    )

    try:
        entries = find_images(doc)
    except Exception:
        entries = []
    part_map: Dict[str, Tuple[int, str, Any]] = {}
    for index, section in enumerate(doc.sections):
        for name in _HF_NAMES:
            hf = getattr(section, name, None)
            if hf is None:
                continue
            try:
                if hf.is_linked_to_previous:
                    continue
                part_map[str(hf.part.partname)] = (index, name, hf)
            except Exception:
                continue
    for entry in entries:
        role = entry.get("role")
        if role not in ("logo", "stamp"):
            continue
        owner = entry.get("owner_part")
        info = part_map.get(owner)
        if info is None:
            continue
        index, name, _hf = info
        paragraph_index = entry.get("paragraph_index")
        location = (
            f"sec[{index}].{name}.p[{paragraph_index}]"
            if isinstance(paragraph_index, int)
            else _first_location_for_prefix(contexts, f"sec[{index}].{name}")
        )
        if location is None:
            continue
        _add(role, location, str(entry.get("evidence") or f"{role} image in {name}"))

    for ctx in table_contexts:
        table = ctx["table"]
        if not table.rows:
            continue
        tr_pr = table.rows[0]._tr.find(qn("w:trPr"))
        if tr_pr is not None and tr_pr.find(qn("w:tblHeader")) is not None:
            _add(
                "repeated_header",
                ctx["table_id"],
                "table row 0 carries w:tblHeader (repeats across pages)",
                severity="warning",
            )

    # CP-W2-002: one blocking region per SDT container with content, addressed by the
    # container itself (`body.sdt[0]`, `sec[0].header.sdt[0]`, cell form).
    for container in sdt_containers:
        location = container.get("location")
        _add(
            "sdt",
            location,
            "%s: content control (w:sdt) wraps %d paragraph(s) / %d table(s); "
            "SDT content is read-only while sdt_edit=false"
            % (location, container["paragraph_count"], container["table_count"]),
        )
    return regions


def _build_layout_constraints(table_contexts: Sequence[Dict[str, Any]], contexts: Sequence[Dict[str, Any]]):
    constraints: List[Dict[str, Any]] = []

    def _add(kind: str, location: str, value: Any) -> None:
        if not _is_location(location):
            return
        constraints.append({
            "constraint_id": f"LC_{len(constraints) + 1:03d}",
            "kind": kind,
            "location_id": location,
            "value": value,
            "source": "template",
        })

    for ctx in table_contexts:
        table = ctx["table"]
        table_id = ctx["table_id"]
        if not table.rows:
            continue
        tr_pr = table.rows[0]._tr.find(qn("w:trPr"))
        if tr_pr is not None and tr_pr.find(qn("w:tblHeader")) is not None:
            _add("repeated_header", table_id, True)
        if any(
            row._tr.find(qn("w:trPr")) is not None
            and row._tr.find(qn("w:trPr")).find(qn("w:cantSplit")) is not None
            for row in table.rows
        ):
            _add("cant_split", table_id, True)

    for ctx in contexts:
        p_el = ctx["p_el"]
        location = ctx["location_id"]
        if p_el.xpath(".//wp:anchor"):
            _add("floating_anchor", location, True)
        p_pr = p_el.find(qn("w:pPr"))
        if p_pr is not None and p_pr.find(qn("w:sectPr")) is not None:
            _add("section_break", location, True)
    return constraints


def _build_unsupported_features(
    doc,
    compatibility: Dict[str, Any],
    contexts: Sequence[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    seen: List[Tuple[str, Optional[str]]] = []

    def _add(code: str, detail: str, location: Optional[str] = None) -> None:
        key = (code, location if _is_location(location) else None)
        if key in seen:
            return
        seen.append(key)
        entry: Dict[str, Any] = {"code": code, "detail": detail}
        if key[1]:
            entry["location_id"] = key[1]
        items.append(entry)

    for feature in compatibility.get("l4_features") or []:
        prefix, _, location = str(feature).partition("@")
        code = _L4_CODES.get(prefix)
        if code:
            _add(code, f"{_L4_DETAILS.get(prefix, prefix)} ({feature})", location)

    for feature in compatibility.get("l3_features") or []:
        prefix, _, location = str(feature).partition("@")
        code = _L3_CODES.get(prefix)
        if code:
            _add(code, f"{_L3_DETAILS.get(prefix, prefix)} ({feature})", location)

    for ctx in contexts:
        if ctx["p_el"].xpath(".//wp:anchor"):
            _add(
                "FLOATING_ANCHOR_LAYOUT_UNSUPPORTED",
                "floating drawing anchor found; post-fill layout cannot be verified",
                ctx["location_id"],
            )

    package = getattr(doc.part, "package", None)
    if package is not None and hasattr(package, "iter_parts"):
        for part in package.iter_parts():
            partname = str(getattr(part, "partname", ""))
            content_type = str(getattr(part, "content_type", "") or "").lower()
            if "/media/" not in partname:
                continue
            is_vector = content_type in VECTOR_MIME_TYPES or partname.lower().endswith(
                (".svg", ".emf", ".wmf", ".wmz")
            )
            if is_vector:
                _add(
                    "VECTOR_IMAGE_UNVERIFIED",
                    f"{partname} ({content_type or 'unknown'}) cannot be decoded or byte-verified",
                )
    return items


# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------


def _capabilities(images: Sequence[Dict[str, Any]], tables: Sequence[Dict[str, Any]]) -> Dict[str, bool]:
    try:
        backend = find_pdf_backend()
        visual_render = (backend.get("name") or "none") != "none"
    except Exception:
        visual_render = False
    return {
        "text_fill": True,
        "table_fill": True,
        "image_replace": any(
            image["object_type"] in ("inline_blip", "anchored_blip", "vml") for image in images
        ),
        "nested_table": any(int(table["depth"]) > 0 for table in tables),
        "field_update": False,
        "sdt_edit": False,
        "smartart_edit": False,
        "visual_render": visual_render,
    }


def _scan_body_sdt(doc) -> Dict[str, Any]:
    """Fail-closed pre-scan for `w:sdt` containers in every addressable story.

    CP-W2-002: the scan covers body roots, header/footer story roots and table cells
    (including nested SDTs and tables inside SDT content). Each container is reported
    with its concrete Contract 01 address (`body.sdt[0]`, `sec[0].header.sdt[0]`,
    `body.tbl[0].r[0].c[0].sdt[0]`) plus direct paragraph/table counts, so disclosure
    and protected regions can name a position instead of only a count. Any container
    with content caps compatibility at L3; a failed scan is treated like a found
    container (fail-closed). A scan error is never downgraded to a low warning.
    """
    scan: Dict[str, Any] = {"containers": [], "scan_error": None}
    try:
        from docx.table import Table

        def _record_container(location: str, content) -> None:
            paragraphs = content.findall(qn("w:p")) if content is not None else []
            tables = content.findall(qn("w:tbl")) if content is not None else []
            scan["containers"].append({
                "location": location,
                "paragraph_count": len(paragraphs),
                "table_count": len(tables),
                "has_content": bool(paragraphs or tables),
            })

        def _scan_container(root_el, prefix: str, parent_obj) -> None:
            for sdt_index, sdt_el in enumerate(root_el.findall(qn("w:sdt"))):
                location = f"{prefix}sdt[{sdt_index}]"
                content = sdt_el.find(qn("w:sdtContent"))
                _record_container(location, content)
                if content is None:
                    continue
                _scan_container(content, location + ".", parent_obj)
                table_elements = content.findall(qn("w:tbl"))
                if table_elements:
                    _scan_tables(
                        [Table(tbl_el, parent_obj) for tbl_el in table_elements],
                        location + ".",
                        parent_obj,
                    )

        def _scan_tables(tables, prefix: str, parent_obj) -> None:
            for t_idx, table in enumerate(tables):
                seen_tcs: set = set()
                for r_idx, row in enumerate(table.rows):
                    for c_idx, cell in enumerate(row.cells):
                        if id(cell._tc) in seen_tcs:
                            continue
                        seen_tcs.add(id(cell._tc))
                        cell_prefix = f"{prefix}tbl[{t_idx}].r[{r_idx}].c[{c_idx}]"
                        _scan_container(cell._tc, cell_prefix + ".", cell)
                        if cell.tables:
                            _scan_tables(cell.tables, cell_prefix + ".", cell)

        _scan_container(doc.element.body, "body.", doc)
        _scan_tables(doc.tables, "body.", doc)
        for s_idx, section in enumerate(doc.sections):
            for hf_name in _HF_NAMES:
                hf = getattr(section, hf_name, None)
                if hf is None:
                    continue
                try:
                    if hf.is_linked_to_previous:
                        continue
                    _scan_container(hf._element, f"sec[{s_idx}].{hf_name}.", hf)
                    if hf.tables:
                        _scan_tables(hf.tables, f"sec[{s_idx}].{hf_name}.", hf)
                except Exception:
                    continue
    except Exception as exc:
        scan["scan_error"] = "%s: %s" % (type(exc).__name__, exc)
    return scan


def build_document_spec(doc, file_path: str = "") -> Dict[str, Any]:
    """Build the complete DocumentSpec 4.0 object for a parsed `docx.Document`."""
    template_sha256, sha_source = _template_sha256(doc, file_path)
    compatibility = assess_template_compatibility_level(doc, file_path=file_path or "")

    sdt_scan = _scan_body_sdt(doc)
    sdt_with_content = [c for c in sdt_scan["containers"] if c["has_content"]]
    if (sdt_with_content or sdt_scan["scan_error"]) and \
            compatibility.get("compatibility_level") in ("L1", "L2"):
        # fail-closed: never claim L1/L2 while SDT content exists in any story/container
        compatibility = dict(compatibility)
        compatibility["compatibility_level"] = "L3"
        compatibility["recommended_strategy"] = "SEMI_AUTOMATIC_WITH_USER_CONFIRMATION"
        compatibility["l3_features"] = list(compatibility.get("l3_features") or []) + ["sdt_body_prescan"]

    all_contexts = list(iter_all_document_paragraphs_with_Wait_context(doc))
    contexts = [ctx for ctx in all_contexts if _is_location(ctx["location_id"])]
    skipped_stories = sorted({
        _story_prefix(ctx["location_id"])
        for ctx in all_contexts
        if not _is_location(ctx["location_id"]) and _context_has_content(ctx)
    })

    all_tables = list(iter_all_document_tables_with_context(doc))
    table_contexts = [ctx for ctx in all_tables if _is_location(ctx["table_id"])]
    skipped_stories.extend(
        _story_prefix(ctx["table_id"])
        for ctx in all_tables
        if not _is_location(ctx["table_id"]) and _table_has_content(ctx["table"])
    )
    skipped_stories = sorted(set(skipped_stories))

    sections = _section_specs(doc)
    printable_width = None
    if sections:
        first = sections[0]
        width = first.get("page_width_twips")
        left = first.get("margins", {}).get("left")
        right = first.get("margins", {}).get("right")
        if width is not None and left is not None and right is not None:
            printable_width = max(int(width) - int(left) - int(right), 0)

    ref_cache = _image_ref_counts(doc)
    images = _structure_images(contexts, ref_cache)
    tables = _structure_tables(table_contexts)

    candidates = _collect_candidates(contexts)
    slots, collisions, conflicts = _build_slots(candidates, template_sha256)
    contexts_by_location = {ctx["location_id"]: ctx for ctx in contexts}

    # Attach slot-level capacity evidence (never used to shrink text).
    for slot in slots:
        ctx = contexts_by_location.get(slot["location_id"])
        if ctx is None:
            continue
        capacity = _capacity_for_paragraph(
            ctx["p_el"], printable_width, slot["style_reference"]["effective_sz_half_pt"]
        )
        if capacity is not None:
            slot["capacity"] = capacity

    capacity_profiles = _build_capacity_profiles(candidates, contexts_by_location, printable_width)
    protected_regions = _build_protected_regions(
        doc, contexts, table_contexts, slots, sdt_containers=sdt_with_content
    )
    layout_constraints = _build_layout_constraints(table_contexts, contexts)
    unsupported_features = _build_unsupported_features(doc, compatibility, contexts)
    for container in sdt_with_content:
        unsupported_features.append({
            "code": "SDT_BODY_UNSUPPORTED",
            "detail": (
                "%s wraps %d paragraph(s) / %d table(s); the content is discovered as "
                "protected positions and is not fillable while sdt_edit=false"
                % (container["location"], container["paragraph_count"], container["table_count"])
            ),
            "location_id": container["location"],
        })
    if sdt_scan["scan_error"]:
        unsupported_features.append({
            "code": "SDT_BODY_SCAN_INCOMPLETE",
            "detail": (
                "SDT pre-scan failed; compatibility was capped at L3 and filling "
                "must be confirmed manually (%s)" % sdt_scan["scan_error"]
            ),
        })
    for story in skipped_stories:
        unsupported_features.append({
            "code": "SLOT_STRUCTURE_UNSUPPORTED",
            "detail": (
                f"story '{story}' cannot be represented by the Contract 01 location grammar; "
                "positions in it are not offered as slots"
            ),
        })

    protected_texts: List[str] = []
    for region in protected_regions:
        if region.get("kind") not in ("header", "footer", "logo", "stamp"):
            continue
        ctx = contexts_by_location.get(region.get("location_id"))
        if ctx is not None:
            text = (ctx["paragraph"].text or "").strip()
            if text:
                protected_texts.append(text)
    hashes = compute_four_hashes(doc, protected_texts=protected_texts)

    warnings: List[Dict[str, Any]] = []
    if sha_source == "package":
        warnings.append({
            "code": "TEMPLATE_SHA_DERIVED",
            "severity": "low",
            "detail": "no template file path was available; template_sha256 is derived from the in-memory package",
        })
    if conflicts:
        warnings.append({
            "code": "SLOT_ID_CONFLICT",
            "severity": "high",
            "detail": "duplicate slot_id computed; analysis is not usable for filling",
        })
    if collisions:
        warnings.append({
            "code": "SLOT_ID_COLLISION_RESOLVED",
            "severity": "medium",
            "detail": "12-hex slot_id collision resolved deterministically: " + ", ".join(collisions),
        })
    low_capacity = [p for p in capacity_profiles if p["confidence"] == "low"]
    if low_capacity:
        warnings.append({
            "code": "CAPACITY_LOW_CONFIDENCE",
            "severity": "low",
            "detail": f"{len(low_capacity)} capacity profile(s) estimated from geometry only; capacity is evidence, not an authority",
        })
    if compatibility.get("compatibility_level") == "L4":
        warnings.append({
            "code": "READ_ONLY_STRUCTURES_PRESENT",
            "severity": "medium",
            "detail": "template is classified L4; unsupported structures are preserved read-only",
        })
    if skipped_stories:
        warnings.append({
            "code": "SLOT_STRUCTURE_UNSUPPORTED",
            "severity": "medium",
            "detail": "unsupported story location(s): " + ", ".join(skipped_stories),
        })
    if sdt_with_content:
        warnings.append({
            "code": "SDT_BODY_PROTECTED_ONLY",
            "severity": "medium",
            "detail": (
                "%d SDT container(s) with content were discovered as protected positions "
                "(sdt_edit=false, so they are disclosed but not fillable): %s"
                % (
                    len(sdt_with_content),
                    ", ".join(container["location"] for container in sdt_with_content),
                )
            ),
        })
    if sdt_scan["scan_error"]:
        warnings.append({
            "code": "SDT_BODY_ENUMERATION_GAP",
            "severity": "high",
            "detail": "SDT pre-scan incomplete (fail-closed): %s" % sdt_scan["scan_error"],
        })
    empty_sdts = [c for c in sdt_scan["containers"] if not c["has_content"]]
    if empty_sdts:
        warnings.append({
            "code": "SDT_BODY_EMPTY",
            "severity": "low",
            "detail": "%d empty SDT container(s) observed (no direct paragraphs/tables inside)" % len(empty_sdts),
        })

    spec: Dict[str, Any] = {
        "schema_version": "4.0",
        "template": {
            "template_id": "T_" + template_sha256[:12],
            "template_sha256": template_sha256,
            "compatibility": compatibility.get("compatibility_level", "L4"),
            "protection_mode": "STRICT",
            "capabilities": _capabilities(images, tables),
        },
        "document": _document_block(sections),
        "structure": {
            "paragraphs": _structure_paragraphs(contexts),
            "tables": tables,
            "images": images,
        },
        "slots": slots,
        "protected_regions": protected_regions,
        "capacity_profiles": capacity_profiles,
        "layout_constraints": layout_constraints,
        "fingerprint_ref": {
            "fingerprint_id": "FP_001",
            "structural_hash": hashes["structural_hash"],
            "style_hash": hashes["style_hash"],
            "protected_hash": hashes["protected_hash"],
            "layout_hash": hashes["layout_hash"],
            "baseline_path": None,
        },
        "unsupported_features": unsupported_features,
        "warnings": warnings,
        "errors": [],
    }
    return spec


def _safe_linked(hf) -> bool:
    try:
        return bool(hf.is_linked_to_previous)
    except Exception:
        return True


def _error_spec(file_path: str, exc: Exception) -> Dict[str, Any]:
    """Schema-valid DocumentSpec for a file that cannot be analyzed at all."""
    try:
        with open(file_path, "rb") as handle:
            raw = handle.read()
        digest = hashlib.sha256(raw).hexdigest()
    except Exception:
        digest = hashlib.sha256(f"unreadable:{file_path}".encode("utf-8")).hexdigest()
    marker = hashlib.sha256(f"unreadable|{file_path}|{type(exc).__name__}".encode("utf-8")).hexdigest()
    hashes = {
        key: hashlib.sha256(f"{key}|{marker}".encode("utf-8")).hexdigest()
        for key in ("structural_hash", "style_hash", "protected_hash", "layout_hash")
    }
    return {
        "schema_version": "4.0",
        "template": {
            "template_id": "T_" + digest[:12],
            "template_sha256": digest,
            "compatibility": "L4",
            "protection_mode": "STRICT",
            "capabilities": {
                "text_fill": False,
                "table_fill": False,
                "image_replace": False,
                "nested_table": False,
                "field_update": False,
                "sdt_edit": False,
                "smartart_edit": False,
                "visual_render": False,
            },
        },
        "document": {"page_size": None, "orientation": None, "sections": [{"section_index": 0}]},
        "structure": {"paragraphs": [], "tables": [], "images": []},
        "slots": [],
        "protected_regions": [],
        "capacity_profiles": [],
        "layout_constraints": [],
        "fingerprint_ref": {"fingerprint_id": "FP_001", **hashes, "baseline_path": None},
        "unsupported_features": [],
        "warnings": [],
        "errors": [{
            "code": "DOCUMENT_UNREADABLE",
            "severity": "blocking",
            "detail": f"template could not be analyzed: {type(exc).__name__}: {exc}",
        }],
    }


def build_document_spec_from_path(path: str) -> Dict[str, Any]:
    """Build DocumentSpec 4.0 from a `.docx` path, returning an error spec when unreadable."""
    from engine.package_guard import check_package, load_limits

    verdict = check_package(path, load_limits())
    if not verdict["ok"]:
        # W3-7: hostile/oversized packages are rejected BEFORE any parser touches them.
        return _error_spec(
            path,
            RuntimeError("%s: %s" % (verdict["code"], str(verdict["violations"])[:300])),
        )
    try:
        document = docx.Document(path)
    except Exception as exc:  # corrupt zip, missing file, not a Word package
        return _error_spec(path, exc)
    return build_document_spec(document, file_path=path)
