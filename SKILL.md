---
name: officecli-template-filler
description: Parse any Word (.docx) or Excel (.xlsx) reference template using OfficeCLI and Python, exhaustively research authoritative standards and organization facts online, ask the user ONCE with smart defaults ONLY for unsearchable internal facts before writing, lock all data via a Single-Source-of-Truth mathematical solver, and generate a document with 100% zero-diff template formatting. Use when the user uploads or specifies ANY reference template and asks to generate a customized version.
---

# OfficeCLI + Python Universal Template Filler Skill (v2.4 — Zero-Format-Diff & Research-First-Ask-Once)

Follow three iron laws across **every** `.docx` and `.xlsx` reference template:
1. **Minimize User Effort (AI Researches 95% First)**: Deeply parse the template and exhaustively search official standards and institution websites FIRST. Never bother the user with questions that can be found online or derived from domain standards.
2. **Pre-Write Confirmation Gate for Unsearchable Facts (Ask Once, Then Write)**: For internal facts that genuinely cannot be found online or are ambiguous (e.g., internal project leader name, unannounced partner enterprises, actual survey headcount, or whether unverified slots should use standard normative defaults), present a **single, consolidated Pre-Write Confirmation Card** (with ready-to-use default options so the user can also just reply "按默认生成"). **Wait until all information is confirmed before generating the document—never guess, fabricate, or leave ugly surprises.**
3. **100% Identical Formatting to the Template (Zero Format Diff)**: The generated document MUST be visually and structurally indistinguishable in formatting from the reference template—preserving exact fonts (`rFonts`), font sizes (`sz`/`szCs`), colors (`color`, with red instruction colors stripped), alignments (`jc`), line/paragraph spacing (`spacing`/`ind`), cell widths (`gridCol`/`tcW`), cell margins, borders, shading (`shd`), and page orientation (`sectPr`).

---

## Core Architecture Rule 1 — Scale Threshold Routing

| Document / Task Scale | Execution Strategy |
|---|---|
| **Small Form / Light Edit** (`≤ 20` cells AND `≤ 15` paragraphs, no new multi-row tables, no image redraws) | **OfficeCLI Direct Mode**: Clone template + use `officecli set / add / remove` directly while preserving node properties. |
| **Heavy Document / Multi-Table Template** (`> 20` cells OR `> 15` paragraphs, e.g., 20–60 page 人才培养方案/申报书/标书/可行性报告, multi-item tables, NxM matrices, multi-sheet Excel workbooks, or image replacement) | **Hybrid Python Script Mode (MANDATORY)**: Use `officecli` for **Phase 1 (baseline schema snapshot & outline)** and **Phase 6 (delta validation)**. Perform all style-cloning mutations, mathematical solving, and format-diff assertions in Python (`python-docx` / `openpyxl` + `matplotlib`). See [references/python-docx-engine.md](references/python-docx-engine.md). |

---

## Core Architecture Rule 2 — Template-Driven Domain & Archetype Inference

After inspecting the template outline and table headers in Phase 1, classify the template into its **Archetype** to guide web research and mathematical modeling:

| Archetype | Typical Templates | Authoritative Standards to Research First | Core Mathematical / Logical Model |
|---|---|---|---|
| **A. Curriculum & Education** | 人才培养方案、课程标准/教学大纲、专业建设方案、教材申报表 | 教育部《职业教育专业目录》《专业教学标准》《课程思政指南》、国家职业技能标准/1+X标准 | 学分-学时换算、总学时与理论/实践/选修/公共课占比约束、各学期周学时均衡、跨表（总要求表/分配表/进程表）同源一致 |
| **B. Project Proposal & Grant / Bidding** | 科研/教改项目申报书、可行性研究报告、招投标技术标书、建设方案 | 国家/省部级申报指南、行业技术规范（GB/T、ISO）、政府采购与招投标规范 | 经费预算表（直接费用+间接费用=总额，分项上限比）、建设周期甘特图/里程碑闭环、跨表预算总额一致 |
| **C. Enterprise Operations & Quality / Audit** | 评估自评报告、立项审批表、标准作业程序(SOP)、年度总结与规划 | 行业监管标准、内控合规指引、质量管理体系规范 | 指标达成率（现状值+增量=目标值）、责任部门-任务-时间节点映射、资源投入产出比配平 |
| **D. Financial & Statistical Workbook (`.xlsx`)** | 预算决算表、排课总表、资产清册、成本测算表 | 财会准则、税率标准、统计口径规范 | 行列双向汇总恒等式（`SUM`/`SUBTOTAL`）、跨 Sheet 引用一致性、百分比列求和为 `100.0%` |

---

## Phase 0 — China-Friendly & Offline-First Environment Setup

Never connect directly to `github.com` or `raw.githubusercontent.com` as the primary channel.
1. **Verify `officecli`**: If missing, run `scripts/ensure-officecli.ps1` (Windows) or `scripts/ensure-officecli.sh` (macOS/Linux).
2. **Verify Python packages (Heavy Document Mode)**:
   ```powershell
   python -c "import docx, openpyxl, matplotlib; print('OK')" 2>$null
   if ($LASTEXITCODE -ne 0) {
       pip install python-docx openpyxl matplotlib pillow -i https://pypi.tuna.tsinghua.edu.cn/simple
   }
   ```

---

## Phase 1 — Deep Template Parsing, Style Fingerprint & Red-Font / Capacity Scan

Before searching the web or asking the user anything, thoroughly understand the template's structure, rules, and formatting baseline:

1. **Baseline Schema Snapshot**:
   Run `officecli validate "$TEMPLATE"` and `officecli view "$TEMPLATE" outline` to record preexisting WPS/Word schema warnings (`Baseline_Schema_Errors`).
2. **Full Style Fingerprint, Red-Font Instruction Scan & Cell Capacity Profile**:
   Run `scan_red_runs_and_cell_capacities(doc)` from [references/python-docx-engine.md](references/python-docx-engine.md) to extract:
   - **All Red-Font Runs (`EE0000` / `FF0000` / `C00000`)**: Every red instruction in body paragraphs and table cells tells you *what rule the template author expects* (e.g., credit divisors, minimum ratios, required sections) and *where placeholders live*.
   - **Physical Cell Capacity Profile**: Record sample character counts, column widths (`gridCol` / `tcW`), row heights (`trHeight`), fonts (`rFonts`), font sizes (`sz`), alignments (`jc`), and cell shadings (`shd`) for every table.
   - **Template Residue Blacklist**: Extract example keywords from the reference template (e.g., `"数控机床"`, `"液压"`, `"本科"`, `"***"`, `"XXXX"`) so they can be 100% purged later.
   - **Structural Traps**: Detect auto-numbered headings (`w:numPr`), merged cells (`gridSpan`/`vMerge`), broken manual TOCs, and placeholder/wrong-major images (`doc.inline_shapes`).

---

## Phase 2 — Exhaustive Dual-Track Web Research (AI Does Maximum Work First)

Do NOT ask the user for information that can be found online! Execute thorough web searches (`WebSearch` / `WebFetch`) across two tracks:
- **Track A (Authoritative National / Industry Standards)**: Retrieve official codes, standard curriculum/project modules, mandatory ratios, qualification certificates, and technical specifications.
- **Track B (Target Organization / Institution Official Website)**: Search the target school/company/institute's official site for secondary department/college names, existing laboratories/platforms, regional industry positioning, and publicly announced cooperative enterprises.

Classify every slot required by the template into two buckets:
- **Bucket 1 — Verified & Resolved (90%–95% of the document)**: Facts found online or governed by national/industry standards.
- **Bucket 2 — Unsearchable / Ambiguous Internal Facts (5%–10% of the document)**: Specific internal data that cannot be verified online (e.g., specific person names, internal approval numbers, unannounced partner companies, actual survey questionnaire counts, or ambiguous user requirements).

---

## Phase 3 — Pre-Write Gap Resolution Gate (Ask User ONCE with Smart Defaults)

**CRITICAL RULE**: Never silently fabricate unsearchable facts (like fake company visits or fake survey counts), and never dump 16 ugly `【待补充】` tags without asking. **Before generating the final document**, if Bucket 2 (unsearchable/ambiguous items) is non-empty:

1. **Present a Concise "Research Summary & Missing Info Confirmation" to the User** (use `AskUserQuestion` when structured choices fit, or a compact numbered list):
   - **Part A — What AI Already Found & Locked In**: Briefly show the verified major/project code, college/department name, core modules/courses, and mathematical target ratios so the user sees 95% of the work is already done.
   - **Part B — Only the Unsearchable / Ambiguous Items Needing User Input**: Group missing items into 2–4 clear questions, and **always provide a "One-Click Low-Effort Option"**:
     - *Option 1 (User Provides Exact Info)*: User types the real leader name, partner company names, or survey data;
     - *Option 2 (Leave Clean Formal Blank `________`)*: For signature/name/ID fields to be filled by administration later;
     - *Option 3 (Use Standard Normative Phrasing — Recommended for effortless draft)*: Fill team/facility/process sections with compliant generic phrasing (no fake specific numbers or fake company names).
2. **Wait for User Confirmation**: Once the user supplies the missing items or selects the default option, **100% of the document's content is now deterministic**. Proceed immediately to Phase 4 & Phase 5. *(Exception: Only if the user explicitly says "直接生成/不用问我/全按默认" in their very first prompt may you skip pausing at Phase 3 and apply Option 2/3 defaults directly.)*

---

## Phase 4 — Single-Source-of-Truth (SSOT) Mathematical Solver

Before writing any paragraph or table cell, build ONE master Python data structure (`master_data`) and run programmatic assertions:
1. **Single Source of Truth (SSOT)**:
   - Derive **every** summary number (e.g., Table 2 Graduation Credit Requirements, Table 6 Credit/Hour Allocation Summary, Table 7 Full Teaching Schedule, and Body Text Summary Paragraphs; or Budget Summary and Detailed Budget Table) from the exact same `master_data` dictionary.
   - **Never calculate or hardcode numbers separately across different tables!**
2. **Zero-Error Constraint Assertions**:
   - Verify row-level sums (`total == sum(parts)`), column-level subtotals/grand totals, largest-remainder percentage closure (`sum(pcts) == 100.0%`), statutory/template footnote ratios (e.g., total hours `≥2500`, practice `≥50%`, public `≥25%`, elective `≥10%`, weekly load `22–28`), and cross-table equality assertions.

---

## Phase 5 — Zero-Format-Diff Document Generation & Capacity-Matched Writing

**THE GOLDEN RULE OF FORMATTING**: Never invent your own styles! Every paragraph, run, table, row, and cell in the generated file MUST inherit its exact OpenXML formatting from the template.

### 5.1 Strict Style-Cloning Execution Rules (MANDATORY)
1. **Clone the Template File First**: Always start by copying the original `.docx` / `.xlsx` file (`shutil.copyfile(template_path, output_path)`), preserving the entire `styles.xml`, `numbering.xml`, `theme1.xml`, headers, footers, and page margins.
2. **Fill Table Cells via `fill_cell_strict_style()` (Never Bare `.text =` or Unstyled Runs)**:
   - Deduplicate merged cells via `get_unique_row_cells(row)` (`id(cell._tc)`) so you never overwrite adjacent label cells.
   - Preserve the cell's existing `<w:pPr>` (alignment `jc`, line spacing, indentation) and `<w:rPr>` (font family `rFonts`, East Asian font, font size `sz`/`szCs`, bold `b`).
   - **Empty Cell `<w:pPr><w:rPr>` Trap (CRITICAL)**: In Word OpenXML, blank template cells have **no `<w:r>` runs**—their font (`宋体 小五`, `sz=18`) is stored inside the paragraph mark's `<w:pPr><w:rPr>`! If you only check `p.runs`, `extract_donor_style_from_table()` returns `None` on empty columns and Word falls back to the ugly theme font `等线 (正文) 11` or `Times New Roman`. Always inspect **both `run._r.rPr` AND `p._p.pPr.find(qn('w:rPr'))`** (plus row 0 header `rPr` with `<w:b>` stripped as fallback), and explicitly lock all 4 font slots (`w:ascii`, `w:hAnsi`, `w:eastAsia`, `w:cs`).
3. **Strip Red Placeholder Color (`<w:color>`) Upon Replacement**:
   - When replacing red instruction/placeholder text (`EE0000`, `FF0000`, `C00000`), remove `<w:color>` from the cloned `rPr` while keeping all other `rPr` children (`rFonts`, `sz`, `szCs`, `b`) untouched.
4. **Lock Table Layout to `fixed` & Clone-Append Rows**:
   - Set `<w:tblLayout w:type="fixed"/>` on modified tables without touching `tblW`, `tblGrid`, `gridCol`, `tcW`, or `shd` so WPS/Word never scrambles column widths.
   - When adding or deleting rows to match item counts, always **deep-copy an existing template data row (`deepcopy(template_row._tr)`)** via `clone_append_table_row()` so row height (`trHeight`), cell borders, shading, and cell widths (`tcW`) remain 100% identical to the template.
5. **Respect Physical Cell Capacity & Compact Empty-Row Density (Never Deform Table Layout)**:
   - Match your writing length to each cell's physical capacity and page row density profiled in Phase 1:
     - **Compact Multi-Row Grid Table (template shows `10–15` empty rows per page, e.g., 课程主要内容表 / 进度表)**: Strictly cap cell text to **`25–45` chars** (`1–2` lines at `宋体 小五 9pt`) so each page still holds `10–13` rows just like the template—never stuff `100–200` chars into a compact grid cell and blow 1 page into 5 pages!
     - **Medium Grid Cell (template sample `30–60` chars)**: Write `35–65` chars of high-density phrases.
     - **Large Narrative Cell / Dedicated Card (template sample `120–250` chars or 1–2 rows per page)**: Write full structured content (`【课程/模块目标】` + `【主要内容】` + `【教学/考核要求】`).
6. **Redraw Broken Placeholder Images & Full-Page Schedule Table Images (1:1 Visual Match)**:
   - Redraw `***` placeholder diagrams using `matplotlib` (`300 DPI`, matching original placeholder width and CJK fonts).
   - **Full-Page Schedule Table Image Trap (e.g., Section 八《教学进程总体安排表》)**: Many templates embed the 60-row × 17-column master schedule table as a **single full-page high-res image** (with `#1F4E79` navy headers, hierarchical category merges, and `#D9E1F2` gray subtotal rows fitting cleanly on 1 portrait page). If you replace it with an unstyled 15-col native Word table on a portrait page, narrow columns (`必修`/`考查`) wrap vertically into 3 lines per row, fonts fall back to `Times New Roman`, and a 1-page table explodes into 5 pages!
     - **Default Strategy (100% Visual Identity)**: Use `render_schedule_table_as_single_page_image()` (in [references/python-docx-engine.md](references/python-docx-engine.md)) to render the exact 17-column table (including `课程类别`、`课程性质`、`序`、`课程编码`、`课程名称`、学分学时、1–6学期周学时、考核方式、开课单位, plus all category `小计` rows and `合计`/`占比`) as a crisp `300 DPI` full-page image and replace the template's `inline_shape` in-place so it stays on **1 single portrait page** exactly like the template.
     - **Optional Native Table Strategy**: Only if the user explicitly requests an editable native Word table for the wide schedule, isolate it in a **Portrait `sectPr` $\rightarrow$ Landscape Wide Table $\rightarrow$ Landscape `sectPr`** section sandwich (`attach_section_break_safe()`), set explicit `w:tcW` twips so 2-char columns (`必修`/`考查`) never wrap vertically, lock `w:eastAsia="宋体"`, and include all hierarchical `小计` rows.

---

## Phase 6 — Automated Format-Diff QA & Text-Residue QA (Zero Tolerance)

Before delivering the file, you MUST run `audit_format_and_text_qa(template_path, output_path, forbidden_residues)` from [references/python-docx-engine.md](references/python-docx-engine.md) and fix any reported diff until all 5 gates pass with **0 errors**:

1. **Gate 1 — Table Format-Diff == 0**:
   - Every preserved table's `w:gridCol` column widths, `w:tcW` distributions, dominant data-row font size (`w:sz`), font family (`w:rFonts`), paragraph alignment (`w:jc`), and background shading (`w:shd`) MUST match the template (`Diff = 0`).
2. **Gate 2 — Red-Font Residue == 0**:
   - Confirm `0` runs with red placeholder colors (`EE0000`, `FF0000`, `C00000`, `FF3300`) remain anywhere in body paragraphs or tables.
3. **Gate 3 — Template Example Residue == 0**:
   - Confirm `0` occurrences of template-polluting strings (`***`, `****`, `数控机床`, `液压`, `本科`, `XXXX`, or any example text from the original template).
4. **Gate 4 — Cross-Table Mathematical Identity**:
   - Confirm all cross-referenced tables and body text totals match 100%.
5. **Gate 5 — OpenXML Schema Delta ≤ 0 & Safe TOC Setting**:
   - Run `officecli validate "$OUTPUT"` and confirm `Final_Schema_Errors <= Baseline_Schema_Errors`.
   - Set `<w:updateFields w:val="true"/>` for TOC fields (never run `officecli refresh` on WPS-only machines) and remind the user to press `Ctrl+A` then `F9` after opening to refresh exact page numbers.
