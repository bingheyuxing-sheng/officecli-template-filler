"""
Template-Driven Style Resolution & Non-Destructive Paragraph Replacement Engine (v3.0).

Integrates with `LogicalParagraphView` (P0-1) so mixed-format paragraphs and cross-run
placeholders are replaced without collapsing surrounding runs, hyperlinked nodes, or
removing `<w:proofErr>` markers.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Optional, Tuple
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

from .ooxml_utils import (
    LogicalParagraphView,
    RED_HEX_SET,
    _is_red_rgb,
    is_red_run,
    ensure_xml_space_preserve_on_run,
    ensure_xml_space_preserve_on_t,
)


def get_styles_root(paragraph):
    """
    Return the package-wide `word/styles.xml` root element, or `None`.

    Every story part (body, header, footer) shares one package, so the same lookup works no matter
    which part the paragraph lives in.
    """
    part = getattr(paragraph, "part", None)
    package = getattr(part, "package", None)
    if package is None or not hasattr(package, "iter_parts"):
        return None
    for candidate in package.iter_parts():
        if str(getattr(candidate, "partname", "")).endswith("/styles.xml"):
            return getattr(candidate, "element", None)
    return None


def _find_style_by_id(styles_root, style_id: Optional[str]):
    if styles_root is None or not style_id:
        return None
    for el in styles_root.iter(qn("w:style")):
        if (el.get(qn("w:styleId")) or "") == style_id:
            return el
    return None


def _style_chain_sz_and_font(style_el, styles_root) -> Tuple[Optional[str], Optional[str]]:
    """Walk `w:basedOn` from `style_el`, returning the first declared (font, sz)."""
    font = None
    sz_val = None
    visited = set()
    cur = style_el
    while cur is not None:
        marker = cur.get(qn("w:styleId")) or id(cur)
        if marker in visited:
            break
        visited.add(marker)
        rPr = cur.find(qn("w:rPr"))
        if rPr is not None:
            if font is None:
                rFonts = rPr.find(qn("w:rFonts"))
                if rFonts is not None:
                    font = rFonts.get(qn("w:eastAsia")) or rFonts.get(qn("w:ascii"))
            if sz_val is None:
                sz = rPr.find(qn("w:sz"))
                if sz is not None and (sz.get(qn("w:val")) or "").strip():
                    sz_val = sz.get(qn("w:val")).strip()
        based_on = cur.find(qn("w:basedOn"))
        cur = _find_style_by_id(styles_root, (based_on.get(qn("w:val")) or "").strip()) if based_on is not None else None
    return font, sz_val


def _doc_defaults_sz_and_font(styles_root) -> Tuple[Optional[str], Optional[str]]:
    """
    Read `w:docDefaults/w:rPrDefault/w:rPr`.

    This is where Word stores the real default body size (usually 21 half-points = 10.5pt or
    24 = 12pt). Named styles such as `Normal` frequently declare no `w:sz` at all, so ignoring
    document defaults made every size comparison silently resolve to `None`.
    """
    if styles_root is None:
        return None, None
    for defaults in styles_root.iter(qn("w:docDefaults")):
        rpr_default = defaults.find(qn("w:rPrDefault"))
        if rpr_default is None:
            continue
        rPr = rpr_default.find(qn("w:rPr"))
        if rPr is None:
            continue
        sz = rPr.find(qn("w:sz"))
        rFonts = rPr.find(qn("w:rFonts"))
        font = (rFonts.get(qn("w:eastAsia")) or rFonts.get(qn("w:ascii"))) if rFonts is not None else None
        sz_val = None
        if sz is not None and (sz.get(qn("w:val")) or "").strip():
            sz_val = sz.get(qn("w:val")).strip()
        return sz_val, font
    return None, None


def resolve_style_sz_and_font(
    paragraph,
    fallback_font: Optional[str] = None,
    fallback_sz: Optional[str] = None,
) -> Tuple[Optional[str], Optional[str]]:
    """
    Walk the paragraph-style inheritance chain and document defaults
    to resolve only properties that the target node does not define.
    """
    ea_font = None
    sz_val = None
    style = getattr(paragraph, "style", None)
    visited = set()
    while style is not None and id(style) not in visited:
        visited.add(id(style))
        el = getattr(style, "element", None)
        if el is not None:
            rPr = el.find(qn("w:rPr"))
            if rPr is not None:
                if ea_font is None:
                    rFonts = rPr.find(qn("w:rFonts"))
                    if rFonts is not None:
                        ea_font = rFonts.get(qn("w:eastAsia")) or rFonts.get(qn("w:ascii"))
                if sz_val is None:
                    sz = rPr.find(qn("w:sz"))
                    if sz is not None and (sz.get(qn("w:val")) or "").strip():
                        sz_val = sz.get(qn("w:val")).strip()
        style = getattr(style, "base_style", None)

    if ea_font is None or sz_val is None:
        default_sz, default_font = _doc_defaults_sz_and_font(get_styles_root(paragraph))
        if sz_val is None:
            sz_val = default_sz
        if ea_font is None:
            ea_font = default_font

    return (ea_font or fallback_font, sz_val or fallback_sz)


def resolve_run_effective_sz(run, paragraph) -> Optional[str]:
    """
    Resolve the size actually applied to `run`, in half-points, using the real cascade:
    run `w:sz` -> run character style (`w:rStyle`) -> paragraph style chain -> `w:docDefaults`.

    Comparing only explicit `w:sz` values misses every inherited drift, which is how a document
    can be regenerated wholesale at the wrong size while the QA gate still reports success.
    """
    rPr = run._r.rPr
    if rPr is not None:
        sz = rPr.find(qn("w:sz"))
        if sz is not None:
            explicit = (sz.get(qn("w:val")) or "").strip()
            if explicit:
                return explicit
        r_style = rPr.find(qn("w:rStyle"))
        if r_style is not None:
            style_id = (r_style.get(qn("w:val")) or "").strip()
            styles_root = get_styles_root(paragraph)
            style_el = _find_style_by_id(styles_root, style_id)
            if style_el is not None:
                _font, style_sz = _style_chain_sz_and_font(style_el, styles_root)
                if style_sz:
                    return style_sz
    return resolve_style_sz_and_font(paragraph)[1]


def _fonts_from_rpr(rPr) -> Tuple[Optional[str], Optional[str]]:
    """Read `(ascii/hAnsi, eastAsia)` from a run-properties element."""
    if rPr is None:
        return (None, None)
    rFonts = rPr.find(qn("w:rFonts"))
    if rFonts is None:
        return (None, None)
    ascii_font = rFonts.get(qn("w:ascii")) or rFonts.get(qn("w:hAnsi"))
    east_asia = rFonts.get(qn("w:eastAsia"))
    return (ascii_font, east_asia)


def resolve_run_effective_font(run, paragraph) -> Tuple[Optional[str], Optional[str]]:
    """
    Resolve the font actually applied to `run` as `(ascii, eastAsia)`.

    Cascade: run `w:rFonts` -> run character style chain -> paragraph style chain ->
    `w:docDefaults`. Without this, a document regenerated in the wrong font passes QA because
    only sizes were ever compared.
    """
    ascii_font = None
    east_asia = None

    rPr = run._r.rPr
    if rPr is not None:
        ascii_font, east_asia = _fonts_from_rpr(rPr)
        if ascii_font is None or east_asia is None:
            r_style = rPr.find(qn("w:rStyle"))
            style_id = (r_style.get(qn("w:val")) or "").strip() if r_style is not None else ""
            if style_id:
                styles_root = get_styles_root(paragraph)
                cur = _find_style_by_id(styles_root, style_id)
                visited = set()
                while cur is not None:
                    marker = cur.get(qn("w:styleId")) or id(cur)
                    if marker in visited:
                        break
                    visited.add(marker)
                    a, e = _fonts_from_rpr(cur.find(qn("w:rPr")))
                    if ascii_font is None:
                        ascii_font = a
                    if east_asia is None:
                        east_asia = e
                    based_on = cur.find(qn("w:basedOn"))
                    cur = (
                        _find_style_by_id(styles_root, (based_on.get(qn("w:val")) or "").strip())
                        if based_on is not None
                        else None
                    )

    if ascii_font is None or east_asia is None:
        style = getattr(paragraph, "style", None)
        visited = set()
        while style is not None and id(style) not in visited:
            visited.add(id(style))
            element = getattr(style, "element", None)
            rPr_style = element.find(qn("w:rPr")) if element is not None else None
            a, e = _fonts_from_rpr(rPr_style)
            if ascii_font is None:
                ascii_font = a
            if east_asia is None:
                east_asia = e
            style = getattr(style, "base_style", None)

    if ascii_font is None or east_asia is None:
        styles_root = get_styles_root(paragraph)
        if styles_root is not None:
            for defaults in styles_root.iter(qn("w:docDefaults")):
                rpr_default = defaults.find(qn("w:rPrDefault"))
                if rpr_default is None:
                    continue
                a, e = _fonts_from_rpr(rpr_default.find(qn("w:rPr")))
                if ascii_font is None:
                    ascii_font = a
                if east_asia is None:
                    east_asia = e
                break

    return (ascii_font, east_asia)


# Alias for backward compatibility
_resolve_style_sz_and_font = resolve_style_sz_and_font


def normalize_rPr_fonts_and_strip_red(
    rPr_element,
    strip_bold: bool = False,
    default_font: Optional[str] = None,
    default_sz: Optional[str] = None,
    lock_all_slots_to_ea: bool = True,
):
    """
    Deep-copy an `rPr` element, strip red placeholder `w:color`, optionally strip bold,
    and synchronize font slots (`ascii`, `hAnsi`, `eastAsia`, `cs`) and `w:bCs`/`w:szCs`
    when a resolved template font/size is present.
    """
    cloned = deepcopy(rPr_element) if rPr_element is not None else OxmlElement("w:rPr")

    color = cloned.find(qn("w:color"))
    if color is not None and _is_red_rgb(color.get(qn("w:val")) or ""):
        cloned.remove(color)

    if strip_bold:
        for b_tag in ("w:b", "w:bCs"):
            b_el = cloned.find(qn(b_tag))
            if b_el is not None:
                cloned.remove(b_el)
    else:
        b_el = cloned.find(qn("w:b"))
        if b_el is not None:
            b_val = b_el.get(qn("w:val"))
            if b_val not in ("0", "false", "none"):
                bCs = cloned.find(qn("w:bCs"))
                if bCs is None:
                    bCs = OxmlElement("w:bCs")
                    cloned.append(bCs)
                if b_val is not None:
                    bCs.set(qn("w:val"), b_val)

    rFonts = cloned.find(qn("w:rFonts"))
    ea_font = (
        (rFonts.get(qn("w:eastAsia")) if rFonts is not None else None)
        or default_font
        or (rFonts.get(qn("w:ascii")) if rFonts is not None else None)
    )
    if ea_font:
        if rFonts is None:
            rFonts = OxmlElement("w:rFonts")
            cloned.insert(0, rFonts)
        en_font = ea_font if lock_all_slots_to_ea else (rFonts.get(qn("w:ascii")) or ea_font)
        rFonts.set(qn("w:eastAsia"), ea_font)
        rFonts.set(qn("w:ascii"), en_font)
        rFonts.set(qn("w:hAnsi"), en_font)
        rFonts.set(qn("w:cs"), en_font)
        rFonts.set(qn("w:hint"), "eastAsia")

    sz = cloned.find(qn("w:sz"))
    if sz is None and default_sz is not None:
        sz = OxmlElement("w:sz")
        sz.set(qn("w:val"), str(default_sz))
        cloned.append(sz)
    if sz is not None:
        sz_val = sz.get(qn("w:val")) or (str(default_sz) if default_sz is not None else None)
        if sz_val is not None:
            szCs = cloned.find(qn("w:szCs"))
            if szCs is None:
                szCs = OxmlElement("w:szCs")
                cloned.append(szCs)
            szCs.set(qn("w:val"), sz_val)

    return cloned


def fill_paragraph_strict_style(
    paragraph,
    new_text: str,
    placeholder_run=None,
    placeholder_token: Optional[str] = None,
) -> None:
    """
    Replace text in `paragraph` while preserving template formatting (v3.0):
    1. If `placeholder_token` is supplied (e.g. `"{{project_name}}"`), uses `LogicalParagraphView`
       to locate and surgically replace the token even if split across multiple `<w:r>` runs
       or separated by `<w:proofErr>` markers—without touching surrounding runs!
    2. If `placeholder_run` is supplied (or mixed red runs exist), replaces only the target run(s)
       while keeping prefix/suffix runs and non-run children intact.
    3. For uniform paragraphs, updates the primary text run in place (preserving any non-text
       elements such as bookmarks/proofErr/hyperlinks when possible).
    """
    inh_font, inh_sz = resolve_style_sz_and_font(paragraph, fallback_font=None, fallback_sz=None)

    # Path A: Surgical cross-run token replacement via LogicalParagraphView (P0-1)
    if placeholder_token:
        view = LogicalParagraphView(paragraph._p)
        idx = view.logical_text.find(placeholder_token)
        if idx != -1:
            view.replace_span(
                idx,
                idx + len(placeholder_token),
                str(new_text),
                strip_red_color=True,
                rPr_normalizer=lambda rPr: normalize_rPr_fonts_and_strip_red(
                    rPr, strip_bold=False, default_font=inh_font, default_sz=inh_sz
                ),
            )
            return

    runs = list(paragraph.runs)
    target_runs = (
        [placeholder_run]
        if placeholder_run is not None
        else [r for r in runs if is_red_run(r) and r.text.strip()]
    )
    target_runs = [r for r in target_runs if r in runs and r.text.strip()]
    non_target_runs = [r for r in runs if r not in target_runs and r.text.strip()]

    # Path B: Mixed-format paragraph with explicit placeholder_run or red placeholder runs
    if target_runs and non_target_runs:
        t_indexes = [i for i, r in enumerate(runs) if r in target_runs]
        first_idx = min(t_indexes)
        last_idx = max(t_indexes)
        prefix_text = "".join(r.text for r in runs[:first_idx] if r not in target_runs)
        suffix_text = "".join(r.text for r in runs[last_idx + 1 :] if r not in target_runs)

        val_text = new_text
        if prefix_text and val_text.startswith(prefix_text):
            val_text = val_text[len(prefix_text) :]
        if suffix_text and val_text.endswith(suffix_text) and len(val_text) >= len(suffix_text):
            val_text = val_text[: len(val_text) - len(suffix_text)]

        if placeholder_run is None and new_text.strip() == (prefix_text + suffix_text).strip():
            for r in target_runs:
                r._r.getparent().remove(r._r)
            for r in list(paragraph.runs):
                cleaned = normalize_rPr_fonts_and_strip_red(
                    r._r.rPr, strip_bold=False, default_font=inh_font, default_sz=inh_sz
                )
                if r._r.rPr is not None:
                    r._r.remove(r._r.rPr)
                r._r.insert(0, cleaned)
                ensure_xml_space_preserve_on_run(r)
            return

        first_target = target_runs[0]
        cleaned_rPr = normalize_rPr_fonts_and_strip_red(
            first_target._r.rPr, strip_bold=False, default_font=inh_font, default_sz=inh_sz
        )
        t_nodes = first_target._r.findall(qn("w:t"))
        if t_nodes:
            t_nodes[0].text = val_text
            ensure_xml_space_preserve_on_t(t_nodes[0])
            for extra_t in t_nodes[1:]:
                first_target._r.remove(extra_t)
        else:
            first_target.text = val_text
            ensure_xml_space_preserve_on_run(first_target)

        if first_target._r.rPr is not None:
            first_target._r.remove(first_target._r.rPr)
        first_target._r.insert(0, deepcopy(cleaned_rPr))

        for extra_r in target_runs[1:]:
            extra_r._r.getparent().remove(extra_r._r)

        for r in list(paragraph.runs):
            if r is not first_target:
                cleaned_other = normalize_rPr_fonts_and_strip_red(
                    r._r.rPr, strip_bold=False, default_font=inh_font, default_sz=inh_sz
                )
                if r._r.rPr is not None:
                    r._r.remove(r._r.rPr)
                r._r.insert(0, cleaned_other)
                ensure_xml_space_preserve_on_run(r)

        if not suffix_text:
            pPr = paragraph._p.get_or_add_pPr()
            old_mark = pPr.find(qn("w:rPr"))
            if old_mark is not None:
                pPr.remove(old_mark)
            pPr.append(deepcopy(cleaned_rPr))
        return

    # Path C: Uniform / single-style paragraph
    donor_rPr = None
    for r in runs:
        if r._r.rPr is not None and not is_red_run(r):
            donor_rPr = normalize_rPr_fonts_and_strip_red(
                r._r.rPr, default_font=inh_font, default_sz=inh_sz
            )
            break
    if donor_rPr is None:
        for r in runs:
            if r._r.rPr is not None:
                donor_rPr = normalize_rPr_fonts_and_strip_red(
                    r._r.rPr, default_font=inh_font, default_sz=inh_sz
                )
                break
    if donor_rPr is None and paragraph._p.pPr is not None:
        mark_rPr = paragraph._p.pPr.find(qn("w:rPr"))
        if mark_rPr is not None:
            donor_rPr = normalize_rPr_fonts_and_strip_red(
                mark_rPr, default_font=inh_font, default_sz=inh_sz
            )
    if donor_rPr is None:
        donor_rPr = normalize_rPr_fonts_and_strip_red(
            None, default_font=inh_font, default_sz=inh_sz
        )

    pPr = paragraph._p.get_or_add_pPr()
    old_mark = pPr.find(qn("w:rPr"))
    if old_mark is not None:
        pPr.remove(old_mark)
    pPr.append(deepcopy(donor_rPr))

    # Preserve first `<w:t>` node attributes if present instead of wiping all runs blindly
    if runs:
        anchor_run = runs[0]
        t_nodes = anchor_run._r.findall(qn("w:t"))
        if t_nodes:
            t_nodes[0].text = str(new_text)
            ensure_xml_space_preserve_on_t(t_nodes[0])
            for extra_t in t_nodes[1:]:
                anchor_run._r.remove(extra_t)
        else:
            anchor_run.text = str(new_text)
            ensure_xml_space_preserve_on_run(anchor_run)
        if anchor_run._r.rPr is not None:
            anchor_run._r.remove(anchor_run._r.rPr)
        anchor_run._r.insert(0, deepcopy(donor_rPr))
        for r in runs[1:]:
            # Only remove plain text runs; never remove runs containing drawings or fields
            if not r._r.xpath(".//w:drawing | .//w:fldChar | .//w:instrText"):
                r._r.getparent().remove(r._r)
    else:
        run = paragraph.add_run(str(new_text))
        run._r.insert(0, deepcopy(donor_rPr))
        ensure_xml_space_preserve_on_run(run)


def replace_red_placeholder_in_mixed_paragraph(paragraph, replacement_text: str) -> None:
    fill_paragraph_strict_style(paragraph, replacement_text)
