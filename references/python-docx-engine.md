# Office Document Intelligence Engine Reference (v4.0.0 stable; v3.5.9 compatibility baseline; contract set 4.2.0)

All core OOXML, Decimal SSOT, Table, Image, Excel, Dual-Document Repair, Process Guard, Transaction, REVIEW/PROOFREAD, and Package/Visual QA logic lives in standalone, unit-tested Python modules under `engine/` with CLI entrypoints in `scripts/` and formal JSON Schemas in `schemas/`.

**CRITICAL RULE**: Never write ad-hoc destructive `set_par_text`, `coalesce_fragmented_runs` (that deletes `<w:proofErr>`), float-based math solvers, or global `taskkill /F /IM` commands. Always import from `engine` or invoke `scripts/*.py`.

---

## 1. Environment Check & Unit Test Verification

```powershell
python -c "import docx, openpyxl; from PIL import Image; print('OK')" 2>$null
if ($LASTEXITCODE -ne 0) {
    pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
}

# Run the full suite (473 tests: v3.5.9 engine baseline, W0 contracts, W1-W3 regressions, E2E)
python -m unittest discover -s tests -p "test_*.py" -v
```

---

## 2. Public API Overview (`engine/__init__.py`)

Add the skill root directory to `sys.path` and import directly from `engine`:

```python
import sys
sys.path.insert(0, r"<skill_root>")  # directory containing engine/ and scripts/

from engine import (
    # P0-1: Non-Destructive Cross-Run Mapping & Full-Story Traversal
    LogicalParagraphView,
    iter_all_document_paragraphs_with_Wait_context,
    sanitize_ooxml_whitespace_and_pagination,
    regenerate_unique_ooxml_ids,
    # P0-2: Exact Decimal SSOT Mathematical Solver
    build_ssot_master_data,
    to_decimal,
    quantize_decimal,
    convert_unit,
    compute_exact_percentages,
    parse_ratio_bound,
    # P0-3: MIME-Aware & Reference-Counted Image Replacement
    count_image_part_references,
    replace_inline_image_in_paragraph,
    verify_docx_images_integrity,
    # P0-4: PID-Scoped Process & Handle Ownership + Automatic SDK Cleanup
    TaskResourceGuard,
    release_office_file_locks,
    EditorSdkSession,
    list_process_pids,
    process_image_name,
    process_start_ticks,
    install_auto_cleanup,
    read_auto_cleanup_log,
    # P1-5: Complex Cell Structure Guard & Donor-Aware Table Engine
    classify_cell_structure,
    fill_cell_strict_style,
    clone_row_preserving_format,
    table_style_signature,
    compare_table_style,
    restore_table_style_from_reference,
    # P1-6: Structural Excel Row Cloning & Formula Evaluation
    copy_excel_cell_style,
    shift_excel_formula_row_refs,
    clone_excel_template_row,
    recalculate_and_verify_excel_formulas,
    audit_excel_formula_and_style_qa,
    # Style & Paragraph Engine
    resolve_style_sz_and_font,
    fill_paragraph_strict_style,
    # v3.0 Task Router, Compatibility Matrix & Document Understanding
    route_document_task,
    assess_template_compatibility_level,
    extract_document_spec,
    # v3.0 Dual-Document Repair Planner & Executor
    build_repair_plan,
    execute_repair_plan,
    # v3.1 REVIEW Mode: Tracked Changes, Comments & Review Integrity
    build_review_plan,
    execute_review_plan,
    audit_review_integrity,
    apply_tracked_replacement,
    add_paragraph_comment,
    enable_track_changes,
    # P1-7 & v3.0 Full Package QA & Visual Layout QA
    audit_docx_package_integrity,
    audit_format_and_text_qa,
    run_visual_layout_qa,
)
```

---

## 3. Module-by-Module Usage Guide

### 3.1 Non-Destructive Cross-Run Mapping (`engine/ooxml_utils.py` — Fixes P0-1)

Word and WPS split tokens like `{{project_name}}` across multiple `<w:r>` nodes and interleave `<w:proofErr>` grammar/spellcheck markers. `LogicalParagraphView` maps every character offset in the concatenated paragraph string to `(r_el, t_el, t_char_idx)` and replaces spans surgically without deleting `<w:proofErr>` or merging unrelated runs:

```python
import docx
from engine import LogicalParagraphView, iter_all_document_paragraphs_with_Wait_context

doc = docx.Document("template.docx")

# Traverse ALL stories: body, nested tables, headers, footers, textboxes (w:txbxContent), footnotes, endnotes, comments
for ctx in iter_all_document_paragraphs_with_Wait_context(doc):
    view = LogicalParagraphView(ctx["p_el"])
    if "{{" in view.logical_text:
        view.replace_all_tokens({
            "{{project_name}}": "新一代智能制造实训基地建设项目",
            "{{header_code}}": "GC-2026-01",
            "{{textbox_tag}}": "重点扶持专项",
        })
```

### 3.2 Exact `decimal.Decimal` SSOT Solver (`engine/ssot_engine.py` — Fixes P0-2)

Never use `float` for financial, credit, or hour calculations. `build_ssot_master_data()` takes a flat
`records` list plus the numeric field names and per-field unit specs:

```python
from engine import build_ssot_master_data

ssot = build_ssot_master_data(
    records=[
        {"name": "思想政治理论", "module": "公共基础课", "total": "144", "theory": "108", "practice": "36"},
        {"name": "大学英语", "module": "公共基础课", "total": "128", "theory": "96", "practice": "32"},
        {"name": "工业机器人编程与调试", "module": "专业核心课", "total": "925", "theory": "300", "practice": "625"},
    ],
    numeric_fields=["total", "theory", "practice"],
    part_sum_rules=[("total", ["theory", "practice"])],
    group_by_keys=["module"],
    field_specs={
        "total": {"unit": "hours", "decimals": 1},
        "theory": {"unit": "hours", "decimals": 1},
        "practice": {"unit": "hours", "decimals": 1},
    },
    # Explicit unit metadata — never rely on `if min_r > 1.0` heuristics!
    ratio_rules=[
        {
            "name": "practice_share",
            "numerator_group": ("__grand__", None, "practice"),
            "denominator_field": "total",
            "min_ratio": {"value": "0.50", "unit": "fraction"},
            "max_ratio": {"value": "85", "unit": "percent"},
        }
    ],
    char_Length_caps={"name": 20},
)

print(ssot["grand"]["total"], ssot["ratios_meta"]["practice_share"]["percent"])
```

### 3.3 MIME-Consistent & Reference-Counted Image Replacement (`engine/image_engine.py` — Fixes P0-3)

Safely replaces `<a:blip>` images while checking reference counts across the entire DOCX package. If an image `rId` is shared by multiple paragraphs/headers, `replace_inline_image_in_paragraph()` automatically allocates a new image part and `rId` so other occurrences are not overwritten:

```python
from engine import replace_inline_image_in_paragraph, verify_docx_images_integrity

res = replace_inline_image_in_paragraph(
    doc,                    # the Document being edited
    doc.paragraphs[4],      # the paragraph owning the <a:blip>
    "new_chart_300dpi.png",
    blip_index=0,
)
# res -> {"mode": "isolated_new_part", "effective": True, "old_rId": "rId7", "new_rId": "rId12",
#         "allocated_new_part": True, "content_type": "image/png", "shared_ref_count": 2}
# `effective=False` means the replacement bytes were identical to the original part (mode="noop_identical_bytes").

doc.save("output.docx")
img_qa = verify_docx_images_integrity("output.docx")
if not img_qa["passed"]:
    raise RuntimeError(img_qa["issues"])
```

### 3.4 PID-Scoped Process Guard (`engine/process_guard.py` — Fixes P0-4)

Replaces dangerous global `taskkill` commands with task-scoped PID and handle tracking:

```python
from engine import TaskResourceGuard

with TaskResourceGuard(task_id="doc-gen-001") as guard:
    res = guard.run_owned_command(["officecli", "validate", "output.docx"], timeout=30)
# Only processes spawned inside this `guard` context are cleaned up on exit.
```

`editor_sdk.exe` is started by WorkBuddy's sandbox, not by this engine, so cleanup is automatic
instead of PID ownership. Every `scripts/*.py` entrypoint calls this on startup and the exit hook
reports its result to `AUTO_CLEANUP_LOG`:

```python
from engine import install_auto_cleanup, read_auto_cleanup_log

install_auto_cleanup()          # snapshot (pid, start_ticks) now, terminate task-spawned SDKs on exit
# ... run the document task ...
print(read_auto_cleanup_log())  # {"verified": true, "spawned_during_task": [], ...}
```

Identity is `(pid, kernel start time)` and every candidate is re-checked by exact image name
(`process_image_name`) before termination, so a recycled PID is never touched. On Linux the image
name comes from `/proc/<pid>/comm`, not from `pgrep -f` command-line matching.

Set `OFFICECLI_DISABLE_AUTO_CLEANUP=1` when the engine is hosted in a long-lived process, and set
`OFFICECLI_TASK_ID` to isolate the manual `cleanup_editor_sdk.py` baseline file between concurrent tasks.

### 3.5 Complex Cell Protection & Table Rendering (`engine/table_engine.py` — Fixes P1-5)

`classify_cell_structure(cell)` inspects each cell (`plain_text`, `mixed_format`, `image_cell`, `hyperlink_cell`, `nested_table`, `sdt_control`, `field_code`, `unknown_complex`) before `fill_cell_strict_style()` modifies it:

```python
from engine import classify_cell_structure, fill_cell_strict_style

cell_type = classify_cell_structure(table.cell(1, 2))
# Safe style-cloned fill (automatically protects nested_table / image_cell / field_code / unknown_complex
# and uses non-destructive token mapping for mixed_format / hyperlink_cell / sdt_control)
res = fill_cell_strict_style(table, row_idx=1, col_idx=2, text="人工智能技术应用")
```

### 3.6 Structural Excel Row Cloning & Formula Verification (`engine/excel_engine.py` — Fixes P1-6)

Clones styles, row dimensions (`hidden`/`outlineLevel`), horizontal merged cell ranges, `DataValidation` rules, `ConditionalFormatting` rules, hyperlinks, shifted formulas (`=C2*D2` → `=C3*D3`), and table ranges:

```python
import openpyxl
from engine import clone_excel_template_row, audit_excel_formula_and_style_qa

wb = openpyxl.load_workbook("budget_template.xlsx", data_only=False)
ws = wb["经费预算表"]

# Clone template row 5 into row 6 with automatic relative formula row shifting
clone_excel_template_row(ws, source_row_idx=5, target_row_idx=6, shift_formulas=True)
ws["A6"] = "高性能实训服务器集群"
ws["C6"] = 4
ws["D6"] = 45000.00
wb.save("budget_output.xlsx")
wb.close()

qa = audit_excel_formula_and_style_qa(
    "budget_template.xlsx",
    "budget_output.xlsx",
    expected_formula_cells={"经费预算表": ["E5", "E6", "E10"]},
)
if not qa["passed"]:
    raise RuntimeError(qa["issues"])
```

### 3.7 Dual-Document `REPAIR` Mode (`engine/repair_engine.py` — v3.0 New Module)

Repairs a formatting-damaged `.docx` against a reference `.docx` template while preserving 100% of the target document's business content:

```python
from engine import build_repair_plan, execute_repair_plan

plan = build_repair_plan("reference_template.docx", "broken_document.docx")
exec_result = execute_repair_plan(plan, "repaired_output.docx")
```

### 3.8 Template-Driven `REVIEW` Mode (`engine/review_engine.py` — v3.1 New Module)

Produces a document a human can accept or reject in WPS/Word revision mode:

```python
from engine import build_review_plan, execute_review_plan, audit_review_integrity

plan = build_review_plan(
    "template.docx",
    "draft.docx",
    author="OfficeCLI Reviewer",
    text_revisions=[
        {"old_text": "待修正表述", "new_text": "标准表述", "reason": "按模板术语规范"},
    ],
)
result = execute_review_plan(plan, "reviewed.docx")
qa = audit_review_integrity("reviewed.docx")
if not qa["passed"]:
    raise RuntimeError(qa["issues"])
```

Review channel rules:

- Format drift (`sz`, fonts, spacing, indents, residual red) is restored; REPAIR applies it directly, while REVIEW pairs every restore with a native `w:*PrChange` formatting revision so the human can accept or reject it.
- Table structure drift (grid widths, `tblLayout`, `jc`, cell margins, borders) becomes a `RESTORE_TABLE_STYLE` action handled by `restore_table_style_from_reference()`, which never touches cell text or merges.
- Each `text_revisions` entry becomes `<w:del>` (`w:delText`) plus `<w:ins>` (`w:t`) with the configured author and a UTC timestamp.
- Residual `{{...}}` / `【...】` placeholders become native Word comments anchored by `commentRangeStart`/`commentRangeEnd`/`commentReference`.
- `enable_track_changes(doc)` writes `<w:trackChanges/>` into `settings.xml` at a schema-valid position.

### 3.9 Full Package QA & Visual Layout QA (`engine/qa_engine.py` — Fixes P1-7)

```python
import docx
from engine import audit_docx_package_integrity, audit_format_and_text_qa, run_visual_layout_qa

pkg_qa = audit_docx_package_integrity("output.docx")
if not pkg_qa["passed"]:
    raise RuntimeError(pkg_qa["issues"])

out_doc = docx.Document("output.docx")
fmt_qa = audit_format_and_text_qa(
    out_doc,
    forbidden_substrings=["请在此填写", "示例数据"],
    docx_path="output.docx",
    reference_docx_path="template.docx",  # required to prove the output matches the template's sizes, fonts and tables
    comparison_profile="STYLE_GUIDE",     # GENERATE: align by text/heading/caption anchors
)
if not fmt_qa["passed"]:
    raise RuntimeError((fmt_qa["size_anomalies"], fmt_qa["font_anomalies"], fmt_qa["table_style_anomalies"]))
print(fmt_qa["comparison_profile"], fmt_qa["size_baseline_source"], fmt_qa["template_sizes"], fmt_qa["template_fonts"])

vis_qa = run_visual_layout_qa(
    "output.docx",
    reference_docx_path="template.docx",
    comparison_profile="STYLE_GUIDE",
)
if not vis_qa["passed"]:
    raise RuntimeError(vis_qa["layout_warnings"])
```

`STYLE_GUIDE` is for GENERATE: added/removed paragraphs and new tables are reported as
`NEW_CONTENT` / `NEW_TABLE` in `alignment`, not compared to an unrelated neighbour.
`REPLICA` is for REPAIR/REVIEW, where preserving the template's paragraph/table order is the contract.
Only `high` severity issues make `passed` false; `medium` / `low` findings are returned in
`warnings` and remain visible without blocking delivery.

`font_anomalies` reports runs whose resolved Chinese font differs from the matched template
paragraph, and `table_style_anomalies` reports per-table grid/layout/border drift. When a table was
regenerated at a uniformly larger size, that drift appears as `table_dominant_size` and the old
document-wide size allowlist could never catch it. A new table with no template counterpart is
reported as `NEW_TABLE`, not as style drift.

Every QA function returns machine-readable issues so callers never parse prose:

```python
{
  "passed": False,
  "issues": [{"code": "FONT_SIZE_ANOMALY", "location": "table_dominant_size[0]",
              "detail": "...", "severity": "high"}],
  "warnings": [{"code": "LAYOUT_POSITION_DRIFT", "location": "body.p[3]", "detail": "...", "severity": "medium"}],
  "warning_count": 1,
  "comparison_profile": "STYLE_GUIDE",
  "alignment": {"matched_paragraphs": 194, "new_paragraphs": [35], "new_tables": [10]},
  "coverage_gaps": [],
  "unverified_count": 0,
}
```

`scripts/run_qa.py` flattens all sections into a top-level `status`
(`PASSED` / `FAILED` / `PENDING_HUMAN_REVIEW` / `UNVERIFIED`), `issues`, `warnings`,
`warning_count`, `comparison_profile`, `alignment`, `coverage_gaps`,
`unverified_count`, `hard_failure_count` and `pending_human_review_count`.
Use `--profile style-guide --task-mode GENERATE` for generated documents and
`--profile replica --task-mode REPAIR/REVIEW` when template order must be preserved.
`PENDING_HUMAN_REVIEW` means only intentional placeholder residue remains under `--review`.

## Pictures by role, OCR and figures

```python
from engine import find_images, replace_image_by_role, render_chart_image, audit_image_text

find_images(doc)                      # [{role, evidence, owner_part, paragraph_index, blip_index, ...}]
find_images(doc, role="logo")         # logo / stamp / qr / illustration / photo

# Raises ValueError when the role matches zero or several pictures.
replace_image_by_role(doc, "illustration", "new.png", fit_mode="fit_image")

# Optional OCR: returns coverage_gaps=["OCR_UNAVAILABLE"] when no backend is installed.
report = audit_image_text("output.docx")

result = render_chart_image({"kind": "bar", "categories": ["2024"], "series": {"招生": [120]}}, "chart.png")
if result["status"] != "RENDERED":
    # RENDER_BACKEND_UNAVAILABLE / CJK_FONT_UNAVAILABLE / INVALID_SPEC
    print(result["status"], result.get("detail"))
```

Role detection is structural (header/footer, size, aspect, dominant hue, caption keywords), so
each result states its `evidence`. Figure rendering needs matplotlib, and Chinese labels need an
installed CJK font; both conditions return an explicit status rather than a broken image.

## REFORMAT: semantic diff plan and tracked apply

```python
from engine import build_reformat_plan, execute_reformat_plan

plan = build_reformat_plan("template.docx", "draft.docx", strip_red=False)
print(plan["summary"])   # total_diffs / auto_fix / review_required / keep / unsupported

# Every entry is readable: where, what changed, what the template says, why the action.
for diff in plan["diffs"][:5]:
    print(diff["target"], diff["property"], diff["current"], "->", diff["reference_value"], diff["action"])

# Apply only AUTO_FIX entries; every change becomes a native w:*PrChange revision.
result = execute_reformat_plan(plan, "formatted.docx", author="OfficeCLI REFORMAT")
print(result["applied_actions"], result["format_revision_count"], result["unresolved_actions"])
```

Actions: `AUTO_FIX` (matched paragraph/table, safe), `REVIEW` (mixed runs / bold /
row-count drift), `KEEP` (new content with no template counterpart), `UNSUPPORTED`
(column-count mismatch). The output opens in Word/WPS revision mode; run
`audit_review_integrity()` and `run_qa.py --profile replica` on it before delivery.

## PDF conversion and page counts

```python
from engine import find_pdf_backend, convert_docx_to_pdf, pdf_page_count

backend = find_pdf_backend()   # {"name": "wps"|"libreoffice"|"none", "executable": ...}
pdf, error, used = convert_docx_to_pdf("output.docx", out_dir, backend)
count, source, error = pdf_page_count(pdf, backend)   # pymupdf -> wps_pdfinfo -> pdfinfo
```

WPS (`kwpsconvert.exe word2pdf` / `pdfinfo`) is preferred on Windows; LibreOffice is the
fallback. `OFFICECLI_PDF_BACKEND=wps|libreoffice|none` overrides detection. A WPS
account without VIP fails with `WPS_VIP_REQUIRED` in `pdf_conversion_errors` — never
silently fall back to the OfficeCLI HTML preview for pagination, because it does not
honor section breaks and its page count is not a pagination measurement.
