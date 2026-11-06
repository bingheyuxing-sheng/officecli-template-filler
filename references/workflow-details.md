# Workflow Details — Transactions, Checkpoints, Rendering and QA

This file holds the detail behind `SKILL.md` Steps 4–5. Read it when you need to
change delivery behavior, staged checkpoints, rendering fallback, TOC handling or
QA report semantics. Do not duplicate these rules in ad-hoc scripts.

## 1. Transactional delivery

`generate_document.py`, `generate_excel.py`, `repair_document.py`,
`review_document.py` and `render_document.py --outdir` never write the final path
directly:

1. **Preflight** — source exists, extension is supported, output directory is
   writable, container family matches (Word → Word, Excel → Excel).
2. **Execute** — the document is saved to a sibling
   `.<name>.tmp-<transaction_id>.<ext>` staged file.
3. **QA** — each entrypoint runs the checks its deliverable contract requires
   against that staged file: `GENERATE` → package integrity + format;
   `REPAIR` → package integrity + format against the reference;
   `REVIEW` / `PROOFREAD` → package integrity + revision/comment integrity;
   `EXCEL_GENERATE` → formula + style; `RENDER` → visual. The full
   package/format/formula/visual suite still runs separately through
   `run_qa.py` (Step 5).
4. **Commit** — two atomic `os.replace` calls, but only when the deliverable's
   contract allows it. **v4 `GENERATE` plan path**: commit only on `PASSED`, or
   on `UNVERIFIED` when `--allow-unverified` was passed and `missing_checks` is
   disclosed; `PENDING_HUMAN_REVIEW` and `FAILED` never commit. Legacy
   entrypoints (`REPAIR`, `REVIEW`, `PROOFREAD`, `RENDER`, Excel) keep their
   existing commit rules (`PASSED` / `PENDING_HUMAN_REVIEW` / `UNVERIFIED`).

Every entrypoint ends with a `transaction` object:

```json
{"transaction_id": "...", "preflight": {"passed": true, "checks": []},
 "qa_status": "PASSED", "committed": true, "abort_reason": null,
 "input_sha256": "...", "output_sha256": "...", "qa_report_path": null}
```

- `committed: false` (exit code 1) means the final file was **not** created;
  exit code 2 means preflight rejected the task. Never tell the user a document
  was produced — report `abort_reason` and the QA `issues` instead.
- `qa_status: "UNVERIFIED"` still publishes the file, but it must be described
  as unverified, never as a pass.
- Do not hand-write the final path in ad-hoc scripts; use the entrypoints or
  `engine.DocumentTransaction` so a failed run leaves no `.tmp` / `.pending`
  artifact behind.

## 2. Staged checkpoints and minimal retry scope

For `STANDARD` and `FULL`, persist and validate four transaction-scoped
checkpoints in order:

1. `content` — body text, headings, placeholders, and semantic preflight repairs;
2. `tables` — all SSOT-derived native tables and cross-table totals;
3. `images` — replacements/redraws and image integrity (`FULL`; otherwise
   explicitly skipped with coverage);
4. `toc` — field state and page-number handling.

Each checkpoint records `input_sha256`, `output_sha256`, `qa_status`, `issues`,
and `coverage_gaps`. A failed stage restarts from the most recent valid
checkpoint, not from the original template, and never redoes a successful earlier
stage. Checkpoints are internal transaction artifacts; only the final committed
Office file is delivered.

## 3. Rendering and TOC degradation chain

Use one bounded rendering attempt per stage; do not manually retry the same file
in place.

1. Render an independent working copy under `TaskResourceGuard` with a single
   configured timeout.
2. On timeout or renderer failure, close only task-owned handles/processes,
   record the exact failure, and fall back to OOXML/package/layout-fingerprint QA.
3. If Word or LibreOffice field refresh is available, refresh TOC fields on the
   working copy, then verify heading entries and rendered page count before
   commit.
4. If no compatible field-refresh engine exists, never preserve known-stale
   template page numbers as if current. Keep/update the TOC field with
   `w:updateFields=true` and set `toc_status: PENDING_FIELD_UPDATE`; if an
   internal pagination estimate is supplied, label it `ESTIMATED` and state that
   Word/WPS pagination may differ.
5. Rendering or TOC checks that did not run must create `coverage_gaps` and
   produce `UNVERIFIED`; repeated ad-hoc retries are forbidden.

## 4. QA report semantics

Read `status` in `qa_report.json` — it is one of four values, never a bare
boolean:

| status | Meaning | Exit code |
|---|---|---|
| `PASSED` | No **high-severity** issues. Medium/low findings are listed in `warnings` and do not block delivery | 0 |
| `PENDING_HUMAN_REVIEW` | Only `TEMPLATE_TEXT_RESIDUAL` items remain and `--review` was passed; the file is structurally sound and waits for a human decision | 0 |
| `UNVERIFIED` | No high-severity issues, but at least one check could not run (`coverage_gaps` / `unverified_count` > 0); never report this as a pass | 0 |
| `FAILED` | At least one high-severity issue | 1 |

The report also carries `issues` (flattened objects with `code`, `location`,
`detail`, `severity`), `warnings`, `warning_count`, `comparison_profile`,
`alignment` (matched/new/removed paragraphs and tables), `coverage_gaps`,
`unverified_count`, `hard_failure_count` and `pending_human_review_count`.
Branch on `code`, never on prose. Never describe a `FAILED` report as delivered,
and never call `PENDING_HUMAN_REVIEW` broken. Medium findings are advisory:
report them to the user, but do not rewrite the document solely to silence them.

### Content truth (`content_qa`, on by default; disable with `--no-content-qa`)

| code | Severity | Meaning |
|---|---|---|
| `CONTENT_VALUE_CONFLICT` | high | an explicit total (总/合计/小计/共) carries different values in prose and a table |
| `CONTENT_SUBTOTAL_MISMATCH` | high | a trailing 合计 row does not equal the sum of the rows above it |
| `CONTENT_LABEL_VALUE_VARIANCE` | medium | the same non-total label appears with a few different values across prose and tables |
| `CONTENT_TERM_DRIFT` | medium | a name in a name column is spelled two ways (张伟 / 张玮) |
| `CONTENT_DATE_FORMAT_MIXED`, `CONTENT_UNIT_STYLE_MIXED` | low | `2026年11月4日` mixed with `2026-11-04`, or 万 mixed with 万元 |

The report returns `label_values` (extracted `label → value` pairs with
locations) so the user can audit what was compared. `audit_fact_sources()`
rejects SSOT `facts` entries without a `source` (`FACT_SOURCE_MISSING`, high) —
every fact must cite a URL, an internal reference name, or the explicit marker
`UNVERIFIED` / `MODEL_GENERATED`. For PROOFREAD, `find_numeric_occurrences()`
returns every occurrence of a suspect number with surrounding context instead of
a bare comment.

For REVIEW outputs, run
`python scripts/run_qa.py "$OUTPUT_FILE" --review --reference "$REF_DOCX" --profile replica --task-mode REVIEW`:

- `review_qa.passed` must be `true`: every revision and comment is structurally
  valid.
- Placeholder residue becomes `PENDING_HUMAN_REVIEW`, not a failure, because
  REVIEW intentionally leaves undecided items for the human.
- Without `--review`, placeholder residue counts as a failure, since nothing is
  expected to stay unresolved.
