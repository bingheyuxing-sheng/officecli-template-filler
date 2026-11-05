# v3.5.9 Compatibility Analysis (W0)

- Scope: files added in W0 vs the released v3.5.9 tree
- Baseline: commit `c5fe9a8`, tag `v3.5.9`, 186 tests
- Verdict: **additive only, no public interface changed**

## 1. Change inventory

| Path | Type | Effect on v3.5.9 |
|---|---|---|
| `contracts/**` | new | None (documentation only) |
| `schemas/document_spec-4.0.schema.json` | new | None |
| `schemas/document_spec-legacy-3.0.schema.json` | new | None (mirrors the existing 3.0 schema) |
| `schemas/document_spec-legacy-cli.schema.json` | new | None |
| `schemas/content_plan-4.0.schema.json` | new | None |
| `schemas/fill_plan-4.0.schema.json` | new | None |
| `schemas/qa_report-4.0.schema.json` | new | None |
| `schemas/tool_envelope-4.0.schema.json` | new | None |
| `schemas/error_code_registry-4.0.schema.json` | new | None |
| `config/qa-policy.json`, `config/error-codes.json` | new | None |
| `examples/**` | new | None |
| `tests/contracts/**` | new | None (separate test package) |
| `reports/w0/**` | new | None |
| `requirements-dev.txt` | new | None (test-only dependency) |

No existing file is modified. `schemas/document_spec.schema.json`, `schemas/qa_report.schema.json`, every `engine/*.py`, every `scripts/*.py`, and every original test file remain byte-identical.

## 2. Public API surface check

The v3.5.9 public surface is the `engine` package exports (`engine/__init__.py:189-309`) plus the CLI arguments of `scripts/*.py`.

| Area | Compatibility rule | W0 evidence |
|---|---|---|
| Python imports | Every symbol exported by `engine.__all__` must still import | `tests/contracts/test_legacy_compat.py` imports the full `__all__` list |
| `extract_document_spec()` | Output shape unchanged (3.0) | validated against `document_spec-legacy-3.0.schema.json` |
| `analyze_template.py` CLI | Output shape unchanged | validated against `document_spec-legacy-cli.schema.json` |
| `generate_document.py` CLI | `--data` path unchanged | not executed in W0; no code change |
| Existing QA/REPAIR/REVIEW CLIs | Output shapes unchanged | no code change |
| Test baseline | 186 tests still pass | re-run recorded in acceptance report |

## 3. Known compatibility gaps

| ID | Gap | Impact | Target |
|---|---|---|---|
| `OI-01` | `analyze_template.py` emits a 7-key summary; it cannot emit DocumentSpec 4.0 | Alpha entry condition; 4.0 schema is not relaxed | W1 / Agent 01 |
| `OI-02` | Pixel-level visual QA unavailable (no PyMuPDF); OCR and chart rendering unavailable on this machine | `VISUAL_PIXEL` / `OCR` must be `UNVERIFIED`, never `PASSED` | W2 / Agent 04 |
| `OI-03` | W0 ships no runtime FillPlan/DocumentSpec validator implementation | Contract tests use a reference checker only | W1 / Agents 01–03 |
| `OI-04` | Existing CLIs do not use ToolEnvelope 4.0 | Orchestrator must keep legacy adapters until beta | Beta / Agent 05 |
| `OI-05` | `logic_qa → workflow → qa_engine` dependency inversion | Cross-agent edits can cascade | W1 / Agents 04–05 |

None of these is a W0 contract defect. `OI-01` is a blocker for alpha, not for contract freeze, because the frozen contract explicitly separates the v4 producer requirement from the current v3.5.9 producer.

## 4. Compatibility review result

- Breaking changes: **0**
- Modified existing files: **0**
- Removed public symbols: **0**
- Renamed error codes: **0** (existing codes are registered under their current names)
- Schema files replaced: **0**

Agent 07 compatibility verdict: see `reports/w0/07-gate-review.md`.
