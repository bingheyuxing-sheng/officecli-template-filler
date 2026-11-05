# Contract 05 — ToolEnvelope / Error Codes

- Contract version: **1.0.0**
- Status: **FROZEN (W0, 2026-11-05)**
- Owner: Agent 05 (Architecture & Integration)
- Schemas: `schemas/tool_envelope-4.0.schema.json`, `schemas/error_code_registry-4.0.schema.json`
- Registry data: `config/error-codes.json`
- Gate: Agent 07

## 1. Purpose

Every v4.0 CLI or MCP tool returns the same outer object, so the orchestrator branches on fields instead of parsing per-tool prose. Error semantics are registered once and reused, so "retryable" and "rollback required" are consistent across modules.

This contract does **not** retrofit v3.5.9 CLIs in W0. Existing CLIs keep their current output; new tools MUST use the envelope. Migration of old tools is a beta task.

## 2. ToolEnvelope 4.0

| Field | Required | Rule |
|---|---|---|
| `schema_version` | yes | const `"4.0"` |
| `task_id` | yes | `^TASK_[0-9A-Za-z_-]{1,64}$` |
| `status` | yes | §3 |
| `data` | yes | object; tool-specific payload; may be empty |
| `warnings` | yes | array of warning records (§4) |
| `errors` | yes | array of error records (§5) |
| `artifacts` | yes | array of artifact records (§6) |
| `next_action` | yes | §7 |
| `transaction` | optional | transaction summary; opaque |
| `metrics` | optional | object of numeric counters |

Arrays MUST be present even when empty. A missing `errors` array is a schema error because "no errors" and "error details discarded" must not look alike.

### 2.1 Task ID

- Format: `TASK_` + 1–64 chars from `[0-9A-Za-z_-]`.
- One user request gets one task id; every step of that request reuses it.
- A retry of the same step keeps the task id and adds a new `OP_` id in `data`.
- A new user request MUST get a new task id.
- Task id MUST NOT encode personal data, file paths, or timestamps.

## 3. `status`

| Status | Meaning | Mutation allowed | Artifact present |
|---|---|---|---|
| `SUCCESS` | All required work completed; no missing required check | yes | yes |
| `PARTIAL` | Some requested work completed; remainder explicitly listed | yes | possibly |
| `NEEDS_CONFIRMATION` | Waiting for user input; nothing committed | no | no |
| `BLOCKED` | A precondition failed before mutation | no | no |
| `FAILED` | Mutation attempted and rolled back; or an unrecoverable error | rolled back | no |
| `UNVERIFIED` | Work completed but at least one required check could not run | yes | yes, with disclosure |

`SUCCESS` MUST NOT be used when `QAReport.missing_checks` is non-empty. `FAILED` MUST NOT leave a staged or partial file referenced by `artifacts`.

## 4. `warnings[]`

| Field | Required | Rule |
|---|---|---|
| `code` | yes | registry code with `severity` = `low` or `medium` |
| `message` | yes | non-empty human-readable string |
| `details` | optional | object |

Warnings never block. A warning that requires a decision MUST be promoted to an error with `human_intervention: true` or to `status: NEEDS_CONFIRMATION`.

## 5. `errors[]`

| Field | Required | Rule |
|---|---|---|
| `code` | yes | registry code |
| `message` | yes | non-empty string, no stack trace |
| `severity` | yes | `low` / `medium` / `high` / `blocking` |
| `retryable` | yes | boolean; true only when retry without changing inputs may succeed |
| `rollback_required` | yes | boolean; true when a partial mutation must be discarded |
| `human_intervention` | yes | boolean; true when the user must decide or supply missing facts |
| `details` | optional | object with location, expected/actual, artifact path |

Rules:

1. `status: FAILED` requires at least one error with `severity: blocking` or `severity: high`.
2. `status: BLOCKED` requires at least one error with `rollback_required: false`.
3. `retryable: true` and `human_intervention: true` together are allowed only for lock-type errors (`OUTPUT_FILE_LOCKED`).
4. An error code that is not registered is a schema-invalid report.

## 6. `artifacts[]`

| Field | Required | Rule |
|---|---|---|
| `path` | yes | absolute or workspace-relative path; must exist when status is `SUCCESS`, `PARTIAL`, or `UNVERIFIED` |
| `kind` | yes | `docx` / `pdf` / `json` / `png` / `other` |
| `sha256` | optional | 64 lowercase hex; required for the final deliverable |
| `required` | yes | boolean; true for the artifact the user asked for |

An artifact MUST NOT be a staging path (`*.tmp-*`, `*.pending-*`). Staged paths are internal and must never be exposed.

## 7. `next_action`

Allowed values and consistency:

| Value | Allowed when |
|---|---|
| `RUN_QA` | status `PARTIAL` and a required check has not run |
| `ASK_USER` | status `NEEDS_CONFIRMATION` or an error has `human_intervention: true` |
| `RETRY` | an error has `retryable: true` |
| `COMMIT` | status `SUCCESS`, or status `UNVERIFIED` with `data.qa_eligible: true` and an attached QA report; `UNVERIFIED` must list the missing checks in `data.missing_checks` |
| `STOP` | status `BLOCKED` or `FAILED` |
| `NONE` | status `SUCCESS` and no further step is required |

`COMMIT` with `status: FAILED`, or `COMMIT` without a QA report, is a contract violation.

## 8. Error code registry

`schema_version: "4.0"`, `codes[]` where each entry has:

| Field | Required | Rule |
|---|---|---|
| `code` | yes | `^[A-Z][A-Z0-9_]{2,63}$`; unique |
| `severity` | yes | `low` / `medium` / `high` / `blocking` |
| `retryable` | yes | boolean |
| `rollback_required` | yes | boolean |
| `human_intervention` | yes | boolean |
| `owner` | yes | `AGENT01` … `AGENT07` / `CORE` |
| `message_template` | yes | non-empty string with `{placeholders}` allowed |
| `introduced_in` | yes | contract or version, e.g. `3.5.9`, `4.0.0` |

Existing v3.5.9 codes are **grandfathered**: they are registered with their current spelling and MUST NOT be renamed. New codes use domain prefixes; `V4_` is reserved for contract-level violations.

### 8.1 Registered core codes (normative data: `config/error-codes.json`)

| Code | Severity | Retry | Rollback | Human | Owner |
|---|---|---|---|---|---|
| `SLOT_ID_CONFLICT` | blocking | false | false | false | AGENT01 |
| `SLOT_LOCATION_UNRESOLVED` | high | false | false | false | AGENT01 |
| `SLOT_TEMPLATE_MISMATCH` | blocking | false | false | false | AGENT01 |
| `SLOT_ID_COLLISION_RESOLVED` | low | false | false | false | AGENT01 |
| `TEMPLATE_SHA_MISMATCH` | blocking | false | false | false | AGENT03 |
| `INVALID_FILL_PLAN` | blocking | false | false | false | AGENT02 |
| `INVALID_CONTENT_PLAN` | blocking | false | false | false | AGENT02 |
| `SOURCE_REF_MISSING` | blocking | false | false | true | AGENT02 |
| `FACT_SOURCE_MISSING` | high | false | false | true | AGENT02 |
| `UNKNOWN_SLOT` | blocking | false | false | false | AGENT02 |
| `PROTECTED_SLOT_VIOLATION` | blocking | false | false | true | AGENT03 |
| `UNAUTHORIZED_SLOT_TARGET` | blocking | false | false | false | AGENT03 |
| `CAPACITY_EXCEEDED` | high | true | true | true | AGENT03 |
| `FORMAT_REPAIR_FORBIDDEN` | blocking | false | false | false | AGENT03 |
| `UNAUTHORIZED_TEMPLATE_CHANGE` | blocking | false | true | true | AGENT04 |
| `QA_POLICY_OVERRIDE_FORBIDDEN` | blocking | false | false | false | AGENT04 |
| `QA_FALSE_PASS` | blocking | false | false | false | AGENT04 |
| `QA_EVIDENCE_MISSING` | high | false | false | false | AGENT04 |
| `QA_REPAIR_UNVERIFIED` | high | false | false | false | AGENT04 |
| `QA_ELIGIBILITY_CONTRADICTION` | blocking | false | false | false | AGENT04 |
| `QA_FIDELITY_BYPASS` | blocking | false | false | false | AGENT04 |
| `OUTPUT_FILE_LOCKED` | high | true | true | true | CORE |
| `SSOT_VALIDATION_FAILED` | high | false | false | true | CORE |
| `TEMPLATE_TEXT_RESIDUAL` | medium | false | false | true | CORE |
| `PACKAGE_DANGLING_REL` | high | false | true | false | AGENT04 |

## 9. Forbidden patterns

| Pattern | Verdict |
|---|---|
| `status: SUCCESS` with errors non-empty | Invalid |
| `status: FAILED` with no blocking/high error | Invalid |
| `next_action: COMMIT` with `status: UNVERIFIED` but without `data.qa_eligible: true` | Invalid |
| `next_action: COMMIT` with `status: FAILED` / `BLOCKED` / `NEEDS_CONFIRMATION` | Invalid |
| Error code absent from registry | Invalid |
| Artifact path pointing to `*.tmp-*` / `*.pending-*` | Invalid |
| Unregistered severity string | Invalid schema |
| Reusing a task id across two user requests | Invalid |

## 10. Examples

`examples/tool-envelope/cases.json`: `minimal_valid`, `full_valid`, `missing_required`, `type_error`, `boundary_conflict` (`status: FAILED` with `next_action: COMMIT`).

## 11. Change log

| Version | Change |
|---|---|
| 1.0.0 | Initial frozen contract (W0) |
