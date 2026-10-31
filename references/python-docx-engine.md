# Python Heavy Template Engine, Strict Style-Cloning & Format-Diff QA Recipes (v2.4)

When a template (`.docx` or `.xlsx`) requires modifying **> 20 cells**, **> 15 paragraphs**, **building multi-row tables/schedules**, or **replacing placeholder images**, do NOT invoke `officecli set` hundreds of times in a shell loop. Use this Python engine pattern instead, while keeping `officecli` for pre-flight structure inspection and post-flight delta validation.

---

## 1. Environment Check for Python Libraries

```powershell
python -c "import docx, openpyxl, matplotlib; print('OK')" 2>$null
if ($LASTEXITCODE -ne 0) {
    pip install python-docx openpyxl matplotlib pillow -i https://pypi.tuna.tsinghua.edu.cn/simple
}
```

---

## 2. Step 1 Scanner: Red-Font Placeholders & Physical Cell Capacity Profiler

Chinese templates commonly mark instructions and placeholders in red (`EE0000`, `FF0000`, `C00000`) and design table cells with specific physical character capacities. Always run this scanner in Step 1:

```python
import docx
from docx.oxml.ns import qn

RED_HEX_SET = {"EE0000", "FF0000", "C00000", "FF3300", "CC0000", "E30000"}

def is_red_run(run) -> bool:
    rPr = run._r.rPr
    if rPr is None:
        return False
    color = rPr.find(qn("w:color"))
    if color is not None:
        val = (color.get(qn("w:val")) or "").upper()
        if val in RED_HEX_SET:
            return True
    return False

def scan_red_runs_and_cell_capacities(doc):
    """
    1. Lists all red-colored instruction/placeholder runs in paragraphs and tables.
    2. Profiles each table's physical capacity (sample text length, grid columns, layout type).
    """
    red_hits = []
    for p_idx, p in enumerate(doc.paragraphs):
        red_texts = [r.text for r in p.runs if is_red_run(r) and r.text.strip()]
        if red_texts:
            red_hits.append(("body_p", p_idx, "".join(red_texts)[:80]))

    table_profiles = []
    for t_idx, tbl in enumerate(doc.tables):
        max_chars_per_col = {}
        for r_idx, row in enumerate(tbl.rows):
            for c_idx, cell in enumerate(row.cells):
                txt = cell.text.strip()
                if r_idx > 0:
                    max_chars_per_col[c_idx] = max(max_chars_per_col.get(c_idx, 0), len(txt))
                for p in cell.paragraphs:
                    rt = [r.text for r in p.runs if is_red_run(r) and r.text.strip()]
                    if rt:
                        red_hits.append((f"tbl[{t_idx}]_r{r_idx}_c{c_idx}", t_idx, "".join(rt)[:60]))
        table_profiles.append({
            "table_index": t_idx,
            "rows": len(tbl.rows),
            "cols": len(tbl.columns),
            "headers": [c.text.strip().replace("\n", "")[:15] for c in tbl.rows[0].cells[:10]],
            "max_sample_chars_by_col": max_chars_per_col,
        })
    return red_hits, table_profiles
```

---

## 3. Executable Style-Preserving Helpers (Strict `rPr`/`pPr` Cloning & Red-Color Stripping)

Never let the model invent its own font size, alignment (`jc`), or line spacing when filling a template table! Follow these rules:
1. **Deduplicate merged cells** by `id(cell._tc)` before indexing;
2. **Clone `pPr` and `rPr`** from the cell itself, or if the cell has no runs (an empty template slot), **deep-copy `pPr` and `rPr` from the nearest populated neighbor cell in the same column or row**;
3. **Strip red placeholder color (`<w:color>`)** from cloned `rPr` so filled formal text turns standard black/auto while keeping exact font family, size, and bold properties;
4. **Lock table layout to `fixed`** without modifying `tblW`, `tblGrid`, or `tcW`.

```python
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from copy import deepcopy
import re

def get_unique_row_cells(row):
    """Return distinct Word Cell objects in visual left-to-right order (skips merged duplicates)."""
    seen_tcs = set()
    unique_cells = []
    for cell in row.cells:
        tc_id = id(cell._tc)
        if tc_id not in seen_tcs:
            seen_tcs.add(tc_id)
            unique_cells.append(cell)
    return unique_cells

def sanitize_rPr_remove_red(rPr_element, strip_bold: bool = False):
    """
    Deep-copy an rPr element, strip red placeholder w:color or w:highlight,
    and ensure w:eastAsia font is explicitly bound if w:rFonts is present.
    """
    if rPr_element is None:
        return None
    cloned = deepcopy(rPr_element)
    color = cloned.find(qn("w:color"))
    if color is not None:
        val = (color.get(qn("w:val")) or "").upper()
        if val in {"EE0000", "FF0000", "C00000", "FF3300", "CC0000", "E30000"}:
            cloned.remove(color)
    if strip_bold:
        for b_tag in ("w:b", "w:bCs"):
            b_el = cloned.find(qn(b_tag))
            if b_el is not None:
                cloned.remove(b_el)
    return cloned

def _extract_rPr_from_paragraph_or_runs(p, strip_bold: bool = False):
    """
    CRITICAL FIX FOR BLANK TEMPLATE CELLS:
    In Word OpenXML, blank cells have NO <w:r> runs; their '宋体 小五' (sz=18) font is stored inside
    the paragraph mark's <w:pPr><w:rPr>! Always check run._r.rPr first, then p._p.pPr.find(qn('w:rPr')).
    """
    for run in p.runs:
        if run._r.rPr is not None:
            return sanitize_rPr_remove_red(run._r.rPr, strip_bold=strip_bold)
    if p._p.pPr is not None:
        mark_rPr = p._p.pPr.find(qn("w:rPr"))
        if mark_rPr is not None:
            return sanitize_rPr_remove_red(mark_rPr, strip_bold=strip_bold)
    return None

def build_explicit_rPr(font_cn: str = "宋体", font_en: str = "宋体", sz_half_pt: int = 18, bold: bool = False):
    """
    Fallback rPr builder that locks all 4 font slots (ascii, hAnsi, eastAsia, cs)
    so Word/WPS NEVER falls back to '等线 (正文) 11' or 'Times New Roman'.
    """
    rPr = OxmlElement("w:rPr")
    rFonts = OxmlElement("w:rFonts")
    rFonts.set(qn("w:ascii"), font_en)
    rFonts.set(qn("w:hAnsi"), font_en)
    rFonts.set(qn("w:eastAsia"), font_cn)
    rFonts.set(qn("w:cs"), font_en)
    rFonts.set(qn("w:hint"), "eastAsia")
    rPr.append(rFonts)
    if bold:
        rPr.append(OxmlElement("w:b"))
    sz = OxmlElement("w:sz")
    sz.set(qn("w:val"), str(sz_half_pt))
    rPr.append(sz)
    szCs = OxmlElement("w:szCs")
    szCs.set(qn("w:val"), str(sz_half_pt))
    rPr.append(szCs)
    return rPr

def extract_donor_style_from_table(table, target_row_idx: int, target_col_idx: int):
    """
    Find a non-empty donor (pPr, rPr) from:
      1. The target cell itself (checking BOTH run._r.rPr AND p._p.pPr/w:rPr for empty template cells!);
      2. Another data cell in the same column (row >= 1);
      3. Another data cell in the same row (col >= 0);
      4. Any data cell in the table (row >= 1);
      5. Header row (row 0) in the same column, with bold stripped;
      6. Explicit '宋体 小五' (sz=18) fallback so '等线 (正文) 11' NEVER happens.
    """
    candidates = [(target_row_idx, target_col_idx, False)]
    for r in range(1, len(table.rows)):
        if r != target_row_idx:
            candidates.append((r, target_col_idx, False))
    for c in range(len(table.columns)):
        if c != target_col_idx:
            candidates.append((target_row_idx, c, False))
    for r in range(1, len(table.rows)):
        for c in range(len(table.columns)):
            candidates.append((r, c, False))
    # Fallback to header row (row 0) with bold stripped
    candidates.append((0, target_col_idx, True))
    candidates.append((0, 0, True))

    fallback_pPr = None
    for r_i, c_i, is_header in candidates:
        if r_i < len(table.rows):
            u_cells = get_unique_row_cells(table.rows[r_i])
            if c_i < len(u_cells):
                cell = u_cells[c_i]
                for p in cell.paragraphs:
                    pPr = deepcopy(p._p.pPr) if p._p.pPr is not None else None
                    if fallback_pPr is None and pPr is not None:
                        fallback_pPr = pPr
                    rPr = _extract_rPr_from_paragraph_or_runs(p, strip_bold=is_header)
                    if rPr is not None:
                        return pPr, rPr
    return fallback_pPr, build_explicit_rPr("宋体", "宋体", 18, bold=False)

def fill_cell_strict_style(table, row_idx: int, unique_col_idx: int, text: str):
    """
    Fill a Word table cell while strictly preserving pPr (jc, spacing, ind) and rPr (rFonts, sz, b),
    borrowing style from neighbor data cells if the target cell is empty, and stripping red placeholder color.
    """
    u_cells = get_unique_row_cells(table.rows[row_idx])
    cell = u_cells[unique_col_idx]
    donor_pPr, donor_rPr = extract_donor_style_from_table(table, row_idx, unique_col_idx)

    if not cell.paragraphs:
        cell.add_paragraph()
    p0 = cell.paragraphs[0]

    # Preserve p0's own pPr if present, otherwise apply donor_pPr
    if p0._p.pPr is None and donor_pPr is not None:
        p0._p.insert(0, deepcopy(donor_pPr))

    # Remove extra paragraphs and clear existing runs on p0
    for p in cell.paragraphs[1:]:
        p._element.getparent().remove(p._element)
    for r in list(p0.runs):
        r._r.getparent().remove(r._r)

    lines = str(text).split("\n")
    for idx, line in enumerate(lines):
        if idx > 0:
            p0.add_run().add_break()
        run = p0.add_run(line)
        if donor_rPr is not None:
            run._r.insert(0, deepcopy(donor_rPr))

def replace_red_runs_in_paragraph(paragraph, replacement_text: str):
    """
    Replace red placeholder runs inside a body paragraph while preserving surrounding black runs
    and stripping the red w:color attribute.
    """
    red_indices = [i for i, r in enumerate(paragraph.runs) if is_red_run(r)]
    if not red_indices:
        return False
    first_idx = red_indices[0]
    first_run = paragraph.runs[first_idx]
    clean_rPr = sanitize_rPr_remove_red(first_run._r.rPr)
    first_run.text = replacement_text
    if first_run._r.rPr is not None:
        first_run._r.remove(first_run._r.rPr)
    if clean_rPr is not None:
        first_run._r.insert(0, clean_rPr)
    for idx in reversed(red_indices[1:]):
        r_elem = paragraph.runs[idx]._r
        r_elem.getparent().remove(r_elem)
    return True

def lock_table_layout_fixed(table):
    """
    Set w:tblLayout to 'fixed' without altering w:tblW, w:tblGrid, or w:tcW,
    preventing WPS/Word from scrambling column widths when text is filled.
    """
    tblPr = table._tbl.tblPr
    if tblPr is None:
        return
    tblLayout = tblPr.find(qn("w:tblLayout"))
    if tblLayout is None:
        tblLayout = OxmlElement("w:tblLayout")
        tblPr.append(tblLayout)
    tblLayout.set(qn("w:type"), "fixed")

def clone_append_table_row(table, template_row_idx: int = -1):
    """
    Clone an existing data row (preserving trPr, tcPr, borders, shading, widths, pPr, and rPr)
    and append it to the table so newly added rows have 0 format diff against the template.
    """
    source_tr = table.rows[template_row_idx]._tr
    new_tr = deepcopy(source_tr)
    table._tbl.append(new_tr)
    new_row = table.rows[-1]
    for cell in get_unique_row_cells(new_row):
        for p in cell.paragraphs:
            for r in p.runs:
                r.text = ""
                if r._r.rPr is not None:
                    clean = sanitize_rPr_remove_red(r._r.rPr)
                    r._r.remove(r._r.rPr)
                    if clean is not None:
                        r._r.insert(0, clean)
    return new_row
```

---

## 4. Landscape Section Sandwich for Wide Tables (`Portrait -> Landscape -> Portrait`)

When inserting a wide table (e.g., 17-column teaching schedule), simply attaching one `sectPr` is not enough—a Word `<w:sectPr>` inside `<w:pPr>` defines the page orientation for all content **up to and including that paragraph**. Therefore, to isolate a wide table on its own Landscape page(s) between Portrait pages:
1. Attach a **Portrait** `sectPr` (`orient="portrait"`, `w=11906, h=16838`) to the paragraph **immediately before** the wide table (ending the Portrait section);
2. Insert the wide table, add a spacer/caption paragraph **immediately after** the wide table, and attach a **Landscape** `sectPr` (`orient="landscape"`, `w=16838, h=11906`) to that after-table paragraph (ending the Landscape section so subsequent body content returns to Portrait).
3. Always append `<w:sectPr>` as the **VERY LAST child of `<w:pPr>`** (after `<w:rPr>`).

```python
def attach_section_break_safe(paragraph, orient="landscape"):
    """
    Attach a valid sectPr as the LAST child of w:pPr (strictly after w:rPr).
    orient='portrait'  -> w=11906, h=16838
    orient='landscape' -> w=16838, h=11906, w:orient='landscape'
    """
    pPr = paragraph._p.get_or_add_pPr()
    existing = pPr.find(qn("w:sectPr"))
    if existing is not None:
        pPr.remove(existing)

    sectPr = OxmlElement("w:sectPr")
    pgSz = OxmlElement("w:pgSz")
    if orient == "landscape":
        pgSz.set(qn("w:w"), "16838")
        pgSz.set(qn("w:h"), "11906")
        pgSz.set(qn("w:orient"), "landscape")
    else:
        pgSz.set(qn("w:w"), "11906")
        pgSz.set(qn("w:h"), "16838")
    sectPr.append(pgSz)

    pgMar = OxmlElement("w:pgMar")
    for k, v in [("top", "1134"), ("right", "1134"), ("bottom", "1134"), ("left", "1134"),
                 ("header", "851"), ("footer", "992"), ("gutter", "0")]:
        pgMar.set(qn(f"w:{k}"), v)
    sectPr.append(pgMar)

    # MUST be appended as the final child of w:pPr
    pPr.append(sectPr)
```

---

## 5. Step 5 Automated Format-Diff & Text-Residue QA (`audit_format_and_text_qa`)

Run this function before delivering any document. It compares the generated `.docx` against the original template `.docx` across **table column grids (`gridCol`), font sizes (`sz`), paragraph alignments (`jc`), shading (`shd`), remaining red placeholder runs, and forbidden template residue strings**:

```python
from collections import Counter

def _table_format_signature(tbl):
    grid_cols = [col.get(qn("w:w")) for col in tbl._tbl.findall(".//" + qn("w:gridCol"))]
    sz_counter = Counter()
    jc_counter = Counter()
    shd_counter = Counter()
    for row in tbl.rows:
        for cell in get_unique_row_cells(row):
            shd = cell._tc.find(".//" + qn("w:shd"))
            if shd is not None:
                shd_counter[shd.get(qn("w:fill"))] += 1
            for p in cell.paragraphs:
                if p._p.pPr is not None:
                    jc = p._p.pPr.find(qn("w:jc"))
                    if jc is not None:
                        jc_counter[jc.get(qn("w:val"))] += 1
                for r in p.runs:
                    if r._r.rPr is not None:
                        sz = r._r.rPr.find(qn("w:sz"))
                        if sz is not None:
                            sz_counter[sz.get(qn("w:val"))] += 1
    return {
        "grid_cols": grid_cols,
        "dominant_sz": sz_counter.most_common(2),
        "jc_keys": set(jc_counter.keys()),
        "shd_fills": set(shd_counter.keys()),
    }

def audit_format_and_text_qa(template_path: str, output_path: str, forbidden_residues: list):
    """
    Comprehensive Format-Level + Text-Level QA check:
      1. Zero red-colored placeholder runs left in output.
      2. Preserved tables keep identical w:gridCol widths, dominant font sizes (w:sz), and shading fills (w:shd).
      3. Zero forbidden residue keywords (e.g., '***', '****', '数控机床', '液压', '本科') in paragraphs or tables.
    """
    tpl_doc = docx.Document(template_path)
    out_doc = docx.Document(output_path)

    issues = []

    # 1. Check remaining red runs in output
    red_hits, _ = scan_red_runs_and_cell_capacities(out_doc)
    if red_hits:
        issues.append(f"RED_FONT_RESIDUE: Found {len(red_hits)} unstripped red runs: {red_hits[:5]}")

    # 2. Check table format diff on corresponding tables
    compare_count = min(len(tpl_doc.tables), len(out_doc.tables))
    for i in range(compare_count):
        sig_tpl = _table_format_signature(tpl_doc.tables[i])
        sig_out = _table_format_signature(out_doc.tables[i])
        if sig_tpl["grid_cols"] and sig_out["grid_cols"] and sig_tpl["grid_cols"] != sig_out["grid_cols"]:
            issues.append(f"TABLE_GRID_DIFF tbl[{i}]: gridCols changed from {sig_tpl['grid_cols']} to {sig_out['grid_cols']}")
        if sig_tpl["dominant_sz"] and sig_out["dominant_sz"]:
            if sig_tpl["dominant_sz"][0][0] != sig_out["dominant_sz"][0][0]:
                issues.append(f"TABLE_FONT_SIZE_DIFF tbl[{i}]: dominant w:sz changed from {sig_tpl['dominant_sz']} to {sig_out['dominant_sz']}")
        if sig_tpl["shd_fills"] != sig_out["shd_fills"]:
            issues.append(f"TABLE_SHADING_DIFF tbl[{i}]: w:shd fills changed from {sig_tpl['shd_fills']} to {sig_out['shd_fills']}")

    # 3. Check forbidden template text residues
    all_texts = [p.text for p in out_doc.paragraphs]
    for t in out_doc.tables:
        for row in t.rows:
            for c in get_unique_row_cells(row):
                all_texts.append(c.text)
    full_blob = "\n".join(all_texts)
    for kw in forbidden_residues:
        if kw and kw in full_blob:
            issues.append(f"TEXT_RESIDUE_FOUND: Forbidden template keyword '{kw}' still present in output!")

    return issues
```

---

## 6. Single-Source-of-Truth (SSOT) Multi-Table Solvers

Never compute numbers separately for different tables! Derive **Table 2 (Graduation Credit Requirements)**, **Table 6 (Credit/Hour Allocation Summary)**, **Table 7 (Full Teaching Schedule)**, and **Body Text Summaries** from one single Python call:

```python
def compute_Exact_percentages(values: list, decimals: int = 1) -> list:
    """Largest-remainder method so rounded percentages are guaranteed to sum to exactly 100.0%."""
    total = sum(values)
    if total == 0:
        return [0.0 for _ in values]
    scale = 10 ** decimals
    target_int = 100 * scale
    raw = [v * target_int / total for v in values]
    floored = [int(x) for x in raw]
    remainders = [(raw[i] - floored[i], i) for i in range(len(values))]
    remainders.sort(reverse=True)
    diff = target_int - sum(floored)
    for k in range(diff):
        floored[remainders[k][1]] += 1
    return [x / scale for x in floored]

def build_curriculum_ssot(courses: list):
    """
    Single Source of Truth (SSOT) solver for Education Templates.
    Returns exact aligned dictionaries for Table 2, Table 6, Table 7, and Body Paragraphs.
    """
    grand_hours = sum(c["total_hours"] for c in courses)
    grand_credits = round(sum(c["credits"] for c in courses), 1)
    grand_theory = sum(c["theory_hours"] for c in courses)
    grand_practice = sum(c["practice_hours"] for c in courses)

    for c in courses:
        assert c["total_hours"] == c["theory_hours"] + c["practice_hours"], f"Hours mismatch in {c['name']}"
        if not c.get("is_weekly_practice", False):
            expected_cr = round(c["total_hours"] / 16.0, 1)
            assert abs(c["credits"] - expected_cr) <= 0.5, f"Credit mismatch in {c['name']}"

    def _sum_group(pred):
        sub = [c for c in courses if pred(c)]
        return {
            "count": len(sub),
            "credits": round(sum(c["credits"] for c in sub), 1),
            "total_hours": sum(c["total_hours"] for c in sub),
            "theory_hours": sum(c["theory_hours"] for c in sub),
            "practice_hours": sum(c["practice_hours"] for c in sub),
        }

    groups = {
        "pub_req": _sum_group(lambda c: c["category"] == "公共基础必修"),
        "pub_elec": _sum_group(lambda c: c["category"] == "公共基础选修"),
        "pro_base": _sum_group(lambda c: c["category"] == "专业基础"),
        "pro_core": _sum_group(lambda c: c["category"] == "专业核心"),
        "pro_elec": _sum_group(lambda c: c["category"] == "专业拓展选修"),
        "prac_conc": _sum_group(lambda c: c["category"] == "集中实践"),
        "all_req": _sum_group(lambda c: c["nature"] == "必修"),
        "all_elec": _sum_group(lambda c: c["nature"] == "选修"),
    }

    pub_hours = groups["pub_req"]["total_hours"] + groups["pub_elec"]["total_hours"]
    elec_hours = groups["all_elec"]["total_hours"]
    practice_ratio = grand_practice / grand_hours
    pub_ratio = pub_hours / grand_hours
    elec_ratio = elec_hours / grand_hours

    assert grand_hours >= 2500, f"Total hours {grand_hours} < 2500"
    assert practice_ratio >= 0.50, f"Practice ratio {practice_ratio:.1%} < 50%"
    assert pub_ratio >= 0.25, f"Public ratio {pub_ratio:.1%} < 25%"
    assert elec_ratio >= 0.10, f"Elective ratio {elec_ratio:.1%} < 10%"

    return {
        "grand_hours": grand_hours,
        "grand_credits": grand_credits,
        "grand_theory": grand_theory,
        "grand_practice": grand_practice,
        "practice_ratio_pct": round(practice_ratio * 100, 1),
        "pub_ratio_pct": round(pub_ratio * 100, 1),
        "elec_ratio_pct": round(elec_ratio * 100, 1),
        "groups": groups,
    }
```

---

## 7. Redrawing Placeholder Diagrams with Matplotlib

```python
import matplotlib.pyplot as plt
import matplotlib.patches as patches

plt.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei', 'PingFang SC', 'Noto Sans CJK SC', 'DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False

def draw_layered_framework_diagram(output_png_path: str, diagram_title: str, layers: list):
    fig, ax = plt.subplots(figsize=(10, 5.6), dpi=300)
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 6)
    ax.axis('off')

    ax.add_patch(patches.FancyBboxPatch((0.5, 5.15), 9.0, 0.62, boxstyle="round,pad=0.08", fc="#1F4E79", ec="none"))
    ax.text(5.0, 5.46, diagram_title, color="white", fontsize=13, weight="bold", ha="center", va="center")

    n_layers = len(layers)
    avail_h = 4.65
    layer_h = (avail_h / n_layers) - 0.22

    for idx, (bg, border, layer_title, items) in enumerate(layers):
        y = 4.9 - (idx + 1) * (layer_h + 0.22) + 0.15
        ax.add_patch(patches.FancyBboxPatch((0.5, y), 9.0, layer_h, boxstyle="round,pad=0.06", fc=bg, ec=border, lw=1.5))
        ax.text(5.0, y + layer_h - 0.26, layer_title, color=border, fontsize=10.5, weight="bold", ha="center", va="center")
        n = len(items)
        box_w = 8.4 / n - 0.15
        for i, item in enumerate(items):
            bx = 0.75 + i * (box_w + 0.15)
            ax.add_patch(patches.FancyBboxPatch((bx, y + 0.12), box_w, layer_h - 0.52, boxstyle="round,pad=0.04", fc="white", ec=border, lw=1))
            ax.text(bx + box_w / 2, y + 0.12 + (layer_h - 0.52) / 2, item, color="#222222", fontsize=8.5, ha="center", va="center", wrap=True)

    plt.tight_layout()
    plt.savefig(output_png_path, dpi=300, bbox_inches='tight')
    plt.close(fig)
```

---

## 8. Rendering a Full-Page Master Schedule Table Image (1:1 Visual Match for Section 八《教学进程总体安排表》)

Many reference templates embed the 60-row × 17-column master teaching schedule (`教学进程总体安排表`) as a **full-page high-resolution image** so that all 17 columns (`课程类别`, `课程性质`, `序`, `课程编码`, `课程名称`, `学分`, `总学时`, `理论`, `实践`, `一`..`六` 学期周学时, `考核方式`, `开课单位`), hierarchical category merges, `#1F4E79` navy-blue header, and `#D9E1F2` gray subtotal (`小计`/`合计`/`占总学时比例`) rows fit onto **one single Portrait page** without vertical text wrapping or 5-page overflow.

Always use `render_schedule_table_as_single_page_image()` by default when the template's schedule is an embedded image:

```python
def render_schedule_table_as_single_page_image(
    output_png_path: str,
    title_text: str,
    rows_data: list,
):
    """
    Renders a 17-column Master Teaching Schedule Table as a crisp 300-DPI single-page portrait image
    matching the exact visual styling of the original template image:
      - Navy blue multi-row header (#1F4E79, white bold text)
      - Light blue/gray subtotal & grand total rows (#D9E1F2 / #EDEDED, bold text)
      - Zero vertical wrapping on narrow columns ('必修', '考查', '1-6学期')
      - Fits cleanly onto 1 Portrait A4 page (width ~16.0 cm, height ~22.5 cm)
    rows_data item format:
      {"type": "data" | "subtotal" | "total", "cells": [col0, col1, ..., col16]}
    """
    headers = [
        "课程\n类别", "课程\n性质", "序", "课程编码", "课程名称",
        "学\n分", "总\n学时", "理\n论", "实\n践",
        "一\n18周", "二\n18周", "三\n18周", "四\n18周", "五\n18周", "六\n18周",
        "考核\n方式", "开课\n单位"
    ]
    col_widths = [0.065, 0.042, 0.028, 0.075, 0.195, 0.035, 0.042, 0.038, 0.038,
                  0.036, 0.036, 0.036, 0.036, 0.036, 0.036, 0.045, 0.085]

    n_rows = len(rows_data) + 1
    fig_h = max(11.5, min(14.2, n_rows * 0.19 + 0.8))
    fig, ax = plt.subplots(figsize=(8.27, fig_h), dpi=300)
    ax.axis("off")

    ax.text(0.5, 0.985, title_text, fontsize=11, weight="bold", ha="center", va="top", color="#111111")

    cell_text = [headers] + [[str(x) for x in r["cells"]] for r in rows_data]
    tbl = ax.table(
        cellText=cell_text,
        colWidths=col_widths,
        loc="center",
        cellLoc="center",
        bbox=[0.01, 0.01, 0.98, 0.955],
    )
    tbl.auto_set_font_size(False)

    for (r_idx, c_idx), cell in tbl.get_celld().items():
        cell.set_edgecolor("#444444")
        cell.set_linewidth(0.45)
        if r_idx == 0:
            cell.set_facecolor("#1F4E79")
            cell.get_text().set_color("white")
            cell.get_text().set_weight("bold")
            cell.get_text().set_fontsize(6.2)
            cell.set_height(0.032)
        else:
            row_type = rows_data[r_idx - 1].get("type", "data")
            cell.set_height(0.92 / n_rows)
            cell.get_text().set_fontsize(5.8)
            if c_idx == 4 and row_type == "data":
                cell._loc = "left"
            if row_type == "subtotal":
                cell.set_facecolor("#D9E1F2")
                cell.get_text().set_weight("bold")
            elif row_type == "total":
                cell.set_facecolor("#BDD7EE")
                cell.get_text().set_weight("bold")
            else:
                cell.set_facecolor("white")

    plt.savefig(output_png_path, dpi=300, bbox_inches="tight", pad_inches=0.04)
    plt.close(fig)
```
