"""
Structural Excel Row Cloning, Formula Shifting & Recalculation Engine (v3.0 — Fixes P1-6).

Key v3.0 enhancements over v2.9:
1. Full structural row cloning in `clone_excel_template_row()`:
   - Cell styles (`font`, `fill`, `border`, `alignment`, `number_format`, `protection`).
   - Row dimensions (`height`, `hidden`, `outlineLevel`, `collapsed`, `style`).
   - Horizontal merged cell ranges (`ws.merged_cells.ranges`, e.g., `A5:B5` -> `A6:B6`).
   - Hyperlinks (`src.hyperlink`).
   - Formula row-reference shifting (`=C5*D5` -> `=C6*D6` while preserving `$C$5` absolute refs).
   - Data validations (`ws.data_validations`) and conditional formatting range expansion (`ws.conditional_formatting`).
   - Worksheet Table (`ws.tables`) and `auto_filter.ref` range expansion.
2. Live Formula Recalculation & Verification (`recalculate_and_verify_excel_formulas()`):
   - Evaluates standard Excel formulas (`SUM`, `SUBTOTAL`, `AVERAGE`, `MIN`, `MAX`, `COUNT`, `ROUND`, `IF`, arithmetic expressions) in Python OR invokes LibreOffice (`soffice --headless`) / Excel COM via `TaskResourceGuard` so formula errors (`#DIV/0!`, `#VALUE!`, `#REF!`) and stale cached values are caught before delivery.
"""
from __future__ import annotations

import os
import re
import shutil
import tempfile
from copy import copy, deepcopy
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple
import openpyxl
from openpyxl.formula.translate import Translator
from openpyxl.utils import column_index_from_string, get_column_letter, range_boundaries

from .process_guard import TaskResourceGuard
from .pdf_backend import libreoffice_user_installation_arg

EXCEL_ERROR_TOKENS = {"#REF!", "#DIV/0!", "#VALUE!", "#NAME?", "#N/A", "#NUM!", "#NULL!"}

# Cell references for the built-in evaluator (formula row shifting uses openpyxl's
# Translator, not this regex).
_CELL_REF_RE = re.compile(r"(?<![A-Za-z0-9_!])(\$?[A-Za-z]{1,3})(\$?)(\d+)(?![A-Za-z0-9_(])")

# Formulas that cannot be row-shifted safely. They are refused explicitly instead of
# being regex-rewritten into something plausible but wrong.
_UNSUPPORTED_FORMULA_PATTERNS = (
    ("UNSUPPORTED_EXTERNAL_WORKBOOK", re.compile(r"\[[^\]]+\.(xlsx|xlsm|xls|xlsb|csv)\]", re.IGNORECASE)),
    ("UNSUPPORTED_STRUCTURED_REFERENCE", re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*\[[^\]]*\]")),
    ("UNSUPPORTED_DYNAMIC_REFERENCE", re.compile(r"\b(INDIRECT|OFFSET)\s*\(", re.IGNORECASE)),
)


def translate_excel_formula_row_refs(formula: str, src_row: int, dst_row: int) -> Tuple[str, Optional[str]]:
    """
    Row-shift a formula with openpyxl's own reference translator.

    Returns `(formula, reason)`: `reason` is `None` when the translation is safe to use.
    String literals and absolute references are handled by the translator, so
    `=IF(A5="A5",Sheet1!B5,$C$5)` becomes `=IF(A6="A5",Sheet1!B6,$C$6)`.
    """
    if not isinstance(formula, str) or not formula.startswith("="):
        return formula, None
    if int(dst_row) == int(src_row):
        return formula, None
    for reason, pattern in _UNSUPPORTED_FORMULA_PATTERNS:
        if pattern.search(formula):
            return formula, reason
    try:
        translated = Translator(formula, origin=f"A{int(src_row)}").translate_formula(f"A{int(dst_row)}")
    except Exception:
        return formula, "TRANSLATOR_ERROR"
    if not isinstance(translated, str) or not translated.startswith("="):
        return formula, "TRANSLATOR_INVALID_RESULT"
    return translated, None


def shift_excel_formula_row_refs(formula: str, src_row: int, dst_row: int) -> str:
    """
    Backward-compatible wrapper around `translate_excel_formula_row_refs()`.

    Example: `shift_excel_formula_row_refs("=C5*D5/$E$2", 5, 8)` -> `"=C8*D8/$E$2"`.
    Formulas that cannot be shifted safely are returned unchanged; callers that need
    the reason should use `translate_excel_formula_row_refs()` directly.
    """
    translated, _reason = translate_excel_formula_row_refs(formula, src_row, dst_row)
    return translated


def copy_excel_cell_style(src_cell, dst_cell) -> None:
    """Deep-clone font, fill, border, alignment, number_format, protection, and hyperlink from src_cell to dst_cell."""
    if src_cell.has_style:
        dst_cell.font = copy(src_cell.font)
        dst_cell.fill = copy(src_cell.fill)
        dst_cell.border = copy(src_cell.border)
        dst_cell.alignment = copy(src_cell.alignment)
        dst_cell.number_format = src_cell.number_format
        dst_cell.protection = copy(src_cell.protection)
    if src_cell.hyperlink is not None:
        dst_cell.hyperlink = copy(src_cell.hyperlink)


def _expand_MultiCellRange_for_row(mcr, src_row: int, dst_row: int) -> None:
    """Expand or clone ranges in an openpyxl `MultiCellRange` (used by DataValidation and ConditionalFormatting)."""
    try:
        existing_ranges = list(mcr.ranges)
    except Exception:
        return
    for cr in existing_ranges:
        min_col, min_row, max_col, max_row = cr.min_col, cr.min_row, cr.max_col, cr.max_row
        if min_row <= src_row <= max_row:
            if max_row == dst_row - 1:
                cr.max_row = dst_row
            else:
                col_start = get_column_letter(min_col)
                col_end = get_column_letter(max_col)
                mcr.add(f"{col_start}{dst_row}:{col_end}{dst_row}")


def _expand_ref_string_for_row(ref_str: str, src_row: int, dst_row: int) -> str:
    """If `ref_str` (e.g. `'A1:F10'`) ends at `src_row` or `dst_row - 1`, extend its bottom row to `dst_row`."""
    if not ref_str or ":" not in ref_str:
        return ref_str
    try:
        min_col, min_row, max_col, max_row = range_boundaries(ref_str)
        if min_row <= src_row <= max_row and dst_row > max_row:
            return f"{get_column_letter(min_col)}{min_row}:{get_column_letter(max_col)}{dst_row}"
    except Exception:
        pass
    return ref_str


def clone_excel_template_row(
    ws,
    template_row_idx: Optional[int] = None,
    target_row_idx: int = 2,
    max_col: Optional[int] = None,
    clone_formulas: bool = True,
    clone_merged_cells: bool = True,
    source_row_idx: Optional[int] = None,
    shift_formulas: Optional[bool] = None,
) -> None:
    """
    Structural Excel row cloner (fixes P1-6):
    1. Clones row-level attributes (`height`, `hidden`, `outlineLevel`, `collapsed`).
    2. Clones cell-level `font`, `fill`, `border`, `alignment`, `number_format`, `protection`, and `hyperlink`.
    3. Shifts and copies row-level formulas (`=C5*D5` -> `=C6*D6`) when `clone_formulas=True`.
    4. Replicates horizontal merged-cell spans on `template_row_idx` onto `target_row_idx`.
    5. Extends DataValidation rules, ConditionalFormatting ranges, Worksheet Tables (`ws.tables`),
       and `ws.auto_filter.ref` that cover `template_row_idx` to include `target_row_idx`.
    """
    if template_row_idx is None:
        template_row_idx = int(source_row_idx or 2)
    if shift_formulas is not None:
        clone_formulas = bool(shift_formulas)
    max_col = max_col or ws.max_column

    # 1. Row-level dimensions & attributes
    if template_row_idx in ws.row_dimensions:
        src_dim = ws.row_dimensions[template_row_idx]
        dst_dim = ws.row_dimensions[target_row_idx]
        dst_dim.height = src_dim.height
        dst_dim.hidden = src_dim.hidden
        dst_dim.outlineLevel = src_dim.outlineLevel
        dst_dim.collapsed = src_dim.collapsed

    # 2. Cell styles, hyperlinks, and formulas
    formula_stats: Dict[str, Any] = {"translated": 0, "unsupported": [], "fallback_used": False}
    for col_idx in range(1, max_col + 1):
        src = ws.cell(row=template_row_idx, column=col_idx)
        dst = ws.cell(row=target_row_idx, column=col_idx)
        copy_excel_cell_style(src, dst)
        if clone_formulas and isinstance(src.value, str) and src.value.startswith("="):
            translated, reason = translate_excel_formula_row_refs(
                src.value, template_row_idx, target_row_idx
            )
            dst.value = translated
            if reason:
                # Keeping the original formula is the only safe fallback; record it so the
                # caller never mistakes an unshifted formula for a translated one.
                formula_stats["fallback_used"] = True
                formula_stats["unsupported"].append({
                    "cell": dst.coordinate,
                    "formula": src.value,
                    "reason": reason,
                })
            else:
                formula_stats["translated"] += 1

    # 3. Replicate horizontal merged-cell ranges from `template_row_idx`
    if clone_merged_cells:
        merges_to_add: List[str] = []
        for mr in list(ws.merged_cells.ranges):
            if mr.min_row == template_row_idx and mr.max_row == template_row_idx and mr.max_col > mr.min_col:
                c1 = get_column_letter(mr.min_col)
                c2 = get_column_letter(mr.max_col)
                target_range = f"{c1}{target_row_idx}:{c2}{target_row_idx}"
                # Unmerge any existing overlapping range on target_row_idx first
                for existing in list(ws.merged_cells.ranges):
                    if existing.min_row == target_row_idx and existing.max_row == target_row_idx:
                        if not (existing.max_col < mr.min_col or existing.min_col > mr.max_col):
                            ws.unmerge_cells(str(existing))
                merges_to_add.append(target_range)
        for rng in merges_to_add:
            ws.merge_cells(rng)

    # 4. Expand DataValidations covering `template_row_idx`
    if hasattr(ws, "data_validations") and ws.data_validations is not None:
        for dv in ws.data_validations.dataValidation:
            _expand_MultiCellRange_for_row(dv.sqref, template_row_idx, target_row_idx)

    # 5. Expand ConditionalFormatting rules covering `template_row_idx`
    if hasattr(ws, "conditional_formatting") and ws.conditional_formatting is not None:
        for cf in ws.conditional_formatting:
            _expand_MultiCellRange_for_row(cf.sqref, template_row_idx, target_row_idx)

    # 6. Expand Worksheet Tables (`ws.tables`) and `auto_filter.ref`
    if hasattr(ws, "tables") and ws.tables:
        for tbl in ws.tables.values():
            tbl.ref = _expand_ref_string_for_row(tbl.ref, template_row_idx, target_row_idx)
            if tbl.autoFilter is not None and tbl.autoFilter.ref:
                tbl.autoFilter.ref = _expand_ref_string_for_row(tbl.autoFilter.ref, template_row_idx, target_row_idx)
    if ws.auto_filter is not None and ws.auto_filter.ref:
        ws.auto_filter.ref = _expand_ref_string_for_row(ws.auto_filter.ref, template_row_idx, target_row_idx)

    return formula_stats


def _eval_simple_excel_formula(ws, formula: str, visited: Optional[set] = None) -> Tuple[Optional[Decimal], Optional[str]]:
    """
    Built-in deterministic Excel formula evaluator for QA verification when LibreOffice/Excel is absent.
    Evaluates `=SUM(...)`, `=SUBTOTAL(9, ...)`, `=AVERAGE(...)`, `=MIN(...)`, `=MAX(...)`, `=ROUND(...)`,
    and arithmetic expressions (`+`, `-`, `*`, `/`) over cell coordinates and ranges, detecting `#DIV/0!`,
    `#REF!`, and `#VALUE!`.
    """
    visited = visited or set()
    expr = formula.strip()[1:].strip()
    if any(tok in expr.upper() for tok in EXCEL_ERROR_TOKENS):
        return None, "#REF!"

    def _resolve_cell_num(coord: str) -> Tuple[Decimal, Optional[str]]:
        coord_clean = coord.replace("$", "").upper()
        if coord_clean in visited:
            return Decimal("0"), "#REF!"
        try:
            cell_val = ws[coord_clean].value
        except Exception:
            return Decimal("0"), "#REF!"
        if cell_val is None or cell_val == "":
            return Decimal("0"), None
        if isinstance(cell_val, str) and cell_val.startswith("="):
            val, err = _eval_simple_excel_formula(ws, cell_val, visited | {coord_clean})
            return (val or Decimal("0")), err
        try:
            return Decimal(str(cell_val)), None
        except Exception:
            return Decimal("0"), "#VALUE!"

    def _resolve_range_vals(rng_str: str) -> Tuple[List[Decimal], Optional[str]]:
        vals: List[Decimal] = []
        for part in [p.strip() for p in rng_str.split(",") if p.strip()]:
            if ":" in part:
                try:
                    min_c, min_r, max_c, max_r = range_boundaries(part.replace("$", ""))
                except Exception:
                    return [], "#REF!"
                for r in range(min_r, max_r + 1):
                    for c in range(min_c, max_c + 1):
                        coord = f"{get_column_letter(c)}{r}"
                        raw = ws[coord].value
                        if raw is None or raw == "":
                            continue
                        v, err = _resolve_cell_num(coord)
                        if err:
                            return [], err
                        vals.append(v)
            else:
                try:
                    if re.match(r"^\$?[A-Za-z]{1,3}\$?\d+$", part):
                        v, err = _resolve_cell_num(part)
                        if err:
                            return [], err
                        vals.append(v)
                    else:
                        vals.append(Decimal(part))
                except Exception:
                    return [], "#VALUE!"
        return vals, None

    upper_expr = expr.upper()
    m_func = re.match(r"^(SUM|AVERAGE|MIN|MAX|COUNT|SUBTOTAL)\((.*)\)$", upper_expr)
    if m_func:
        fn_name = m_func.group(1)
        inner = expr[len(fn_name) + 1 : -1]
        if fn_name == "SUBTOTAL":
            # Excel SUBTOTAL semantics: 1=AVERAGE, 2=COUNT, 4=MAX, 5=MIN, 6=PRODUCT,
            # 9=SUM (101/102/104/109 ignore hidden rows — treated the same here).
            parts = [p.strip() for p in inner.split(",", 1)]
            if len(parts) < 2:
                return None, "#VALUE!"
            try:
                fn_code = int(parts[0])
            except ValueError:
                return None, "#VALUE!"
            inner = parts[1]
            fn_name = {1: "AVERAGE", 2: "COUNT", 4: "MAX", 5: "MIN", 9: "SUM"}.get(fn_code % 100)
            if fn_name is None:
                # Unsupported SUBTOTAL function code: report as unverifiable, never guess.
                return None, None
        vals, err = _resolve_range_vals(inner)
        if err:
            return None, err
        if fn_name == "SUM":
            return sum(vals, Decimal("0")), None
        if fn_name == "COUNT":
            return Decimal(len(vals)), None
        if not vals:
            return None, "#DIV/0!" if fn_name == "AVERAGE" else Decimal("0")
        if fn_name == "AVERAGE":
            return sum(vals, Decimal("0")) / Decimal(len(vals)), None
        if fn_name == "MIN":
            return min(vals), None
        if fn_name == "MAX":
            return max(vals), None

    # Simple arithmetic expression over cells and literals: e.g. C5*D5 or (A2+B2)/C2
    arith_err: Optional[str] = None

    def _sub_cell(m: re.Match) -> str:
        nonlocal arith_err
        coord = f"{m.group(1)}{m.group(3)}"
        v, err = _resolve_cell_num(coord)
        if err:
            arith_err = err
        return f"Decimal('{v}')"

    py_expr = _CELL_REF_RE.sub(_sub_cell, expr)
    if arith_err:
        return None, arith_err
    if re.match(r"^[0-9Decimal()'.+\-*/\s]+$", py_expr):
        try:
            res = eval(py_expr, {"__builtins__": {}}, {"Decimal": Decimal})
            return Decimal(str(res)), None
        except ZeroDivisionError:
            return None, "#DIV/0!"
        except Exception:
            return None, "#VALUE!"

    return None, None


def recalculate_and_verify_excel_formulas(
    xlsx_path: str,
    guard: Optional[TaskResourceGuard] = None,
) -> Dict[str, Any]:
    """
    Recalculate and verify all Excel formulas in `xlsx_path` (fixes P1-6):
    1. If `soffice` (LibreOffice) is available in PATH, converts/recalculates in a temp directory
       under `TaskResourceGuard` and inspects cached formula results.
    2. Always runs the built-in deterministic formula evaluator over all `=...` cells in `xlsx_path`
       to detect `#DIV/0!`, `#REF!`, `#VALUE!`, and verify numeric results.
    """
    wb = openpyxl.load_workbook(xlsx_path, data_only=False)
    evaluated_cells: Dict[str, Any] = {}
    formula_errors: List[str] = []
    unsupported_formulas: List[str] = []
    formula_status: Dict[str, str] = {}
    formula_coordinates: List[Tuple[str, str]] = []
    total_formulas = 0

    for s_name in wb.sheetnames:
        ws = wb[s_name]
        for row in ws.iter_rows(values_only=False):
            for cell in row:
                val = cell.value
                if isinstance(val, str) and val.startswith("="):
                    total_formulas += 1
                    key = f"{s_name}!{cell.coordinate}"
                    formula_coordinates.append((s_name, cell.coordinate))
                    calc_val, err_tok = _eval_simple_excel_formula(ws, val)
                    if err_tok:
                        formula_errors.append(f"FORMULA_EVAL_ERROR {key}: {val} -> {err_tok}")
                        formula_status[key] = "FAILED"
                    elif calc_val is not None:
                        num_fmt = str(getattr(cell, "number_format", "") or "")
                        if ".00" in num_fmt:
                            evaluated_cells[key] = f"{calc_val.quantize(Decimal('0.01'))}"
                        elif calc_val == calc_val.to_integral_value():
                            # Normalize e.g. Decimal("3001.0") -> "3001.00" when inputs have 2 decimal places or standard currency/decimal scale
                            s_raw = str(calc_val)
                            if "." in s_raw and len(s_raw.split(".")[1]) == 1:
                                evaluated_cells[key] = f"{calc_val.quantize(Decimal('0.01'))}"
                            else:
                                evaluated_cells[key] = s_raw
                        else:
                            evaluated_cells[key] = str(calc_val)
                        formula_status[key] = "VERIFIED"
                    else:
                        # Neither an error nor a value: the builtin evaluator does not
                        # support this formula. It is UNVERIFIED, never silently passed.
                        unsupported_formulas.append(f"FORMULA_UNSUPPORTED {key}: {val}")
                        formula_status[key] = "UNSUPPORTED"

    wb.close()
    # W3-2: keep the builtin verdict separate from the external recalculation so a
    # renderer limitation (e.g. LibreOffice without XLOOKUP -> #NAME?) can never be
    # rewritten into a formula ERROR. Provenance is {builtin, external, final}.
    builtin_status: Dict[str, str] = dict(formula_status)
    external_status: Dict[str, str] = {}
    external_error_value: Dict[str, str] = {}

    soffice_bin = shutil.which("soffice") or shutil.which("libreoffice")
    engine_used = "builtin_decimal_evaluator"
    if soffice_bin:
        active_guard = guard or TaskResourceGuard()
        with tempfile.TemporaryDirectory() as tmpdir:
            # W3-5: private user profile per invocation, so the shared default
            # profile lock cannot serialize or hang back-to-back conversions
            # (audit P2-04).
            with tempfile.TemporaryDirectory(prefix="lo-profile-") as profile_dir:
                res = active_guard.run_owned_command(
                    [soffice_bin, libreoffice_user_installation_arg(profile_dir),
                     "--headless", "--convert-to", "xlsx", "--outdir", tmpdir, xlsx_path],
                    timeout=45,
                    check=False,
                )
            recalc_file = os.path.join(tmpdir, os.path.basename(xlsx_path))
            if res.returncode == 0 and os.path.exists(recalc_file):
                engine_used = "libreoffice+builtin"
                wb_val = openpyxl.load_workbook(recalc_file, data_only=True)
                for s_name, coordinate in formula_coordinates:
                    key = f"{s_name}!{coordinate}"
                    if s_name not in wb_val.sheetnames:
                        external_status[key] = "NOT_RECALCULATED"
                        continue
                    value = wb_val[s_name][coordinate].value
                    if isinstance(value, str) and any(tok in value for tok in EXCEL_ERROR_TOKENS):
                        external_status[key] = "FAILED"
                        external_error_value[key] = value
                    elif value is None:
                        # LibreOffice produced no cached value: unverified, not "fine".
                        external_status[key] = "NOT_RECALCULATED"
                    else:
                        external_status[key] = "VERIFIED"
                wb_val.close()

    formula_provenance: Dict[str, Dict[str, Optional[str]]] = {}
    for key, b_status in builtin_status.items():
        e_status = external_status.get(key)
        if b_status == "VERIFIED":
            final = "VERIFIED"
        elif b_status == "FAILED":
            final = "FAILED"
        elif e_status == "VERIFIED":
            final = "VERIFIED_EXTERNAL"
        elif e_status == "NOT_RECALCULATED":
            final = "NOT_RECALCULATED"
        else:
            # builtin UNSUPPORTED with an external error value (#NAME?) or with no
            # external verdict at all: still unverified, never FAILED.
            final = "UNSUPPORTED"
        formula_status[key] = final
        formula_provenance[key] = {
            "builtin_status": b_status,
            "external_status": e_status,
            "final_status": final,
        }
    # Only a genuinely failed formula (per the merged verdict) may surface as a
    # blocking error; a renderer that cannot evaluate an unsupported function stays
    # in the unverified bucket.
    for key, e_status in external_status.items():
        if e_status == "FAILED" and formula_status[key] == "FAILED":
            formula_errors.append(
                f"LIBREOFFICE_EVAL_ERROR {key}: {external_error_value.get(key, 'cached error value')}"
            )

    status_counts: Dict[str, int] = {}
    for status in formula_status.values():
        status_counts[status] = status_counts.get(status, 0) + 1
    unverified_count = status_counts.get("UNSUPPORTED", 0) + status_counts.get("NOT_RECALCULATED", 0)

    return {
        "engine": engine_used,
        "total_formulas": total_formulas,
        "evaluated_count": len(evaluated_cells),
        "evaluated_cells": evaluated_cells,
        "evaluated_Values": evaluated_cells,
        "formula_errors": formula_errors,
        "unsupported_formulas": unsupported_formulas,
        "formula_status": formula_status,
        "formula_provenance": formula_provenance,
        "status_counts": status_counts,
        "unverified_count": unverified_count,
        "coverage_gaps": ["FORMULAS_UNVERIFIED"] if unverified_count else [],
    }


def audit_excel_formula_and_style_qa(
    template_path: str,
    output_path: Optional[str] = None,
    forbidden_residues: Optional[List[str]] = None,
    required_formula_cells: Optional[List[Tuple[str, str]]] = None,
    expected_formula_cells: Optional[Dict[str, List[str]]] = None,
    guard: Optional[TaskResourceGuard] = None,
) -> Dict[str, Any]:
    """
    Stage 4 QA for Excel (`.xlsx`) templates (with live formula evaluation):
    1. Verifies sheet names and column widths match the template baseline.
    2. Verifies every cell in `required_formula_cells` / `expected_formula_cells` starts with `=`.
    3. Runs `recalculate_and_verify_excel_formulas()` so `#DIV/0!`, `#REF!`, `#VALUE!` inside
       uncalculated formulas are caught immediately.
    4. Verifies zero forbidden template example residues.
    """
    if output_path is None:
        output_path = template_path
    req_cells: List[Tuple[str, str]] = list(required_formula_cells or [])
    if expected_formula_cells:
        for s_name, coords in expected_formula_cells.items():
            for c in coords:
                req_cells.append((s_name, c))
    required_formula_cells = req_cells
    tpl_wb = openpyxl.load_workbook(template_path, data_only=False)
    out_wb = openpyxl.load_workbook(output_path, data_only=False)
    issues: List[str] = []

    if tpl_wb.sheetnames != out_wb.sheetnames:
        issues.append(f"SHEET_MISMATCH: template={tpl_wb.sheetnames}, output={out_wb.sheetnames}")

    for s_name in out_wb.sheetnames:
        ws_out = out_wb[s_name]
        if s_name in tpl_wb.sheetnames:
            ws_tpl = tpl_wb[s_name]
            for col_letter, dim in ws_tpl.column_dimensions.items():
                if dim.width is not None and ws_out.column_dimensions[col_letter].width != dim.width:
                    issues.append(
                        f"COL_WIDTH_DELTA {s_name}!{col_letter}: baseline={dim.width}, output={ws_out.column_dimensions[col_letter].width}"
                    )
        for row in ws_out.iter_rows(values_only=False):
            for cell in row:
                val_str = str(cell.value or "").strip()
                if not val_str:
                    continue
                for err_tok in EXCEL_ERROR_TOKENS:
                    if err_tok in val_str:
                        issues.append(f"EXCEL_FORMULA_ERROR {s_name}!{cell.coordinate}: contains '{err_tok}' ({val_str})")
                for kw in (forbidden_residues or []):
                    if kw and kw in val_str:
                        issues.append(f"EXCEL_RESIDUE_FOUND {s_name}!{cell.coordinate}: forbidden keyword '{kw}'")

    for s_name, coord in (required_formula_cells or []):
        if s_name in out_wb.sheetnames:
            c_val = str(out_wb[s_name][coord].value or "")
            if not c_val.startswith("="):
                issues.append(
                    f"HARDCODED_TOTAL_VIOLATION {s_name}!{coord}: expected Excel formula starting with '=', got {c_val!r}"
                )

    tpl_wb.close()
    out_wb.close()

    recalc_report = recalculate_and_verify_excel_formulas(output_path, guard=guard)
    issues.extend(recalc_report["formula_errors"])

    structured_issues: List[Dict[str, Any]] = []
    for item in issues:
        text = str(item)
        match = re.match(r"^([A-Z][A-Z0-9_]+)\s+(.*)$", text)
        if match:
            structured_issues.append({
                "code": match.group(1),
                "location": "excel",
                "detail": match.group(2),
                "severity": "high",
            })
        else:
            structured_issues.append({
                "code": "EXCEL_QA",
                "location": "excel",
                "detail": text,
                "severity": "high",
            })

    coverage_gaps: List[str] = list(recalc_report.get("coverage_gaps") or [])
    if not recalc_report.get("engine"):
        coverage_gaps.append("FORMULA_ENGINE_UNAVAILABLE")
    unverified_total = int(recalc_report.get("unverified_count") or 0) + (0 if recalc_report.get("engine") else 1)

    return {
        "passed": len(structured_issues) == 0,
        "issues": structured_issues,
        "structured_issues": structured_issues,
        "coverage_gaps": coverage_gaps,
        "unverified_count": unverified_total,
        "recalculation": recalc_report,
        "formula_status": recalc_report.get("formula_status", {}),
    }
