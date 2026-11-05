# W0 Gate Review Report — Agent 07

- Report ID: W0-GATE-07
- Reviewed contract set: **4.0.0**
- Review date: 2026-11-05
- Reviewer: Agent 07 (Architecture Reviewer, read-only; did not author the contracts)
- Inputs: `contracts/`, `schemas/`, `examples/`, `config/`, `tests/contracts/`, `reports/w0/issues.md`
- Verdict: **PASS** (formal W0 gate)

> Historical record of the W0 gate at contract set **4.0.0**. OI-01 was closed in W1 (`reports/w1/w1-acceptance.md` §6); OI-03 and OI-05 were closed in W1/W2. Current contract set: **4.2.0**.

## 1. Review method

1. Read all five contracts and the compatibility matrix.
2. Compared every contract MUST against its JSON Schema and its examples.
3. Ran the contract suite and the full baseline suite.
4. Traced every consumer path for bypasses: QA, template protection, final path, rollback, parallel ownership.
5. Re-derived the required-check sets from `config/qa-policy.json` instead of trusting the report text.
6. Checked that no v3.5.9 tracked file was modified (`git diff --name-only` empty).

## 2. Nine required review items

| # | Item | Verdict | Evidence / notes |
|---|---|---|---|
| 1 | Do the five contracts cover the intended functionality? | **PASS** | Slot identity, template understanding, content planning, execution planning, QA, tool envelope and error semantics are all specified. `analyze_template` cannot yet emit 4.0, tracked as OI-01; the contract itself is complete and the 4.0 schema was not weakened. |
| 2 | Are there contradictory fields or states? | **PASS after fixes** | G-01 and G-02 were found and fixed before freeze; see §3. No remaining contradiction found. |
| 3 | Are interface constraints executable? | **PASS** | Slot `scope` matches the existing all-story iterator; `image_role` matches `find_images()` roles; `location_id` grammar matches the v3.5.9 locator; status/next_action tables are implementable with `DocumentTransaction`. |
| 4 | Are there duplicate responsibilities or unnecessary abstractions? | **PASS** | No DocumentIR. ContentPlan and FillPlan are separated by artifact. Each schema has one owner. The error registry registers rather than renames. |
| 5 | Is there a QA bypass path? | **PASS after fix** | G-02 closed the "choose a weaker policy" path by binding `task_mode/gate_mode` to `policy_source`. `required_checks` is policy-owned. Missing checks force `UNVERIFIED`; STRICT cannot commit. Runtime enforcement is OI-03 (W1/W2), explicitly tracked. |
| 6 | Is there a template protection bypass path? | **PASS after clarification** | G-03: `not_protected` now explicitly includes `protected_regions` whose location is the target or an ancestor. `baseline.allowed_slot_ids` is a subset requirement, and protected slots cannot be authorized by listing them. Runtime region containment test is owned by W2. |
| 7 | Is there a path that writes directly to the final deliverable? | **PASS** | FillPlan contains no output path; Contract 03 §3.8 mandates `tx.stage()` only; Contract 05 rejects `*.tmp-*` / `*.pending-*` artifacts. |
| 8 | Are rollback and traceability supported? | **PASS** | Error records carry `rollback_required`; transaction publishes only after QA; `fill_ledger` is mandatory per operation with before/after hashes; QA repairs require rechecks. |
| 9 | Are interfaces stable enough for parallel development? | **PASS** | Five frozen contracts, versioned schemas, explicit ownership matrix, single writer for `engine/__init__.py`, and a freeze manifest with SHA-256 digests. No existing file changed. |

## 3. Findings

### G-01 — COMMIT vs UNVERIFIED eligibility (fixed)

**Found:** Contract 05 allowed `next_action: COMMIT` only with `status: SUCCESS`, while Contract 04 allows STANDARD policy to publish `UNVERIFIED` with disclosure. A STANDARD run with a non-empty `missing_checks` had no legal `next_action`.

**Resolution:** Contract 05 §7 now allows `COMMIT` for `UNVERIFIED` only when `data.qa_eligible: true` and `data.missing_checks` is non-empty. The semantic checker enforces both; a dedicated test covers the negative and positive case.

**Status:** closed before freeze.

### G-02 — QA policy spoofing (fixed)

**Found:** QAReport carried `policy_source` but not the task that produced it. A GENERATE result could present a `REVIEW/REPLICA` report with fewer required checks and still look valid.

**Resolution:** `task_mode` and `gate_mode` are now required, and `policy_source` MUST equal `"{task_mode}/{gate_mode}"`. The semantic checker rejects mismatches; a dedicated test covers it.

**Status:** closed before freeze.

### G-03 — Protected region bypass (clarified)

**Found:** `not_protected` could be read as slot-level only, leaving a fillable slot inside a protected header/region unprotected.

**Resolution:** Contract 03 §3.4 rule 5 defines `not_protected` as slot status **plus** every enclosing `protected_regions` entry. The region wins.

**Status:** closed at contract level; runtime containment test belongs to W2.

### G-04 — Direct final-path write (clarified)

**Found:** The contract did not state the write boundary explicitly.

**Resolution:** Contract 03 §3.8 mandates staging-only writes, a per-operation ledger, and QA reading the artifact rather than memory.

**Status:** closed at contract level.

### G-05 — `analyze_template` conformance interpretation (tracked, not lowered)

**Finding:** The v3.5.9 `analyze_template.py` output validates against `document_spec-legacy-cli.schema.json`, not against DocumentSpec 4.0. This is a producer gap, not a schema defect.

**Ruling:** W0's scope is contract freeze. The 4.0 schema remains strict; the legacy output is validated by its own compatibility schema. OI-01 is recorded as an **alpha blocker** and must be closed before alpha starts. This is not a CONDITIONAL_PASS: W0's entry rules do not include a 4.0 producer, and no requirement was reduced.

**Status:** tracked as OI-01.

### Observations (non-blocking)

| ID | Observation | Recommendation |
|---|---|---|
| O-01 | FillPlan has `mode` (STRICT/STANDARD) and operation `policy` (const STRICT). They are different concepts (operation safety vs delivery gate) but the naming is close. | Clarify wording in beta; do not change semantics. |
| O-02 | `capacity.hard_limit` supports only `explicit_charlimit` and `fixed_height_cell`. | Conservative by design; expand only with evidence and tests. |
| O-03 | ToolEnvelope `data` is intentionally untyped. | Keep it tool-specific; never put contract-critical fields only inside `data`. |
| O-04 | The error registry registers core v4 codes plus four legacy codes, not every v3.5.9 code. | Beta: register the remaining legacy codes without renaming. |
| O-05 | Cross-field rules are enforced by contract tests, not by JSON Schema. | OI-03: implement runtime validators in W1 before beta. |

## 4. Bypass analysis results

| Bypass attempt | Result |
|---|---|
| Claim `PASSED` with a skipped required check | Rejected: semantic check + `QA_FALSE_PASS` code |
| Present a weaker `policy_source` | Rejected: `task_mode/gate_mode` binding |
| Override `required_checks` | Rejected: policy set comparison |
| Fill a protected slot listed in `allowed_slot_ids` | Rejected: slot status + region rule |
| Write the final path directly | Rejected: contract write boundary + artifact path rule |
| Expose a staging path as an artifact | Rejected: semantic check |
| Commit after `FAILED` | Rejected: envelope consistency |
| Use a blocking error with auto-retry | Rejected: registry test (`blocking` ⇒ `retryable: false`) |
| Fill without a source | Rejected: `SOURCE_REF_MISSING` / `FACT_SOURCE_MISSING` |
| Shrink font to satisfy capacity | Rejected: `FORMAT_REPAIR_FORBIDDEN`, overflow `REJECT` only |

No unmitigated bypass path found at the contract level.

## 5. Compatibility review

| Check | Result |
|---|---|
| Modified tracked files | 0 (`git diff --name-only` empty) |
| Removed or renamed public symbols | 0 (all `engine.__all__` present) |
| `engine.__version__` | still `3.5.9` |
| `document_spec.schema.json` | still `schema_version: "3.0"` |
| `qa_report.schema.json` | still four-state `status` |
| Original 186 tests | pass unchanged |
| Legacy output rejected by 4.0 schema | confirmed by test |
| Error codes renamed | 0 |

## 6. Test evidence reviewed

| Suite | Result |
|---|---|
| Contract tests (`tests/contracts`, 11 files) | **70 passed** |
| Full suite | **256 passed** (186 + 70) |
| Valid examples | 11 pass |
| Invalid examples | 6 fail schema as expected |
| Semantic-invalid examples | 5 pass schema, fail semantic rules as expected |
| Slot ID vectors | 5 reproduce exactly |

Commands:

```powershell
py -3.15 -m unittest discover -s tests/contracts -t tests
py -3.15 -m unittest discover -s tests -p "test_*.py"
```

## 7. Verdict

**PASS — W0 contract gate.**

Conditions carried into alpha (not W0 defects):

1. **OI-01 was a hard alpha blocker at W0** (closed in W1): `analyze_template.py --spec-version 4` must emit a schema-valid DocumentSpec 4.0.
2. OI-03 runtime validators must exist before beta; W0 tests prove the rules are expressible, not that a runtime enforces them.
3. OI-02 environment limits must be reported as `UNVERIFIED`, never `PASSED`.

No blocking contract issue remains. No requirement was lowered to obtain this PASS.

## 8. Appendix — contract test file digests

SHA-256, first 16 hex:

| File | SHA-256 (16) |
|---|---|
| `tests/contracts/__init__.py` | `80B46CB92C7576A4` |
| `tests/contracts/helpers.py` | `C1277D280F20CB96` |
| `tests/contracts/test_cross_contract.py` | `7BB50FD8DEC22A60` |
| `tests/contracts/test_document_spec.py` | `76FF307D29AF232B` |
| `tests/contracts/test_error_registry.py` | `6D52EB48D238E78E` |
| `tests/contracts/test_legacy_compat.py` | `7627B6EA8ADBEF4F` |
| `tests/contracts/test_plans.py` | `1B973D016BEE1827` |
| `tests/contracts/test_qa_report.py` | `48850DEC7F2671C7` |
| `tests/contracts/test_schemas.py` | `271111318F7A8B25` |
| `tests/contracts/test_slot_id.py` | `F776231B03F60BC1` |
| `tests/contracts/test_tool_envelope.py` | `E081CFB9B43158AD` |
