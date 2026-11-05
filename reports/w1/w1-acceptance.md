# W1 Implementation & Acceptance Report

- Report ID: W1-ACCEPT-01
- Date: 2026-11-05
- Scope: W1-A…W1-E + end-to-end integration
- Contract baseline: **4.0.0 (frozen, unchanged)**
- Decision: **W1 COMPLETE — 4.0 data chain is executable**

## 1. What was built

| Work package | Deliverable | Owner agent |
|---|---|---|
| W1-A | `template_intelligence/` (slot_id, fingerprint, spec_builder); `analyze_template.py --spec-version 4` | Agent 01 |
| W1-B | `template_intelligence/spec_validator.py` | Agent 01 (validator track) |
| W1-C | `content_intelligence/` (ContentPlan/FillPlan builders + validators) | Agent 02/03 |
| W1-D | `document_engine/` (executor, ledger, pipeline); `generate_document.py --plan` | Agent 03 |
| W1-E | `qa/` (gate, report builder, full QA runner) | Agent 04 |
| Integration | CLI `--content-plan`, optional visual-gap handling, 8-scenario E2E | Orchestrator |

No frozen contract, schema, config, example or W0 test was modified (`git diff -- contracts schemas config examples tests/contracts` = 0 lines).

## 2. Executable chain

```
DOCX template
  -> build_document_spec()                 (DocumentSpec 4.0)
  -> validate_document_spec()              (schema + semantic)
  -> build_content_plan() / build_fill_plan()
  -> execute_fill_plan()                   (preconditions, primitives, staging)
  -> fill_ledger.json                      (one record per operation)
  -> qa.pipeline.run_full_qa()             (QAReport 4.0, staged file only)
  -> commit or abort                       (STRICT/STANDARD eligibility)
  -> final DOCX
```

CLI:

```powershell
python scripts/analyze_template.py --input t.docx --spec-version 4
python scripts/generate_document.py --template t.docx --spec spec.json `
  --content-plan content.json --plan fill_plan.json --output out.docx `
  --mode STANDARD --allow-unverified
```

The legacy `--data` token path is unchanged and still passes its original tests.

## 3. Eight acceptance scenarios

Implemented in `tests/test_e2e_v4.py` (10 tests; 8 required + 2 CLI tests).

| # | Scenario | Test | Result |
|---|---|---|---|
| 1 | Normal fill commits | `test_01_normal_fill_commits` | PASS — output contains filled text and table value |
| 2 | Missing required content | `test_02_missing_required_content_blocks` | PASS — `BLOCKED`, `REQUIRED_SLOT_MISSING` |
| 3 | Capacity overflow | `test_03_capacity_overflow_blocks` | PASS — `BLOCKED`, `CAPACITY_EXCEEDED`, no shrink |
| 4 | Protected region | `test_04_protected_slot_blocks` | PASS — `BLOCKED`, `PROTECTED_SLOT_VIOLATION` |
| 5 | QA failure | `test_05_qa_failure_prevents_commit` | PASS — `FAILED`, no deliverable |
| 6 | Mid-execution failure | `test_06_mid_execution_failure_rolls_back` | PASS — `FAILED`, ledger records failure, no partial file |
| 7 | COMMIT refused | `test_07_strict_unverified_refuses_commit` | PASS — STRICT refuses `UNVERIFIED` even with `--allow-unverified` |
| 8 | Rollback byte-identical | `test_08_rollback_is_byte_identical` | PASS — template SHA unchanged, no `.tmp`/`.pending` |
| 9 | CLI emits DocumentSpec 4.0 | `test_09_analyze_template_emits_spec_4_cli` | PASS — schema + semantic validation |
| 10 | CLI executes FillPlan | `test_10_generate_document_plan_cli` | PASS — committed output, no hidden write |

## 4. Test evidence

| Suite | Result |
|---|---|
| W1-A producer | 25 passed |
| W1-B validator | 17 passed |
| W1-C plans | 15 passed |
| W1-D executor | 16 passed |
| W1-E QA gate | 18 passed |
| W1-F E2E | 10 passed |
| W0 contracts | 70 passed |
| v3.5.9 baseline | 186 passed |
| **Full suite** | **357 passed in 101.9s** |

Command: `py -3.15 -m unittest discover -s tests -p "test_*.py"`.

## 5. Integration decisions made during W1

### I-01 Optional visual gaps do not force UNVERIFIED

`run_visual_layout_qa()` reports `PDF_PAGE_DIFF_UNAVAILABLE` when PyMuPDF is missing, even though pixel comparison is an **optional** check. Treating that as a global coverage gap made every run on this machine `UNVERIFIED`. `qa/pipeline.py` now keeps optional pixel/font gaps out of the global `coverage_gaps`; the required `VISUAL_PAGE_COUNT` verdict still controls status. Missing required checks still force `UNVERIFIED`.

### I-02 FIDELITY image authorization uses the FillPlan

The QA runner previously looked for `operations` on the ContentPlan (which has none), so an authorized image replacement could be reported as `UNAUTHORIZED_TEMPLATE_CHANGE`. `run_full_qa(..., fill_plan=...)` now reads the FillPlan; image-driven layout changes are a warning, other layout changes remain blocking.

### I-03 CLI gained `--content-plan`

`--plan` without a ContentPlan cannot verify `value_ref` facts. `generate_document.py` now accepts `--content-plan` and passes it to the executor; the legacy `--data` path is untouched.

### I-04 Empty header/footer parts are re-linked

The v3.5.9 story iterator makes python-docx materialize empty header/footer parts, which changed the structural fingerprint after save. The executor snapshots linked state and re-links definitions that did not exist before traversal. Verified on a template with a real header.

## 6. Issue status

| ID | Status after W1 | Notes |
|---|---|---|
| OI-01 (4.0 producer) | **CLOSED** | `--spec-version 4` emits a validated 4.0 spec; legacy default unchanged |
| OI-02 (environment) | OPEN | PyMuPDF/matplotlib/OCR still absent; optional checks stay UNVERIFIED |
| OI-03 (runtime validators) | **CLOSED (validators)** | `spec_validator`, `plan_validator`, `qa.gate` exist and are exercised end-to-end; transaction-level gate hook is enforced by the executor |
| OI-04 (legacy envelope) | OPEN | old CLIs still emit their original shapes |
| OI-05 (dependency inversion) | OPEN | `logic_qa -> workflow` untouched |
| OI-06 (policy/mode naming) | OPEN | unchanged, non-blocking |

New observations carried into W2:

| ID | Observation | Impact |
|---|---|---|
| W1-N1 | `location_id` schema allows only `sec[n].header/footer`, while the iterator also produces `first_page_header` / `even_page_header`. The producer excludes those stories and records `SLOT_STRUCTURE_UNSUPPORTED`. | No fill targets in first/even-page headers until a contract change proposal. |
| W1-N2 | `matched_text` span presence is not re-verified against the live paragraph by the spec validator (it has no package access). | Executor requires the token at apply time; a missing token falls back to paragraph fill. |
| W1-N3 | Defense in depth: `DocumentTransaction` itself does not call `qa.gate.assert_commit_eligible`; the executor enforces eligibility before commit. | Add a transaction-level hook in W2 without changing frozen contracts. |

## 7. Alpha readiness

- OI-01 closed: 4.0 producer exists and is CLI-reachable.
- End-to-end chain is covered by 8 required scenarios.
- Contracts remain 4.0.0 and unchanged.
- Remaining alpha-entry conditions (from the review): 6 template fixtures (L1–L4 / merged / nested), environment matrix file, ownership/path guard, integration branch green. These are W2 items, not code defects.

**W1 decision: complete.** The next milestone is W2: real-template fixtures, adversarial OOXML cases, and transaction-level gate hardening.
