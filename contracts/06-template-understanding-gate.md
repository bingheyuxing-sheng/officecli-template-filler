# Contract 06 — Template Understanding Gate

- Contract version: **1.0.0**
- Status: **DRAFT (W4-1); freeze requires Agent 07 review after W4-6**
- Owner: Agent 05 (Architecture & Integration)
- Schemas: `schemas/template_evidence-1.0.schema.json`, `schemas/template_gate_record-1.0.schema.json`, `schemas/template_analysis_report-1.0.schema.json`
- Data: `config/template-gate-policy.json`
- Consumers: `template_gate/`, `document_engine/fill_executor.py`, `engine/{repair,review,reformat}_engine.py`, `scripts/{generate,repair,review,reformat}_document.py`

## 1. Purpose

Contract 06 makes template understanding a mandatory, evidence-backed gate for
template-dependent document work. A task may enter formal execution only after:

1. the template has been analyzed;
2. every property required by the task type has evidence;
3. every blocking unknown, ambiguity or conflict has been resolved;
4. the user explicitly confirmed the analysis report;
5. the confirmation record still matches the current template, DocumentSpec,
   evidence digest and task type.

This contract is **additive**. DocumentSpec 4.0, ContentPlan/FillPlan, QAReport
4.0 and contracts 01–05 keep their frozen semantics.

## 2. Terms and evidence states

| Term | Meaning |
|---|---|
| Evidence | One verifiable property of one document object, with source, value and status |
| `VERIFIED` | A deterministic source (OOXML, style definition, DocumentSpec, user answer, or a matched reference document) supports the value |
| `UNVERIFIED` | The property is required by the task but no usable evidence exists |
| `AMBIGUOUS` | Multiple explanations are possible and structure/material cannot decide |
| `CONFLICT` | Two or more VERIFIED sources disagree about the same object/property |
| `task_relevant` | The property can change the correctness of the current task type |
| `blocking` | A task-relevant UNVERIFIED / AMBIGUOUS / CONFLICT item that MUST be resolved before confirmation |

Rules:

1. Model confidence, common formatting conventions and visual position MUST NOT
   be recorded as `VERIFIED`.
2. Red text is a clue, not proof. It MAY be a placeholder, an instruction or
   emphasis; without an explicit token or user statement it is `AMBIGUOUS`.
3. Unknown OOXML objects that are safely preserved MAY be registered as
   `object.preservable` with `task_relevant=false`, even when their semantics
   are unknown.
4. `unresolved blocking item` means an evidence record with `blocking=true`.

## 3. Task type matrix

| Task type | Gate | Required evidence |
|---|---|---|
| `GENERATE` | MUST | page setup, slot fillability/location/style, target table structure/capacity/purpose, protected regions, slot font family/size, red-text semantics |
| `REPAIR` | MUST | page setup, paragraph style/spacing, table structure/border/shading/merge/column width/purpose, textbox position |
| `REFORMAT` | MUST | same as `REPAIR` |
| `REVIEW` | MUST | page setup, paragraph style, slot fillability/location, protected regions, table purpose |
| `PROOFREAD` | MUST NOT | none (no template reference) |
| `EXCEL_GENERATE` | MUST NOT | unchanged v4 behavior |
| `POLISH` / `MERGE` | MUST NOT | capability remains `CAPABILITY_NOT_AVAILABLE` |

The policy matrix is system-owned (`config/template-gate-policy.json`). A caller
MUST NOT remove required properties or downgrade blocking statuses.

## 4. Gate state machine

States: `DISCOVERING`, `ANALYZING`, `VALIDATING`, `BLOCKED`,
`WAITING_USER_INPUT`, `READY_FOR_REVIEW`, `CONFIRMED`, `EXECUTING`,
`INVALIDATED`, `REJECTED`.

Allowed transitions:

```text
DISCOVERING        -> ANALYZING
ANALYZING          -> VALIDATING | REJECTED
VALIDATING         -> BLOCKED | READY_FOR_REVIEW | REJECTED
BLOCKED            -> WAITING_USER_INPUT | REJECTED
WAITING_USER_INPUT -> ANALYZING | REJECTED
READY_FOR_REVIEW   -> CONFIRMED | ANALYZING | REJECTED
CONFIRMED          -> EXECUTING | INVALIDATED
EXECUTING          -> INVALIDATED
INVALIDATED        -> ANALYZING
REJECTED           -> terminal
```

Mandatory:

1. Only `CONFIRMED -> EXECUTING` is a legal path to formal execution.
2. `BLOCKED -> EXECUTING`, `WAITING_USER_INPUT -> EXECUTING` and
   `READY_FOR_REVIEW -> EXECUTING` MUST raise `TEMPLATE_GATE_ILLEGAL_TRANSITION`.
3. `EXECUTING` is a runtime state; the persisted record remains `CONFIRMED` and
   appends an entry to `executions[]`.
4. `ANY -> INVALIDATED` is triggered only by deterministic binding checks, never
   by model narration.

## 5. Gate Record

Required fields are defined by `schemas/template_gate_record-1.0.schema.json`.
The record binds at least:

- `template_sha256` and `template_name` (basename only; no absolute path);
- `spec_schema_version`, `spec_digest`, `fingerprint_ref`;
- `analysis_version`, `parser_version`, `policy_version`;
- `task_type`;
- `evidence_digest` and `evidence_summary`;
- `blocking_count`;
- `status`, `user_confirmed`, `confirmed_at`, `user_statement`;
- `confirmation_token`;
- `supplements[]`;
- `created_at`, `updated_at`, `executions[]`.

Invalidation:

| Change | Required result |
|---|---|
| Template bytes differ | `TEMPLATE_GATE_STALE` |
| DocumentSpec digest or fingerprint differs | `TEMPLATE_GATE_STALE` |
| Evidence digest differs | `TEMPLATE_GATE_STALE` |
| Analysis/parser/policy version differs | `TEMPLATE_GATE_STALE` |
| Task type differs | `TEMPLATE_GATE_REQUIRED` |
| Token invalid or `user_confirmed=false` | `TEMPLATE_GATE_CONFIRMATION_REQUIRED` |
| Status is BLOCKED/WAITING/READY/REJECTED | `TEMPLATE_GATE_BLOCKED` |
| Record missing | `TEMPLATE_GATE_REQUIRED` |

## 6. User confirmation

A confirmation is valid only when:

1. an Analysis Report exists for the current analysis;
2. `blocking_count == 0`;
3. the user explicitly confirms the report (recorded as `user_statement`);
4. the `review_token` presented with the report matches the report digest;
5. the confirmation record is written by `template_gate.store.GateStore`.

No reply, a read-only view, an AI judgement, or an auto-generated record MUST
NOT be treated as confirmation.

## 7. Analysis Report

The JSON report is defined by `schemas/template_analysis_report-1.0.schema.json`; the
Markdown rendering MUST include:

1. template basics (name, SHA-256, page count when verifiable, sections, tables,
   images, special objects);
2. page and style rules (page size, margins, fonts, sizes, heading/body styles,
   paragraph spacing, table styles, headers/footers);
3. document structure (cover/title/body/table/signature/fixed/fillable/protected);
4. analysis quality (VERIFIED/UNVERIFIED/AMBIGUOUS/CONFLICT counts, resolved,
   unresolved blocking, coverage with the explicit caveat that coverage is not
   correctness);
5. user confirmation prompt and the blocking-item list with: item id, location,
   current result, uncertainty reason, possible error, required material and
   acceptable resolutions.

## 8. Gate validation

`validate_gate(template_path, task_type, gate_record, spec)` MUST check, in order:

1. record exists;
2. record matches its schema and semantics;
3. `status == CONFIRMED` and `user_confirmed == true`;
4. `confirmation_token` HMAC matches;
5. `template_sha256` matches the current template;
6. `spec_schema_version == "4.0"` and `spec_digest` matches when a spec is supplied;
7. `fingerprint_ref` matches a fresh fingerprint;
8. `analysis_version`, `parser_version`, `policy_version` match the runtime;
9. `evidence_digest` matches the current analysis;
10. `blocking_count == 0`;
11. `task_type` matches.

Failure returns `TEMPLATE_GATE_REQUIRED`, `TEMPLATE_GATE_BLOCKED`,
`TEMPLATE_GATE_STALE`, `TEMPLATE_GATE_CONFIRMATION_REQUIRED`,
`TEMPLATE_EVIDENCE_CONFLICT` or `TEMPLATE_EVIDENCE_INCOMPLETE` as applicable.
No failure path may downgrade to the legacy payload chain.

## 9. Execution integration

Mandatory call sites:

- `document_engine.fill_executor.execute_fill_plan` (GENERATE);
- `engine.repair_engine.execute_repair_plan` (REPAIR);
- `engine.review_engine.execute_review_plan` (REVIEW only; PROOFREAD skipped);
- `engine.reformat_engine.execute_reformat_plan` (REFORMAT);
- legacy `scripts/generate_document.py --data` path (GENERATE).

CLI callers MAY pass an explicit `--gate-record`; when omitted the validator
looks up the newest `CONFIRMED` record for the template SHA + task type. An
explicit record is still validated by the same rules and is not a bypass.

## 10. Error codes

The following codes are additive to `config/error-codes.json`:
`TEMPLATE_GATE_REQUIRED`, `TEMPLATE_GATE_BLOCKED`, `TEMPLATE_GATE_STALE`,
`TEMPLATE_GATE_CONFIRMATION_REQUIRED`, `TEMPLATE_EVIDENCE_CONFLICT`,
`TEMPLATE_EVIDENCE_INCOMPLETE`, `TEMPLATE_GATE_ILLEGAL_TRANSITION`.

`TEMPLATE_SHA_MISMATCH` keeps its existing execution-time meaning and is not
reused for gate binding failures.

## 11. Versioning and compatibility

- Contract 06 starts at 1.0.0; the contract set moves from 4.2.0 to 4.3.0 when
  this contract and its schemas pass Agent 07 review.
- Contracts 01–05 and their schemas MUST NOT be modified by this contract.
- Existing CLI defaults, including `analyze_template.py --spec-version 3`, remain
  unchanged.
- The gate intentionally changes the default behavior of gated modes: an
  unconfirmed template can no longer be executed. This is the purpose of W4 and
  MUST be documented in Release Notes.
