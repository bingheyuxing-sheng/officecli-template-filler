# -*- coding: utf-8 -*-
"""DocumentSpec 4.0 fingerprints.

Four canonical, content-independent SHA-256 digests:

* `structural_hash` — element local-name tree of every story plus selected attributes;
  text-bearing elements carry no text, so an authorized text fill does not change it.
* `style_hash`      — canonical `word/styles.xml` tree (all `w:style` elements and `docDefaults`).
* `protected_hash`  — sorted protected texts plus header/footer and image partnames.
* `layout_hash`     — section geometry, table grid widths and inline image extents.

The fingerprint is never a raw ZIP hash: every hash is `sha256` over
`json.dumps(..., sort_keys=True)` output.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List, Optional

from docx.oxml.ns import qn

from engine.ooxml_utils import (
    iter_all_document_paragraphs_with_Wait_context,
    iter_all_document_tables_with_context,
)

# Elements whose character data is content, not structure. Dropping their text (and their
# attributes on `w:t`, which fill code may add as `xml:space="preserve"`) keeps the
# structural digest stable across authorized text fills.
_TEXT_BEARING = frozenset({"t", "instrText", "delText", "delInstrText"})

# Layout-only attributes. ``fit_mode="fit_image"`` legitimately rewrites the
# drawing extents, so their values belong to ``layout_hash`` only; the nodes
# themselves stay in ``structural_hash`` so a real node change is still caught.
_LAYOUT_ATTRIBUTES = {
    "extent": frozenset({"cx", "cy"}),
    "ext": frozenset({"cx", "cy"}),
}

_HF_NAMES = (
    "header", "first_page_header", "even_page_header",
    "footer", "first_page_footer", "even_page_footer",
)


def _local_name(el) -> str:
    tag = el.tag if isinstance(el.tag, str) else ""
    return tag.split("}")[-1] if "}" in tag else tag


def _local_name_key(key: Any) -> str:
    name = str(key)
    return name.split("}")[-1] if "}" in name else name


# Formatting-only elements do not belong to the structural tree: an authorized
# fill removes a red placeholder colour (w:color) while keeping the run and rPr
# wrappers, and that must not read as an unauthorized structure change. Direct
# formatting is covered by FORMAT QA and the style hash, not here.
_FORMAT_ELEMENTS = frozenset({"color"})


def _canonical_node(el) -> Dict[str, Any]:
    name = _local_name(el)
    if name in _TEXT_BEARING:
        children = []
        attributes: List[List[str]] = []
    else:
        children = [
            _canonical_node(child)
            for child in el
            if isinstance(child.tag, str) and _local_name(child) not in _FORMAT_ELEMENTS
        ]
        excluded = _LAYOUT_ATTRIBUTES.get(name, frozenset())
        attributes = sorted(
            [str(key), str(value)]
            for key, value in el.attrib.items()
            if _local_name_key(key) not in excluded
        )
    return {"n": name, "a": attributes, "c": children}


def _digest(payload: Any) -> str:
    text = json.dumps(payload, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _has_visible_content(element) -> bool:
    """True when a header/footer actually carries text, a table or a picture."""
    if element is None:
        return False
    text = "".join(node.text or "" for node in element.iter(qn("w:t")))
    return bool(
        text.strip()
        or element.xpath(".//w:tbl")
        or element.xpath(".//w:drawing | .//w:pict")
    )


def _header_footer_elements(doc) -> List[Any]:
    """Header/footer roots that actually carry content, in deterministic order."""
    roots: List[Any] = []
    seen_partnames: Dict[str, bool] = {}
    for section in doc.sections:
        for name in _HF_NAMES:
            hf = getattr(section, name, None)
            if hf is None:
                continue
            try:
                if hf.is_linked_to_previous:
                    continue
                part = hf.part
            except Exception:
                continue
            partname = str(getattr(part, "partname", ""))
            if partname in seen_partnames:
                continue
            seen_partnames[partname] = True
            element = getattr(part, "element", None)
            if element is not None and _has_visible_content(element):
                roots.append(element)
    return roots


def _notes_elements(doc) -> List[Any]:
    roots: List[Any] = []
    document_part = doc.part
    for rel_id in sorted(document_part.rels):
        rel = document_part.rels[rel_id]
        if getattr(rel, "is_external", False):
            continue
        reltype = (rel.reltype or "").lower()
        if any(kind in reltype for kind in ("footnotes", "endnotes", "comments")):
            element = getattr(rel.target_part, "element", None)
            if element is not None:
                roots.append(element)
    return roots


def _header_footer_texts(doc) -> List[str]:
    texts: List[str] = []
    for section in doc.sections:
        for name in _HF_NAMES:
            hf = getattr(section, name, None)
            if hf is None:
                continue
            try:
                if hf.is_linked_to_previous:
                    continue
                joined = "".join(p.text for p in hf.paragraphs).strip()
            except Exception:
                continue
            if joined:
                texts.append(joined)
    return texts


def _partnames(doc) -> Dict[str, List[str]]:
    """Header/footer and image partnames present in the package."""
    hf: List[str] = []
    images: List[str] = []
    for section in doc.sections:
        for name in _HF_NAMES:
            hf_obj = getattr(section, name, None)
            if hf_obj is None:
                continue
            try:
                if hf_obj.is_linked_to_previous:
                    continue
                part = hf_obj.part
            except Exception:
                continue
            if not _has_visible_content(getattr(part, "element", None)):
                continue
            partname = str(getattr(part, "partname", ""))
            if partname and partname not in hf:
                hf.append(partname)
    package = getattr(doc.part, "package", None)
    if package is not None and hasattr(package, "iter_parts"):
        for part in package.iter_parts():
            partname = str(getattr(part, "partname", ""))
            if partname and ("/media/" in partname or partname.startswith("/word/media/")):
                if partname not in images:
                    images.append(partname)
    return {"header_footer": sorted(hf), "images": sorted(images)}


def _structural_hash(doc) -> str:
    roots = [{"p": "document", "t": _canonical_node(doc.element)}]
    for element in _header_footer_elements(doc):
        roots.append({"p": _local_name(element), "t": _canonical_node(element)})
    for element in _notes_elements(doc):
        roots.append({"p": _local_name(element), "t": _canonical_node(element)})
    return _digest({"roots": roots})


def _styles_root(doc):
    package = getattr(doc.part, "package", None)
    if package is not None and hasattr(package, "iter_parts"):
        for part in package.iter_parts():
            if str(getattr(part, "partname", "")).endswith("/styles.xml"):
                return getattr(part, "element", None)
    return None


def _style_hash(doc) -> str:
    root = _styles_root(doc)
    if root is None:
        return _digest({"styles": None})
    styles = [_canonical_node(child) for child in root if _local_name(child) == "style"]
    defaults = [_canonical_node(child) for child in root if _local_name(child) == "docDefaults"]
    return _digest({"docDefaults": defaults, "styles": styles})


def _protected_hash(doc, protected_texts: Optional[List[str]]) -> str:
    texts = _header_footer_texts(doc) if protected_texts is None else list(protected_texts)
    partnames = _partnames(doc)
    return _digest({
        "protected_texts": sorted({str(text) for text in texts if str(text).strip()}),
        "header_footer_parts": partnames["header_footer"],
        "image_parts": partnames["images"],
    })


def _section_layout(section, index: int) -> Dict[str, Any]:
    def _twips(value):
        try:
            return int(value.twips) if value is not None else None
        except Exception:
            return None

    return {
        "section_index": index,
        "page_width": _twips(section.page_width),
        "page_height": _twips(section.page_height),
        "orientation": int(section.orientation) if section.orientation is not None else None,
        "margins": {
            "top": _twips(section.top_margin),
            "bottom": _twips(section.bottom_margin),
            "left": _twips(section.left_margin),
            "right": _twips(section.right_margin),
        },
        "header_distance": _twips(section.header_distance),
        "footer_distance": _twips(section.footer_distance),
    }


def _layout_hash(doc) -> str:
    sections = [_section_layout(section, i) for i, section in enumerate(doc.sections)]

    tables = []
    for ctx in iter_all_document_tables_with_context(doc):
        grid = ctx["table"]._tbl.find(qn("w:tblGrid"))
        widths: List[int] = []
        if grid is not None:
            for column in grid.findall(qn("w:gridCol")):
                raw = column.get(qn("w:w")) or ""
                if raw.isdigit():
                    widths.append(int(raw))
        tables.append({"table_id": ctx["table_id"], "column_widths": widths})

    images = []
    for ctx in iter_all_document_paragraphs_with_Wait_context(doc):
        for index, inline in enumerate(ctx["p_el"].xpath(".//wp:inline")):
            extents = inline.xpath("./wp:extent") or inline.xpath(".//wp:extent")
            if not extents:
                continue
            images.append({
                "location": f"{ctx['location_id']}.image[{index}]",
                "width": int(extents[0].get("cx") or 0),
                "height": int(extents[0].get("cy") or 0),
            })

    return _digest({"sections": sections, "tables": tables, "images": images})


def compute_four_hashes(doc, protected_texts: Optional[List[str]] = None) -> Dict[str, str]:
    """Return the four canonical 64-hex fingerprints for a parsed document."""
    return {
        "structural_hash": _structural_hash(doc),
        "style_hash": _style_hash(doc),
        "protected_hash": _protected_hash(doc, protected_texts),
        "layout_hash": _layout_hash(doc),
    }
