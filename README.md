# Office Template Filler

Template-driven Word and Excel document engine for AI agents: route a request, confirm the template,
plan the content, execute the fill as a transaction, and report QA in four states.

> **Current status: no automated tests and no CI.**
> This repository ships only the files that implement the workflows. There is no `tests/`, no `.github/`
> and no regression gate, so any change to the engine can only be validated by running the full chain
> manually on a real template. Treat every release as unverified beyond the packaging checks recorded in
> its manifest.

## What this is

The repository is the runtime behind the `officecli-template-filler` skill. Everything is Python and runs
directly from `scripts/`; nothing is installed as a package or compiled.

It edits documents in two ways:

- **Generated content** is decided before any OOXML is touched. A `DocumentSpec` describes the template,
  a `ContentPlan` states what to write, and a `FillPlan` states where and how. Only the executor writes.
- **Review content** is written as native Word revisions (`w:ins`, `w:del`) or native format revisions
  (`w:rPrChange`, `w:pPrChange`), never as plain overwrites.

### Relationship to OfficeCLI

[OfficeCLI](https://github.com/iOfficeAI/OfficeCLI) is an **optional write backend**, not a dependency.
The default is `python-docx`; pass `--writer officecli` to fill through the OfficeCLI CLI instead.

- If OfficeCLI cannot express a location (headers, footers, content controls, text boxes), the engine
  abandons the OfficeCLI path for the whole document and falls back to `python-docx`, recording the reason
  in `writer_fallback`.
- The default is never flipped automatically. There is no shared code, no vendored binary and no version
  handshake; OfficeCLI is discovered via `OFFICECLI_BINARY`, then `PATH`, then its default install path.

## Requirements

**Python 3.10 or newer.** This is a hard requirement and it is stated nowhere else in the repository: the
code compares iterables with `zip(..., strict=True)` in six places, which raises `TypeError` on 3.9.

| Component | Requirement |
|---|---|
| Python | >= 3.10 (uses `zip(strict=)`; see `engine/table_engine.py`, `engine/review_engine.py`, `engine/ssot_engine.py`, `engine/consistency_qa.py`, `template_intelligence/spec_builder.py`) |
| `python-docx` | >= 1.1.0 — DOCX read/write, tracked revisions |
| `openpyxl` | >= 3.1.2 — XLSX read/write, formula preservation |
| `lxml` | >= 5.0.0 — OOXML namespace handling |
| `Pillow` | >= 10.0.0 — image inspection |
| `jsonschema` | >= 4.20 — validation of the versioned JSON artifacts |
| `PyMuPDF` | optional (`>= 1.24`) — page rendering and page-level visual comparison; page counts fall back to WPS `pdfinfo` or poppler |
| WPS Office or LibreOffice | optional — PDF conversion for visual QA; without it `RENDER_PDF_NOT_PRODUCED` |
| OfficeCLI | optional — only for `--writer officecli` |

```powershell
python -m pip install -r requirements.txt
```

## Workflows and entrypoints

| Mode | Entrypoint | Purpose | Template gate |
|---|---|---|---|
| `GENERATE` | `scripts/generate_document.py` | Fill a `.docx` template from a ContentPlan/FillPlan, or from a legacy token map via `--data` | **CONFIRMED required** |
| `REPAIR` | `scripts/repair_document.py` | Rebuild a broken `.docx` against a reference template, preserving its content | **CONFIRMED required** |
| `REFORMAT` | `scripts/reformat_document.py` | Align typography to a reference template, written as `w:*PrChange` | **CONFIRMED required** |
| `REVIEW` | `scripts/review_document.py` | Review one document against a reference, or attach external `--findings` as comments | **CONFIRMED required** |
| `PROOFREAD` | `scripts/proofread_document.py` | Apply tracked text corrections to a single document | not required |

Excel templates are a separate routed path: `EXCEL_GENERATE` → `scripts/generate_excel.py`
(`--template`, `--data`, `--out`), which fills cells and keeps existing formulas.

`POLISH` and `MERGE` are **not implemented**. The router returns `CAPABILITY_NOT_AVAILABLE` for both;
they must not be simulated with another mode.

## Shortest usable path

Routing and the template gate come first. The gate writes a signed record; every mutation entrypoint
refuses to run without a `CONFIRMED` one.

```powershell
# 1. Route the request
python scripts/inspect_document.py --inputs template.docx --intent "generate a project proposal" --out routing.json

# 2. Analyze the template and review the evidence
python scripts/template_gate.py analyze --template template.docx --task-type GENERATE --out gate-analysis.json
python scripts/template_gate.py report --analysis gate-analysis.json

# 3. Confirm with the token printed by `report`, which persists the Gate Record
python scripts/template_gate.py confirm --analysis gate-analysis.json --review-token <token> --user-statement "confirmed" --out-record gate.json
```

With a confirmed gate, the shortest end-to-end fill uses the legacy token map:

```powershell
python scripts/generate_document.py --template template.docx --data values.json --out out.docx
python scripts/run_qa.py out.docx --reference template.docx --task-mode GENERATE --out qa.json
```

The versioned plan chain is the same entrypoint with explicit artifacts:

```powershell
python scripts/analyze_template.py template.docx --spec-version 4 --out spec.json
python scripts/generate_document.py --template template.docx --spec spec.json `
    --content-plan content.json --plan fill.json --out out.docx --mode STANDARD
```

There is no CLI that produces `content.json` / `fill.json`: build them with the `content_intelligence`
API (`build_content_plan`, `build_fill_plan`) and validate them before execution.

One document, three review-shaped runs:

```powershell
python scripts/review_document.py    --reference template.docx --target draft.docx --revisions revisions.json --out reviewed.docx
python scripts/proofread_document.py --target draft.docx --revisions revisions.json --out proofread.docx
python scripts/reformat_document.py  --reference template.docx --target draft.docx --out reformatted.docx
python scripts/repair_document.py    --reference template.docx --broken broken.docx --out repaired.docx
python scripts/generate_excel.py     --template budget.xlsx --data values.json --out budget-filled.xlsx
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
├── SKILL.md                  # Agent-facing workflow contract (authoritative)
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

Current version: **4.2.2** (`engine/__init__.py`, `SKILL.md`).

- `dist/` is ignored by git. It is build output produced by the release flow, never committed.
- A release consists of `officecli-template-filler-<version>.zip` plus a matching
  `officecli-template-filler-<version>.manifest.json`.
- The manifest records the source commit, build time, archive SHA-256, entry counts, and the path,
  byte size and SHA-256 of every file in the archive. Verify the zip against the manifest before use.

## Known limitations

- **No automated tests, no CI.** This is the single largest risk in the repository; see the notice at the
  top. Engine changes require a manual run of the full chain on a representative template.
- `POLISH` and `MERGE` have no handler.
- The OfficeCLI writer covers body paragraphs and tables only and falls back for the whole document when a
  target lives elsewhere; its behavior is not re-verified for every OfficeCLI release.
- Visual QA needs WPS/LibreOffice for PDF conversion and PyMuPDF for page rendering; when either is
  missing the corresponding checks stay `UNVERIFIED` instead of passing.
- XLSX handling cannot guarantee preservation of shapes, charts or other objects that `openpyxl` does not
  round-trip; such objects are reported instead of silently dropped.
