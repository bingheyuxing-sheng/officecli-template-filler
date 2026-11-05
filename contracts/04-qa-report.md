# Contract 04 — QAReport 4.0

- Contract version: **1.0.0**
- Status: **FROZEN (W0, 2026-11-05)**
- Owner: Agent 04 (QA & Verification)
- Schema: `schemas/qa_report-4.0.schema.json`
- Policy data: `config/qa-policy.json`
- Gate: Agent 07

## 1. Purpose

`QAReport 4.0` is the only artifact that may authorize delivery. It records what was checked, with what evidence, what could not be checked, what was repaired, and whether the result may be committed.

The generator MUST NOT decide its own required checks. `required_checks` is derived from the system-owned policy matrix in `config/qa-policy.json`, selected by `policy_source`. A caller-supplied list is invalid and MUST be rejected with `QA_POLICY_OVERRIDE_FORBIDDEN`.

## 2. Overall status (four states)

| Status | Condition | Commit effect |
|---|---|---|
| `PASSED` | Every required check executed with `PASSED`; no blocking issue; no missing check; no coverage gap | Eligible in every mode |
| `PENDING_HUMAN_REVIEW` | No blocking issue; only explicitly pending codes remain (e.g. intentional placeholder residue in REVIEW) | Eligible only when policy allows |
| `UNVERIFIED` | No blocking issue, but at least one required check is `SKIPPED` / `UNVERIFIED`, or `coverage_gaps` is non-empty | Not eligible in STRICT; eligible with disclosure in STANDARD |
| `FAILED` | At least one blocking issue, or any unauthorized template difference | Never eligible |

`UNVERIFIED` MUST NOT be described as a pass. A report with `missing_checks` non-empty MUST NOT carry `status: PASSED`.

## 3. Top-level object

| Field | Required | Rule |
|---|---|---|
| `schema_version` | yes | const `"4.0"` |
| `task_id` | yes | Contract 05 task id |
| `status` | yes | §2 |
| `task_mode` | yes | `GENERATE` / `REPAIR` / `REVIEW` / `EXCEL_GENERATE`; must match the FillPlan task |
| `gate_mode` | yes | `STRICT` / `STANDARD` / `REPLICA` |
| `policy_source` | yes | MUST equal `"{task_mode}/{gate_mode}"`; this binding prevents a caller from selecting a weaker policy |
| `required_checks` | yes | array of check ids, minItems 1; MUST equal the policy set |
| `executed_checks` | yes | array of check ids actually executed |
| `missing_checks` | yes | array of check ids required but not executed |
| `checks` | yes | array of check records (§4) |
| `issues` | yes | array of issue records (§5) |
| `warnings` | optional | array of non-blocking findings |
| `coverage_gaps` | yes | array of non-empty strings |
| `repairs` | yes | array of repair records (§6) |
| `final` | yes | §7 |
| `transaction` | optional | transaction summary, opaque to this contract |

Set consistency:

1. `required_checks ∩ missing_checks` = `missing_checks`.
2. `executed_checks` ⊆ `required_checks ∪ optional_checks`.
3. Every `required_checks` entry MUST appear exactly once in `checks`.
4. `missing_checks` MUST have a corresponding check record with `status: SKIPPED` and an evidence note.

## 4. `checks[]`

| Field | Required | Rule |
|---|---|---|
| `check_id` | yes | enum: `PACKAGE`, `FORMAT`, `FIDELITY`, `CONTENT`, `DATA`, `VISUAL_PAGE_COUNT`, `VISUAL_PIXEL`, `OCR`, `REVIEW_INTEGRITY`, `EXCEL_FORMULA` |
| `required` | yes | boolean; must match membership in `required_checks` |
| `status` | yes | `PASSED` / `FAILED` / `PENDING_HUMAN_REVIEW` / `UNVERIFIED` / `SKIPPED` |
| `evidence.method` | yes | non-empty string naming the actual implementation used |
| `evidence.artifact_path` | optional | path of the inspected artifact; MUST NOT be the generator's in-memory object |
| `evidence.input_sha256` | optional | 64 lowercase hex |
| `evidence.output_sha256` | optional | 64 lowercase hex |
| `evidence.detail` | optional | string |
| `issues` | optional | array of issue records owned by this check |

Evidence rules:

1. `PASSED` requires `evidence.method` and, except for `CONTENT`/`DATA` which operate on parsed content, an `artifact_path` that exists at report time.
2. `UNVERIFIED` requires `evidence.detail` naming what could not run (e.g. `PDF_BACKEND_UNAVAILABLE`, `PYMUPDF_UNAVAILABLE`).
3. `SKIPPED` requires `evidence.detail` with the policy reason. A required check skipped without a reason is a schema-level `UNVERIFIED`, not a pass.

### 4.1 Check definitions

| Check | Implementation source | Evidence |
|---|---|---|
| `PACKAGE` | `audit_docx_package_integrity` | package report path + part count |
| `FORMAT` | `audit_format_and_text_qa` | artifact path + profile |
| `FIDELITY` | new `qa/fidelity_qa.py` (W2) | fingerprint diff counts |
| `CONTENT` | `audit_content_consistency` | label/value count |
| `DATA` | SSOT validation + `audit_fact_sources` | fact count + conflict count |
| `VISUAL_PAGE_COUNT` | `run_visual_layout_qa` | PDF backend + page counts |
| `VISUAL_PIXEL` | PyMuPDF page diff | compared page count |
| `OCR` | `audit_image_text` | OCR backend name |
| `REVIEW_INTEGRITY` | `audit_review_integrity` | revision/comment counts |
| `EXCEL_FORMULA` | `audit_excel_formula_and_style_qa` | verified/unsupported counts |

## 5. `issues[]`

| Field | Required | Rule |
|---|---|---|
| `code` | yes | Contract 05 registry code |
| `severity` | yes | `high` / `medium` / `low` |
| `location` | yes | non-empty string (location id, package part, or check scope) |
| `detail` | yes | non-empty string |
| `blocking` | yes | boolean |
| `check_id` | optional | owning check |

Blocking rule: `blocking: true` OR `severity: high` makes the report `FAILED`. `medium`/`low` findings are warnings and MUST NOT be reported as failures. An issue with `blocking: false` and `severity: high` is contradictory and invalid.

## 6. `repairs[]`

| Field | Required | Rule |
|---|---|---|
| `repair_id` | yes | `^REP_[0-9A-Za-z_-]{1,32}$`; unique |
| `issue_code` | yes | code of the fixed issue |
| `action` | yes | non-empty string (`AUTO_FIX`, `RESTORE_BASELINE`, `MANUAL_NOTE`, ...) |
| `revision_id` | optional | Word revision id when the fix was tracked |
| `applied` | yes | boolean |
| `recheck.status` | yes | `PASSED` / `FAILED` / `UNVERIFIED` / `SKIPPED` |
| `recheck.report_ref` | optional | path of the recheck report |

Rule: a repair with `applied: true` MUST have `recheck`; a repair that changes formatting MUST carry a `revision_id` (so Word/WPS can accept or reject it).

## 7. `final`

| Field | Required | Rule |
|---|---|---|
| `eligible_for_commit` | yes | boolean |
| `reasons` | yes | array of non-empty strings |

Eligibility is computed, never asserted by the generator:

| `policy_source` suffix | Eligible statuses | Extra condition |
|---|---|---|
| `/STRICT` | `PASSED` only | `missing_checks` empty; no unauthorized fidelity diff |
| `/STANDARD` | `PASSED`, `PENDING_HUMAN_REVIEW`, `UNVERIFIED` | `UNVERIFIED` must list `missing_checks` in `reasons`; no unauthorized fidelity diff |
| `REVIEW/*` | `PASSED`, `PENDING_HUMAN_REVIEW` | review integrity passed |

If `final.eligible_for_commit` disagrees with this table, the report is invalid (`QA_ELIGIBILITY_CONTRADICTION`).

## 8. Repair and recheck loop

1. A blocking issue may produce a repair record.
2. After any repair, the affected check MUST be re-executed; `recheck.status` records the outcome.
3. A repair that changes the document MUST be followed by `PACKAGE` + `FORMAT` + `FIDELITY` re-execution.
4. A failed recheck returns the report to `FAILED`; the failed repair MUST NOT be hidden by a later passing check.

## 9. Forbidden patterns

| Pattern | Code |
|---|---|
| `required_checks` different from the policy set | `QA_POLICY_OVERRIDE_FORBIDDEN` |
| `status: PASSED` with `missing_checks` | `QA_FALSE_PASS` |
| `VISUAL_PAGE_COUNT` marked `PASSED` without a backend | `QA_FALSE_PASS` |
| Check evidence pointing to a staged file that no longer exists | `QA_EVIDENCE_MISSING` |
| Repair applied without recheck | `QA_REPAIR_UNVERIFIED` |
| Unauthorized fidelity diff marked non-blocking | `QA_FIDELITY_BYPASS` |

## 10. Policy matrix (normative data: `config/qa-policy.json`)

| Policy source | Required | Optional |
|---|---|---|
| `GENERATE/STRICT` | `PACKAGE`, `FORMAT`, `FIDELITY`, `CONTENT`, `DATA`, `VISUAL_PAGE_COUNT` | `VISUAL_PIXEL`, `OCR` |
| `GENERATE/STANDARD` | `PACKAGE`, `FORMAT`, `FIDELITY`, `CONTENT`, `DATA`, `VISUAL_PAGE_COUNT` | `VISUAL_PIXEL`, `OCR` |
| `REPAIR/REPLICA` | `PACKAGE`, `FORMAT`, `FIDELITY`, `DATA` | `VISUAL_PAGE_COUNT` |
| `REVIEW/REPLICA` | `PACKAGE`, `FORMAT`, `REVIEW_INTEGRITY` | `VISUAL_PAGE_COUNT` |

STRICT and STANDARD differ only in commit eligibility, not in required checks. That is intentional: the same evidence is gathered; STRICT refuses to publish while unverified.

## 11. Examples

`examples/qa-report/cases.json`: `minimal_valid`, `full_valid`, `missing_required`, `type_error`, `boundary_conflict` (`status: PASSED` with non-empty `missing_checks`).

## 12. Change log

| Version | Change |
|---|---|
| 1.0.0 | Initial frozen contract (W0) |
