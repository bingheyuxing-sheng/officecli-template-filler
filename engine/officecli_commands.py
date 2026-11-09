# -*- coding: utf-8 -*-
"""Builders for OfficeCLI batch commands.

Engines describe *what* should change; this module turns a DocumentSpec location
and a formatting profile into the ``set`` / ``add`` items OfficeCLI executes.
Nothing here touches OOXML. Keeping the builders pure makes the mutation plans
testable without an OfficeCLI binary.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional

from docx.oxml.ns import qn

from .ooxml_utils import is_red_run
from .style_engine import resolve_run_effective_font, resolve_run_effective_sz
from .table_engine import classify_cell_structure, get_unique_row_cells


def set_command(path: str, props: Mapping[str, Any]) -> Dict[str, Any]:
    """One ``set`` item. Empty property maps are dropped by the caller."""
    return {"command": "set", "path": path, "props": dict(props)}


def add_comment_command(
    path: str,
    text: str,
    *,
    author: str,
    date: Optional[str] = None,
    run_start: int = 0,
) -> Dict[str, Any]:
    props: Dict[str, Any] = {
        "author": author,
        "text": text,
        "runStart": int(run_start),
    }
    if date:
        props["date"] = date
    return {
        "command": "add",
        "parent": path,
        "type": "comment",
        "props": props,
    }


def tracked_replace_command(
    path: str,
    old_text: str,
    new_text: str,
    *,
    author: str,
    date: Optional[str] = None,
) -> Dict[str, Any]:
    """Find/replace scoped to one path; OfficeCLI emits ``w:del`` + ``w:ins``."""
    props: Dict[str, Any] = {
        "find": old_text,
        "replace": new_text,
        "revision.author": author,
    }
    if date:
        props["revision.date"] = date
    return {"command": "set", "path": path, "props": props}


def revision_action_command(revision_id: Any, action: str) -> Dict[str, Any]:
    if action not in ("accept", "reject"):
        raise ValueError("unsupported revision action: %r" % (action,))
    return {
        "command": "set",
        "path": "/revision[@id={}]".format(revision_id),
        "props": {"revision.action": action},
    }


def _twips(value: Any) -> Optional[int]:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _half_points_to_pt(value: Any) -> Optional[str]:
    try:
        number = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    return ("%g" % (number / 2.0)) + "pt"


def paragraph_props(profile: Mapping[str, Any]) -> Dict[str, Any]:
    """Map a REPAIR/REVIEW paragraph profile to OfficeCLI paragraph properties."""
    props: Dict[str, Any] = {}
    if profile.get("jc"):
        props["align"] = str(profile["jc"])

    before = _twips(profile.get("spacing_before"))
    after = _twips(profile.get("spacing_after"))
    if before is not None:
        props["spaceBefore"] = before
    if after is not None:
        props["spaceAfter"] = after

    line = _twips(profile.get("spacing_line"))
    rule = profile.get("spacing_lineRule")
    if line is not None:
        if rule in (None, "", "auto"):
            props["lineSpacing"] = "%gx" % (line / 240.0)
        else:
            props["lineSpacing"] = "%gpt" % (line / 20.0)
            props["lineRule"] = str(rule)

    first_chars = _twips(profile.get("first_line_chars"))
    first = _twips(profile.get("first_line_indent"))
    if first_chars is not None:
        props["firstLineChars"] = first_chars
    elif first is not None:
        props["firstLineIndent"] = first

    left = _twips(profile.get("left_indent"))
    if left is not None:
        props["indent"] = left

    return props


def run_props(
    profile: Mapping[str, Any],
    run,
    paragraph=None,
    *,
    strip_red: bool = False,
) -> Dict[str, Any]:
    """Map a paragraph profile to the formatting properties of one run."""
    props: Dict[str, Any] = {}
    font_ea = profile.get("font_east_asia")
    font_ascii = profile.get("font_ascii")
    if font_ea:
        props["font.ea"] = str(font_ea)
    if font_ascii:
        props["font.latin"] = str(font_ascii)
    size = _half_points_to_pt(profile.get("sz_val"))
    if size:
        props["size"] = size
    if strip_red and is_red_run(run, paragraph):
        # OfficeCLI writes <w:color w:val="auto"/> rather than deleting the node;
        # the visible result is the same and the change stays on the CLI path.
        props["color"] = "auto"
    return props


def _with_revision(
    props: Mapping[str, Any],
    *,
    author: Optional[str],
    date: Optional[str],
) -> Dict[str, Any]:
    result = dict(props)
    if author:
        result["revision.author"] = author
        if date:
            result["revision.date"] = date
    return result


def paragraph_format_commands(
    path: str,
    paragraph,
    profile: Mapping[str, Any],
    *,
    author: Optional[str] = None,
    date: Optional[str] = None,
    strip_red: bool = False,
    runs: bool = True,
) -> List[Dict[str, Any]]:
    """Restore one paragraph profile through paragraph- and run-level ``set`` items.

    Paragraph props (alignment/spacing/indent) are one ``set`` on the paragraph.
    Font/size live on runs, so each run gets its own ``set``; OfficeCLI records a
    ``w:rPrChange`` per run when ``revision.author`` is present.
    """
    commands: List[Dict[str, Any]] = []
    p_props = _with_revision(paragraph_props(profile), author=author, date=date)
    if p_props:
        commands.append(set_command(path, p_props))
    if not runs:
        return commands
    for index, run in enumerate(getattr(paragraph, "runs", []) or [], start=1):
        if not (run.text or "").strip():
            continue
        r_props = run_props(profile, run, paragraph, strip_red=strip_red)
        if not r_props:
            continue
        commands.append(
            set_command(
                "%s/r[%d]" % (path, index),
                _with_revision(r_props, author=author, date=date),
            )
        )
    return commands


def _row_height_props(row) -> Dict[str, Any]:
    tr_pr = row._tr.find(qn("w:trPr"))
    height = tr_pr.find(qn("w:trHeight")) if tr_pr is not None else None
    if height is None:
        return {}
    value = _twips(height.get(qn("w:val")))
    if value is None:
        return {}
    if (height.get(qn("w:hRule")) or "") == "exact":
        return {"height.exact": value}
    return {"height": value}


def _row_flag_props(row) -> Dict[str, Any]:
    tr_pr = row._tr.find(qn("w:trPr"))
    if tr_pr is None:
        return {}
    props: Dict[str, Any] = {}
    if tr_pr.find(qn("w:cantSplit")) is not None:
        props["cantSplit"] = True
    if tr_pr.find(qn("w:tblHeader")) is not None:
        props["header"] = True
    return props


def _cell_fill(cell) -> Optional[str]:
    tc_pr = cell._tc.tcPr
    shd = tc_pr.find(qn("w:shd")) if tc_pr is not None else None
    if shd is None:
        return None
    return shd.get(qn("w:fill")) or shd.get(qn("w:color"))


def _cell_valign(cell) -> Optional[str]:
    tc_pr = cell._tc.tcPr
    node = tc_pr.find(qn("w:vAlign")) if tc_pr is not None else None
    return node.get(qn("w:val")) if node is not None else None


def _cell_width(cell) -> Optional[str]:
    tc_pr = cell._tc.tcPr
    node = tc_pr.find(qn("w:tcW")) if tc_pr is not None else None
    if node is None:
        return None
    width = node.get(qn("w:w"))
    kind = node.get(qn("w:type")) or "dxa"
    if width is None:
        return None
    if kind == "dxa":
        return "%sdxa" % width
    if kind == "pct":
        return "%s%%" % (int(float(width)) / 50.0)
    return None


def _cell_margin_props(cell) -> Dict[str, Any]:
    tc_pr = cell._tc.tcPr
    margins = tc_pr.find(qn("w:tcMar")) if tc_pr is not None else None
    if margins is None:
        return {}
    props: Dict[str, Any] = {}
    for side in ("top", "left", "bottom", "right"):
        node = margins.find(qn("w:%s" % side))
        if node is None:
            continue
        value = _twips(node.get(qn("w:w")))
        if value is not None:
            props["padding.%s" % side] = value
    return props


_BORDER_SIDE = {
    "top": "border.top",
    "left": "border.left",
    "bottom": "border.bottom",
    "right": "border.right",
    "insideH": "border.horizontal",
    "insideV": "border.vertical",
}


def _border_value(node) -> Optional[str]:
    if node is None:
        return None
    style = node.get(qn("w:val")) or "single"
    size = node.get(qn("w:sz")) or "4"
    color = node.get(qn("w:color")) or "auto"
    return "%s;%s;%s" % (style, size, color)


def _table_props(reference_tbl) -> Dict[str, Any]:
    tbl_pr = reference_tbl._tbl.find(qn("w:tblPr"))
    props: Dict[str, Any] = {}
    if tbl_pr is None:
        return props

    style = tbl_pr.find(qn("w:tblStyle"))
    if style is not None and style.get(qn("w:val")):
        props["style"] = style.get(qn("w:val"))
    layout = tbl_pr.find(qn("w:tblLayout"))
    if layout is not None and layout.get(qn("w:type")):
        props["layout"] = layout.get(qn("w:type"))
    jc = tbl_pr.find(qn("w:jc"))
    if jc is not None and jc.get(qn("w:val")):
        props["align"] = jc.get(qn("w:val"))
    ind = tbl_pr.find(qn("w:tblInd"))
    if ind is not None and _twips(ind.get(qn("w:w"))) is not None:
        props["indent"] = _twips(ind.get(qn("w:w")))
    spacing = tbl_pr.find(qn("w:tblCellSpacing"))
    if spacing is not None and _twips(spacing.get(qn("w:w"))) is not None:
        props["cellSpacing"] = _twips(spacing.get(qn("w:w")))

    grid = reference_tbl._tbl.find(qn("w:tblGrid"))
    total = 0
    if grid is not None:
        for col in grid.findall(qn("w:gridCol")):
            width = _twips(col.get(qn("w:w")))
            if width:
                total += width
    if total:
        props["width"] = total

    borders = tbl_pr.find(qn("w:tblBorders"))
    if borders is not None:
        for side, prop_name in _BORDER_SIDE.items():
            value = _border_value(borders.find(qn("w:%s" % side)))
            if value:
                props[prop_name] = value

    margins = tbl_pr.find(qn("w:tblCellMar"))
    if margins is not None:
        values = {
            side: _twips(margins.find(qn("w:%s" % side)).get(qn("w:w")))
            if margins.find(qn("w:%s" % side)) is not None
            else None
            for side in ("top", "left", "bottom", "right")
        }
        if values and len({value for value in values.values() if value is not None}) == 1:
            props["padding"] = next(value for value in values.values() if value is not None)
    return props


def _donor_run_props(reference_paragraph, run_index: int) -> Dict[str, Any]:
    donor_runs = reference_paragraph.runs
    if not donor_runs:
        return {}
    donor = donor_runs[min(run_index, len(donor_runs) - 1)]
    if not (donor.text or "").strip():
        return {}
    ascii_font, east_asia = resolve_run_effective_font(donor, reference_paragraph)
    size = resolve_run_effective_sz(donor, reference_paragraph)
    props: Dict[str, Any] = {}
    if east_asia:
        props["font.ea"] = east_asia
    if ascii_font:
        props["font.latin"] = ascii_font
    size_pt = _half_points_to_pt(size)
    if size_pt:
        props["size"] = size_pt
    if donor.bold is not None:
        props["bold"] = bool(donor.bold)
    return props


def table_format_commands(
    path: str,
    target_table,
    reference_table,
    *,
    author: Optional[str] = None,
    date: Optional[str] = None,
    include_text_styles: bool = True,
) -> List[Dict[str, Any]]:
    """Restore a table's formatting from a reference table through OfficeCLI ``set``."""
    commands: List[Dict[str, Any]] = []
    props = _with_revision(_table_props(reference_table), author=author, date=date)
    if props:
        commands.append(set_command(path, props))

    for row_index, reference_row in enumerate(reference_table.rows):
        if row_index >= len(target_table.rows):
            break
        row_props = _with_revision(
            {**_row_height_props(reference_row), **_row_flag_props(reference_row)},
            author=author,
            date=date,
        )
        if row_props:
            commands.append(
                set_command("%s/tr[%d]" % (path, row_index + 1), row_props)
            )

    for row_index, reference_row in enumerate(reference_table.rows):
        if row_index >= len(target_table.rows):
            break
        target_row = target_table.rows[row_index]
        reference_cells = get_unique_row_cells(reference_row)
        target_cells = get_unique_row_cells(target_row)
        for cell_index, (target_cell, reference_cell) in enumerate(
            zip(target_cells, reference_cells, strict=False), start=1
        ):
            cell_path = "%s/tr[%d]/tc[%d]" % (path, row_index + 1, cell_index)
            cell_props: Dict[str, Any] = {}
            width = _cell_width(reference_cell)
            if width:
                cell_props["width"] = width
            fill = _cell_fill(reference_cell)
            if fill:
                cell_props["fill"] = fill
            valign = _cell_valign(reference_cell)
            if valign:
                cell_props["valign"] = valign
            cell_props.update(_cell_margin_props(reference_cell))
            if cell_props:
                commands.append(
                    set_command(
                        cell_path,
                        _with_revision(cell_props, author=author, date=date),
                    )
                )

            if not include_text_styles:
                continue
            if str(classify_cell_structure(target_cell)) in (
                "nested_table",
                "image_cell",
                "sdt_control",
                "field_code",
                "unknown_complex",
            ):
                continue
            for p_index, (target_p, reference_p) in enumerate(
                zip(target_cell.paragraphs, reference_cell.paragraphs, strict=False),
                start=1,
            ):
                for r_index, target_run in enumerate(target_p.runs, start=1):
                    if not (target_run.text or "").strip():
                        continue
                    run_props_map = _donor_run_props(reference_p, r_index - 1)
                    if not run_props_map:
                        continue
                    commands.append(
                        set_command(
                            "%s/p[%d]/r[%d]" % (cell_path, p_index, r_index),
                            _with_revision(
                                run_props_map, author=author, date=date
                            ),
                        )
                    )
    return commands


def section_setup_commands(
    path: str,
    reference_signature: Mapping[str, Any],
) -> List[Dict[str, Any]]:
    """Map a python-docx section signature (EMU) to OfficeCLI section lengths."""
    props: Dict[str, Any] = {}
    mapping = {
        "page_width": "pageWidth",
        "page_height": "pageHeight",
        "top_margin": "marginTop",
        "bottom_margin": "marginBottom",
        "left_margin": "marginLeft",
        "right_margin": "marginRight",
        "header_distance": "marginHeader",
        "footer_distance": "marginFooter",
    }
    for key, prop_name in mapping.items():
        value = reference_signature.get(key)
        if value is None:
            continue
        # python-docx exposes EMU; OfficeCLI accepts raw twips.
        props[prop_name] = int(round(float(value) / 635.0))
    orientation = reference_signature.get("orientation")
    if orientation is not None:
        props["orientation"] = "landscape" if int(orientation) == 1 else "portrait"
    return [set_command(path, props)] if props else []


__all__ = [
    "add_comment_command",
    "paragraph_format_commands",
    "paragraph_props",
    "revision_action_command",
    "run_props",
    "section_setup_commands",
    "set_command",
    "table_format_commands",
    "tracked_replace_command",
]
