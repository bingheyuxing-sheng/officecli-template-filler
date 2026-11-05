---
name: officecli-template-filler
description: Template-driven Office document engine for Word (.docx) and Excel (.xlsx/.xlsm). Routes tasks into eight modes (GENERATE, REPAIR, REFORMAT, REVIEW, PROOFREAD, EXCEL_GENERATE, POLISH, MERGE), classifies template compatibility L1-L4, fills through a strict FillPlan executor with Zero Unintended Formatting Delta and native tracked changes, and gates delivery with four-state QA plus honest coverage_gaps. Use whenever the user supplies a .docx or .xlsx template to fill, generate, repair, reformat, review, proofread, or QA — e.g. 模板填充, 按模板生成文档, 按模板修复/对齐格式, 审阅留痕修订, 课程计划生成, Excel 模板填数 — even if no mode name is given; unimplemented modes (POLISH/MERGE) are reported as CAPABILITY_NOT_AVAILABLE. Do not use for PDF, PPTX, or writing without a template.
---

# OfficeCLI + Python Office Document Intelligence Skill (v4.0.2 stable — contract set 4.2.0; v3.5.9 compatibility baseline)

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
   **Universal process cleanup (ALL eight modes)**: automatic, never a manual step or a user instruction. Every document entrypoint calls `install_auto_cleanup()` on startup, snapshots live `editor_sdk.exe` identities, and on exit terminates only PIDs recorded as spawned by this task — anything else is reported in `unowned_pids` / `unreleased_pids`, never killed on a guess, and each task writes its own per-task cleanup evidence. Step 6 defines the full contract and the agent-facing duties.
6. **Zero Unintended Formatting Delta + Package & Visual QA (with honest coverage reporting)**:
   Deliver documents that preserve every unmapped style, run property, `<w:proofErr>` node, complex cell structure, shared image `rId`, and Excel formula, verified by `audit_docx_package_integrity()`, `audit_format_and_text_qa()`, `run_visual_layout_qa()`, and `audit_excel_formula_and_style_qa()`.
   This is a guarantee about **unintended** changes only. Never claim 100% byte-identical rendering versus Word/WPS: list every unsupported object in `coverage_gaps` and never treat "not detected" as "passed".
   Size, font and table checks always compare an output item against its **matched** template counterpart — never a document-wide allowlist — so pass `reference_docx_path=template_path` to `audit_format_and_text_qa(...)` with `comparison_profile="STYLE_GUIDE"` for GENERATE (or `scripts/run_qa.py output.docx --reference template.docx --profile style-guide`) and `REPLICA` for REPAIR/REVIEW. The resolution cascades, Chinese font-name normalization, table geometry fields, pagination rules and row-count gating are specified in [`references/python-docx-engine.md`](references/python-docx-engine.md) §3.9 — read it before changing QA comparison code.

---

## Core Architecture Rule 1 — Task Router & Web Search Strategy

Run `python scripts/inspect_document.py --inputs <file1> [<file2> ...] --intent "<user_prompt>"` (or call `route_document_task()`) to route every request:

| Task Mode | Trigger Condition | Primary Engine Pipeline | Web Search Policy | Default Confirmation Tier |
|---|---|---|---|---|
| **`GENERATE`** | 1 `.docx` template + user topic/data to populate; an accompanying `.xlsx` is recorded as `data_sources` when the intent is generation | `analyze_template.py --spec-version 4` → validate DocumentSpec → ContentPlan + FillPlan → `generate_document.py --spec/--plan/--content-plan` → QAReport + commit gate | **ENABLED** (Standards + Official Institution Site) | `FULL_CONFIRM` (if unsearchable internal slots exist) or `LIGHT_CONFIRM` |
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

## Core Architecture Rule 3 — Directory & Module Architecture (v4.0)

```
officecli-template-filler/
├── AGENTS.md / SKILL.md                  # Project rules (authoritative) / this skill workflow
├── contracts/  config/  schemas/         # Frozen contract set 4.2.0 / QA policy, error codes, capability matrix / JSON Schemas
├── template_intelligence/                # DocumentSpec 4.0 producer, slot ids, fingerprint, validator
├── content_intelligence/                 # ContentPlan / FillPlan builders and validators
├── document_engine/                      # FillPlan executor, fill ledger, execution pipeline
├── qa/                                   # QAReport 4.0, QA gate, pipeline, environment probe
├── engine/                               # v3.5.9 standalone, importable Python engine package
├── scripts/                              # CLI entrypoints — the surface an agent calls (table below)
├── tests/                                # Automated suite (479 tests)
├── reports/                              # W0–W3 acceptance, gate and issue records
└── references/                           # engine-internals.md / python-docx-engine.md
```

CLI surface an agent orchestrates through (`scripts/`):

| script | purpose |
|---|---|
| `inspect_document.py` | Route task mode & inspect input files |
| `analyze_template.py` | Emit DocumentSpec JSON (`--spec-version 4` for the GENERATE plan chain) |
| `analyze_excel_template.py` | Emit Excel template spec (`.xlsx`/`.xlsm`) |
| `generate_document.py` | v4 plan chain executor + legacy `--data` token path |
| `generate_excel.py` | EXCEL_GENERATE (fills `.xlsx`, keeps formulas) |
| `repair_document.py` | Dual-document REPAIR (emit & execute repair_plan.json) |
| `review_document.py` | REVIEW (tracked changes + comments + review_report.json) |
| `proofread_document.py` | PROOFREAD (single-document tracked fixes) |
| `reformat_document.py` | REFORMAT (semantic format diff + tracked `w:*PrChange` apply) |
| `render_document.py` | DOCX visual QA; PDF via WPS word2pdf / LibreOffice, else `RENDER_PDF_NOT_PRODUCED` |
| `run_qa.py` | Package / Format / Content / Image-text / Excel Formula / Visual QA |
| `cleanup_editor_sdk.py` | Manual diagnostic only — auto cleanup runs inside every entrypoint |

Per-module internals of `engine/` (LogicalParagraphView, SSOT solver, image/process/table/excel engines, transaction, workflow & research helpers) live in [`references/engine-internals.md`](references/engine-internals.md) — read it before editing `engine/`. Python API usage and QA verification mechanics live in [`references/python-docx-engine.md`](references/python-docx-engine.md).

---

## Engine Guarantees (implemented and test-covered)

The behaviours below are enforced in `engine/`, not advisory. Rationale, code paths and
per-version history live in [`references/engine-internals.md`](references/engine-internals.md).

| Area | Guarantee |
|---|---|
| Text edits | `LogicalParagraphView` maps logical characters to `<w:t>` slices; no global `proofErr` stripping, no destructive run merging |
| Numbers | `Decimal` only, explicit rounding and units, largest-remainder percentages summing to exactly 100% |
| Images | MIME-matched in-place replacement, shared-part forking, SVG dual-embed cleanup, VML support, crop/extent handling, post-save verification |
| Processes | `TaskResourceGuard` tracks only task-spawned PIDs; global `taskkill /IM` is forbidden |
| Tables | 9-way cell classification before mutation; hyperlink/image/sdt/nested cells are never wiped |
| Excel | Row cloning copies height, fill, border, number format and merges; formulas are re-verified after write |
| Delivery | `DocumentTransaction` stages, validates and atomically publishes; a failure never leaves a half-written deliverable |
| QA | Four-state status (`PASSED` / `FAILED` / `PENDING_HUMAN_REVIEW` / `UNVERIFIED`); unverifiable checks become `coverage_gaps` |
| Routing | Role-aware: template + data + generate intent stays `GENERATE`; unimplemented modes return `CAPABILITY_NOT_AVAILABLE` |
| Content | Numeric conflicts, subtotal closure and name drift are checked; every SSOT fact needs a `source` |
| Images by role | `find_images(role=...)` / `replace_image_by_role()` target logo / stamp / qr / illustration with stated evidence |
| OCR | Optional backend; without one the run reports `OCR_UNAVAILABLE` instead of claiming image text was read |
| Figures | `render_chart_image()` renders table/bar/pie from payload data; missing matplotlib or CJK font returns an explicit status |

## Standard End-to-End Execution Workflow

### Step 1: Route Task & Inspect Inputs
```powershell
python scripts/inspect_document.py --inputs "$INPUT_1" --intent "$USER_PROMPT" --output "$TEMP/routing.json"
```

### Step 2: Analyze Template & Emit `DocumentSpec`
Pick the analyzer by container type — never run the Word analyzer on a workbook:
```powershell
# .docx / .docm — GENERATE must use the v4 spec
python scripts/analyze_template.py --input "$INPUT_1" --spec-version 4 --output "$TEMP/document_spec.json"

# .xlsx / .xlsm
python scripts/analyze_excel_template.py --input "$INPUT_1" --output "$TEMP/document_spec.json"
```
For `GENERATE`, **always pass `--spec-version 4`**. The default (`3`) is the legacy CLI summary kept for the old `--data` token path and non-generation modes; it is never the v4 plan chain. Inspect the v4 artifact's `slots`, `protected_regions`, `unsupported_features` and `warnings` — not `candidate_hits` (`L1`–`L4` still appears under `template.compatibility`). A body-level `w:sdt` is discovered as PROTECTED (`kind: "sdt"` region); `sdt_edit` stays false.

Also read `routing.capability` from Step 1 before executing anything:

| field | Meaning |
|---|---|
| `enabled: true` | The mode has a real handler (`capability.handler`); continue. |
| `enabled: false`, `reason: CAPABILITY_NOT_AVAILABLE` | The mode is routed but not implemented (`POLISH` / `MERGE`). Stop and tell the user the capability is missing — do not substitute another script. |
| `OCR_UNAVAILABLE` in `coverage_gaps` | Image-internal text was requested (`--ocr`) but no OCR backend is installed. Tell the user the check did not run; never claim it passed. |
| `RENDER_BACKEND_UNAVAILABLE` / `CJK_FONT_UNAVAILABLE` | Figure rendering cannot run here (no matplotlib, or no CJK font). Report it and keep the placeholder as `NEEDS_REDRAW`; do not ship a garbled image. |
| `task_mode: UNSUPPORTED_INPUT` | At least one input is `.pdf` / `.doc` / `.wps` / `.et` or another unsupported container. Report `unsupported_files` plus `supported_formats` and stop; `inspect_document.py` exits with code 2 for this verdict. |

#### Step 2A: Template Semantic Preflight (before research or writing)

For curriculum/education templates, supplement the structural `DocumentSpec` with a semantic preflight and a repair plan. This is orchestration logic; do not rewrite the OOXML engine to implement it.

Check all of the following across body text, native tables, headers/footers, textboxes, field results, and image captions/surrounding text. Text painted **inside** a picture is only readable through the optional OCR adapter (Step 3A, `run_qa.py --ocr`); without a backend record `OCR_UNAVAILABLE` in `coverage_gaps` and ask the user for the source text if an image's content matters.

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
- **Scope honesty**: execution profiles, the P2 confirmation gate, staged checkpoints and TOC assessment are available as deterministic helpers in `engine/workflow.py` (`resolve_confirmation_gate`, `resolve_execution_profile`, `WorkflowCheckpointStore`, `assess_toc`, `run_visual_qa_rounds`). Research policy, query planning and provenance checks live in `engine/research.py`; the actual web lookup is still performed by the agent. There is still no CLI `--profile` flag: the agent selects the profile and applies the helpers. Semantic preflight remains an orchestration step. (The `run_qa.py --profile replica|style-guide` flag is a **QA comparison profile**, a separate engine feature.)

#### Step 3A: Working with pictures

Target pictures by role, not by `blip_index` — business requests say "the logo" or "the stamp".

```python
from engine import find_images, replace_image_by_role, render_chart_image

find_images(doc)                 # every picture with role + evidence
find_images(doc, role="logo")    # filter: logo / stamp / qr / illustration / photo

# Refuses when the role matches more than one picture, so the wrong image is never replaced.
replace_image_by_role(doc, "logo", "new_logo.png", fit_mode="fit_image")
```

Each entry carries `role`, `evidence`, `owner_part`, `paragraph_index`, `blip_index`, `partname`, pixel size and caption. Roles come from structure (header/footer, size, aspect, dominant hue, caption keywords), so **state the evidence when reporting**, and fall back to asking the user if the guess looks wrong.

Placeholder detection inside a picture requires OCR, which is optional:

```powershell
python scripts/run_qa.py --output "$OUTPUT_FILE" --ocr --report "$TEMP/qa_report.json"
```

- With a backend (`rapidocr_onnxruntime`, `paddleocr`, or `pytesseract` + `tesseract`), image text is read and `PLACEHOLDER_TEXT_IN_IMAGE` is reported.
- Without one the report contains `OCR_UNAVAILABLE` and the run becomes `UNVERIFIED`. Never claim you inspected text inside an image unless `image_text_qa.backend` is not `none`.
- Vector parts (`svg` / `emf` / `wmf`) are listed as `VECTOR_IMAGE_OCR_UNSUPPORTED`; they cannot be OCR'd or byte-verified.

Redrawing a placeholder figure (`FULL` profile):

```python
result = render_chart_image(
    {"kind": "table", "rows": [["课程", "学分"], ["Python 程序设计", 4]], "title": "课程设置"},
    "figure.png",
)
if result["status"] == "RENDERED":
    replace_image_by_role(doc, "illustration", result["path"])
else:
    # RENDER_BACKEND_UNAVAILABLE / CJK_FONT_UNAVAILABLE / INVALID_SPEC — keep NEEDS_REDRAW
    report_coverage_gap(result["status"], result.get("detail"))
```

`kind` is `table`, `bar` or `pie`. Only `RENDERED` means an image exists; every other status must stay in `coverage_gaps`, never be shipped as a redrawn figure.

### Step 4: Execute Mode-Specific Engine Pipeline

**Transactional delivery (v3.5 M1) — stage, verify, then commit**

`generate_document.py`, `generate_excel.py`, `repair_document.py`, `review_document.py` and `render_document.py --outdir` never write the final path directly:

1. `Preflight` — source exists, extension is supported, output directory is writable, container family matches (Word → Word, Excel → Excel).
2. `Execute` — the document is saved to a sibling `.<name>.tmp-<transaction_id>.<ext>` staged file.
3. `QA` — each entrypoint runs the checks its deliverable contract requires against that staged file: `GENERATE` → package integrity + format; `REPAIR` → package integrity + format against the reference; `REVIEW` / `PROOFREAD` → package integrity + revision/comment integrity; `EXCEL_GENERATE` → formula + style; `RENDER` → visual. The full package/format/formula/visual suite still runs separately through `run_qa.py` (Step 5).
4. `Commit` — two atomic `os.replace` calls, but only when the deliverable's contract allows it. **v4 `GENERATE` plan path**: commit only on `PASSED`, or on `UNVERIFIED` when `--allow-unverified` was passed and `missing_checks` is disclosed; `PENDING_HUMAN_REVIEW` and `FAILED` never commit. Legacy entrypoints (`REPAIR`, `REVIEW`, `PROOFREAD`, `RENDER`, Excel) keep their existing commit rules (`PASSED` / `PENDING_HUMAN_REVIEW` / `UNVERIFIED`).

Every entrypoint ends with a `transaction` object:

```json
{"transaction_id": "...", "preflight": {"passed": true, "checks": []},
 "qa_status": "PASSED", "committed": true, "abort_reason": null,
 "input_sha256": "...", "output_sha256": "...", "qa_report_path": null}
```

- `committed: false` (exit code 1) means the final file was **not** created; exit code 2 means preflight rejected the task. Never tell the user a document was produced — report `abort_reason` and the QA `issues` instead.
- `qa_status: "UNVERIFIED"` still publishes the file, but it must be described as unverified, never as a pass.
- Do not hand-write the final path in ad-hoc scripts; use the entrypoints or `engine.DocumentTransaction` so a failed run leaves no `.tmp` / `.pending` artifact behind.

- **For `GENERATE` only (v4 plan chain — the default workflow)**:
  1. Analyze with `--spec-version 4`, then validate the artifact (`template_intelligence.spec_validator.validate_document_spec`) before building anything.
  2. Build `ContentPlan` (facts with `source`, sections, target slots) and `FillPlan` (operations, preconditions, `overflow.strategy: REJECT`) per `schemas/content_plan-4.0.schema.json` / `fill_plan-4.0.schema.json`. Canonical builders: `content_intelligence.build_content_plan()` and `build_fill_plan()`; validate with `validate_content_plan()` / `validate_fill_plan()`. Never invent facts; missing sources stay missing and fail validation.
  3. Execute the deterministic chain:
  ```powershell
  python scripts/generate_document.py --template "$INPUT_1" --spec "$TEMP/document_spec.json" `
      --content-plan "$TEMP/content_plan.json" --plan "$TEMP/fill_plan.json" `
      --output "$OUTPUT_FILE" --mode STANDARD --allow-unverified
  ```
  - `STRICT` commits only a `PASSED` QAReport; `STANDARD` may commit `UNVERIFIED` only with `--allow-unverified` and the missing checks disclosed.
  - The executor writes only to a staging path, emits a per-operation fill ledger, and rejects protected/unauthorized/overflow targets before mutation.
  - Legacy token mode `--data payload.json` (no `--plan`) remains available as a **compatibility path** for simple token maps; it is not the v4 chain and must be labeled as legacy if used.
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
