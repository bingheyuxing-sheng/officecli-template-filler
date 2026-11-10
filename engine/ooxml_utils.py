"""
Non-Destructive OOXML Utilities & Logical Cross-Run Text View Engine (v3.0 — Fixes P0-1).

Key v3.0 architectural changes over v2.9:
1. Never deletes `<w:proofErr>` spellcheck markers or merges all runs destructively up front.
2. Builds a read-only `LogicalParagraphView` mapping every character offset in the concatenated
   paragraph text back to its exact `(run_element, t_element, char_index_in_t)` tuple.
3. Replaces matched placeholder spans across 1..N runs surgically while preserving `<w:t>` attributes
   (including `xml:space="preserve"` and any extension attributes) and leaving untouched runs,
   hyperlinks, fields, comments, and proofErr nodes intact.
4. Traverses the ENTIRE document story tree: body paragraphs, nested tables, headers, footers,
   textboxes (`w:txbxContent`), footnotes, endnotes, and comments.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, Iterator, List, Optional, Set, Tuple
from docx.oxml.ns import qn
from lxml import etree

XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"
W14_PARA_ID = "{http://schemas.microsoft.com/office/word/2010/wordml}paraId"
W14_TEXT_ID = "{http://schemas.microsoft.com/office/word/2010/wordml}textId"

RED_HEX_SET = {"EE0000", "FF0000", "C00000", "FF3300", "CC0000", "E30000"}
TOKEN_PATTERN = re.compile(r"(\{\{[^{}]+\}\}|【[^【】]+】|\*{3,}|_{3,})")
_W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"


def _is_red_rgb(value: str) -> bool:
    """Recognize red hues instead of relying on a small hard-coded color allowlist."""
    value = (value or "").strip().lstrip("#").upper()
    if len(value) != 6 or any(ch not in "0123456789ABCDEF" for ch in value):
        return False
    red, green, blue = (int(value[i:i + 2], 16) for i in (0, 2, 4))
    return red >= 120 and red > green * 1.25 and red > blue * 1.25 and (red - min(green, blue)) >= 35


def _theme_rgb(paragraph, theme_name: str) -> Optional[str]:
    part = getattr(paragraph, "part", None)
    package = getattr(part, "package", None)
    if package is None or not hasattr(package, "iter_parts"):
        return None
    theme_map = {
        "dk1": "lt1", "lt1": "dk1", "dk2": "lt2", "lt2": "dk2",
        "accent1": "accent1", "accent2": "accent2", "accent3": "accent3",
        "accent4": "accent4", "accent5": "accent5", "accent6": "accent6",
        "hlink": "hlink", "folHlink": "folHlink",
    }
    key = theme_map.get(theme_name, theme_name)
    for candidate in package.iter_parts():
        if not str(getattr(candidate, "partname", "")).endswith("/theme/theme1.xml"):
            continue
        root = getattr(candidate, "element", None)
        if root is None and hasattr(candidate, "blob"):
            try:
                root = etree.fromstring(candidate.blob)
            except Exception:
                root = None
        if root is None:
            continue
        for node in root.iter():
            if node.tag.rsplit("}", 1)[-1] == key:
                child = next(iter(node), None)
                if child is not None:
                    return child.get("val") or child.get("lastClr")
    return None


def _apply_theme_modifier(rgb: str, color_el) -> str:
    """Apply the OOXML tint/shade approximation used for theme colors."""
    if not rgb:
        return rgb
    try:
        channels = [int(rgb[i:i + 2], 16) for i in (0, 2, 4)]
        tint = color_el.get(qn("w:themeTint"))
        shade = color_el.get(qn("w:themeShade"))
        if tint:
            factor = int(tint, 16) / 255.0
            channels = [round(c + (255 - c) * factor) for c in channels]
        if shade:
            factor = int(shade, 16) / 255.0
            channels = [round(c * (1 - factor)) for c in channels]
        return "".join(f"{max(0, min(255, c)):02X}" for c in channels)
    except (TypeError, ValueError):
        return rgb


def _styles_root_for(paragraph):
    part = getattr(paragraph, "part", None)
    package = getattr(part, "package", None)
    if package is None or not hasattr(package, "iter_parts"):
        return None
    for candidate in package.iter_parts():
        if str(getattr(candidate, "partname", "")).endswith("/styles.xml"):
            return getattr(candidate, "element", None)
    return None


def _style_by_id(styles_root, style_id):
    if styles_root is None or not style_id:
        return None
    for style in styles_root.iter(qn("w:style")):
        if style.get(qn("w:styleId")) == style_id:
            return style
    return None


def _color_from_rpr(rPr, paragraph) -> Optional[str]:
    if rPr is None:
        return None
    color = rPr.find(qn("w:color"))
    if color is not None:
        theme = color.get(qn("w:themeColor"))
        if theme:
            return _apply_theme_modifier(_theme_rgb(paragraph, theme) or "", color)
        val = (color.get(qn("w:val")) or "").upper()
        if val != "AUTO" and len(val) == 6:
            return _apply_theme_modifier(val, color)
    return None


def _effective_run_color(run, paragraph=None) -> Optional[str]:
    r_el = getattr(run, "_r", run)
    if paragraph is None:
        parent = r_el.getparent() if hasattr(r_el, "getparent") else None
        while parent is not None and parent.tag != qn("w:p"):
            parent = parent.getparent()
        if parent is not None:
            paragraph = getattr(parent, "_parent", None)
    rPr = getattr(r_el, "rPr", None) if hasattr(r_el, "rPr") else r_el.find(qn("w:rPr"))
    direct = _color_from_rpr(rPr, paragraph)
    if direct:
        return direct
    styles_root = _styles_root_for(paragraph)
    if rPr is not None:
        r_style = rPr.find(qn("w:rStyle"))
        if r_style is not None:
            style = _style_by_id(styles_root, r_style.get(qn("w:val")))
            while style is not None:
                found = _color_from_rpr(style.find(qn("w:rPr")), paragraph)
                if found:
                    return found
                based = style.find(qn("w:basedOn"))
                style = _style_by_id(styles_root, based.get(qn("w:val"))) if based is not None else None
    style = getattr(paragraph, "style", None)
    while style is not None:
        found = _color_from_rpr(getattr(style, "element", None).find(qn("w:rPr")) if getattr(style, "element", None) is not None else None, paragraph)
        if found:
            return found
        style = getattr(style, "base_style", None)
    if styles_root is not None:
        defaults = styles_root.find(qn("w:docDefaults"))
        rpr_default = defaults.find(qn("w:rPrDefault")) if defaults is not None else None
        default_rpr = rpr_default.find(qn("w:rPr")) if rpr_default is not None else None
        return _color_from_rpr(default_rpr, paragraph)
    return None


def is_red_run(run, paragraph=None) -> bool:
    """Check direct and inherited RGB/theme colors for a red run."""
    return _is_red_rgb(_effective_run_color(run, paragraph) or "")


@dataclass
class CharNodeMap:
    """Maps a single logical character offset to its physical XML `<w:r>` and `<w:t>` node."""
    logical_idx: int
    char: str
    r_el: any
    t_el: any
    t_char_idx: int


class LogicalParagraphView:
    """
    Non-destructive logical text view over a `<w:p>` element (P0-1 fix).
    Instead of stripping `<w:proofErr>` and merging adjacent runs globally,
    this builds a character-to-XML-node mapping across all `<w:r>/<w:t>` elements
    in reading order so cross-run placeholders (e.g. `{{` + `project_name` + `}}`)
    can be searched and replaced surgically without altering surrounding runs or proofErr nodes.
    """

    def __init__(self, p_el):
        self.p_el = p_el
        self.char_map: List[CharNodeMap] = []
        self.logical_text: str = ""
        self._rebuild()

    def _rebuild(self) -> None:
        self.char_map.clear()
        chars: List[str] = []
        # Iterate direct and nested runs inside paragraph (excluding nested w:txbxContent paragraphs which are traversed separately)
        for r_el in self._iter_own_runs(self.p_el):
            for t_el in r_el.findall(qn("w:t")):
                txt = t_el.text or ""
                for idx_in_t, ch in enumerate(txt):
                    self.char_map.append(
                        CharNodeMap(
                            logical_idx=len(chars),
                            char=ch,
                            r_el=r_el,
                            t_el=t_el,
                            t_char_idx=idx_in_t,
                        )
                    )
                    chars.append(ch)
        self.logical_text = "".join(chars)

    @staticmethod
    def _iter_own_runs(p_el) -> Iterator[any]:
        """
        Yield `<w:r>` elements belonging to `p_el` in document order (including inside hyperlinks,
        smartTags, or SDT inline runs), without descending into nested tables or textbox paragraphs.
        """
        def _walk(node):
            for child in node:
                local = child.tag.split("}")[-1] if "}" in child.tag else child.tag
                if local in ("tbl", "txbxContent", "p"):
                    continue
                if child.tag == qn("w:r"):
                    yield child
                else:
                    yield from _walk(child)

        yield from _walk(p_el)

    def find_spans(self, pattern: str | re.Pattern) -> List[Tuple[int, int, str]]:
        """Find all `(start_offset, end_offset, matched_text)` spans in the logical text view."""
        rx = re.compile(pattern) if isinstance(pattern, str) else pattern
        return [(m.start(), m.end(), m.group(0)) for m in rx.finditer(self.logical_text)]

    def find_regex_spans(self, pattern: str | re.Pattern) -> List[Tuple[int, int, str]]:
        """Alias for `find_spans`."""
        return self.find_spans(pattern)

    def replace_span(
        self,
        start_idx: int,
        end_idx: int,
        replacement: str,
        strip_red_color: bool = True,
        rPr_normalizer=None,
        preserve_empty_runs: bool = False,
    ) -> bool:
        """
        Surgically replace `[start_idx, end_idx)` in the logical text with `replacement`:
        - Places `replacement` at the slice position inside the first `<w:t>` of the span,
          preserving all attributes on `<w:t>` and updating `xml:space="preserve"` when needed.
        - Trims only the matched character range from any subsequent `<w:t>` elements in the span.
        - Removes a subsequent `<w:r>` ONLY if its `<w:t>` becomes completely empty AND the run
          contains no other non-text children (drawings, breaks, tabs, fields, etc.) AND no custom `<w:t>` attributes.
        - Never touches `<w:proofErr>` or runs outside `[start_idx, end_idx)`.
        """
        if start_idx < 0 or end_idx > len(self.char_map) or start_idx >= end_idx:
            return False

        affected = self.char_map[start_idx:end_idx]
        # Group affected characters by their `t_el` preserving order
        t_groups: List[Tuple[any, any, List[int]]] = []
        seen_t_ids: Dict[int, int] = {}
        for item in affected:
            tid = id(item.t_el)
            if tid not in seen_t_ids:
                seen_t_ids[tid] = len(t_groups)
                t_groups.append((item.r_el, item.t_el, []))
            t_groups[seen_t_ids[tid]][2].append(item.t_char_idx)

        # 1. Update the anchor (first) <w:t>
        first_r, first_t, first_indices = t_groups[0]
        orig_first_text = first_t.text or ""
        f_start = min(first_indices)
        f_end = max(first_indices) + 1
        new_first_text = orig_first_text[:f_start] + replacement + orig_first_text[f_end:]
        first_t.text = new_first_text
        ensure_xml_space_preserve_on_t(first_t)

        # Optionally strip red placeholder color on the anchor run
        if strip_red_color:
            rPr = first_r.find(qn("w:rPr"))
            if rPr_normalizer is not None:
                new_rPr = rPr_normalizer(rPr)
                if rPr is not None:
                    first_r.remove(rPr)
                first_r.insert(0, new_rPr)
            elif rPr is not None:
                color = rPr.find(qn("w:color"))
                if color is not None and _is_red_rgb((color.get(qn("w:val")) or "")):
                    rPr.remove(color)

        # 2. Trim matched characters from remaining <w:t> nodes in the span
        for r_el, t_el, c_indices in t_groups[1:]:
            orig_txt = t_el.text or ""
            c_start = min(c_indices)
            c_end = max(c_indices) + 1
            rem_txt = orig_txt[:c_start] + orig_txt[c_end:]
            t_el.text = rem_txt
            ensure_xml_space_preserve_on_t(t_el)
            # Only remove run if it has no remaining text, no other content nodes, and no custom <w:t> attributes.
            # The v4 FillPlan path sets preserve_empty_runs so an authorized text fill does not
            # change the element tree (structural fingerprint) by deleting emptied runs.
            if rem_txt == "" and not preserve_empty_runs and _can_safely_remove_empty_run(r_el, t_el):
                parent = r_el.getparent()
                if parent is not None:
                    parent.remove(r_el)

        self._rebuild()
        return True

    def replace_all_tokens(
        self,
        replacements: Dict[str, str] | str,
        replacement_val: Optional[str] = None,
        strip_red_color: bool = True,
        strip_red: Optional[bool] = None,
        rPr_normalizer=None,
    ) -> int:
        """
        Replace all exact token keys across runs in this paragraph.
        Supports either `replace_all_tokens({token: new_val})` OR `replace_all_tokens(token_str, new_val_str)`.
        """
        if strip_red is not None:
            strip_red_color = strip_red
        if isinstance(replacements, str):
            rep_map = {replacements: "" if replacement_val is None else str(replacement_val)}
        else:
            rep_map = replacements
        count = 0
        for token, new_val in rep_map.items():
            if not token:
                continue
            replacement = str(new_val)
            # Advance past each replacement so a value that itself contains `token`
            # (or equals it) cannot make this loop spin forever.
            search_from = 0
            while True:
                idx = self.logical_text.find(token, search_from)
                if idx == -1:
                    break
                if not self.replace_span(
                    idx,
                    idx + len(token),
                    replacement,
                    strip_red_color=strip_red_color,
                    rPr_normalizer=rPr_normalizer,
                ):
                    break
                count += 1
                search_from = idx + len(replacement)
        return count


def _can_safely_remove_empty_run(r_el, t_el) -> bool:
    """
    Verify that `r_el` only contains `w:rPr` and a single empty `w:t` without special attributes
    (other than standard `xml:space`). Preserves runs that carry drawings, breaks, tabs, fields,
    footnoteReferences, or custom `w:t` extension attributes.
    """
    extra_t_attrs = {k for k in t_el.attrib.keys() if k != XML_SPACE}
    if extra_t_attrs:
        return False
    t_count = 0
    for child in r_el:
        local = child.tag.split("}")[-1] if "}" in child.tag else child.tag
        if local == "rPr":
            continue
        if local == "t":
            t_count += 1
            if (child.text or "") != "":
                return False
        else:
            return False
    return t_count <= 1


def ensure_xml_space_preserve_on_t(t_el) -> None:
    """Set `xml:space="preserve"` on `<w:t>` when text has leading/trailing/multiple spaces or tabs."""
    txt = t_el.text or ""
    if txt.startswith(" ") or txt.endswith(" ") or "  " in txt or "\t" in txt:
        t_el.set(XML_SPACE, "preserve")


def ensure_xml_space_preserve_on_run(run) -> None:
    """Ensure `<w:t xml:space="preserve">` on all `<w:t>` inside a `python-docx` Run."""
    for t_el in run._r.findall(qn("w:t")):
        ensure_xml_space_preserve_on_t(t_el)


class ParagraphContext(dict):
    """
    Hybrid context object yielded by `iter_all_document_paragraphs_with_Wait_context(doc)`.
    Supports BOTH dictionary access (`ctx["p_el"]`, `ctx["location_id"]`, `ctx["scope"]`, `ctx["paragraph"]`)
    AND 2-tuple unpacking (`loc, p = ctx`).
    """

    def __iter__(self):
        yield self["location_id"]
        yield self["paragraph"]


def iter_all_document_paragraphs_with_Wait_context(doc) -> Iterator[ParagraphContext]:
    """
    Comprehensive traversal across the ENTIRE DOCX package (fixes P0-1 scope gap):
    - Body top-level paragraphs (`body_p[i]`)
    - Tables & recursively nested tables (`tbl[...].r[...].c[...].p[...]`)
    - Textboxes (`w:txbxContent//w:p`) inside body, tables, headers, footers
    - Headers & footers across all sections (`section[s].header/footer`)
    - Footnotes, endnotes, and comments XML parts when present in the package
    Yields `ParagraphContext` supporting both dict keys and `(locator_path, paragraph)` tuple unpacking.
    """
    from docx.text.paragraph import Paragraph

    seen_p_ids: Set[int] = set()
    # lxml drops element proxies once nothing references them, and CPython may reuse the
    # freed address for a different node. Deduping on `id()` alone would then skip a real
    # paragraph; the strong references below keep every seen id unique for this traversal.
    seen_p_elements: List[Any] = []

    def _infer_scope(loc: str) -> str:
        if ".txbx_p[" in loc:
            return "textbox"
        if loc.startswith("sec["):
            return "header_footer"
        if loc.startswith("footnotes."):
            return "footnote"
        if loc.startswith("endnotes."):
            return "endnote"
        if loc.startswith("comments."):
            return "comment"
        if "tbl[" in loc:
            return "table"
        return "body"

    def _yield_p(loc: str, p_el, parent_obj):
        pid = id(p_el)
        if pid in seen_p_ids:
            return
        seen_p_ids.add(pid)
        seen_p_elements.append(p_el)
        p_obj = Paragraph(p_el, parent_obj)
        yield ParagraphContext(
            location_id=loc,
            scope=_infer_scope(loc),
            paragraph=p_obj,
            p_el=p_el,
        )

    def _walk_sdt_container(sdt_el, sdt_location: str, parent_obj):
        """Yield content of one `w:sdt` container (CP-W2-002).

        `sdt[i]` addresses the i-th direct `w:sdt` child of its container. Paragraphs
        and tables are indexed only among direct `w:sdtContent` children (gate
        amendment B3): the global `w:txbxContent` pass above already yields textbox
        paragraphs under their stable `txbx_p[i]` locations, so descending into
        `w:txbxContent` here would let the `id()`-based de-duplication steal those
        paragraphs and change existing slot ids.
        """
        content = sdt_el.find(qn("w:sdtContent"))
        if content is None:
            return
        for p_idx, p in enumerate(content.findall(qn("w:p"))):
            yield from _yield_p(f"{sdt_location}.p[{p_idx}]", p, parent_obj)
        table_elements = content.findall(qn("w:tbl"))
        if table_elements:
            from docx.table import Table

            tables = [Table(tbl_el, parent_obj) for tbl_el in table_elements]
            yield from _walk_tables(tables, f"{sdt_location}.", parent_obj)
        for nested_idx, nested in enumerate(content.findall(qn("w:sdt"))):
            yield from _walk_sdt_container(
                nested, f"{sdt_location}.sdt[{nested_idx}]", parent_obj
            )

    def _walk_tables(tables, prefix: str, parent_obj):
        for t_idx, tbl in enumerate(tables):
            seen_tcs: Set[int] = set()
            for r_idx, row in enumerate(tbl.rows):
                for c_idx, cell in enumerate(row.cells):
                    if id(cell._tc) in seen_tcs:
                        continue
                    seen_tcs.add(id(cell._tc))
                    seen_p_elements.append(cell._tc)
                    cell_prefix = f"{prefix}tbl[{t_idx}].r[{r_idx}].c[{c_idx}]"
                    for p_idx, p in enumerate(cell.paragraphs):
                        yield from _yield_p(f"{cell_prefix}.p[{p_idx}]", p._p, cell)
                    if cell.tables:
                        yield from _walk_tables(cell.tables, f"{cell_prefix}.", cell)
                    for sdt_idx, sdt_el in enumerate(cell._tc.findall(qn("w:sdt"))):
                        yield from _walk_sdt_container(
                            sdt_el, f"{cell_prefix}.sdt[{sdt_idx}]", cell
                        )

    # 1. Main body paragraphs
    for i, p in enumerate(doc.paragraphs):
        yield from _yield_p(f"body.p[{i}]", p._p, doc)

    # 2. Main body tables + nested tables
    yield from _walk_tables(doc.tables, "body.", doc)

    # 3. Textboxes (`w:txbxContent`) in main body
    for txbx_idx, p_el in enumerate(doc.element.body.xpath(".//w:txbxContent//w:p")):
        yield from _yield_p(f"body.txbx_p[{txbx_idx}]", p_el, doc)

    # 3b. Body-level `w:sdt` containers (CP-W2-002). Kept after the textbox pass so
    # textbox paragraphs keep their `body.txbx_p[i]` locations and ids.
    for sdt_idx, sdt_el in enumerate(doc.element.body.findall(qn("w:sdt"))):
        yield from _walk_sdt_container(sdt_el, f"body.sdt[{sdt_idx}]", doc)

    # 4. Headers & Footers across all sections (including default, even_page, first_page)
    for s_idx, section in enumerate(doc.sections):
        hf_candidates = [
            ("header", getattr(section, "header", None)),
            ("first_page_header", getattr(section, "first_page_header", None)),
            ("even_page_header", getattr(section, "even_page_header", None)),
            ("footer", getattr(section, "footer", None)),
            ("first_page_footer", getattr(section, "first_page_footer", None)),
            ("even_page_footer", getattr(section, "even_page_footer", None)),
        ]
        for hf_name, hf_obj in hf_candidates:
            if hf_obj is None:
                continue
            try:
                # A linked-to-previous header/footer has no own definition in this
                # section. Reading ``.paragraphs``/``.tables``/``._element`` would make
                # python-docx lazily CREATE an empty part and a ``w:headerReference``
                # in ``w:sectPr``, mutating the supposedly read-only document and
                # polluting the structural fingerprint (phantom ``r:id`` differs per
                # file). Skip before any content access, for every section index.
                if hf_obj.is_linked_to_previous:
                    continue
                for p_idx, p in enumerate(hf_obj.paragraphs):
                    yield from _yield_p(f"sec[{s_idx}].{hf_name}.p[{p_idx}]", p._p, hf_obj)
                if hf_obj.tables:
                    yield from _walk_tables(hf_obj.tables, f"sec[{s_idx}].{hf_name}.", hf_obj)
                for txbx_idx, p_el in enumerate(hf_obj._element.xpath(".//w:txbxContent//w:p")):
                    yield from _yield_p(f"sec[{s_idx}].{hf_name}.txbx_p[{txbx_idx}]", p_el, hf_obj)
                for sdt_idx, sdt_el in enumerate(hf_obj._element.findall(qn("w:sdt"))):
                    yield from _walk_sdt_container(
                        sdt_el, f"sec[{s_idx}].{hf_name}.sdt[{sdt_idx}]", hf_obj
                    )
            except Exception:
                continue

    # 5. Footnotes, Endnotes, Comments parts in package relationships
    for rel in doc.part.rels.values():
        if rel.is_external:
            continue
        reltype = (rel.reltype or "").lower()
        if any(k in reltype for k in ("footnotes", "endnotes", "comments")):
            target_part = rel.target_part
            el = getattr(target_part, "element", None)
            if el is None:
                el = getattr(target_part, "_element", None)
            if el is None:
                blob = getattr(target_part, "blob", None)
                if blob:
                    from docx.oxml import parse_xml

                    el = parse_xml(blob)
            if el is not None:
                part_short = reltype.split("/")[-1]
                for idx, p_el in enumerate(el.findall(".//" + qn("w:p"))):
                    yield from _yield_p(f"{part_short}.p[{idx}]", p_el, target_part)


def iter_all_document_tables_with_context(doc) -> Iterator[Dict[str, any]]:
    """
    Yield all tables across body, nested tables, and headers/footers with context metadata:
    `{"table_id": str, "scope": str, "depth": int, "table": Table}`.
    """
    seen_tbl_ids: Set[int] = set()
    # Same proxy-recycling guard as the paragraph iterator above.
    seen_elements: List[Any] = []

    def _walk_sdt_tables(sdt_el, sdt_location: str, scope: str, depth: int, parent_obj):
        """Tables directly inside one `w:sdt` container (CP-W2-002).

        Direct `w:sdtContent` children only, matching the paragraph iterator. Nested
        SDTs are walked recursively with their own `sdt[i]` segment.
        """
        content = sdt_el.find(qn("w:sdtContent"))
        if content is None:
            return
        table_elements = content.findall(qn("w:tbl"))
        if table_elements:
            from docx.table import Table

            tables = [Table(tbl_el, parent_obj) for tbl_el in table_elements]
            yield from _walk(tables, scope=scope, prefix=f"{sdt_location}.", depth=depth)
        for nested_idx, nested in enumerate(content.findall(qn("w:sdt"))):
            yield from _walk_sdt_tables(
                nested, f"{sdt_location}.sdt[{nested_idx}]", scope, depth, parent_obj
            )

    def _walk(tables, scope: str, prefix: str, depth: int):
        for t_idx, tbl in enumerate(tables):
            tid = id(tbl._tbl)
            if tid in seen_tbl_ids:
                continue
            seen_tbl_ids.add(tid)
            seen_elements.append(tbl._tbl)
            table_id = f"{prefix}tbl[{t_idx}]"
            yield {
                "table_id": table_id,
                "scope": scope,
                "depth": depth,
                "table": tbl,
            }
            seen_tcs: Set[int] = set()
            for r_idx, row in enumerate(tbl.rows):
                for c_idx, cell in enumerate(row.cells):
                    if id(cell._tc) in seen_tcs:
                        continue
                    seen_tcs.add(id(cell._tc))
                    seen_elements.append(cell._tc)
                    if cell.tables:
                        yield from _walk(
                            cell.tables,
                            scope="nested_table",
                            prefix=f"{table_id}.r[{r_idx}].c[{c_idx}].",
                            depth=depth + 1,
                        )
                    for sdt_idx, sdt_el in enumerate(cell._tc.findall(qn("w:sdt"))):
                        yield from _walk_sdt_tables(
                            sdt_el,
                            f"{table_id}.r[{r_idx}].c[{c_idx}].sdt[{sdt_idx}]",
                            "nested_table",
                            depth + 1,
                            cell,
                        )

    yield from _walk(doc.tables, scope="body", prefix="body.", depth=0)
    for sdt_idx, sdt_el in enumerate(doc.element.body.findall(qn("w:sdt"))):
        yield from _walk_sdt_tables(sdt_el, f"body.sdt[{sdt_idx}]", "body", 0, doc)
    for s_idx, section in enumerate(doc.sections):
        for hf_name in ("header", "first_page_header", "even_page_header", "footer", "first_page_footer", "even_page_footer"):
            hf_obj = getattr(section, hf_name, None)
            if hf_obj is None:
                continue
            try:
                # Same lazy-creation guard as the paragraph iterator: never read
                # ``.tables``/``._element`` off a linked header/footer, or python-docx
                # creates a phantom part and a ``w:headerReference`` in the body.
                if hf_obj.is_linked_to_previous:
                    continue
                if hf_obj.tables:
                    yield from _walk(hf_obj.tables, scope=hf_name, prefix=f"sec[{s_idx}].{hf_name}.", depth=0)
                for sdt_idx, sdt_el in enumerate(hf_obj._element.findall(qn("w:sdt"))):
                    yield from _walk_sdt_tables(
                        sdt_el, f"sec[{s_idx}].{hf_name}.sdt[{sdt_idx}]", hf_name, 0, hf_obj
                    )
            except Exception:
                continue


def coalesce_adjacent_runs_in_paragraph(paragraph, strip_proof_err: bool = False) -> LogicalParagraphView:
    """
    v3.0 backward-compatible entry point (fixes P0-1):
    By default (`strip_proof_err=False`), does NOT remove `<w:proofErr>` or destructively
    collapse `<w:t>` nodes. Instead, returns a non-destructive `LogicalParagraphView`
    capable of cross-run token detection and surgical replacement.
    """
    return LogicalParagraphView(paragraph._p)


def coalesce_fragmented_runs(doc, strip_proof_err: bool = False) -> Dict[str, LogicalParagraphView]:
    """
    Build non-destructive `LogicalParagraphView` instances across all document stories
    (body, nested tables, textboxes, headers, footers, footnotes, endnotes, comments).
    """
    views: Dict[str, LogicalParagraphView] = {}
    for loc, p in iter_all_document_paragraphs_with_Wait_context(doc):
        views[loc] = LogicalParagraphView(p._p)
    return views


_NEXT_UNIQUE_OOXML_SEQ = 0x1A000000


def regenerate_unique_ooxml_ids(element, existing_ids: Optional[Set[str]] = None) -> None:
    """
    Regenerate unique `w14:paraId`, `w14:textId` (0 < id < 0x80000000), and drawing
    `docPr`/`cNvPr` `id` attributes inside a cloned XML subtree.
    """
    global _NEXT_UNIQUE_OOXML_SEQ
    used = set(existing_ids) if existing_ids else set()
    root = element.getroottree().getroot() if hasattr(element, "getroottree") else element
    for node in root.iter():
        for attr in (W14_PARA_ID, W14_TEXT_ID, "id"):
            if attr in node.attrib:
                used.add(node.attrib[attr].upper())

    def _next_hex() -> str:
        global _NEXT_UNIQUE_OOXML_SEQ
        while True:
            _NEXT_UNIQUE_OOXML_SEQ = (_NEXT_UNIQUE_OOXML_SEQ + 1) % 0x7FFFFFFF
            if _NEXT_UNIQUE_OOXML_SEQ == 0:
                _NEXT_UNIQUE_OOXML_SEQ = 1
            cand = f"{_NEXT_UNIQUE_OOXML_SEQ:08X}"
            if cand not in used:
                used.add(cand)
                return cand

    def _next_int_str() -> str:
        global _NEXT_UNIQUE_OOXML_SEQ
        while True:
            _NEXT_UNIQUE_OOXML_SEQ = (_NEXT_UNIQUE_OOXML_SEQ + 1) % 0x7FFFFFFF
            if _NEXT_UNIQUE_OOXML_SEQ == 0:
                _NEXT_UNIQUE_OOXML_SEQ = 1
            cand = str(_NEXT_UNIQUE_OOXML_SEQ)
            if cand not in used:
                used.add(cand)
                return cand

    for el in element.iter():
        if W14_PARA_ID in el.attrib:
            el.set(W14_PARA_ID, _next_hex())
        if W14_TEXT_ID in el.attrib:
            el.set(W14_TEXT_ID, _next_hex())
        local_tag = el.tag.split("}")[-1] if "}" in el.tag else el.tag
        if local_tag in ("docPr", "cNvPr") and "id" in el.attrib:
            el.set("id", _next_int_str())


def sanitize_ooxml_whitespace_and_pagination(doc) -> None:
    """
    Global OOXML hygiene pass across all stories:
    1. Sets `xml:space="preserve"` on any `<w:t>` with leading/trailing/multiple spaces or tabs.
    2. Deduplicates any repeated `w14:paraId` across body, headers, footers, and notes.
    3. Removes redundant explicit page breaks immediately following a section break on empty paragraphs.
    """
    seen_para_ids: Set[str] = set()
    for _loc, p in iter_all_document_paragraphs_with_Wait_context(doc):
        p_el = p._p
        for t_el in p_el.iter(qn("w:t")):
            ensure_xml_space_preserve_on_t(t_el)
        for el in p_el.iter():
            if W14_PARA_ID in el.attrib:
                pid = el.get(W14_PARA_ID).upper()
                if pid in seen_para_ids:
                    regenerate_unique_ooxml_ids(el, existing_ids=seen_para_ids)
                    pid = el.get(W14_PARA_ID).upper()
                seen_para_ids.add(pid)

    body = doc.element.body
    prev_had_sectPr = False
    for p_el in body.findall(qn("w:p")):
        if prev_had_sectPr:
            visible_txt = "".join((t.text or "") for t in p_el.iter(qn("w:t"))).strip()
            has_drawing = bool(p_el.findall(".//" + qn("w:drawing")))
            if not visible_txt and not has_drawing:
                for br in list(p_el.findall(".//" + qn("w:br"))):
                    if br.get(qn("w:type")) == "page":
                        br.getparent().remove(br)
        pPr = p_el.find(qn("w:pPr"))
        prev_had_sectPr = pPr is not None and pPr.find(qn("w:sectPr")) is not None
