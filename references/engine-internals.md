# Engine internals (reference)

Implementation detail behind the guarantees summarised in `SKILL.md`. Read this when you
are changing `engine/` or debugging a QA result — it is not needed for routine document work.

## Core Engineering Fixes Enforced in `engine/` (P0-1 through P1-8)

### 1. Non-Destructive Cross-Run Mapping (`engine/ooxml_utils.py` — Fixes P0-1)
- **Never** globally strip `<w:proofErr>` or destructively merge all adjacent runs up front.
- Always use `LogicalParagraphView(p_el)` to build a read-only character-offset map `char_map[logical_idx] -> (r_el, t_el, t_char_idx)`.
- When replacing a cross-run token (e.g. `{{` + `project_name` + `}}`), `view.replace_span()` updates only the slice inside the affected `<w:t>` nodes, preserves `<w:t>` attributes (`xml:space="preserve"`), leaves untouched runs and `<w:proofErr>` markers intact, and removes a trailing run **only** if its `<w:t>` becomes empty and the run contains no drawings, breaks, tabs, or fields.
- Use `iter_all_document_paragraphs_with_Wait_context(doc)` to traverse **all** document stories: body paragraphs, nested tables, headers, footers, textboxes (`w:txbxContent`), footnotes, endnotes, and comments. The v4 iterator additionally exposes body, header/footer, cell and nested SDT content (Contract 01 §3.1).

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
  - `sdt_control`: A legacy v3 table-cell path can rewrite text inside `<w:sdtContent>` while preserving the `<w:sdtPr>` control wrapper. The v4 FillPlan chain treats all SDT content as PROTECTED (`sdt_edit=false`) and rejects such targets with `PROTECTED_SLOT_VIOLATION`.
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
- `run_visual_layout_qa(docx_path, reference_docx_path)` checks table grid widths against printable page margins, inline image aspect-ratio distortion, and (when a PDF backend — WPS or LibreOffice — is available) renders a PDF preview for visual layout verification.

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

## v3.5.9 additions — pictures by role, optional OCR, figure rendering

- `find_images(doc, role=None)` walks every story part (`.//w:p` works for `w:body`, `w:hdr` and `w:ftr` roots) and returns `role`, `evidence`, `owner_part`, `paragraph_index`, `blip_index`, pixel size and caption. Role heuristics use structure first: header/footer → `logo` (or `stamp` when square and predominantly red), small square grayscale body image → `qr`, caption keywords (`示意图`/`流程图`/`二维码`) → `illustration`/`qr`, large body image → `illustration`.
- `replace_image_by_role()` resolves exactly one match and refuses on ambiguity, because silently replacing the wrong logo is worse than asking.
- `ocr_engine` probes `rapidocr_onnxruntime` → `paddleocr` → `pytesseract`+`tesseract`, normalises their three different return shapes into text, and returns `OCR_UNAVAILABLE` as a coverage gap when none exists. `audit_image_text()` reports `PLACEHOLDER_TEXT_IN_IMAGE` (medium) for `***`, `XXXX`, `___`, `待填写`, `示例文本`, `此处插入`, and records `VECTOR_IMAGE_OCR_UNSUPPORTED` for SVG/EMF/WMF parts.
- `chart_render.render_chart_image(spec, out)` renders `table` / `bar` / `pie` from payload data at 200 dpi. It returns `INVALID_SPEC`, `RENDER_BACKEND_UNAVAILABLE` (no matplotlib) or `CJK_FONT_UNAVAILABLE` (Chinese labels but no CJK font) instead of writing a garbled image; only `RENDERED` produces a file.
- `SKILL.md` was split: this file now holds engine implementation detail and per-version history, while the skill keeps routing, workflow and QA gates (64.7 KB → ~41 KB).
