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

### 7. Dual-Document `REPAIR` Mode (`engine/repair_engine.py`)
- When given a reference template (`reference.docx`) and a formatting-damaged target document (`broken.docx`), run `scripts/repair_document.py`:
  1. `build_repair_plan(ref_path, brk_path)` diffs section page margins/orientations, heading/body paragraph typography (`rFonts`, `sz`, `line`, `firstLineChars`), residual red colors, and table borders/alignments/column grids/pagination (`w:cantSplit`, `w:tblHeader`), outputting `repair_plan.json` (`schemas/repair_plan.schema.json`).
  2. `execute_repair_plan(plan, output_path)` applies all formatting repairs while preserving **100% of the business text and data** in `broken.docx`.
  3. Row-level pagination detected by the plan is actually written, not just reported: every row gets `<w:cantSplit/>`, and `<w:tblHeader/>` is added **only** when the reference table marks row 0 as a header, or row 0 is fully bold while row 1 is not. A data row is never promoted to a repeating header. `w:cantSplit` is inserted before `w:trHeight` per the `w:trPr` schema order, and the execution report counts `fixed_cant_split_rows`, `fixed_tbl_header_rows` and `skipped_header_candidates`.
  4. Table style restoration is shared with REVIEW: `restore_table_style_from_reference()` syncs `w:tblStyle`, `tblW`, `jc`, `tblBorders`, `tblLayout`, `tblCellMar`, grid column widths, header-row `w:shd`, every cell's `w:vAlign`, and missing `w:trHeight` values, all inserted in schema order and without touching cell text or merges.

### 8. Full Package QA + Visual QA (`engine/qa_engine.py` — Fixes P1-7)
- `audit_docx_package_integrity(docx_path)` inspects the raw ZIP archive to verify well-formed XML across all parts (`document.xml`, `styles.xml`, `numbering.xml`, `settings.xml`, `header*.xml`, `footer*.xml`, `footnotes.xml`, `endnotes.xml`, `comments.xml`), zero dangling `.rels` targets, valid `[Content_Types].xml`, and intact media binaries.
- `run_visual_layout_qa(docx_path, reference_docx_path)` checks table grid widths against printable page margins, inline image aspect-ratio distortion, and (when a PDF backend — WPS or LibreOffice — is available) renders a PDF preview for visual layout verification.

### 9. Template-Driven REVIEW Mode (`engine/review_engine.py`)
Use REVIEW when a human must decide, not when the agent should silently rewrite. The engine splits every finding into three channels:

| Channel | OOXML mechanism | Human action | Report field |
|---|---|---|---|
| Format drift (font family, size, spacing, indent, residual red) | Restored AND written as tracked formatting revisions (`w:rPrChange` / `w:pPrChange` carrying the pre-change properties), so Word/WPS shows them as accept/reject-able "Formatting" entries — nothing is silently rewritten | Accept or reject each formatting revision in the review pane | `format_restore_actions`, `tracked_format_changes` |
| Table structure drift (column widths, `tblLayout`, alignment, cell margins, borders, `tblStyle`, header shading, cell `vAlign`, row heights) | Restored via `restore_table_style_from_reference()` AND recorded as `w:tblPrChange` / `w:trPrChange` / `w:tcPrChange` / cell `w:rPrChange`; cell text and merges untouched | Accept or reject in the review pane | `table_style_restores`, `tracked_format_changes` |
| Text correction submitted as `text_revisions` | `<w:del>` + `<w:delText>` for old text, `<w:ins>` + `<w:t>` for new text, each with `w:author`/`w:date` | Accept or reject each revision in WPS/Word review pane | `tracked_text_revisions` |
| Unresolved placeholders and judgement calls | Native `word/comments.xml` + `commentRangeStart`/`commentRangeEnd`/`commentReference` | Reply or resolve the comment | `comments` |

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
| `--findings findings.json` | External evidence (Excel/JSON/consistency QA) converted to inline comments; `--reference` then becomes optional |
| `--out reviewed.docx` | **Required for delivery.** The revision-mode document the user opens in Word/WPS |
| `--report review_report.json` | Internal audit trail, not a deliverable |

Rules:

1. `--plan-only` is allowed for internal inspection only. It must never be the final step of a REVIEW task.
2. If the analysis produced a findings list (for example a Markdown checklist), convert each actionable item into a `revisions.json` entry, or pass it as `--findings findings.json` when the evidence is Excel/JSON; do not ship the checklist instead of the document.
3. Items you cannot express as a text replacement become native comments with `ADD_REVIEW_COMMENT`, so the human sees them inline in Word. `--findings` rejects unresolved locations instead of dropping them; fix the location or add a manual comment anchor.
4. Format-only repairs (font, size, paragraph properties, and supported table properties) must be paired with native `w:*PrChange` formatting revisions. Unsupported or structurally unsafe changes remain comments or `manual_required`; never apply them silently.
5. Final response format: link the `.docx`, list counts of revisions and comments, and name the file that opens in revision mode. Do not paste the Markdown report in place of the file.

## Pictures by role, optional OCR, figure rendering

- `find_images(doc, role=None)` walks every story part (`.//w:p` works for `w:body`, `w:hdr` and `w:ftr` roots) and returns `role`, `evidence`, `owner_part`, `paragraph_index`, `blip_index`, pixel size and caption. Role heuristics use structure first: header/footer → `logo` (or `stamp` when square and predominantly red), small square grayscale body image → `qr`, caption keywords (`示意图`/`流程图`/`二维码`) → `illustration`/`qr`, large body image → `illustration`.
- `replace_image_by_role()` resolves exactly one match and refuses on ambiguity, because silently replacing the wrong logo is worse than asking.
- `ocr_engine` probes `rapidocr_onnxruntime` → `paddleocr` → `pytesseract`+`tesseract`, normalises their three different return shapes into text, and returns `OCR_UNAVAILABLE` as a coverage gap when none exists. `audit_image_text()` reports `PLACEHOLDER_TEXT_IN_IMAGE` (medium) for `***`, `XXXX`, `___`, `待填写`, `示例文本`, `此处插入`, and records `VECTOR_IMAGE_OCR_UNSUPPORTED` for SVG/EMF/WMF parts.
- `chart_render.render_chart_image(spec, out)` renders `table` / `bar` / `pie` from payload data at 200 dpi. It returns `INVALID_SPEC`, `RENDER_BACKEND_UNAVAILABLE` (no matplotlib) or `CJK_FONT_UNAVAILABLE` (Chinese labels but no CJK font) instead of writing a garbled image; only `RENDERED` produces a file.
- This file holds engine implementation detail; `SKILL.md` keeps routing, workflow and QA gates.
