---
name: officecli-template-filler
description: Parse any Word or Excel reference template using OfficeCLI and Python, research national standards and institution-specific data online, solve multi-constraint curriculum tables via code, redraw broken template images, and generate a style-preserving document. Use when the user uploads or specifies a reference template such as a 40-page talent training program, course syllabus, project proposal, or form and asks to generate a customized version for a specific major, course, or organization.
---

# OfficeCLI + Python Hybrid Multi-Template Research & Generation Skill (v2.0)

Generate complete, production-grade documents from any user-provided reference template (`.docx` or `.xlsx`) by combining **OfficeCLI structural inspection & baseline validation**, **dual-track web research**, **code-driven mathematical modeling**, **automated diagram redrawing**, and **scale-aware document mutation**.

---

## Core Architecture Rule — Scale Threshold Routing (CRITICAL)

Do NOT blindly use `officecli set` in shell loops for large documents. Choose your execution engine based on template scale:

| Document / Task Scale | Execution Strategy |
|---|---|
| **Small Form / Light Edit** (`≤ 20` table cells AND `≤ 15` paragraphs, no new 50-row tables, no image redraws) | **OfficeCLI Direct Mode**: Clone template + use `officecli set / add / remove` directly. |
| **Heavy Document / Talent Training Program** (`> 20` cells OR `> 15` paragraphs, e.g., 40-page 人才培养方案, 28 course descriptions, 62×12 support matrices, 70×17 schedules, or image replacement) | **Hybrid Python-Docx Script Mode (MANDATORY)**: Use `officecli` ONLY for **Step 1 (lightweight outline/text probing + baseline schema error count)** and **Step 5 (delta validation + issue check)**. Perform all data modeling, bulk table generation, cell filling, and image replacement in a single Python script using `python-docx` and `matplotlib`. Read [references/python-docx-engine.md](references/python-docx-engine.md) for ready-to-use code templates. |

---

## Step 0 — China-Friendly & Offline-First Environment Setup

Never connect directly to `github.com` or `raw.githubusercontent.com` as the primary installation channel.
1. **Verify `officecli`**: If missing, run `scripts/ensure-officecli.ps1` (Windows) or `scripts/ensure-officecli.sh` (macOS/Linux), which checks local binaries first, then `https://d.officecli.ai`, domestic proxies (`ghfast.top`), and Taobao npm mirror (`registry.npmmirror.com`).
2. **Verify Python packages (when in Heavy Document Mode)**:
   ```powershell
   python -c "import docx, matplotlib; print('OK')" 2>$null
   if ($LASTEXITCODE -ne 0) {
       pip install python-docx matplotlib pillow -i https://pypi.tuna.tsinghua.edu.cn/simple
   }
   ```

---

## Step 1 — Lightweight Template Triage, Pitfall Audit & Baseline Snapshot

Never dump 5+ huge tables with `officecli get "/body/tbl[N]" --depth 3` (which floods context with 90KB+ of XML). Inspect compactly:

1. **Record the Baseline Validation Snapshot (Crucial for Step 5)**:
   Many real-world templates saved by WPS or older Word versions already contain 50+ harmless schema warnings (e.g., `uiPriority` order in `styles.xml`). Run validation on the untouched template first and record the baseline count:
   ```powershell
   officecli validate "$TEMPLATE"
   officecli view "$TEMPLATE" outline
   officecli view "$TEMPLATE" text --start 1 --end 120
   ```
2. **Compact Table & Image Inventory (One Python One-Liner)**:
   Instead of dumping full XML trees, run a compact probe to list every table's dimensions, first-row headers, merged-cell presence, and embedded images:
   ```python
   import docx
   doc = docx.Document(TEMPLATE)
   for i, t in enumerate(doc.tables):
       hdr = [c.text.strip().replace('\n','')[:12] for c in t.rows[0].cells[:8]]
       print(f"tbl[{i}]: {len(t.rows)}x{len(t.columns)} | {hdr}")
   ```
3. **Pre-Flight Word Structural Pitfall Audit**:
   Check for these 4 traps before writing a single line of content:
   - **Trap 1 — Auto-Numbered Paragraphs (`w:numPr`)**: Headings that visually display `"3. 本科同专业调研"` often have `p.text == "本科同专业调研"` because the number comes from XML numbering properties. **Never match paragraphs by leading numbers**; match by core text substring.
   - **Trap 2 — Merged Cells (`gridSpan` / `vMerge`)**: In `python-docx`, `row.cells[3]` on a merged row may return the exact same `_tc` object as `row.cells[2]`, causing you to overwrite a label cell (e.g., `"学分要求"`) with a number. Always deduplicate cells by `id(cell._tc)` before indexing (see helper in `references/python-docx-engine.md`).
   - **Trap 3 — Broken Manual Table of Contents (TOC)**: Check whether the template uses a manual text list with hardcoded page numbers or stale headings (e.g., `"四、学位"` already deleted from body). Plan to either sync entries to actual body headings or replace with an auto-updating Word TOC field (`updateFields=true`).
   - **Trap 4 — Placeholder or Wrong-Major Images**: Inspect all inline shapes/drawings in the template (`doc.inline_shapes` or `/word/media/*`). Classify each image into one of three actions:
     - **Action A (Redraw via Matplotlib)**: Diagrams full of `***` placeholders (e.g., 课程体系框架图, 人才培养模式图).
     - **Action B (Delete & Replace with Real Word Table)**: Screenshots/photos of another major's schedule (e.g., a photo of a Mechanical Engineering schedule pasted into an AI major template) — remove the image paragraph and insert a native, properly formatted Word table.
     - **Action C (Keep)**: Valid school logos or generic decorative banners in headers.

---

## Step 2 — Dual-Track Research & 3-Tier Anti-Hallucination Policy

Use `WebSearch` and `WebFetch` to retrieve authoritative data:
- **Track A (National Standards)**: Query Ministry of Education《职业教育专业目录》and《高等职业教育专科/本科 XXX 专业教学标准》for exact Major Code (专业代码), Major Category, Target Occupations, 1+X Certificates, Training Objectives, Graduation Specifications (素质/知识/能力), Core Courses (6–8), and Practical Training standards.
- **Track B (Institution Facts)**: Query the target institution's official website (`site:xxx.edu.cn`) for college name, program leader, laboratories, and partner enterprises.

### 3-Tier Anti-Hallucination & Deliverability Policy (No More 16 Ugly Placeholders!)
Never invent human names, but **never litter a formal deliverable with 16 raw `【待补充】` tags** either. Apply this strict 3-tier gradation:

| Tier | Field Category | Rule When Unverified Online | Example Wording in Document |
|---|---|---|---|
| **Tier 1: Strict Real-Name Slots** | Specific person names, phone numbers, official document approval numbers (专业负责人姓名、审定人签字) | Leave **at most 1–3 consolidated placeholders** in the signature/metadata block, or use clean blank underlines `________` matching formal stationery. | `专业带头人：________（由学院教务办核定签章）` |
| **Tier 2: Institutional / Team / Lab / Enterprise Slots** | Teaching team structure, research office staffing, on-campus labs, cooperative enterprises (教研室团队、校内实训基地、校企合作单位) | **Use standard normative / functional academic phrasing** aligned with national teaching standards so the document reads as a finished official draft. | Instead of `【待补充：实训室】`, write: `"依托学院人工智能综合实训中心、机器学习与数据处理实训室等校内实训基地，以及区域信息技术龙头企业校外实践基地..."` |
| **Tier 3: Survey Data & Compilation Timeline** | Industry survey metrics, graduate tracking analysis, compilation process timeline (调研数据、编制说明时间轴) | Construct **methodologically sound, realistic academic prose and timeline milestones** based on national industry reports and standard academic calendar cycles (e.g., Mar–Apr enterprise survey, May expert argumentation, Jun academic committee review). | `"调研组面向区域内 20 余家相关企事业单位发放问卷，结合教育部专业教学标准开展三轮专家论证..."` |

---

## Step 3 — Code-Driven Mathematical Solver (Data-Model-First)

For complex schedules like《课程设置及教学进程表》, **NEVER calculate hours by hand or fill cells row-by-row without a solver**. Build a Python dictionary/list data model first and run programmatic assertions to satisfy all statutory and template constraints simultaneously:

1. **Dual Credit Conversion Rules**:
   - **Regular Classroom / Lab Courses**: `1 Credit = 16 or 18 Hours` (strictly follow template divisor), and `Total Hours == Theoretical Hours + Practical Hours`.
   - **Concentrated Weekly Practice (军训、入学教育、认识实习、跟岗/顶岗实习、毕业设计)**: `1 Week = 1 Credit = 24–30 Hours` (follow template rule).
2. **Macro Statutory Ratios (Ministry of Education Vocational Standards)**:
   - **Grand Total Hours (总学时)**: Typically `≥ 2500` (3-year vocational college, usually `2500–2700`).
   - **Practical Teaching Ratio (实践教学学时占比)**: `(课内实践学时 + 集中实践/顶岗实习学时) / 总学时 ≥ 50%`.
   - **Public Foundation Courses Ratio (公共基础课程学时占比)**: `公共基础课总学时 / 总学时 ≥ 25%` (including mandatory 思想政治, 体育, 军事课, 心理健康, 劳动教育, 美育, 英语, 高数, 信息技术).
   - **Elective Courses Ratio (选修课学时占比)**: `选修课总学时 / 总学时 ≥ 10%`.
   - **Semester Weekly Load Balance (各学期周学时)**: Semesters 1–5 classroom weekly hours balanced within `22–28 学时/周`.
3. **Execution Order**: Write the Python `courses = [...]` list $\rightarrow$ run `validate_and_summarize_curriculum(courses)` (from [references/python-docx-engine.md](references/python-docx-engine.md)) until all assertions pass $\rightarrow$ auto-generate subtotal rows (必修小计、选修小计、公共课小计、专业课小计、总计) $\rightarrow$ render into the Word table in one batch.

---

## Step 4 — Content Depth Standards & Visual Asset Generation

80% of a 40-page training program is substantive academic writing. Enforce these concrete depth standards:

### 4.1 Writing Depth Specifications
1. **Graduation Requirement Specs (素质 / 知识 / 能力规格)**:
   - Provide **8–15 numbered sub-items** across Ideological/Moral Quality, Cultural/Professional Quality, Basic/Professional Knowledge, and General/Core/Comprehensive Abilities, each with a clear title (`【素质1：家国情怀与职业道德】`) and 40–80 words of measurable behavioral description.
2. **Course Descriptions (课程目标与主要教学内容, typically 20–30 courses)**:
   - Each course cell MUST contain **120–220 Chinese characters** structured in three parts:
     - `【课程目标】` (2–3 sentences covering knowledge, skill, and 课程思政/职业素养 goals);
     - `【主要内容】` (5–7 concrete modules/projects);
     - `【教学与考核要求】` (project-based teaching method, lab/software environment, formative + summative assessment weights).
3. **Course–Specification Support Matrix (课程对培养规格支撑矩阵, e.g., 62×12)**:
   - Deterministic assignment rules for **H (High / 强支撑)**, **M (Medium / 中支撑)**, **L (Low / 弱支撑)**:
     - Every graduation requirement column MUST have **at least 2–4 `H` courses**;
     - **Public Base Courses** map `H` to Ideological/Cultural/Health/General Literacy columns (`素质1–4, 知识1, 能力1`);
     - **Professional Base Courses** map `H/M` to Fundamental Professional Knowledge & Basic Technical Ability columns (`知识2–3, 能力2`);
     - **Professional Core Courses & Comprehensive Internships** map `H` to Core Occupational Abilities & Comprehensive Innovation columns (`知识4, 能力3–5`).

### 4.2 Redrawing Diagrams & Handling Landscape Wide Tables
1. **Redraw Placeholder Images (`***`) with Matplotlib**:
   - Configure CJK font fallback (`Microsoft YaHei`, `SimHei`, `PingFang SC`, `Noto Sans CJK SC`).
   - Match the aspect ratio and width of the original placeholder (`14–15 cm` width at `300 DPI` for portrait pages).
   - Replace the broken image in-place or remove the `***` paragraph and insert `p.add_run().add_picture(png_path, width=Cm(15))`.
2. **Inserting Wide Schedule Tables (70×17) with Landscape Section Breaks**:
   - When replacing a screenshot of a schedule with a real 17-column Word table, use compact font (`小五 / 9pt` or `六号 / 7.5pt`), tight cell margins, and repeat header rows (`w:tblHeader`).
   - If switching a section to Landscape (`w:orient="landscape"`), **strictly append `<w:sectPr>` as the VERY LAST child of `<w:pPr>`** (after `<w:rPr>`), using `insert_section_break_on_paragraph()` from [references/python-docx-engine.md](references/python-docx-engine.md) so OpenXML schema order is never violated.

---

## Step 5 — Environment-Aware QA & Baseline-Delta Validation

Do NOT run commands that hang when Microsoft Word or a headless browser is absent.

1. **Banned / Unsafe Commands in Headless or WPS-Only Environments**:
   - **DO NOT run `officecli refresh`** (invokes COM/Word automation and hangs for 180s on WPS-only machines). Instead, set `<w:updateFields w:val="true"/>` in `settings.xml` (`officecli set "$FILE" /settings --prop updateFields=true`) and inform the user to press `Ctrl+A` then `F9` if page numbers need refreshing.
   - **DO NOT rely on `officecli view pdf` or `officecli view screenshot`** unless you have verified exporter plugins exist.
2. **Baseline-Delta Validation (`Δ Schema Errors ≤ 0`)**:
   Run `officecli validate "$FILE"` and `officecli view "$FILE" issues` on the generated document and compare against the **Step 1 Baseline Snapshot**:
   - **Pass Criterion**: `New_Schema_Errors <= Baseline_Schema_Errors` (zero newly introduced XML schema errors) AND `0` leftover `***` or wrong-major text in the document.
3. **Programmatic Post-Flight Audit (Python)**:
   Run a quick verification check in Python before finishing:
   - Confirm 0 occurrences of `***`, `数控机床` (or other template-polluting major terms), or raw unformatted `TODO` strings;
   - Confirm every table has non-empty cells in required columns;
   - Confirm TOC entries match actual body headings.
4. **Delivery Protocol**:
   - If the `present_files` tool is available in the runtime environment, call `present_files` to surface the generated `.docx`. Otherwise, provide the clickable file reference (`computer://...` or workspace path) according to system rules.
   - Output a concise **Engineering & Academic Audit Summary**:
     - **Scale & Engine Used**: Total paragraphs, tables, cells populated, and diagrams redrawn.
     - **19-Constraint Curriculum Solver Result**: Grand total hours, credits, practice ratio (`≥50%`), public base ratio (`≥25%`), elective ratio (`≥10%`), and semester weekly load range.
     - **Baseline vs. Final Validation**: `Baseline Errors: N -> Final Errors: N (Δ = 0)`.
     - **3-Tier Localization Summary**: List the 1–3 signature/person slots left as `________` for administrative sign-off.
