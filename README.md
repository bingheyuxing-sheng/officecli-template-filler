# Office Template Filler

English | [简体中文](README.zh-CN.md)

Template-driven Word and Excel document engine for AI agents: route a request, confirm the template,
plan the content, execute the fill as a transaction, and report QA in four states.

> **Current status: core regression tests and Windows CI.**
> `tests/` covers transaction, QA-state, template-gate and cache invariants. GitHub Actions runs `pytest`
> and Ruff on Windows for Python 3.10 and 3.13. This suite does not replace end-to-end validation on
> representative templates before a release.

## What this is

The repository is the runtime behind the `officecli-template-filler` skill. Everything is Python and runs
directly from `scripts/`; nothing is installed as a package or compiled.

It edits documents in two ways:

- **Generated content** is decided before any OOXML is touched. A `DocumentSpec` describes the template,
  a `ContentPlan` states what to write, and a `FillPlan` states where and how. Only the executor writes.
- **Review content** is written as native Word revisions (`w:ins`, `w:del`) or native format revisions
  (`w:rPrChange`, `w:pPrChange`), never as plain overwrites.

### Relationship to OfficeCLI

[OfficeCLI](https://github.com/iOfficeAI/OfficeCLI) is the **execution substrate** for mutation, not an
optional add-on. The FillPlan path applies every operation as one atomic `officecli batch` on the staging
copy; headers, footers, tables and body paragraphs are addressed through OfficeCLI's own DOM paths.

- OfficeCLI is discovered via `OFFICECLI_BINARY`, then `PATH`, then its default install path, and must
  meet the capability floor checked by `engine/officecli_runtime.py`.
- A plan OfficeCLI cannot express faithfully **blocks** with `WRITER_UNSUPPORTED` instead of silently
  switching backends. `--allow-writer-fallback` is the explicit opt-in, and the reason is recorded in
  `writer_fallback`.
- Every default document mutation path (GENERATE FillPlan / GENERATE legacy `--data` /
  REPAIR / REFORMAT / REVIEW / PROOFREAD / POLISH / MERGE / EXCEL_GENERATE) executes through
  OfficeCLI; Python OOXML is read-only for analysis, fingerprints and QA. The legacy
  `--writer python-docx` switch is an explicit compatibility backend, never an automatic
  fallback.

## Requirements

**Python 3.10 or newer.** This is a hard requirement and it is stated nowhere else in the repository: the
code compares iterables with `zip(..., strict=True)` in six places, which raises `TypeError` on 3.9.

| Component | Requirement |
|---|---|
| Python | >= 3.10 (uses `zip(strict=)`; see `engine/table_engine.py`, `engine/review_engine.py`, `engine/ssot_engine.py`, `engine/consistency_qa.py`, `template_intelligence/spec_builder.py`) |
| `python-docx` | >= 1.1.0 — DOCX analysis/fingerprints and the explicit legacy writer fallback |
| `openpyxl` | >= 3.1.2 — XLSX template analysis and the explicit `.xlsm` fallback |
| `lxml` | >= 5.0.0 — OOXML namespace handling |
| `Pillow` | >= 10.0.0 — image inspection |
| `jsonschema` | >= 4.20 — validation of the versioned JSON artifacts |
| `PyMuPDF` | optional (`>= 1.24`) — page rendering and page-level visual comparison; page counts fall back to WPS `pdfinfo` or poppler |
| WPS Office or LibreOffice | optional — PDF conversion for visual QA; without it `RENDER_PDF_NOT_PRODUCED` |
| OfficeCLI | >= 1.0.130 (verified on 1.0.160) — required for every mutation workflow and the package QA check |

```powershell
python -m pip install -r requirements.txt
```

## Workflows and entrypoints

| Mode | Entrypoint | Purpose | Template gate |
|---|---|---|---|
| `GENERATE` | `scripts/generate_document.py` | Fill a `.docx` template from a ContentPlan/FillPlan, or from a legacy token map via `--data` (both OfficeCLI by default) | **CONFIRMED required** |
| `REPAIR` | `scripts/repair_document.py` | Rebuild a broken `.docx` against a reference template through OfficeCLI, preserving its content | **CONFIRMED required** |
| `REFORMAT` | `scripts/reformat_document.py` | Align typography to a reference template through OfficeCLI, written as `w:*PrChange` | **CONFIRMED required** |
| `REVIEW` | `scripts/review_document.py` | Review one document against a reference through OfficeCLI, or attach external `--findings` as comments | **CONFIRMED required** |
| `PROOFREAD` | `scripts/proofread_document.py` | Apply tracked text corrections to a single document through OfficeCLI | not required |
| `POLISH` | `scripts/polish_document.py` | Refine wording/terminology in place with OfficeCLI run/paragraph edits | not required |
| `MERGE` | `scripts/merge_documents.py` | Consolidate 2+ DOCX or XLSX files with OfficeCLI dump/replay | not required |

Excel templates are a separate routed path: `EXCEL_GENERATE` → `scripts/generate_excel.py`
(`--template`, `--data`, `--out`), which fills cells through OfficeCLI and keeps existing
formulas; macro-enabled `.xlsm` files require an explicit `--allow-writer-fallback`. When the
template has no `{{...}}` / `【...】` tokens, pass a `cells` plan in the payload (a list of
`{sheet, cell, value, type}` objects or a `"Sheet1!B2": value` map); formula cells and
non-top-left merged cells are refused with `INVALID_CELL_PLAN`. A payload with neither tokens
nor cells returns `NO_MATCHING_PLACEHOLDERS` and publishes nothing.

`POLISH` and `MERGE` run on the OfficeCLI backend. `POLISH` refuses a span that crosses
differently formatted runs instead of letting OfficeCLI rebuild the paragraph; `MERGE` uses the
first input as the base package and replays every later input as an OfficeCLI batch, reporting
story/object limitations instead of silently dropping them. When an appended document defines a
style id the base already has, the base definition wins; only missing styles are imported.

## Shortest usable path

Routing and the template gate come first. The gate writes a signed record; every mutation entrypoint
refuses to run without a `CONFIRMED` one.

```powershell
# 1. Route the request
python scripts/inspect_document.py --inputs template.docx --intent "generate a project proposal" --out routing.json

# 2. Analyze the template, emit the spec and render the report in one cached pass
python scripts/template_gate.py analyze --template template.docx --task-type GENERATE `
  --out gate-analysis.json --spec-out spec.json --report-out template-report.md

# 3. Confirm with the token printed by `analyze` / `report`, which persists the Gate Record
python scripts/template_gate.py confirm --analysis gate-analysis.json --review-token <token> --user-statement "confirmed" --out-record gate.json
```

With a confirmed gate, the shortest end-to-end fill uses the legacy token map:

```powershell
python scripts/generate_document.py --template template.docx --data values.json --out out.docx
python scripts/run_qa.py out.docx --reference template.docx --task-mode GENERATE --out qa.json
```

The versioned plan chain is the same entrypoint with explicit artifacts:

```powershell
# spec.json already exists when step 2 used --spec-out; otherwise run analyze_template.py.
python scripts/generate_document.py --template template.docx --spec spec.json `
    --content-plan content.json --plan fill.json --out out.docx --mode STANDARD `
    --qa-report qa.json

# Reuse the executor's full QAReport instead of running the same suite twice.
python scripts/run_qa.py out.docx --reuse-report qa.json
```

There is no CLI that produces `content.json` / `fill.json`: build them with the `content_intelligence`
API (`build_content_plan`, `build_fill_plan`) and validate them before execution.

## Performance and caching

- The v4 DocumentSpec and Gate Analysis are cached under `%USERPROFILE%\.officecli-template-filler\cache`,
  keyed by template SHA-256, engine version, schema version, policy digest and package limits.
- Gate validation skips evidence/fingerprint rebuilds when the template SHA and spec digest still match
  the confirmed record; any change falls back to the full validation path.
- The reference PDF used by visual QA is cached by template SHA and PDF-backend fingerprint; the output
  PDF is always regenerated.
- `generate_document.py --qa-report` writes the executor QAReport sidecar on the v4 `--plan` path only;
  `run_qa.py --reuse-report`
  returns it only when the output SHA-256 matches and the report validates. Otherwise it runs full QA.
- Override the cache location with `OFFICECLI_CACHE_HOME`; disable all caches with
  `OFFICECLI_DISABLE_CACHE=1`.

## Tests and CI

```powershell
python -m pip install -r requirements.txt -r requirements-dev.txt
python -m pytest -q
python -m ruff check .
```

GitHub Actions runs the same commands on `windows-latest` for Python 3.10 and 3.13.

One document, three review-shaped runs:

```powershell
python scripts/review_document.py    --reference template.docx --target draft.docx --revisions revisions.json --out reviewed.docx
python scripts/proofread_document.py --target draft.docx --revisions revisions.json --out proofread.docx
python scripts/reformat_document.py  --reference template.docx --target draft.docx --out reformatted.docx
python scripts/repair_document.py    --reference template.docx --broken broken.docx --out repaired.docx
python scripts/generate_excel.py     --template budget.xlsx --data values.json --out budget-filled.xlsx
python scripts/polish_document.py    --target draft.docx --edits edits.json --out polished.docx
python scripts/merge_documents.py    --inputs part1.docx part2.docx --out merged.docx
```

All of these accept `--output` as an alias of `--out`, and `generate_document.py` / `generate_excel.py`
accept `--payload` as an alias of `--data`. One asymmetry to remember: on `run_qa.py`, `--output` is an
alias for the **input document**, and the JSON report path is `--out` / `--report`.

## Gate and QA rules

These are invariants, not conventions.

- **No confirmed gate, no execution.** `GENERATE`, `REPAIR`, `REFORMAT` and `REVIEW` require a `CONFIRMED`
  Gate Record bound to the template's hash, spec and fingerprint. Editing the template invalidates it
  (`TEMPLATE_GATE_STALE`).
- **Four QA states.** `PASSED`, `FAILED`, `PENDING_HUMAN_REVIEW`, `UNVERIFIED`. A check that did not run
  becomes `UNVERIFIED` and is listed in `coverage_gaps`; it is never reported as passed.
- **`UNVERIFIED` is not a pass.** It can only be committed in `STANDARD` mode with `--allow-unverified`,
  and the deliverable must disclose it.
- **`committed: false` means no final file.** The transaction record (see `engine/transaction.py`) reports
  `committed`; when it is false the staged file was discarded and the output path was not written.
- **Exit codes.**

  | Code | `generate_document.py` | `run_qa.py` |
  |---|---|---|
  | `0` | Document committed | `PASSED`, `PENDING_HUMAN_REVIEW`, or `UNVERIFIED` with `--allow-unverified` |
  | `1` | Not committed (QA failed, or `UNVERIFIED` without the flag) | `FAILED`, or `UNVERIFIED` without the flag |
  | `2` | Rejected before writing (gate, package quota, missing spec, blocked plan) | Usage error or package quota rejection |

  `review_document.py` and `proofread_document.py` return `1` when the transaction did not commit,
  `2` for gate or preflight rejection. Do not treat a produced file as delivered until `committed` is true.

## Repository layout

```
officecli-template-filler/
├── .github/workflows/ci.yml  # Windows CI: pytest + Ruff
├── SKILL.md                  # Agent-facing workflow contract (authoritative)
├── tests/                    # Core invariant regression suite
├── pyproject.toml            # pytest and Ruff configuration
├── requirements-dev.txt      # Test and lint dependencies
├── config/                   # Package quotas, QA policy, error codes, gate policy, environment probes
├── schemas/                  # JSON Schemas for DocumentSpec, ContentPlan, FillPlan, QAReport (schema 4.0)
├── template_gate/            # Evidence analysis, state machine, Gate Record storage and validation
├── template_intelligence/    # DocumentSpec producer: slots, fingerprints, unsupported features
├── content_intelligence/     # ContentPlan and FillPlan builders and validators
├── document_engine/          # FillPlan executor, fill ledger, transactional pipeline
├── qa/                       # QAReport assembly, required-check matrix, commit eligibility
├── engine/                   # Shared engine: OOXML, styles, tables, images, Excel, PDF, transactions, review
└── scripts/                  # CLI entrypoints (the surface an agent calls)
```

| Module | Responsibility | Start here |
|---|---|---|
| `scripts/` | Argument parsing, file-level preconditions, exit codes | `scripts/generate_document.py` |
| `document_engine/` | Validate the plan, stage the file, execute fills, run QA, commit or abort | `document_engine/fill_executor.py` |
| `template_gate/` | Analyze evidence, require confirmation, persist an HMAC-signed record | `template_gate/validator.py` |
| `template_intelligence/` | Turn a template into a `DocumentSpec` with stable slot ids | `template_intelligence/spec_builder.py` |
| `content_intelligence/` | Turn content into `ContentPlan` / `FillPlan` and validate both | `content_intelligence/plan_builder.py` |
| `qa/` | Fold check results into one status and decide commit eligibility | `qa/pipeline.py` |
| `engine/` | All OOXML and file-format mechanics, plus transactions and revision writers | `engine/transaction.py`, `engine/review_engine.py` |
| `config/`, `schemas/` | Policy values and machine-readable contracts | `config/qa-policy.json` |

Writes are always transactional: `preflight` → stage a copy → execute → QA → atomic replace. `w:proofErr`
markers, unmapped styles, complex table cells, shared image relationships and Excel formulas are preserved
by design; a failed check aborts the transaction rather than degrading the output.

## Version and releases

Current version: **4.3.2** (`engine/__init__.py`, `SKILL.md`).

- `dist/` is ignored by git. It is build output produced by the release flow, never committed.
- `python scripts/package_skill.py` builds a working-tree skill zip and manifest under `dist/`; the
  manifest sets `source_dirty` when the checkout contains uncommitted files.
- A release consists of `officecli-template-filler-<version>.zip` plus a matching
  `officecli-template-filler-<version>.manifest.json`.
- The manifest records the source commit, build time, archive SHA-256, entry counts, and the path,
  byte size and SHA-256 of every file in the archive. Verify the zip against the manifest before use.

## Known limitations

- **Regression coverage is intentionally narrow.** Tests cover core invariants, not every document
  workflow; validate generated deliverables on representative templates before release.
- `GENERATE`, `POLISH` / `MERGE` require OfficeCLI; without the binary they exit 2 with
  `OFFICECLI_UNAVAILABLE`.
- `POLISH` cannot isolate one of several matches inside a single run, or a replacement that spans
  differently formatted runs; it returns a planning error instead of changing run formatting.
- `MERGE` consolidates document bodies into the first input's package. Appended headers/footers,
  footnotes, endnotes, comments and each source's final section page setup are not carried;
  XLSX named ranges, charts, pivots and macros are not merged. These are reported as
  `limitations` in the merge report.
- The GENERATE FillPlan writer covers body paragraphs, tables, headers and footers. Footnotes, endnotes,
  content controls and text boxes still block with `WRITER_LOCATION_UNSUPPORTED` unless the caller passes
  `--allow-writer-fallback`. `REPAIR`, `REFORMAT`, `REVIEW`, `PROOFREAD` and Excel fills now execute
  through OfficeCLI; `docs/officecli-first.md` is the migration ledger.
- The legacy `--data` token map executes through OfficeCLI by default. Text boxes, SDTs and
  individual footnote/endnote paragraphs are not addressable; they block with
  `WRITER_LOCATION_UNSUPPORTED` unless `--writer python-docx` or `--allow-writer-fallback` is
  explicit. The python-docx backend is never selected automatically.
- Visual QA needs WPS/LibreOffice for PDF conversion and PyMuPDF for page rendering; when either is
  missing the corresponding checks stay `UNVERIFIED` instead of passing.
- XLSX handling cannot guarantee preservation of shapes, charts or other objects that `openpyxl` does not
  round-trip; such objects are reported instead of silently dropped.
