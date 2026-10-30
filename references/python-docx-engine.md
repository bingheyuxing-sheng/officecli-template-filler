# Python-Docx Heavy Template Engine & Word XML Pitfall Recipes

When a template requires modifying **> 20 table cells**, **> 15 paragraphs**, **building multi-row schedules (e.g., 60×17 teaching plans)**, or **replacing placeholder images**, do NOT invoke `officecli set` hundreds of times in a shell loop. Use this Python engine pattern instead, while keeping `officecli` for pre-flight structure inspection and post-flight delta validation.

---

## 1. Environment Check for Python Libraries

```powershell
python -c "import docx, matplotlib; print('OK')" 2>$null
if ($LASTEXITCODE -ne 0) {
    pip install python-docx matplotlib pillow -i https://pypi.tuna.tsinghua.edu.cn/simple
}
```

---

## 2. Core Pitfall Helpers (`docx_helpers.py` pattern)

Copy these helper functions into your generation script to avoid the three classic OpenXML traps:

### Trap A: Merged Cells (`row.cells` returns duplicate `<w:tc>` references)
Writing `row.cells[col_idx].text = val` on a row with horizontal/vertical merges will overwrite adjacent label cells because `row.cells` repeats the same underlying `_tc` object for every spanned grid column.

```python
from docx.oxml.ns import qn
from copy import deepcopy

def get_unique_row_cells(row):
    """Return distinct Cell objects in visual left-to-right order (skips merged duplicates)."""
    seen_tcs = set()
    unique_cells = []
    for cell in row.cells:
        tc_id = id(cell._tc)
        if tc_id not in seen_tcs:
            seen_tcs.add(tc_id)
            unique_cells.append(cell)
    return unique_cells

def set_cell_text_preserve_style(cell, text: str):
    """Replace cell text while preserving the first paragraph's alignment and first run's font/size."""
    if not cell.paragraphs:
        cell.text = str(text)
        return
    p0 = cell.paragraphs[0]
    # Preserve first run's rPr if available
    saved_rPr = None
    if p0.runs and p0.runs[0]._r.rPr is not None:
        saved_rPr = deepcopy(p0.runs[0]._r.rPr)
    # Remove extra paragraphs in cell
    for p in cell.paragraphs[1:]:
        p._element.getparent().remove(p._element)
    # Clear existing runs in p0
    for r in list(p0.runs):
        r._r.getparent().remove(r._r)
    lines = str(text).split("\n")
    for idx, line in enumerate(lines):
        if idx > 0:
            p0.add_run().add_break()
        run = p0.add_run(line)
        if saved_rPr is not None:
            run._r.insert(0, deepcopy(saved_rPr))
```

### Trap B: Auto-Numbered Paragraphs (`w:numPr` hides `"1."`, `"3."` from `p.text`)
In Word, a heading that visually reads `"3. 本科同专业调研"` often has `p.text == "本科同专业调研"` because `"3."` is generated dynamically by `<w:numPr>`. Never match headings by leading numbers.

```python
import re

def find_paragraph_by_core_text(doc, keyword: str):
    """Match paragraph ignoring leading numbering, spaces, and full-width punctuation."""
    clean_kw = re.sub(r'^[\d一二三四五六七八九十]+[\.、\s）\)]*', '', keyword).strip()
    for i, p in enumerate(doc.paragraphs):
        clean_p = re.sub(r'^[\d一二三四五六七八九十]+[\.、\s）\)]*', '', p.text).strip()
        if clean_kw in clean_p:
            return i, p
    return -1, None
```

### Trap C: Landscape Section Breaks & OpenXML `<w:pPr>` Schema Order
In `CT_PPr` (`<w:pPr>`), `<w:sectPr>` **MUST be the very last child element** (specifically, `<w:rPr>` must appear *before* `<w:sectPr>`). Appending `rPr` after `sectPr` triggers OpenXML schema validation errors (`Invalid child element rPr`).

```python
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

def insert_section_break_on_paragraph(paragraph, orient="landscape", page_w_twips=16838, page_h_twips=11906):
    """
    Safely attach a sectPr to `paragraph` as the LAST child of w:pPr.
    Default twips are A4 Landscape (29.7cm x 21.0cm -> 16838 x 11906).
    For A4 Portrait restoration, pass orient="portrait", page_w_twips=11906, page_h_twips=16838.
    """
    pPr = paragraph._p.get_or_add_pPr()
    # Remove any existing sectPr first so the new one is guaranteed to be appended at the very end
    existing = pPr.find(qn('w:sectPr'))
    if existing is not None:
        pPr.remove(existing)

    sectPr = OxmlElement('w:sectPr')
    pgSz = OxmlElement('w:pgSz')
    pgSz.set(qn('w:w'), str(page_w_twips))
    pgSz.set(qn('w:h'), str(page_h_twips))
    if orient == "landscape":
        pgSz.set(qn('w:orient'), 'landscape')
    sectPr.append(pgSz)

    pgMar = OxmlElement('w:pgMar')
    for k, v in [('top', '1134'), ('right', '1134'), ('bottom', '1134'), ('left', '1134'),
                 ('header', '851'), ('footer', '992'), ('gutter', '0')]:
        pgMar.set(qn(f'w:{k}'), v)
    sectPr.append(pgMar)

    # Append as the LAST child of pPr (after pStyle, numPr, spacing, ind, rPr)
    pPr.append(sectPr)
```

---

## 3. Data-Model-First Solver for Curriculum Schedule (19 Constraints)

Never fill curriculum tables by hand or row-by-row guessing. Build a Python list of dicts, run `assert_curriculum_constraints()`, and only render into `.docx` after all assertions pass.

```python
def validate_and_summarize_curriculum(courses, total_weeks_per_term=(16, 18, 18, 18, 18, 0)):
    """
    Each item in `courses` is a dict:
    {
        "category": "公共基础必修" | "公共基础选修" | "专业基础" | "专业核心" | "专业拓展选修" | "集中实践",
        "code": "010101",
        "name": "高等数学",
        "nature": "必修" | "选修",
        "exam_term": "1",
        "credits": 4.0,
        "total_hours": 64,
        "theory_hours": 56,
        "practice_hours": 8,
        "is_weekly_practice": False, # True for 军训/认识实习/岗位实习 where 1 week = 1 credit (24-30h)
        "term_weekly_hours": [4, 0, 0, 0, 0, 0], # Weekly class hours in semesters 1..6
    }
    """
    grand_hours = sum(c["total_hours"] for c in courses)
    grand_credits = sum(c["credits"] for c in courses)
    grand_theory = sum(c["theory_hours"] for c in courses)
    grand_practice = sum(c["practice_hours"] for c in courses)

    # 1. Row-level identity: total == theory + practice
    for c in courses:
        assert c["total_hours"] == c["theory_hours"] + c["practice_hours"], f"Hours mismatch in {c['name']}"
        if not c.get("is_weekly_practice", False):
            # Standard course: 16 or 18 hours = 1 credit
            expected_cr = round(c["total_hours"] / 16.0, 1)
            assert abs(c["credits"] - expected_cr) <= 0.5, f"Credit ratio mismatch in {c['name']}"

    # 2. Macro statutory ratios (Ministry of Education Vocational Standards)
    pub_hours = sum(c["total_hours"] for c in courses if "公共基础" in c["category"])
    elec_hours = sum(c["total_hours"] for c in courses if c["nature"] == "选修")
    practice_ratio = grand_practice / grand_hours
    pub_ratio = pub_hours / grand_hours
    elec_ratio = elec_hours / grand_hours

    assert grand_hours >= 2500, f"Total hours {grand_hours} < 2500 minimum"
    assert practice_ratio >= 0.50, f"Practice ratio {practice_ratio:.1%} < 50%"
    assert pub_ratio >= 0.25, f"Public course ratio {pub_ratio:.1%} < 25%"
    assert elec_ratio >= 0.10, f"Elective ratio {elec_ratio:.1%} < 10%"

    # 3. Weekly load balance (Semesters 1-5 typically 22-28 hours/week)
    term_loads = [
        sum(c["term_weekly_hours"][t] for c in courses if not c.get("is_weekly_practice", False))
        for t in range(5)
    ]
    for t_idx, load in enumerate(term_loads, 1):
        assert 20 <= load <= 30, f"Semester {t_idx} weekly hours ({load}) out of balanced range [20, 30]"

    return {
        "grand_hours": grand_hours,
        "grand_credits": grand_credits,
        "grand_theory": grand_theory,
        "grand_practice": grand_practice,
        "practice_ratio": f"{practice_ratio * 100:.1f}%",
        "pub_ratio": f"{pub_ratio * 100:.1f}%",
        "elec_ratio": f"{elec_ratio * 100:.1f}%",
        "term_loads": term_loads,
    }
```

---

## 4. Redrawing Placeholder Diagrams with Matplotlib (Chinese Font Safe)

Templates often contain broken placeholder images (`***`) or screenshots copied from unrelated majors. Generate clean diagrams using `matplotlib` with built-in Windows/macOS/Linux CJK fonts:

```python
import matplotlib.pyplot as plt
import matplotlib.patches as patches

# Safe CJK font fallback chain (Windows SimHei/Microsoft YaHei, macOS PingFang, Linux Noto)
plt.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei', 'PingFang SC', 'Noto Sans CJK SC', 'DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False

def draw_curriculum_architecture_diagram(output_png_path: str, major_name: str, core_courses: list):
    """Draw a clean 3-layer curriculum system diagram matching typical Word page width (15cm x 8.5cm, 300 DPI)."""
    fig, ax = plt.subplots(figsize=(10, 5.6), dpi=300)
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 6)
    ax.axis('off')

    # Title banner
    ax.add_patch(patches.FancyBboxPatch((0.5, 5.1), 9.0, 0.65, boxstyle="round,pad=0.08", fc="#1F4E79", ec="none"))
    ax.text(5.0, 5.42, f"{major_name}专业课程体系与能力递进结构图", color="white", fontsize=13, weight="bold", ha="center", va="center")

    layers = [
        (3.6, "#D9E1F2", "#2F5597", "高阶综合与岗位实践层（第5-6学期）", ["专业拓展选修课群", "综合项目实训", "毕业设计（论文）", "顶岗/岗位实习（6个月）"]),
        (2.0, "#E2EFDA", "#385723", "核心技能与1+X证书融通层（第3-4学期）", core_courses[:6]),
        (0.4, "#FFF2CC", "#806000", "公共素养与专业基础层（第1-2学期）", ["思想政治与职业素养", "高等数学/英语/体育", "计算机与人工智能导论", "专业基础核心课群"]),
    ]

    for y, bg, border, title, items in layers:
        ax.add_patch(patches.FancyBboxPatch((0.5, y), 9.0, 1.3, boxstyle="round,pad=0.06", fc=bg, ec=border, lw=1.5))
        ax.text(5.0, y + 1.02, title, color=border, fontsize=10.5, weight="bold", ha="center", va="center")
        n = len(items)
        box_w = 8.4 / n - 0.15
        for i, item in enumerate(items):
            bx = 0.75 + i * (box_w + 0.15)
            ax.add_patch(patches.FancyBboxPatch((bx, y + 0.15), box_w, 0.62, boxstyle="round,pad=0.04", fc="white", ec=border, lw=1))
            ax.text(bx + box_w / 2, y + 0.46, item, color="#222222", fontsize=8.5, ha="center", va="center", wrap=True)

    plt.tight_layout()
    plt.savefig(output_png_path, dpi=300, bbox_inches='tight')
    plt.close(fig)
```
