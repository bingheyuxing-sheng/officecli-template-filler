---
name: officecli-template-filler
description: Office Document Intelligence engine for Word (.docx) and Excel (.xlsx/.xlsm) templates. Routes tasks via a 7-mode Task Router (GENERATE, POLISH, REPAIR, REVIEW, MERGE, REFORMAT, EXCEL_GENERATE), classifies template compatibility (L1-L4), and applies non-destructive cross-run replacement, Decimal SSOT solving, MIME/reference-counted image replacement, PID-scoped resource cleanup, and Package plus Format/Font/Table QA. REVIEW mode writes native Word tracked changes (w:ins/w:del plus w:*PrChange format revisions) and comments so a human accepts or rejects every change. L1-L3 targets Zero Unintended Formatting Delta; L4 objects are preserved read-only and reported in coverage_gaps rather than claimed as 100 percent fidelity.
---

# OfficeCLI + Python Office Document Intelligence Skill (v3.4.2 — 7-Mode Task Router, L1–L4 Compatibility Matrix, Dual-Document REPAIR, REVIEW with Native Word Tracked Changes & Format Revisions, Non-Destructive OOXML & Decimal SSOT Engine)

Follow five architectural pillars across **every** `.docx` and `.xlsx` document task:

1. **Task Router First (7 Specialized Modes & Context-Aware Web Search Policy)**:
   Always classify the user's input files and prompt into one of seven execution modes (`GENERATE`, `POLISH`, `REPAIR`, `REVIEW`, `MERGE`, `REFORMAT`, `EXCEL_GENERATE`) via `engine.docx_parser.route_document_task()` before taking action. Web search is **enabled by default ONLY for `GENERATE` / `EXCEL_GENERATE`** when domain standards or public institution facts are needed, and **disabled by default for `REPAIR`, `REVIEW`, `POLISH`, `MERGE`, and `REFORMAT`** (unless the user explicitly requests external fact verification).
2. **4-Tier User Confirmation Gate (`SKIP`, `LIGHT_CONFIRM`, `FULL_CONFIRM`, `HOLD_AND_ASK`)**:
   Tailor user interaction to task certainty:
   - **`SKIP`**: User explicitly says "直接生成/按默认生成", or task is pure `REPAIR`/`REFORMAT` with 100% deterministic content and compatible structures.
   - **`LIGHT_CONFIRM`**: Minor optional slots or low-impact formatting choices exist; present a compact 1–2 item summary with smart defaults.
   - **`FULL_CONFIRM`**: Unsearchable internal facts exist in `GENERATE`/`EXCEL_GENERATE` (e.g., project leader name, unannounced partner companies, internal approval IDs); present a consolidated Pre-Write Confirmation Card once with one-click normative defaults.
   - **`HOLD_AND_ASK`**: High-risk `L4` structural unsupported elements (e.g., SmartArt/OLE/Chart binary data mutation, password-protected VBA macros) or conflicting dual-document structures are detected; pause and ask the user how to handle those specific regions before writing.
3. **Template Compatibility Level Classification (`L1`–`L4`)**:
   Every template is automatically profiled into `L1` (Standard), `L2` (Moderately Complex), `L3` (Complex Styled), or `L4` (Manual Confirmation Required) via `engine.docx_parser.assess_template_compatibility_level()` and output as a formal `DocumentSpec` (`schemas/document_spec.schema.json`).
4. **Modular, Unit-Tested Python Engine (`engine/` + `scripts/`) — Never Reinvent Ad-Hoc Helpers**:
   All core OOXML, Decimal SSOT, Table, Image, Excel, Repair, Process Guard, and QA algorithms reside in standalone, unit-tested Python modules under `engine/` with CLI entrypoints in `scripts/`. Never write ad-hoc destructive `set_par_text` or `taskkill /F /IM` commands.
   **Validation never uses `assert`**: `python -O` strips assertions, so every quality gate raises a real exception instead — `SSOTValidationError` from `engine.ssot_engine` and `QAValidationError` from `engine.qa_engine`. Pass `raise_on_failure=False` to `audit_format_and_text_qa()` when a structured `{"passed": false, "issues": [...]}` report is preferred over an exception.
   **Universal process cleanup (applies to ALL seven modes, not only red-text QA)**: the cleanup is automatic, not a manual step. Every `scripts/*.py` entrypoint calls `install_auto_cleanup()` on startup, which snapshots live `editor_sdk.exe` identities `(pid, start_ticks)` and registers an exit hook that terminates only the instances spawned during that process. Identity is re-checked by exact image name and kernel start time before any termination, so a recycled PID or a user-opened SDK is never touched. WorkBuddy's sandbox keeps `editor_sdk.exe` alive after an agent turn, which is exactly what leaves the DOCX locked in WPS, so never skip this and never ask the user to run a cleanup command.
5. **Zero Unintended Formatting Delta + Package & Visual QA (with honest coverage reporting)**:
   Deliver documents that preserve every unmapped style, run property, `<w:proofErr>` node, complex cell structure, shared image `rId`, and Excel formula, verified by `audit_docx_package_integrity()`, `audit_format_and_text_qa()`, `run_visual_layout_qa()`, and `audit_excel_formula_and_style_qa()`.
   This is a guarantee about **unintended** changes only. Never claim 100% byte-identical rendering versus Word/WPS: list every unsupported object in `coverage_gaps` and never treat "not detected" as "passed".
   Font size is verified per run against the template: always call `audit_format_and_text_qa(..., reference_docx_path=template_path)` (or `scripts/run_qa.py output.docx --reference template.docx`). The effective size cascade is run `w:sz` -> character style -> paragraph style -> `w:docDefaults`; without the template the baseline falls back to the output's own dominant size and `size_baseline_source` says so, which cannot prove anything for a document that drifted uniformly.
   Font family and table structure are verified the same way, and they are NOT covered by size checks:
   - Fonts resolve through run `w:rFonts` -> character style -> paragraph style -> `w:docDefaults`, then compare against the template's font inventory (`font_anomalies`).
   - Each table is compared against the template table at the same index: grid column widths and ratios, total width, `tblLayout`, `jc`, `tblCellMar`, `tblBorders` (including border size and color), `w:tblStyle`, header-row `w:shd` fill, cell `w:vAlign` distribution, and per-row `trHeight` (`table_style_anomalies`). Text-only checks miss an entire class of drift: a table can match every font and size yet still have the wrong header band, no vertical centering, and collapsed row heights.
   - Row-level pagination is verified only where the template proves it: if the template sets `w:cantSplit` on all rows or `w:tblHeader` on row 0, the output must match (`pagination_anomalies`).
   - Table font and size are compared against that table's own dominant value (`table_dominant_size` / `table_dominant_font`). Never accept a document-wide size allowlist here: a table regenerated at a larger size still uses a size the template used somewhere else, which is exactly how drifting tables slipped through before.

---

## Core Architecture Rule 1 — Task Router & Web Search Strategy

Run `python scripts/inspect_document.py --inputs <file1> [<file2> ...] --intent "<user_prompt>"` (or call `route_document_task()`) to route every request:

| Task Mode | Trigger Condition | Primary Engine Pipeline | Web Search Policy | Default Confirmation Tier |
|---|---|---|---|---|
| **`GENERATE`** | 1 `.docx` template + user topic/data to populate | `analyze_template.py` → Research → `ssot_engine` → `generate_document.py` → `run_qa.py` | **ENABLED** (Standards + Official Institution Site) | `FULL_CONFIRM` (if unsearchable internal slots exist) or `LIGHT_CONFIRM` |
| **`REPAIR`** | exactly 2 `.docx` files (`reference_template.docx` + `broken_target.docx`) | `repair_document.py` (`build_repair_plan` → `repair_plan.json` → `execute_repair_plan`) → `run_qa.py` | **DISABLED BY DEFAULT** (Strict content preservation from broken doc) | `SKIP` (or `HOLD_AND_ASK` if `L4` structural mismatch) |
| **`REVIEW`** | 2 `.docx` files + intent containing 审核/审阅/修订/留痕/review/track changes/按模板修正 | `review_document.py` (`build_review_plan` → `execute_review_plan`) → `audit_review_integrity` + `run_qa.py` | **DISABLED BY DEFAULT** (No external rewriting during audit) | `LIGHT_CONFIRM` for the revision list; `HOLD_AND_ASK` if `L4` regions need manual edits |
| **`POLISH`** | 1 `.docx` draft + request to refine wording/terminology while keeping layout | `analyze_template.py` → `LogicalParagraphView` surgical replacement → `run_qa.py` | **DISABLED BY DEFAULT** (On-demand only if user asks to verify standards) | `LIGHT_CONFIRM` |
| **`MERGE`** | 2+ `.xlsx`, or a `.docx`/`.xlsx` mix, or any multi-source merge request | `analyze_template.py` → `ssot_engine` cross-doc reconciliation → format-specific generator → `run_qa.py` | **DISABLED BY DEFAULT** | `LIGHT_CONFIRM` |
| **`REFORMAT`** | 1 or 2 `.docx` + typographic intent (统一字体/统一字号/重新排版/格式统一/修复格式) | `repair_engine` profile application + `sanitize_ooxml_whitespace_and_pagination` → `run_qa.py` | **DISABLED BY DEFAULT** | `SKIP` |
| **`EXCEL_GENERATE`** | exactly 1 `.xlsx`/`.xlsm` template + data/topic to populate | `analyze_template.py` → `ssot_engine` (`Decimal`) → `generate_excel.py` → `run_qa.py` | **CONDITIONAL** (Enabled if external standards/rates needed) | `FULL_CONFIRM` or `LIGHT_CONFIRM` |

Routing notes that prevent the common misroutes:

- A single `.docx` with "统一字体/重新排版/修复格式" is `REFORMAT`, never `REPAIR` — dual-document REPAIR requires exactly two `.docx` inputs.
- Two or more `.xlsx` files, or a `.docx` + `.xlsx` mix, route to `MERGE` regardless of the intent wording; only a single workbook is `EXCEL_GENERATE`.
- `EXCEL_GENERATE` must run `generate_excel.py`; never send an `.xlsx` input to `generate_document.py`.

---

## Core Architecture Rule 2 — Template Compatibility Matrix (`L1`–`L4`)

`classify_template_compatibility(doc)` inspects all stories (body, headers, footers, nested tables, `w:txbxContent` textboxes, footnotes, endnotes, comments) and classifies the template:

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
│   ├── style_engine.py                   # Style hierarchy resolver & non-destructive paragraph filler
│   ├── docx_parser.py                    # Task Router, L1-L4 compatibility classifier & DocumentSpec builder
│   ├── repair_engine.py                  # Dual-document REPAIR diff planner & non-destructive executor
│   ├── review_engine.py                  # v3.1: tracked changes, native comments & review integrity QA
│   └── qa_engine.py                      # P1-7: Full DOCX Package XML/Rels/Media QA + Visual Layout QA
├── scripts/                              # CLI entrypoints for Agent orchestration
│   ├── inspect_document.py               # Route task mode & inspect input files
│   ├── analyze_template.py               # Emit DocumentSpec JSON (schemas/document_spec.schema.json)
│   ├── generate_document.py              # Execute SSOT + non-destructive DOCX rendering
│   ├── generate_excel.py                 # v3.2: EXCEL_GENERATE entrypoint (fills .xlsx, keeps formulas)
│   ├── repair_document.py                # Dual-document REPAIR mode (emit & execute repair_plan.json)
│   ├── review_document.py                # v3.1: REVIEW mode (tracked changes + comments + review_report.json)
│   ├── cleanup_editor_sdk.py             # Manual diagnostic: list SDK PIDs (auto cleanup runs in every entrypoint)
│   ├── render_document.py                # Render DOCX/XLSX to PDF via TaskResourceGuard for visual inspection
│   ├── run_qa.py                         # Run Package QA, Format QA, Excel Formula QA & Visual QA
│   ├── ensure-officecli.ps1              # Windows OfficeCLI installer
│   └── ensure-officecli.sh               # macOS/Linux OfficeCLI installer
├── schemas/                              # Formal JSON Schemas for intermediate artifacts
│   ├── document_spec.schema.json         # DocumentSpec output schema
│   ├── repair_plan.schema.json           # RepairPlan output schema
│   ├── review_report.schema.json         # v3.1: REVIEW mode execution + integrity report
│   └── qa_report.schema.json             # Unified QA Report schema
├── tests/                                # Automated unit test suite
│   └── test_v3_engine.py                 # 100% coverage of P0-1..P1-8 & REPAIR mode
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
- **Font & render risk QA**: `run_visual_layout_qa()` now reports `FONT_NOT_INSTALLED` (declared font missing on this machine → renderer will substitute), `RENDER_PAGE_COUNT_MISMATCH` and `RENDER_PAGE_PIXEL_DIFF` when both PDFs and PyMuPDF are available; unverifiable checks are recorded as `coverage_gaps` (`FONT_AVAILABILITY_UNVERIFIED`, `PDF_PAGE_DIFF_UNAVAILABLE`, `RENDER_PDF_NOT_PRODUCED`), never silently passed.
- **v3.4.1 — no silent format edits in REVIEW**: every format restore is paired with a Word formatting-revision mark (`w:rPrChange`, `w:pPrChange`, `w:tblPrChange`, `w:trPrChange`, `w:tcPrChange`) holding the pre-change properties, so the delivered document always contains accept/reject-able revisions in addition to comments. `execute_review_plan()` reports `tracked_format_changes` and per-action `format_revision_ids`; `list_format_revisions(docx)` lists them; `audit_review_integrity()` validates their ids/authors/dates and reports `format_revision_count`. A REVIEW output with zero revisions AND zero format marks while the plan had format actions is a bug, not a delivery. REPAIR remains direct (no marks) by design.
- **v3.4.2 — Review safety & honest QA**:
  - Revision ids reported in `action_results` are the ids actually written into the XML (recorded at `ids.take()` time, never back-derived).
  - Tracked replacements cannot reorder paragraph structure: matches must live inside one contiguous plain-run group; hyperlink/SDT/field containers never move; runs carrying drawings/field codes are refused (degrade to comment).
  - `location_id` + `occurrence` now drive revision targeting. Multiple matches with no location → the edit is refused and an `AMBIGUOUS_MULTIPLE_MATCHES` comment is anchored instead of silently editing the first hit.
  - Merge topology (`gridSpan`/`hMerge`/`vMerge`) is not rewritten; a table action that still differs in merges reports `PARTIALLY_APPLIED` with `unresolved_properties` and `requires_human_review: true`.
  - `generate_excel.py` keeps VBA for `.xlsm` (`keep_vba=True`, `.xlsm` output enforced) and runs Excel QA against the ORIGINAL template, not the output itself.
  - Excel formulas the builtin evaluator cannot compute are counted in `unsupported_formulas` / `unverified_count` with `FORMULAS_UNVERIFIED` coverage gap — never silently passed. `SUBTOTAL` dispatches by function code (1=AVERAGE, 2=COUNT, 4=MAX, 5=MIN, 9=SUM).
  - `run_qa.py` gains a fourth status: when any check could not run (`unverified_count`/`coverage_gaps` non-empty with zero issues), overall status is `UNVERIFIED`, not `PASSED`.

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
4. Format-only repairs (font, size, table structure) are applied directly because tracked changes cannot represent them; say so in the handoff, then point the user at the `.docx`.
5. Final response format: link the `.docx`, list counts of revisions and comments, and name the file that opens in revision mode. Do not paste the Markdown report in place of the file.

---

## Standard End-to-End Execution Workflow

### Step 1: Route Task & Inspect Inputs
```powershell
python scripts/inspect_document.py --inputs "$INPUT_1" --intent "$USER_PROMPT" --output "$TEMP/routing.json"
```

### Step 2: Analyze Template & Emit `DocumentSpec`
```powershell
python scripts/analyze_template.py --input "$INPUT_1" --output "$TEMP/document_spec.json"
```
Inspect `compatibility.level` (`L1`–`L4`) and `placeholder_Inventory`.

### Step 3: Conditional Research & 4-Tier Confirmation Gate
- Follow the routed `web_search_policy` (`ENABLED` for `GENERATE`, `DISABLED_BY_DEFAULT` for `REPAIR`/`POLISH`/`MERGE`/`REFORMAT`).
- Apply the routed Confirmation Tier (`SKIP`, `LIGHT_CONFIRM`, `FULL_CONFIRM`, or `HOLD_AND_ASK`).

### Step 4: Execute Mode-Specific Engine Pipeline
- **For `GENERATE` / `EXCEL_GENERATE` / `POLISH` / `MERGE`**:
  Build `ssot_payload.json` (validated via `build_ssot_master_data()`) and run:
  ```powershell
  python scripts/generate_document.py --template "$INPUT_1" --payload "$TEMP/payload.json" --output "$OUTPUT_FILE"
  ```
  *(Or import `engine` directly in a task-specific Python script using the canonical APIs documented in [references/python-docx-engine.md](references/python-docx-engine.md)).*
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
      --out "$OUTPUT_DOCX" --plan-out "$TEMP/review_plan.json" --report "$TEMP/review_report.json"
  ```
  Hand the user the generated `.docx` — not a Markdown checklist and not the JSON report. Tell them WPS/Word opens it in revision mode, format repairs are already applied, and each `<w:ins>`/`<w:del>` and comment still needs their accept/reject decision.

### Step 5: Mandatory Package, Format, Formula & Visual QA
```powershell
python scripts/run_qa.py --output "$OUTPUT_FILE" --reference "$INPUT_1" --report "$TEMP/qa_report.json"
```
Read `status` in `qa_report.json` — it is one of three values, never a bare boolean:

| status | Meaning | Exit code |
|---|---|---|
| `PASSED` | No issues at all | 0 |
| `PENDING_HUMAN_REVIEW` | Only `TEMPLATE_TEXT_RESIDUAL` items remain and `--review` was passed; the file is structurally sound and waits for a human decision | 0 |
| `FAILED` | At least one hard failure | 1 |

The report also carries `issues` (flattened objects with `code`, `location`, `detail`, `severity`), `coverage_gaps`, `unverified_count`, `hard_failure_count` and `pending_human_review_count`. Branch on `code`, never on prose. Never describe a `FAILED` report as delivered, and never call `PENDING_HUMAN_REVIEW` broken.

For REVIEW outputs, run `python scripts/run_qa.py "$OUTPUT_FILE" --review --reference "$REF_DOCX"`:

- `review_qa.passed` must be `true`: every revision and comment is structurally valid.
- Placeholder residue becomes `PENDING_HUMAN_REVIEW`, not a failure, because REVIEW intentionally leaves undecided items for the human.
- Without `--review`, placeholder residue counts as a failure, since nothing is expected to stay unresolved.

### Step 6: Automatic Agent Shutdown & File-Lock Release
This step is automatic and applies to every document task, including success, QA failure, cancellation, and exceptions. Do not ask the user to run a cleanup command, and do not make cleanup a separate workflow step.

**How it works**

1. Every `scripts/*.py` entrypoint calls `install_auto_cleanup()` as its first statement. That records the live `editor_sdk.exe` PID snapshot and registers an `atexit` hook.
2. When the process exits — normally, on error, or on `sys.exit` — the hook compares live PIDs against the snapshot and terminates only instances that appeared during that run. A SDK the user opened before the task is never touched.
3. The hook writes the outcome to `%TEMP%\officecli_editor_sdk_cleanup.json` with `verified`, `spawned_during_task`, `terminated_pids`, `still_running`, and `source_process`.

**What the agent must do**

- Run document work through `scripts/*.py` so the hook is installed; if a task needs a custom Python snippet, call `install_auto_cleanup()` at its top.
- Before the final response, read `read_auto_cleanup_log()` (or the JSON file) and report the cleanup result. Do not state that the file lock was released without this evidence.
- If the log shows `"verified": false` or the output file still cannot be opened for read/write, run `python scripts/cleanup_editor_sdk.py --list` to name the exact owning PID, then re-run the task entrypoint or stop that single PID.
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
assert cleanup.get("verified", False), cleanup
```
