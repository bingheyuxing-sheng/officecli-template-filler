---
name: officecli-template-filler
description: Office Document Intelligence engine for Word (.docx) and Excel (.xlsx/.xlsm) templates. Routes tasks via an 8-mode Task Router (GENERATE, POLISH, REPAIR, REVIEW, MERGE, REFORMAT, EXCEL_GENERATE, PROOFREAD), classifies template compatibility (L1-L4), and applies non-destructive cross-run replacement, Decimal SSOT solving, MIME/reference-counted image replacement, PID-scoped resource cleanup with proof-based ownership, and Package plus Format/Font/Table/Layout QA. REVIEW and PROOFREAD write native Word tracked changes (w:ins/w:del plus w:*PrChange format revisions) and comments so a human accepts or rejects every change. L1-L3 targets Zero Unintended Formatting Delta; L4 objects are preserved read-only and reported in coverage_gaps rather than claimed as 100 percent fidelity.
---

# OfficeCLI + Python Office Document Intelligence Skill (v3.5.8 — Content Truth QA, SVG/VML Image Truth, Fact Provenance, REFORMAT Diff Plan, WPS PDF Path)

Follow six architectural pillars across **every** `.docx` and `.xlsx` document task:

1. **Task Router First (8 Specialized Modes & Context-Aware Web Search Policy)**:
   Always classify the user's input files and prompt into one of eight execution modes (`GENERATE`, `POLISH`, `REPAIR`, `REVIEW`, `MERGE`, `REFORMAT`, `EXCEL_GENERATE`, `PROOFREAD`) via `engine.docx_parser.route_document_task()` before taking action. Web search is **enabled by default ONLY for `GENERATE` / `EXCEL_GENERATE`** when domain standards or public institution facts are needed, and **disabled by default for `REPAIR`, `REVIEW`, `POLISH`, `MERGE`, `REFORMAT`, and `PROOFREAD`** (unless the user explicitly requests external fact verification).
2. **4-Tier User Confirmation Gate (`SKIP`, `LIGHT_CONFIRM`, `FULL_CONFIRM`, `HOLD_AND_ASK`)**:
   Tailor user interaction to task certainty:
   - **`SKIP`**: User explicitly says "直接生成/按默认生成", or task is pure `REPAIR`/`REFORMAT` with 100% deterministic content and compatible structures.
   - **`LIGHT_CONFIRM`**: Minor optional slots or low-impact formatting choices exist; present a compact 1–2 item summary with smart defaults.
   - **`FULL_CONFIRM`**: Unsearchable internal facts exist in `GENERATE`/`EXCEL_GENERATE` (e.g., project leader name, unannounced partner companies, internal approval IDs); present a consolidated Pre-Write Confirmation Card once with one-click normative defaults.
   - **`HOLD_AND_ASK`**: High-risk `L4` structural unsupported elements (e.g., SmartArt/OLE/Chart binary data mutation, password-protected VBA macros) or conflicting dual-document structures are detected; pause and ask the user how to handle those specific regions before writing.
3. **Execution Profile Gate (`FAST`, `STANDARD`, `FULL`)**:
   For `GENERATE` and `EXCEL_GENERATE`, choose the workload before writing. Ask once with the compact choices **快速填专业内容 / 标准完整成稿 / 含图表精修** unless the user already selected a profile. `FAST` replaces confirmed placeholders only and does not rebuild tables or images; `STANDARD` fills all supported paragraphs and native tables and runs semantic plus mathematical QA; `FULL` additionally redraws placeholder/sample images, rebuilds schedule visuals when required, performs staged rendering, and runs multi-pass visual QA. The profile changes scope, never safety: Package QA, SSOT validation, transaction commit, and honest `coverage_gaps` reporting remain mandatory in all profiles.
4. **Template Compatibility Level Classification (`L1`–`L4`)**:
   Every template is automatically profiled into `L1` (Standard), `L2` (Moderately Complex), `L3` (Complex Styled), or `L4` (Manual Confirmation Required) via `engine.docx_parser.assess_template_compatibility_level()` and output as a formal `DocumentSpec` (`schemas/document_spec.schema.json`).
5. **Modular, Unit-Tested Python Engine (`engine/` + `scripts/`) — Never Reinvent Ad-Hoc Helpers**:
   All core OOXML, Decimal SSOT, Table, Image, Excel, Repair, Process Guard, and QA algorithms reside in standalone, unit-tested Python modules under `engine/` with CLI entrypoints in `scripts/`. Never write ad-hoc destructive `set_par_text` or `taskkill /F /IM` commands.
   **Validation never uses `assert`**: `python -O` strips assertions, so every quality gate raises a real exception instead — `SSOTValidationError` from `engine.ssot_engine` and `QAValidationError` from `engine.qa_engine`. Pass `raise_on_failure=False` to `audit_format_and_text_qa()` when a structured `{"passed": false, "issues": [...]}` report is preferred over an exception.
   **Universal process cleanup (applies to ALL eight modes, not only red-text QA)**: the cleanup is automatic, not a manual step. Every document-processing entrypoint (`inspect_document`, `analyze_template`, `analyze_excel_template`, `generate_document`, `generate_excel`, `repair_document`, `review_document`, `proofread_document`, `render_document`, `run_qa`) calls `install_auto_cleanup()` on startup, which snapshots live `editor_sdk.exe` identities `(pid, image, creation time)` and registers an exit hook that terminates only PIDs explicitly recorded as spawned by the task. A process that merely appeared after the snapshot is reported in `unowned_pids` and left running, because a concurrent task may own it; an owned candidate whose creation time cannot be read is reported in `unreleased_pids` instead of being killed on a guess. Each task writes `officecli_editor_sdk_cleanup_<task_id>.json` (plus the shared latest log) so concurrent tasks never overwrite each other's evidence. WorkBuddy's sandbox keeps `editor_sdk.exe` alive after an agent turn, which is exactly what leaves the DOCX locked in WPS, so never skip this and never ask the user to run a cleanup command.
6. **Zero Unintended Formatting Delta + Package & Visual QA (with honest coverage reporting)**:
   Deliver documents that preserve every unmapped style, run property, `<w:proofErr>` node, complex cell structure, shared image `rId`, and Excel formula, verified by `audit_docx_package_integrity()`, `audit_format_and_text_qa()`, `run_visual_layout_qa()`, and `audit_excel_formula_and_style_qa()`.
   This is a guarantee about **unintended** changes only. Never claim 100% byte-identical rendering versus Word/WPS: list every unsupported object in `coverage_gaps` and never treat "not detected" as "passed".
   Font size is verified per run against the **matched** template paragraph/table: always call `audit_format_and_text_qa(..., reference_docx_path=template_path, comparison_profile="STYLE_GUIDE")` for GENERATE (or `scripts/run_qa.py output.docx --reference template.docx --profile style-guide`). The effective size cascade is run `w:sz` -> character style -> paragraph style -> `w:docDefaults`. `STYLE_GUIDE` skips size comparison for unmatched/new paragraphs and new tables; `REPLICA` keeps the strict template baseline for REPAIR/REVIEW.
   Font family and table structure are verified the same way, and they are NOT covered by size checks:
   - Fonts resolve through run `w:rFonts` -> character style -> paragraph style -> `w:docDefaults`, then compare against the matched paragraph's font set (`font_anomalies`). Chinese family names are normalized against Windows' English registry names (`黑体` ↔ `SimHei`, `仿宋` ↔ `FangSong`, `宋体` ↔ `SimSun`, `Courier` ↔ `Courier New`), so an installed font is not reported missing.
   - Tables are aligned by caption, header row, column count and grid geometry, then compared with the matched template table: grid column widths and ratios, total width, `tblLayout`, `jc`, `tblCellMar`, `tblBorders` (including border size and color), `w:tblStyle`, header-row `w:shd` fill, cell `w:vAlign` distribution, and per-row `trHeight` (`table_style_anomalies`). A table with no template counterpart is reported as `NEW_TABLE` and is not compared to an unrelated neighbour.
   - Row-level pagination is verified only where the template proves it: if the template sets `w:cantSplit` on all rows or `w:tblHeader` on row 0, the output must match (`pagination_anomalies`).
   - Table font and size are compared against the **matched** table's dominant value (`table_dominant_size` / `table_dominant_font`). Row-level cell checks run only when both tables have the same row count; otherwise the row-count change is reported separately and the shifted rows are not compared. Never accept a document-wide size allowlist here: a table regenerated at a larger size still uses a size the template used somewhere else, which is exactly how drifting tables slipped through before.

---

## Core Architecture Rule 1 — Task Router & Web Search Strategy

Run `python scripts/inspect_document.py --inputs <file1> [<file2> ...] --intent "<user_prompt>"` (or call `route_document_task()`) to route every request:

| Task Mode | Trigger Condition | Primary Engine Pipeline | Web Search Policy | Default Confirmation Tier |
|---|---|---|---|---|
| **`GENERATE`** | 1 `.docx` template + user topic/data to populate; an accompanying `.xlsx` is recorded as `data_sources` when the intent is generation | `analyze_template.py` → Research → `ssot_engine` → `generate_document.py` → `run_qa.py` | **ENABLED** (Standards + Official Institution Site) | `FULL_CONFIRM` (if unsearchable internal slots exist) or `LIGHT_CONFIRM` |
| **`REPAIR`** | exactly 2 `.docx` files (`reference_template.docx` + `broken_target.docx`) | `repair_document.py` (`build_repair_plan` → `repair_plan.json` → `execute_repair_plan`) → `run_qa.py` | **DISABLED BY DEFAULT** (Strict content preservation from broken doc) | `SKIP` (or `HOLD_AND_ASK` if `L4` structural mismatch) |
| **`REVIEW`** | 2 `.docx` files + intent containing 审核/审阅/修订/留痕/review/track changes/按模板修正 | `review_document.py` (`build_review_plan` → `execute_review_plan`) → `audit_review_integrity` + `run_qa.py` | **DISABLED BY DEFAULT** (No external rewriting during audit) | `LIGHT_CONFIRM` for the revision list; `HOLD_AND_ASK` if `L4` regions need manual edits |
| **`POLISH`** | 1 `.docx` draft + request to refine wording/terminology while keeping layout | **NO HANDLER — `CAPABILITY_NOT_AVAILABLE`** (planned: `analyze_template.py` → `LogicalParagraphView` surgical replacement → `run_qa.py`) | **DISABLED BY DEFAULT** (On-demand only if user asks to verify standards) | `LIGHT_CONFIRM` |
| **`MERGE`** | Explicit merge/summarize intent (合并/汇总/整合/merge), 2+ same-format sources without a template, or a multi-source input with no intent signal | **NO HANDLER — `CAPABILITY_NOT_AVAILABLE`** (planned: `analyze_template.py` → `ssot_engine` cross-doc reconciliation → format-specific generator → `run_qa.py`) | **DISABLED BY DEFAULT** | `LIGHT_CONFIRM` |
| **`REFORMAT`** | 1 or 2 `.docx` + typographic intent (统一字体/统一字号/重新排版/格式统一/按模板修改格式/改格式/对齐格式/修复格式) | `reformat_document.py` (`build_reformat_plan` → `format_plan.json` → `execute_reformat_plan` writes `w:*PrChange`) → `audit_review_integrity` + `run_qa.py` | **DISABLED BY DEFAULT** | `SKIP` (plan-only) / `LIGHT_CONFIRM` (apply: show the diff summary first) |
| **`EXCEL_GENERATE`** | exactly 1 `.xlsx`/`.xlsm` template + data/topic to populate; extra workbooks become `data_sources` | `analyze_excel_template.py` → `ssot_engine` (`Decimal`) → `generate_excel.py` → `run_qa.py` | **CONDITIONAL** (Enabled if external standards/rates needed) | `FULL_CONFIRM` or `LIGHT_CONFIRM` |

Routing notes that prevent the common misroutes:

- A single `.docx` with "统一字体/重新排版/修复格式" is `REFORMAT`, never `REPAIR` — dual-document REPAIR requires exactly two `.docx` inputs.
- A `.docx` + `.xlsx` pair is **not automatically `MERGE`**. With a create intent ("生成/编制/起草") the `.docx` is the template and the `.xlsx` is a data source, so the primary mode is `GENERATE`; with a modify intent ("按模板修改格式/对齐") it is `REFORMAT`; only an explicit merge intent or a no-intent multi-source request stays `MERGE`.
- Two `.docx` + "按模板修复格式" stays `REPAIR`; the word 修复 wins over the template phrase.
- `EXCEL_GENERATE` must run `generate_excel.py`; never send an `.xlsx` input to `generate_document.py`.

---

## Core Architecture Rule 2 — Template Compatibility Matrix (`L1`–`L4`)

`assess_template_compatibility_level(doc)` inspects all stories (body, headers, footers, nested tables, `w:txbxContent` textboxes, footnotes, endnotes, comments) and classifies the template:

| Level | Classification Name | Structural Characteristics | Engine Execution Guarantee |
|---|---|---|---|
| **`L1`** | **Standard Template** | Body paragraphs, flat tables, explicit tokens (`{{...}}`, `【...】`) or red clues, inline PNG/JPEG images (`a:blip`). | **Full Automated Support**: Zero Unintended Formatting Delta. |
| **`L2`** | **Moderately Complex** | Merged cells (`gridSpan`/`vMerge`), headers/footers, multi-section page setups (portrait/landscape mix), auto-numbering (`w:numPr`), mixed-format paragraphs. | **Full Automated Support**: Cross-run `LogicalParagraphView` + section/header/footer traversal + donor style inheritance. |
| **`L3`** | **Complex Styled / Form** | Nested tables (`w:tbl` inside `w:tc`), floating textboxes (`w:txbxContent`), SDT content controls (`w:sdt`), simple fields (`w:fldSimple`), footnotes/endnotes, shared image `rId`s. | **Protected Automated Support**: `classify_cell_structure()` guards complex cells; `replace_inline_image_in_paragraph()` forks shared `rId`s safely. |
| **`L4`** | **Manual / Hold Boundary** | Embedded OLE binaries (`w:object` / `o:OLEObject`), SmartArt diagrams (`dgm:relIds`), native DrawingML Charts (`c:chart`), OMML equations (`m:oMath`), or macro-enabled locks. | **Read-Only Preservation + `HOLD_AND_ASK`**: Engine leaves `L4` nodes 100% untouched and prompts user if mutation inside those objects was requested. |

---

## Core Architecture Rule 3 — Directory & Module Architecture (`v3.0`)

```
officecli-template-filler/
├── SKILL.md                              # Primary skill workflow & architecture rules
├── engine/                               # Standalone, importable Python engine package
│   ├── __init__.py                       # Public API exports
│   ├── ooxml_utils.py                    # P0-1: LogicalParagraphView cross-run mapper & full-story iterator
│   ├── ssot_engine.py                    # P0-2: decimal.Decimal SSOT solver, unit converter & explicit ratio bounds
│   ├── image_engine.py                   # P0-3: MIME-aware, rId reference-counted image replacement & verifier
│   ├── process_guard.py                  # P0-4: PID-scoped TaskResourceGuard (zero global taskkill)
│   ├── table_engine.py                   # P1-5: 8-class cell structure classifier & donor-aware table filler
│   ├── excel_engine.py                   # P1-6: Full structural Excel row cloner, formula shifter & Decimal evaluator
│   ├── excel_spec.py                     # v3.5 M3: Excel template spec (sheets, formulas, placeholders, macros)
│   ├── excel_objects.py                  # v3.5 M5: XLSM object preflight (ActiveX/pivot/slicer loss risk)
│   ├── layout_qa.py                      # v3.5 M6: content-independent layout fingerprint comparison
│   ├── style_engine.py                   # Style hierarchy resolver & non-destructive paragraph filler
│   ├── docx_parser.py                    # Task Router, L1-L4 compatibility classifier & DocumentSpec builder
│   ├── capabilities.py                   # v3.5 M3: task capability registry (handler + enabled per mode)
│   ├── repair_engine.py                  # Dual-document REPAIR diff planner & non-destructive executor
│   ├── review_engine.py                  # v3.1: tracked changes, native comments & review integrity QA
│   ├── qa_engine.py                      # P1-7: Full DOCX Package XML/Rels/Media QA + Visual Layout QA
│   └── transaction.py                    # v3.5 M1: Preflight → Execute(temp) → QA → atomic Commit
├── scripts/                              # CLI entrypoints for Agent orchestration
│   ├── inspect_document.py               # Route task mode & inspect input files
│   ├── analyze_template.py               # Emit DocumentSpec JSON (schemas/document_spec.schema.json)
│   ├── analyze_excel_template.py         # v3.5 M3: Emit Excel template spec (.xlsx/.xlsm)
│   ├── generate_document.py              # Execute SSOT + non-destructive DOCX rendering
│   ├── generate_excel.py                 # v3.2: EXCEL_GENERATE entrypoint (fills .xlsx, keeps formulas)
│   ├── repair_document.py                # Dual-document REPAIR mode (emit & execute repair_plan.json)
│   ├── review_document.py                # v3.1: REVIEW mode (tracked changes + comments + review_report.json)
│   ├── proofread_document.py             # v3.5 M8: PROOFREAD mode (single-document tracked fixes)
│   ├── cleanup_editor_sdk.py             # Manual diagnostic: list SDK PIDs (auto cleanup runs in every entrypoint)
│   ├── reformat_document.py              # v3.5.7: REFORMAT mode (semantic format diff plan + tracked w:*PrChange apply)
│   ├── render_document.py                # DOCX visual QA; PDF via WPS word2pdf or LibreOffice, otherwise RENDER_PDF_NOT_PRODUCED
│   ├── run_qa.py                         # Run Package QA, Format QA, Excel Formula QA & Visual QA
│   ├── ensure-officecli.ps1              # Windows OfficeCLI installer
│   └── ensure-officecli.sh               # macOS/Linux OfficeCLI installer
├── schemas/                              # Formal JSON Schemas for intermediate artifacts
│   ├── document_spec.schema.json         # DocumentSpec output schema
│   ├── repair_plan.schema.json           # RepairPlan output schema
│   ├── review_report.schema.json         # v3.1: REVIEW mode execution + integrity report
│   └── qa_report.schema.json             # Unified QA Report schema
├── tests/                                # Automated unit test suite (138 tests)
│   ├── test_v3_engine.py                 # P0-1..P1-8, REPAIR, REVIEW & Excel regression baseline
│   ├── test_transaction.py               # v3.5 M1: staged write, abort on QA failure, atomic commit
│   ├── test_review_lifecycle.py          # v3.5 M2: revision marks, accept/reject/restore, snapshot
│   ├── test_table_signature.py           # v3.5 M2/M9: table signature, drift thresholds, merge gating
│   ├── test_router_capabilities.py       # v3.5 M3/M8: capability registry, unsupported input, proofread routing
│   ├── test_excel_reliability.py         # v3.5 M4/M5: Translator shifting, formula status, object preflight
│   ├── test_layout_qa.py                 # v3.5 M6: layout fingerprint comparison
│   ├── test_process_ownership.py         # v3.5 M7: process identity, spawned-only cleanup, per-task logs
│   └── test_proofread.py                 # v3.5 M8: proofread deliverable + snapshot
└── references/
    └── python-docx-engine.md             # API reference & usage examples for engine/ modules
```

---

## Core Engineering Fixes Enforced in `engine/` (P0-1 through P1-8)

### 1. Non-Destructive Cross-Run Mapping (`engine/ooxml_utils.py` — Fixes P0-1)
- **Never** globally strip `<w:proofErr>` or destructively merge all adjacent runs up front.
- Always use `LogicalParagraphView(p_el)` to build a read-only character-offset map `char_map[logical_idx] -> (r_el, t_el, t_char_idx)`.
- When replacing a cross-run token (e.g. `{{` + `project_name` + `}}`), `view.replace_span()` updates only the slice inside the affected `<w:t>` nodes, preserves `<w:t>` attributes (`xml:space="preserve"`), leaves untouched runs and `<w:proofErr>` markers intact, and removes a trailing run **only** if its `<w:t>` becomes empty and the run contains no drawings, breaks, tabs, or fields.
- Use `iter_all_document_paragraphs_with_Wait_context(doc)` to traverse **all** document stories: body paragraphs, nested tables, headers, footers, textboxes (`w:txbxContent`), footnotes, endnotes, and comments.

### 2. Exact `decimal.Decimal` SSOT Mathematical Solver (`engine/ssot_engine.py` — Fixes P0-2)
- Binary `float` and `round(..., 4)` are strictly prohibited in financial, credit, and hour calculations.
- `build_ssot_master_data()` uses `decimal.Decimal` with explicit rounding modes (`ROUND_HALF_UP`, `ROUND_HALF_EVEN`), unit conversions (`yuan`, `wan_yuan`, `percent`, `fraction`, `hours`, `credits`), and largest-remainder percentage closure (`compute_exact_percentages()` so rounded percentages sum to exactly `100.00%`).
- Ratio bounds MUST declare explicit units (`{"value": "0.50", "unit": "fraction"}` or `{"value": "50", "unit": "percent"}`) parsed by `parse_ratio_bound()`—never guess units via `if min_r > 1.0`.

### 3. MIME-Consistent & Reference-Counted Image Replacement (`engine/image_engine.py` — Fixes P0-3)
- Before replacing an inline image (`a:blip`), `count_image_part_references(doc)` counts how many drawing elements across the entire DOCX package reference that `rId` / image part.
- **Unshared Part (`ref_count == 1`)**: Converts the replacement image via Pillow to match the original part's exact MIME `content_type` (`image/png`, `image/jpeg`, etc.) before updating `_blob`, preventing Content-Type / binary header mismatches.
- **Shared Part (`ref_count > 1`)**: Allocates a brand-new image part and `rId` on the owning story part and updates **only** the target `<a:blip r:embed="...">`, leaving all other occurrences of the shared image (such as logos or watermarks) untouched.
- Post-save verification (`verify_docx_images_integrity(docx_path)`) re-opens the saved archive and validates every image relationship and bitmap stream with Pillow.

### 4. PID-Scoped Process & Handle Ownership (`engine/process_guard.py` — Fixes P0-4)
- Global `taskkill /F /IM officecli.exe /IM editor_sdk.exe` is **strictly forbidden** because it kills concurrent tasks or user processes.
- Always wrap subprocesses and open handles in `with TaskResourceGuard(task_id=...) as guard:`. It tracks only child PIDs spawned by the current task (`guard.run_owned_command(...)`) and registered file/ZipFile/Workbook/COM objects, terminating only owned PIDs on exit.

### 5. Complex Cell Structure Classification (`engine/table_engine.py` — Fixes P1-5)
- `classify_cell_structure(cell)` classifies every table cell into one of 9 types before mutation:
  - `plain_text`: Safe for donor-cloned direct fill via `fill_cell_strict_style()`.
  - `mixed_format`: Multi-run formatted cell; updated surgically via `LogicalParagraphView` token replacement without wiping surrounding runs.
  - `hyperlink_cell`: Updates text inside `<w:hyperlink>` runs without destroying the relationship `r:id`.
  - `sdt_control`: Updates text inside `<w:sdtContent>` runs while preserving the `<w:sdtPr>` control wrapper.
  - `anchored_text`: Contains bookmarks, comment ranges, or tracked-change wrappers (`w:ins`/`w:del`); filled by rewriting `<w:t>` characters only, never by deleting the wrapping nodes.
  - `image_cell`, `nested_table`, `field_code`, `unknown_complex`: Protected from destructive paragraph wiping (`status: "skipped_protected"` unless targeted by specialized handlers).

### 6. Structural Excel Row Cloning & Formula Verification (`engine/excel_engine.py` — Fixes P1-6)
- `clone_excel_template_row()` clones not only cell `font`, `fill`, `border`, `alignment`, `number_format`, and `protection`, but also:
  - Row height, `hidden`, `outlineLevel`, and `collapsed` attributes;
  - Horizontal merged cell ranges (`ws.merged_cells`);
  - DataValidation rules (`ws.data_validations`) and ConditionalFormatting rules;
  - Cell hyperlinks and dynamic formula row-reference shifting (`shift_excel_formula_row_refs()`, e.g., `=C2*D2` → `=C3*D3` while keeping `=$C$2*D2` anchored at `$C$2`);
  - Worksheet table (`ws.tables`) and `auto_filter.ref` range expansion.
- `recalculate_and_verify_excel_formulas()` evaluates formulas via the built-in `Decimal` formula engine (and headless LibreOffice when installed) to catch `#DIV/0!`, `#REF!`, `#VALUE!`, and verify mathematical totals.

### 7. Dual-Document `REPAIR` Mode (`engine/repair_engine.py` — v3.0 Core Module)
- When given a reference template (`reference.docx`) and a formatting-damaged target document (`broken.docx`), run `scripts/repair_document.py`:
  1. `build_repair_plan(ref_path, brk_path)` diffs section page margins/orientations, heading/body paragraph typography (`rFonts`, `sz`, `line`, `firstLineChars`), residual red colors, and table borders/alignments/column grids/pagination (`w:cantSplit`, `w:tblHeader`), outputting `repair_plan.json` (`schemas/repair_plan.schema.json`).
  2. `execute_repair_plan(plan, output_path)` applies all formatting repairs while preserving **100% of the business text and data** in `broken.docx`.
  3. Row-level pagination detected by the plan is actually written, not just reported: every row gets `<w:cantSplit/>`, and `<w:tblHeader/>` is added **only** when the reference table marks row 0 as a header, or row 0 is fully bold while row 1 is not. A data row is never promoted to a repeating header. `w:cantSplit` is inserted before `w:trHeight` per the `w:trPr` schema order, and the execution report counts `fixed_cant_split_rows`, `fixed_tbl_header_rows` and `skipped_header_candidates`.
  4. Table style restoration is shared with REVIEW: `restore_table_style_from_reference()` syncs `w:tblStyle`, `tblW`, `jc`, `tblBorders`, `tblLayout`, `tblCellMar`, grid column widths, header-row `w:shd`, every cell's `w:vAlign`, and missing `w:trHeight` values, all inserted in schema order and without touching cell text or merges.

### 8. Full Package QA + Visual QA (`engine/qa_engine.py` — Fixes P1-7)
- `audit_docx_package_integrity(docx_path)` inspects the raw ZIP archive to verify well-formed XML across all parts (`document.xml`, `styles.xml`, `numbering.xml`, `settings.xml`, `header*.xml`, `footer*.xml`, `footnotes.xml`, `endnotes.xml`, `comments.xml`), zero dangling `.rels` targets, valid `[Content_Types].xml`, and intact media binaries.
- `run_visual_layout_qa(docx_path, reference_docx_path)` checks table grid widths against printable page margins, inline image aspect-ratio distortion, and (when LibreOffice is available) renders headless PDF previews for visual layout verification.

### 9. Template-Driven REVIEW Mode (`engine/review_engine.py` — v3.1)
Use REVIEW when a human must decide, not when the agent should silently rewrite. The engine splits every finding into three channels:

| Channel | OOXML mechanism | Human action | Report field |
|---|---|---|---|
| Format drift (font family, size, spacing, indent, residual red) | Restored AND written as tracked formatting revisions (`w:rPrChange` / `w:pPrChange` carrying the pre-change properties), so Word/WPS shows them as accept/reject-able "Formatting" entries — nothing is silently rewritten | Accept or reject each formatting revision in the review pane | `format_restore_actions`, `tracked_format_changes` |
| Table structure drift (column widths, `tblLayout`, alignment, cell margins, borders, `tblStyle`, header shading, cell `vAlign`, row heights) | Restored via `restore_table_style_from_reference()` AND recorded as `w:tblPrChange` / `w:trPrChange` / `w:tcPrChange` / cell `w:rPrChange`; cell text and merges untouched | Accept or reject in the review pane | `table_style_restores`, `tracked_format_changes` |
| Text correction submitted as `text_revisions` | `<w:del>` + `<w:delText>` for old text, `<w:ins>` + `<w:t>` for new text, each with `w:author`/`w:date` | Accept or reject each revision in WPS/Word review pane | `tracked_text_revisions` |
| Unresolved placeholders and judgement calls | Native `word/comments.xml` + `commentRangeStart`/`commentRangeEnd`/`commentReference` | Reply or resolve the comment | `comments` |

v3.4 additions:

- **Table-internal revisions**: text revision location walks the full document story (body, tables, nested tables, textboxes, headers/footers, footnotes), so `old_text` inside a table cell is tracked like body text.
- **Per-cell table diff**: `table_style_signature()` records every cell's `tcW`/`gridSpan`/`hMerge`/`vMerge`/`tcMar`, and `compare_table_style()` reports `table_cell_property` with table/row/column/property precision. `restore_table_style_from_reference()` also writes `tcW`/`tcMar` back from the template.
- **Plan-to-document mapping**: `execute_review_plan()` returns `action_results` — one entry per action with `status` (`APPLIED`/`UNRESOLVED`), resolved `target` location, and the actual `revision_ids` written into the DOCX.
- **Revision lifecycle API**: `list_revisions(docx)` lists every `w:ins`/`w:del` across all package parts with id/author/date/text; `accept_revision()`, `reject_revision()`, `restore_revision()` rewrite the package per revision id for programmatic accept/reject/undo.
- **Table style profiles**: `save_table_style_profile()` / `load_table_style_profile()` persist a template's table fingerprint as JSON for independent audit and later comparison.
- **Font & render risk QA**: `run_visual_layout_qa()` reports `FONT_NOT_INSTALLED` (declared font missing on this machine → renderer will substitute), `RENDER_PAGE_COUNT_MISMATCH` and `RENDER_PAGE_PIXEL_DIFF`; unverifiable checks are recorded as `coverage_gaps` (`FONT_AVAILABILITY_UNVERIFIED`, `PDF_PAGE_DIFF_UNAVAILABLE`, `RENDER_PDF_NOT_PRODUCED`), never silently passed. PDF conversion picks a backend automatically: **WPS `kwpsconvert.exe word2pdf`** (found under `C:\Program Files (x86)\WPS\WPS Office\*\office6`, override with `OFFICECLI_WPS_CONVERTER` / backend with `OFFICECLI_PDF_BACKEND=wps|libreoffice|none`) or LibreOffice `soffice`. Page counts come from PyMuPDF when available, otherwise **WPS `pdfinfo`** — a real pagination measurement, unlike the OfficeCLI `view ... screenshot --render html` preview, which does not honor section breaks and whose page count must never be used to verify pagination. WPS word2pdf requires a signed-in WPS account with VIP; the failure surfaces as `WPS_VIP_REQUIRED` in `pdf_conversion_errors`.
- **v3.4.1 — no silent format edits in REVIEW**: every format restore is paired with a Word formatting-revision mark (`w:rPrChange`, `w:pPrChange`, `w:tblPrChange`, `w:trPrChange`, `w:tcPrChange`) holding the pre-change properties, so the delivered document always contains accept/reject-able revisions in addition to comments. `execute_review_plan()` reports `tracked_format_changes` and per-action `format_revision_ids`; `list_format_revisions(docx)` lists them; `audit_review_integrity()` validates their ids/authors/dates and reports `format_revision_count`. A REVIEW output with zero revisions AND zero format marks while the plan had format actions is a bug, not a delivery. REPAIR remains direct (no marks) by design.
- **v3.4.2 — Review safety & honest QA**:
  - Revision ids reported in `action_results` are the ids actually written into the XML (recorded at `ids.take()` time, never back-derived).
  - Tracked replacements cannot reorder paragraph structure: matches must live inside one contiguous plain-run group; hyperlink/SDT/field containers never move; runs carrying drawings/field codes are refused (degrade to comment).
  - `location_id` + `occurrence` now drive revision targeting. Multiple matches with no location → the edit is refused and an `AMBIGUOUS_MULTIPLE_MATCHES` comment is anchored instead of silently editing the first hit.
  - Merge topology (`gridSpan`/`hMerge`/`vMerge`) is not rewritten; a table action that still differs in merges reports `PARTIALLY_APPLIED` with `unresolved_properties` and `requires_human_review: true`.
  - `generate_excel.py` keeps VBA for `.xlsm` (`keep_vba=True`, `.xlsm` output enforced) and runs Excel QA against the ORIGINAL template, not the output itself.
  - Excel formulas the builtin evaluator cannot compute are counted in `unsupported_formulas` / `unverified_count` with `FORMULAS_UNVERIFIED` coverage gap — never silently passed. `SUBTOTAL` dispatches by function code (1=AVERAGE, 2=COUNT, 4=MAX, 5=MIN, 9=SUM).
  - `run_qa.py` gains a fourth status: when any check could not run (`unverified_count`/`coverage_gaps` non-empty with zero issues), overall status is `UNVERIFIED`, not `PASSED`.
- **v3.5.0 — Transactional delivery, revision lifecycle & capability registry (M1–M3)**:
  - Every writer (`generate_document`, `generate_excel`, `repair_document`, `review_document`, `render_document`) stages its output in `.<name>.tmp-<transaction_id>.<ext>`, runs QA against that staged file, and only then publishes it with two `os.replace` calls. Each JSON result carries `transaction: {transaction_id, preflight, qa_status, committed, abort_reason, lock_info, input_sha256, output_sha256}`. A failed run leaves no final file and no `.tmp` / `.pending` artifact. A locked final path yields `abort_reason: OUTPUT_FILE_LOCKED` and `lock_info` instead of a bare `PermissionError`.
  - `accept_revision` / `reject_revision` / `restore_revision` publish through the same transaction; a revision action that changes nothing produces no output file (`status: NOT_FOUND`).
  - Format revisions (`w:*PrChange`) are schema-valid (old properties wrapped in `w:rPr` / `w:pPr` / `w:tblPr` / `w:trPr` / `w:tcPr`), can be accepted or rejected programmatically, and REVIEW writes `<deliverable>.review_snapshot.json` so an already decided revision can be rebuilt (`restore_revision`), reporting `SNAPSHOT_MISSING` / `LOCATION_LOST` instead of guessing.
  - Table signatures add `row_count`, per-row `{val, hRule}`, `tblLook` and band sizes; comparison reports `table_row_count` (report-only), `table_row_height` (>15% drift or missing), `table_row_height_rule`, `table_tbl_look` and `table_band_size`; repair restores band/look/indent/spacing plus rows whose height drifts more than 15%.
  - `route_document_task()` returns `capability: {enabled, handler, reason}` from `engine/capabilities.py`. `REFORMAT` / `POLISH` / `MERGE` are declared but disabled — report `CAPABILITY_NOT_AVAILABLE` and stop instead of picking another script. Non-Office inputs return `task_mode: UNSUPPORTED_INPUT` with `unsupported_files` and `supported_formats`.
  - Workbook inputs use `scripts/analyze_excel_template.py` (`extract_excel_spec()`), so Step 2 never runs the Word analyzer on an `.xlsx`.
- **v3.5.1 / v3.5.2 — Excel reliability, layout QA, process ownership, PROOFREAD, merge restore (M4–M9)**:
  - Formula row-shifting uses `openpyxl.formula.translate.Translator`: string literals stay intact, sheet-qualified references shift correctly, and structured / external / `INDIRECT`-`OFFSET` formulas return an explicit `UNSUPPORTED_*` reason instead of being regex-rewritten into something plausible but wrong.
  - Every formula carries `formula_status` (`VERIFIED` / `FAILED` / `UNSUPPORTED` / `NOT_RECALCULATED`); `unverified_count` counts the latter two, so `run_qa.py` reports `UNVERIFIED` rather than `PASSED`.
  - `inspect_excel_objects()` lists ActiveX / Power Query / pivot / slicer / connection / chart parts `openpyxl` cannot preserve; `generate_excel.py` refuses with `OBJECT_LOSS_RISK` (exit 3) unless `--allow-object-loss` is passed.
  - `run_visual_layout_qa()` compares a content-independent layout fingerprint (`LAYOUT_FONT_DRIFT`, `LAYOUT_POSITION_DRIFT`, `LAYOUT_TABLE_DRIFT`, `LAYOUT_PAGE_DRIFT`, `LAYOUT_IMAGE_DRIFT`) instead of relying on whole-page pixel diffs. **Only `REPLICA` compares by list index**; `STYLE_GUIDE` aligns paragraphs by text/heading anchors and tables by caption/header, so added paragraphs and new tables are `NEW_CONTENT`/`NEW_TABLE` rather than drift. "Replacing text alone raises nothing" holds only when paragraph/table order is unchanged; a changed content volume is expected to produce new/removed entries.
  - Process cleanup proves ownership with `(pid, image, creation time)`: Windows uses `GetProcessTimes`, a recycled PID is never touched, unprovable candidates are reported in `unreleased_pids`, `taskkill` no longer kills whole trees, and each task writes its own cleanup log.
  - `PROOFREAD` is a first-class mode for single-document proofing: `scripts/proofread_document.py` writes tracked text revisions plus comments, publishes through the transaction, and emits a revision snapshot.
  - Merge topology is restored only when the region is provably safe (identical topology, at most one non-empty text, no revision/comment anchors); anything else goes to `manual_required` and stays `PARTIALLY_APPLIED`.
- **v3.5.4 — Ownership proof and transaction QA coverage**:
  - Cleanup no longer treats a baseline diff as ownership: only PIDs recorded through `note_spawned()` may be terminated. Processes that merely appeared during the run are reported in `unowned_pids` and left alone, so a concurrent task can never be killed.
  - `generate_document.py` now runs package-integrity QA alongside format QA before commit; `repair_document.py` now runs format QA against the reference alongside package QA. A partial gate can no longer be reported as `transaction.qa_status: PASSED`.
  - `run_qa.py` reports `UNVERIFIED` when a check could not run even if placeholder residue would otherwise yield `PENDING_HUMAN_REVIEW`; a missing check never hides behind pending review.
- **v3.5.5 — Review revision-ID uniqueness and revision-aware layout QA**:
  - Splitting a run that already carries a `w:*PrChange` mark must not copy the same `w:id` into every prefix/`w:del`/`w:ins`/suffix clone. Only the first clone keeps the format mark; `audit_review_integrity()` must always pass with unique ids.
  - `fingerprint_docx()` compares the accepted-revision view: `w:del`/`w:moveFrom` runs and comment-reference runs are ignored, adjacent runs with identical formatting are coalesced, and the comments story is excluded. A legitimate REVIEW document must not fail QA with `LAYOUT_RUN_COUNT` / `LAYOUT_PARAGRAPH_COUNT`.
- **v3.5.6 — Role-aware routing, semantic QA, severity-aware gate**:
  - `.docx` + `.xlsx` is not automatically `MERGE`: a create intent makes the `.docx` the template and the `.xlsx` a `data_sources` entry (`GENERATE`); a modify intent routes `REFORMAT`; only an explicit merge intent or a no-intent multi-source request stays `MERGE`.
  - `alignment.py` maps paragraphs by text/heading anchors and tables by caption/header/column geometry. `STYLE_GUIDE` reports unmatched output items as `NEW_CONTENT`/`NEW_TABLE`, not as drift; `REPLICA` keeps index-based template order for REPAIR/REVIEW.
  - Only `high` severity issues are hard failures. `medium`/`low` findings are `warnings`; `coverage_gaps` still yields `UNVERIFIED`. A `FAILED` status therefore means "a high-severity problem", not "any advisory exists".
  - Table cell styles are compared as a set of non-empty effective styles; empty template cells that are filled by the output no longer raise `table_cell_font_or_size`, and row-level checks are skipped when row counts differ.
  - Font availability normalizes Chinese family names against Windows' English registry names (`黑体` ↔ `SimHei`, `仿宋` ↔ `FangSong`, `宋体` ↔ `SimSun`, `Courier` ↔ `Courier New`).
  - A locked output returns `OUTPUT_FILE_LOCKED` with `lock_info.editor_sdk_pids`; `cleanup_editor_sdk.py --kill-pid <pid> --confirm` verifies image name and creation time before terminating exactly that PID. Global `taskkill /IM editor_sdk.exe` remains forbidden.
- **v3.5.7 — REFORMAT diff plan and WPS PDF path**:
  - `scripts/reformat_document.py` implements the REFORMAT handler: `build_reformat_plan()` produces a semantic diff list (paragraphs and tables aligned by text/heading/caption anchors; each entry carries `current`, `reference_value`, `action`, `reason`, `confidence`), and `execute_reformat_plan()` applies only `AUTO_FIX` entries, recording every change as a native `w:*PrChange` revision so the user can accept/reject in Word/WPS.
  - Plan actions: `AUTO_FIX` (matched + safe), `REVIEW` (mixed runs / bold / row-count drift), `KEEP` (new content), `UNSUPPORTED` (column-count mismatch). Plan-only mode writes no output; apply mode publishes through the transaction with package QA, and reports `PENDING_HUMAN_REVIEW` when the plan still contains review items.
  - PDF conversion is backend-based (`engine/pdf_backend.py`): WPS `kwpsconvert.exe word2pdf` preferred on Windows, LibreOffice as fallback, `OFFICECLI_PDF_BACKEND` overrides. Page counts use PyMuPDF when installed, else WPS `pdfinfo`. Visual QA reports `pdf_backend`, `page_count_source`, `page_count_available`; a page-count check that cannot run becomes `PDF_PAGE_COUNT_UNVERIFIED` instead of silence.
- **v3.5.8 — Content truth and image truth**:
  - **SVG dual embed fixed**: Word stores an inserted icon/SVG as a raster `<a:blip>` plus `<asvg:svgBlip>`, and Word renders the SVG. Replacement now removes the stale `svgBlip` extension (`adjustments: ["svg_fallback_removed"]`) instead of reporting success while the old artwork keeps showing. `count_image_part_references()` counts `svgBlip` and VML `v:imagedata` references too, so a shared part is never treated as exclusive.
  - **Vector images are no longer silently skipped**: SVG/EMF/WMF parts cannot be decoded by Pillow, so `verify_docx_images_integrity()` returns `VECTOR_IMAGE_UNVERIFIED` in `coverage_gaps`, which propagates to `package_integrity.coverage_gaps` and turns the run `UNVERIFIED`. Replacement results carry `verification: "unverified_vector"`.
  - **VML pictures replaced**: `w:pict` / `v:imagedata` (WPS header logos, stamps, old templates) now go through the same shared-reference-safe path (`reference_kind: "vml"`), in place when exclusive or via a new part when shared.
  - **Crop and frame**: replacement clears `a:srcRect` (`crop_rect_cleared`) and supports `fit_mode="fit_image"` to recompute `wp:extent` from the new aspect ratio instead of stretching the new image into the old crop.
  - **External images reported**: `r:link` images are no longer skipped silently — `EXTERNAL_IMAGE_LINK` lists the owning part and target, because a distributed copy would lose them.
  - **Content-truth QA (`engine/consistency_qa.py`)**: `audit_content_consistency()` extracts `label → value` pairs from prose, tables and headers, and reports `CONTENT_VALUE_CONFLICT` / `CONTENT_SUBTOTAL_MISMATCH` (high), `CONTENT_LABEL_VALUE_VARIANCE` / `CONTENT_TERM_DRIFT` (medium), and mixed date/unit styles (low). `run_qa.py` runs it by default (`--no-content-qa` disables).
  - **Fact provenance**: `audit_fact_sources()` fails (`FACT_SOURCE_MISSING`, high) when an SSOT fact has no `source`; `UNVERIFIED` / `MODEL_GENERATED` are recorded as unverified facts rather than silently trusted.
  - **Honest scope**: no OCR — image-internal text is reported as `OCR_UNAVAILABLE`, never claimed as verified. No chart/placeholder redraw pipeline: `FULL`-profile redrawing stays an orchestration rule, and the engine only supplies the replacement channel.

Mandatory rules:

- **The deliverable is an `.docx`, never a Markdown/JSON report.** When the user asks to 检查/审核/按模板修正, they expect a Word file that opens in revision mode, so they can accept or reject each change. A `.md` findings list, a `.json` report, or a chat summary is an **internal intermediate artifact only** — it must never be the final answer, never be the only file delivered, and never be described as "the review result".
- Always call `enable_track_changes(doc)` before saving; a review file without `<w:trackChanges/>` will not open in review mode.
- Never invent business text during REVIEW. Text revisions come from an explicit `revisions.json` list or stay as comments for the human.
- Every `w:ins`/`w:del` must carry a non-empty author and an ISO `YYYY-MM-DDTHH:MM:SSZ` date; `w:del` children must use `w:delText`, never `w:t`.
- Call `audit_review_integrity(output_path)` before delivery; it fails on missing authors, malformed dates, duplicate revision ids, `w:del` without `w:delText`, and comment references that do not match `comments.xml`.
- Write `review_report.json` (`schemas/review_report.schema.json`) for auditability, then hand the **`.docx`** to the user. State how many revisions and comments still need a human decision, but do not replace the document with the report.

### 9.1 REVIEW Deliverable Contract (`scripts/review_document.py`)

Inputs:

| Input | Meaning |
|---|---|
| `--reference template.docx` | Style/format baseline |
| `--target draft.docx` | Document whose business text must be preserved |
| `--revisions revisions.json` | Optional list of `{"old_text", "new_text", "reason"}` items to write as `<w:del>`/`<w:ins>` |
| `--out reviewed.docx` | **Required for delivery.** The revision-mode document the user opens in Word/WPS |
| `--report review_report.json` | Internal audit trail, not a deliverable |

Rules:

1. `--plan-only` is allowed for internal inspection only. It must never be the final step of a REVIEW task.
2. If the analysis produced a findings list (for example a Markdown checklist), convert each actionable item into a `revisions.json` entry and run `review_document.py`; do not ship the checklist instead of the document.
3. Items you cannot express as a text replacement become native comments with `ADD_REVIEW_COMMENT`, so the human sees them inline in Word.
4. Format-only repairs (font, size, paragraph properties, and supported table properties) must be paired with native `w:*PrChange` formatting revisions. Unsupported or structurally unsafe changes remain comments or `manual_required`; never apply them silently.
5. Final response format: link the `.docx`, list counts of revisions and comments, and name the file that opens in revision mode. Do not paste the Markdown report in place of the file.

---

## Standard End-to-End Execution Workflow

### Step 1: Route Task & Inspect Inputs
```powershell
python scripts/inspect_document.py --inputs "$INPUT_1" --intent "$USER_PROMPT" --output "$TEMP/routing.json"
```

### Step 2: Analyze Template & Emit `DocumentSpec`
Pick the analyzer by container type — never run the Word analyzer on a workbook:
```powershell
# .docx / .docm
python scripts/analyze_template.py --input "$INPUT_1" --output "$TEMP/document_spec.json"

# .xlsx / .xlsm
python scripts/analyze_excel_template.py --input "$INPUT_1" --output "$TEMP/document_spec.json"
```
Inspect `compatibility.level` (`L1`–`L4`) and the placeholder inventory (`candidate_hits` for Word, `placeholder_tokens` for Excel).

Also read `routing.capability` from Step 1 before executing anything:

| field | Meaning |
|---|---|
| `enabled: true` | The mode has a real handler (`capability.handler`); continue. |
| `enabled: false`, `reason: CAPABILITY_NOT_AVAILABLE` | The mode is routed but not implemented (`POLISH` / `MERGE`). Stop and tell the user the capability is missing — do not substitute another script. |
| `task_mode: UNSUPPORTED_INPUT` | At least one input is `.pdf` / `.doc` / `.wps` / `.et` or another unsupported container. Report `unsupported_files` plus `supported_formats` and stop; `inspect_document.py` exits with code 2 for this verdict. |

#### Step 2A: Template Semantic Preflight (before research or writing)

For curriculum/education templates, supplement the structural `DocumentSpec` with a semantic preflight and a repair plan. This is orchestration logic; do not rewrite the OOXML engine to implement it.

Check all of the following across body text, native tables, headers/footers, textboxes, field results, and image captions/surrounding text. **The engine has no OCR**: text painted inside a picture is not readable, so never claim to have verified it — record `OCR_UNAVAILABLE` in `coverage_gaps` and ask the user for the source text if an image's content matters.

- education level and vocabulary are consistent (`本科` / `专科` / `高职` / `中职`);
- TOC headings match actual body headings and heading order;
- course names/codes are consistent across graduation requirements, curriculum matrix, credit allocation, and teaching schedule;
- credit/hour totals, required/elective splits, theory/practice splits, and semester subtotals close mathematically;
- semester count and schedule columns agree everywhere;
- images containing `***`, `XXXX`, generic labels, or another major's examples are marked `NEEDS_REDRAW`, never preserved as normal artwork (judged from captions and surrounding text, not from pixels);
- stale field results or template page numbers are recorded as `TOC_STALE`, not accepted as current.

Emit a structured `semantic_preflight` object with `issues`, `repair_plan`, `image_actions`, `toc_status`, and `blocking_conflicts`. Any conflict that changes business meaning enters `HOLD_AND_ASK`; deterministic template residue enters the selected execution profile. A preflight with unexamined stories or images is `UNVERIFIED`, not passed.

#### Step 2B: Curriculum SSOT Specialization

When the template is a curriculum plan, build one `curriculum_ssot` payload on top of `build_ssot_master_data()` and derive every dependent artifact from it: graduation requirements, course-to-outcome matrix, credit/hour allocation, semester subtotals, and the teaching schedule. Use `Decimal` throughout. Validate total credits, total hours, required/elective, theory/practice, category totals, semester totals, and all cross-table references before document mutation. Never independently hardcode the same course or total in multiple outputs.

### Step 3: Conditional Research, Execution Profile & Confirmation Gate
- Follow the routed `web_search_policy` (`ENABLED` for `GENERATE`, `DISABLED_BY_DEFAULT` for `REPAIR`/`POLISH`/`MERGE`/`REFORMAT`).
- For `GENERATE` / `EXCEL_GENERATE`, select exactly one execution profile before writing: `FAST` (**快速填专业内容**), `STANDARD` (**标准完整成稿**, default), or `FULL` (**含图表精修**). If the user already chose one, do not ask again.
- Apply the routed Confirmation Tier (`SKIP`, `LIGHT_CONFIRM`, `FULL_CONFIRM`, or `HOLD_AND_ASK`) in the same consolidated prompt. Profile choice and missing-fact confirmation must not become two separate interruptions.
- `FAST` may leave unsupported tables/images untouched only when each omission is listed in `coverage_gaps`; it may never claim a complete final draft. `STANDARD` fills all supported native tables. `FULL` is required when placeholder/sample images or a schedule visual must be redrawn.
- **Scope honesty**: execution profiles (`FAST`/`STANDARD`/`FULL`), semantic preflight, staged checkpoints, and TOC degradation are v3.5.3 **orchestration rules**, not engine APIs. There is no execution-profile `--profile` flag, checkpoint store, or preflight module; execute these steps in the task workflow and never describe them as implemented engine features. (The `run_qa.py --profile replica|style-guide` flag is a **QA comparison profile**, a separate engine feature.)

### Step 4: Execute Mode-Specific Engine Pipeline

**Transactional delivery (v3.5 M1) — stage, verify, then commit**

`generate_document.py`, `generate_excel.py`, `repair_document.py`, `review_document.py` and `render_document.py --outdir` never write the final path directly:

1. `Preflight` — source exists, extension is supported, output directory is writable, container family matches (Word → Word, Excel → Excel).
2. `Execute` — the document is saved to a sibling `.<name>.tmp-<transaction_id>.<ext>` staged file.
3. `QA` — each entrypoint runs the checks its deliverable contract requires against that staged file: `GENERATE` → package integrity + format; `REPAIR` → package integrity + format against the reference; `REVIEW` / `PROOFREAD` → package integrity + revision/comment integrity; `EXCEL_GENERATE` → formula + style; `RENDER` → visual. The full package/format/formula/visual suite still runs separately through `run_qa.py` (Step 5).
4. `Commit` — two atomic `os.replace` calls publish the file only when `qa_status` is `PASSED`, `PENDING_HUMAN_REVIEW` or `UNVERIFIED`.

Every entrypoint ends with a `transaction` object:

```json
{"transaction_id": "...", "preflight": {"passed": true, "checks": []},
 "qa_status": "PASSED", "committed": true, "abort_reason": null,
 "input_sha256": "...", "output_sha256": "...", "qa_report_path": null}
```

- `committed: false` (exit code 1) means the final file was **not** created; exit code 2 means preflight rejected the task. Never tell the user a document was produced — report `abort_reason` and the QA `issues` instead.
- `qa_status: "UNVERIFIED"` still publishes the file, but it must be described as unverified, never as a pass.
- Do not hand-write the final path in ad-hoc scripts; use the entrypoints or `engine.DocumentTransaction` so a failed run leaves no `.tmp` / `.pending` artifact behind.

- **For `GENERATE` only**:
  Build `ssot_payload.json` (validated via `build_ssot_master_data()`) and run:
  ```powershell
  python scripts/generate_document.py --template "$INPUT_1" --payload "$TEMP/payload.json" --output "$OUTPUT_FILE"
  ```
  *(Or import `engine` directly in a task-specific Python script using the canonical APIs documented in [references/python-docx-engine.md](references/python-docx-engine.md)).*
- **For `POLISH` / `MERGE`**: these modes have no handler. Report `CAPABILITY_NOT_AVAILABLE` and stop — never substitute `generate_document.py` or any other script.
- **For `REFORMAT` (align formatting to a template, content preserved)**:
  ```powershell
  # Step 1 — plan only: prints the semantic diff list, writes nothing
  python scripts/reformat_document.py --reference "$REF_DOCX" --target "$TARGET_DOCX" --plan-out "$TEMP/format_plan.json" --plan-only
  # Step 2 — apply: only AUTO_FIX entries run; each is recorded as a native w:*PrChange revision
  python scripts/reformat_document.py --reference "$REF_DOCX" --target "$TARGET_DOCX" `
      --plan-out "$TEMP/format_plan.json" --out "$OUTPUT_DOCX" [--strip-red]
  ```
  The plan classifies every difference: `AUTO_FIX` (matched paragraph/table, safe to restore), `REVIEW` (mixed runs, bold changes, or row-count drift), `KEEP` (new paragraphs/tables with no template counterpart), `UNSUPPORTED` (column-count mismatch). Show `plan.summary` to the user before applying; the deliverable is a `.docx` whose format changes open in Word/WPS revision mode for accept/reject. After applying, run `audit_review_integrity()` plus `run_qa.py --profile replica`.
- **For Dual-Document `REPAIR`**:
  ```powershell
  python scripts/repair_document.py --reference "$REF_DOCX" --broken "$BROKEN_DOCX" --plan-out "$TEMP/repair_plan.json" --output "$OUTPUT_DOCX"
  ```
- **For `EXCEL_GENERATE`**:
  ```powershell
  python scripts/generate_excel.py --template "$INPUT_XLSX" --payload "$TEMP/payload.json" --output "$OUTPUT_XLSX"
  ```
  `generate_excel.py` only rewrites string cells that contain `{{...}}` / `【...】`; formulas and cell styles are preserved. `openpyxl` cannot round-trip charts, images, or VBA, so record any such object in `coverage_gaps` instead of claiming fidelity.
- **For `REVIEW` (human accept/reject required)**:
  ```powershell
  python scripts/review_document.py --reference "$REF_DOCX" --target "$DRAFT_DOCX" `
      --author "OfficeCLI Reviewer" --revisions "$TEMP/revisions.json" `
      --out "$OUTPUT_DOCX" --plan-out "$TEMP/review_plan.json" --report "$TEMP/review_report.json" `
      [--snapshot "$TEMP/review_snapshot.json"]
  ```
  Hand the user the generated `.docx` — not a Markdown checklist and not the JSON report. Tell them WPS/Word opens it in revision mode, format repairs are already applied, and each `<w:ins>`/`<w:del>` and comment still needs their accept/reject decision.
  The run also writes `<deliverable>.review_snapshot.json` (override with `--snapshot`). Keep it next to the document until the user has finished deciding: `restore_revision()` reads it to rebuild a revision that was already accepted or rejected, and without it the restore returns `SNAPSHOT_MISSING` instead of guessing.
- **For `PROOFREAD` (single document, no template)**:
  ```powershell
  python scripts/proofread_document.py --target "$INPUT_DOCX" --out "$OUTPUT_DOCX" `
      --revisions "$TEMP/revisions.json" --report "$TEMP/proofread_report.json"
  ```
  Same deliverable contract as REVIEW: a `.docx` in revision mode plus its snapshot. Only explicit text fixes are written as `w:ins`/`w:del`; judgement calls and data questions stay as comments. Never invent numeric corrections — leave them for the human unless the same value is consistent across all occurrences.

#### Step 4A: Staged Checkpoints and Minimal Retry Scope

For `STANDARD` and `FULL`, persist and validate four transaction-scoped checkpoints in order:

1. `content` — body text, headings, placeholders, and semantic preflight repairs;
2. `tables` — all SSOT-derived native tables and cross-table totals;
3. `images` — replacements/redraws and image integrity (`FULL`; otherwise explicitly skipped with coverage);
4. `toc` — field state and page-number handling.

Each checkpoint records `input_sha256`, `output_sha256`, `qa_status`, `issues`, and `coverage_gaps`. A failed stage restarts from the most recent valid checkpoint, not from the original template, and never redoes a successful earlier stage. Checkpoints are internal transaction artifacts; only the final committed Office file is delivered.

#### Step 4B: Rendering and TOC Degradation Chain

Use one bounded rendering attempt per stage; do not manually retry the same file in place.

1. Render an independent working copy under `TaskResourceGuard` with a single configured timeout.
2. On timeout or renderer failure, close only task-owned handles/processes, record the exact failure, and fall back to OOXML/package/layout-fingerprint QA.
3. If Word or LibreOffice field refresh is available, refresh TOC fields on the working copy, then verify heading entries and rendered page count before commit.
4. If no compatible field-refresh engine exists, never preserve known-stale template page numbers as if current. Keep/update the TOC field with `w:updateFields=true` and set `toc_status: PENDING_FIELD_UPDATE`; if an internal pagination estimate is supplied, label it `ESTIMATED` and state that Word/WPS pagination may differ.
5. Rendering or TOC checks that did not run must create `coverage_gaps` and produce `UNVERIFIED`; repeated ad-hoc retries are forbidden.

### Step 5: Mandatory Package, Format, Formula & Visual QA
```powershell
# GENERATE / EXCEL_GENERATE: template is a style guide; content volume may change
python scripts/run_qa.py --output "$OUTPUT_FILE" --reference "$INPUT_1" `
  --profile style-guide --task-mode GENERATE --report "$TEMP/qa_report.json"

# REPAIR / REVIEW: template order is the contract
python scripts/run_qa.py --output "$OUTPUT_FILE" --reference "$REF_DOCX" `
  --profile replica --task-mode REPAIR --report "$TEMP/qa_report.json"
```
`--profile auto` (default) chooses `REPLICA` for `--task-mode REPAIR/REVIEW`, otherwise `STYLE_GUIDE` when `--reference` is present. The selected profile is echoed as `comparison_profile`.

Read `status` in `qa_report.json` — it is one of four values, never a bare boolean:

| status | Meaning | Exit code |
|---|---|---|
| `PASSED` | No **high-severity** issues. Medium/low findings are listed in `warnings` and do not block delivery | 0 |
| `PENDING_HUMAN_REVIEW` | Only `TEMPLATE_TEXT_RESIDUAL` items remain and `--review` was passed; the file is structurally sound and waits for a human decision | 0 |
| `UNVERIFIED` | No high-severity issues, but at least one check could not run (`coverage_gaps` / `unverified_count` > 0); never report this as a pass | 0 |
| `FAILED` | At least one high-severity issue | 1 |

The report also carries `issues` (flattened objects with `code`, `location`, `detail`, `severity`), `warnings`, `warning_count`, `comparison_profile`, `alignment` (matched/new/removed paragraphs and tables), `coverage_gaps`, `unverified_count`, `hard_failure_count` and `pending_human_review_count`. Branch on `code`, never on prose. Never describe a `FAILED` report as delivered, and never call `PENDING_HUMAN_REVIEW` broken. Medium findings are advisory: report them to the user, but do not rewrite the document solely to silence them.

**Content-truth section (`content_qa`, on by default; disable with `--no-content-qa`)** checks whether the numbers and names agree with each other, which format QA cannot see:

| code | Severity | Meaning |
|---|---|---|
| `CONTENT_VALUE_CONFLICT` | high | an explicit total (总/合计/小计/共) carries different values in prose and a table |
| `CONTENT_SUBTOTAL_MISMATCH` | high | a trailing 合计 row does not equal the sum of the rows above it |
| `CONTENT_LABEL_VALUE_VARIANCE` | medium | the same non-total label appears with a few different values across prose and tables |
| `CONTENT_TERM_DRIFT` | medium | a name in a name column is spelled two ways (张伟 / 张玮) |
| `CONTENT_DATE_FORMAT_MIXED`, `CONTENT_UNIT_STYLE_MIXED` | low | `2026年11月4日` mixed with `2026-11-04`, or 万 mixed with 万元 |

The report also returns `label_values` (extracted `label → value` pairs with locations) so the user can audit what was compared. `audit_fact_sources()` rejects SSOT `facts` entries without a `source` (`FACT_SOURCE_MISSING`, high) — every fact must cite a URL, an internal reference name, or the explicit marker `UNVERIFIED` / `MODEL_GENERATED`. For PROOFREAD, `find_numeric_occurrences()` returns every occurrence of a suspect number with surrounding context instead of a bare comment.

For REVIEW outputs, run `python scripts/run_qa.py "$OUTPUT_FILE" --review --reference "$REF_DOCX" --profile replica --task-mode REVIEW`:

- `review_qa.passed` must be `true`: every revision and comment is structurally valid.
- Placeholder residue becomes `PENDING_HUMAN_REVIEW`, not a failure, because REVIEW intentionally leaves undecided items for the human.
- Without `--review`, placeholder residue counts as a failure, since nothing is expected to stay unresolved.

### Step 6: Automatic Agent Shutdown & File-Lock Release
This step is automatic and applies to every document task, including success, QA failure, cancellation, and exceptions. Do not ask the user to run a cleanup command, and do not make cleanup a separate workflow step.

**How it works**

1. Every document-processing entrypoint calls `install_auto_cleanup()` before doing work. That records the live `editor_sdk.exe` PID snapshot and registers an `atexit` hook.
2. When the process exits — normally, on error, or on `sys.exit` — the hook terminates only PIDs explicitly recorded as spawned by the task. A PID that merely appeared after the snapshot is reported in `unowned_pids` and left running; an SDK the user opened before the task is never touched.
3. The hook writes the outcome to `%TEMP%\officecli_editor_sdk_cleanup.json` with `verified`, `spawned_during_task`, `unowned_pids`, `unreleased_pids`, `terminated_pids`, `still_running`, and `source_process`.

**What the agent must do**

- Run document work through `scripts/*.py` so the hook is installed; if a task needs a custom Python snippet, call `install_auto_cleanup()` at its top.
- Before the final response, read `read_auto_cleanup_log()` (or the JSON file) and report the cleanup result. Do not state that the file lock was released without this evidence.
- If the log shows `"verified": false` or the output file still cannot be opened for read/write, run `python scripts/cleanup_editor_sdk.py --list` to name the exact owning PID. If the lock belongs to a preview process the user is willing to close, run `python scripts/cleanup_editor_sdk.py --kill-pid <pid> --confirm` — the command verifies the PID's image name and creation time before terminating that single process. Never use a global `taskkill /IM editor_sdk.exe`.
- A transaction that hits a locked output returns `abort_reason: OUTPUT_FILE_LOCKED` with `lock_info.editor_sdk_pids` and a `hint`; report those facts and do not retry blindly.
- Set `OFFICECLI_DISABLE_AUTO_CLEANUP=1` only when hosting the engine inside a longer-lived process that must not terminate SDKs on exit.

**Manual tooling remains available for diagnosis only** (`python scripts/cleanup_editor_sdk.py --list`), never as the primary cleanup path.

Subprocess and handle ownership for everything the engine itself spawns:

- Start every `officecli.exe`, `soffice`, Excel, or Word helper inside the current task's `TaskResourceGuard`; record the exact PID immediately after launch.
- Close registered document handles and call `guard.release_all()`. Never use `taskkill /IM`, process-name matching, or a global kill.

Canonical pattern:
```python
from engine import TaskResourceGuard, install_auto_cleanup, read_auto_cleanup_log

# Automatic SDK cleanup: snapshot now, terminate task-spawned SDKs on exit.
install_auto_cleanup()

with TaskResourceGuard(task_id=task_id) as guard:
    try:
        result = guard.run_owned_command(command, cwd=work_dir, check=True)
        run_all_qa()
    finally:
        guard.release_all()

cleanup = read_auto_cleanup_log()  # report this in the final answer
if not cleanup.get("verified", False):
    raise RuntimeError(f"OfficeCLI cleanup could not be verified: {cleanup}")
```
