# Office Skill v4.0 — W0 Contract Index

- Contract set version: **4.1.0** (W0 freeze 4.0.0 + CP-W2-001, additive)
- Freeze date: 2026-11-05; change date: 2026-11-05
- Freeze authority: Agent 05 (Architecture & Integration)
- Independent gate: Agent 07 (Architecture Reviewer)
- Normative language: **MUST / MUST NOT / SHOULD / MAY** (RFC 2119)

## 1. Contract set

| No. | Contract | Owner | Schema(s) | Purpose |
|---|---|---|---|---|
| 01 | [Slot ID](01-slot-id.md) | Agent 01 | none (algorithm + vectors) | Stable identity for fillable positions |
| 02 | [DocumentSpec 4.0](02-document-spec.md) | Agent 01 | `document_spec-4.0.schema.json` | Template understanding output |
| 03 | [ContentPlan / FillPlan](03-content-fill-plan.md) | Agent 02 (ContentPlan), Agent 03 (FillPlan) | `content_plan-4.0.schema.json`, `fill_plan-4.0.schema.json` | Separate content planning from DOCX execution |
| 04 | [QAReport 4.0](04-qa-report.md) | Agent 04 | `qa_report-4.0.schema.json` | Independent verification and commit eligibility |
| 05 | [ToolEnvelope / Error Codes](05-tool-envelope-error-codes.md) | Agent 05 | `tool_envelope-4.0.schema.json`, `error_code_registry-4.0.schema.json` | Uniform tool output and error semantics |

Supporting artifacts:

| Artifact | Purpose |
|---|---|
| `schemas/document_spec-legacy-3.0.schema.json` | Validates the v3.5.9 library output (`extract_document_spec`) |
| `schemas/document_spec-legacy-cli.schema.json` | Validates the v3.5.9 `analyze_template.py` CLI output |
| `config/qa-policy.json` | System-owned required-check matrix |
| `config/error-codes.json` | Error code registry data |
| `examples/slot-id/cases.json` | Normative slot ID vectors |
| `examples/*/cases.json` | Positive and negative examples per schema |
| `tests/contracts/` | Automated contract tests |
| `reports/w0/` | Freeze report, gate review, acceptance report, issue list |

## 2. Precedence

When two documents disagree, the order is:

1. JSON Schema under `schemas/` (machine-enforced shape)
2. This contract set (normative semantics)
3. `SKILL.md` / `README.md` (human workflow description)
4. Architecture review report (rationale, not normative)

No implementation may weaken a MUST because a test is inconvenient. If a MUST cannot be met, it becomes an open issue and blocks the affected milestone.

## 3. Versioning and freeze

- Contract set version follows `MAJOR.MINOR.PATCH`.
- `MAJOR`: breaking field removal, type change, or semantic inversion.
- `MINOR`: additive optional field or new check/error code.
- `PATCH`: wording or example fixes with no semantic change.
- A frozen contract changes only through a **Change Proposal**:
  1. Owner writes the proposal in `reports/w0/issues.md` (or a new issue file).
  2. Affected owners co-sign.
  3. Agent 05 records the version bump.
  4. Agent 07 reviews for contradiction and bypass paths.
  5. Only then may code/tests follow.

**Code never leads the contract.** A field that is not in the contract is not implemented.

## 4. Ownership and write access

| Artifact | Sole writer |
|---|---|
| `contracts/01-slot-id.md`, `02-document-spec.md`, `schemas/document_spec-*.json` | Agent 01 |
| `contracts/03-*.md` (ContentPlan section), `schemas/content_plan-4.0.schema.json` | Agent 02 |
| `contracts/03-*.md` (FillPlan section), `schemas/fill_plan-4.0.schema.json` | Agent 03 |
| `contracts/04-*.md`, `schemas/qa_report-4.0.schema.json` | Agent 04 |
| `contracts/05-*.md`, `schemas/tool_envelope-4.0.schema.json`, `schemas/error_code_registry-4.0.schema.json`, `config/*` | Agent 05 |
| `contracts/README.md`, `contracts/compatibility-v3.5.9.md` | Agent 05 |
| `examples/**`, `tests/contracts/**` | Agent 06 |
| `reports/w0/07-gate-review.md` | Agent 07 |

No two agents may own the same schema file. `engine/__init__.py` remains a single-writer file held by Agent 05 and is **not** touched in W0.

## 5. W0 scope boundary

In scope: contracts, schemas, examples, contract tests, freeze/gate/acceptance reports.

Out of scope (must not be implemented in W0):

- DOCX analysis or filling logic for 4.0 fields
- Content generation
- QA gate runtime wiring
- Changes to any v3.5.9 file

The current `analyze_template.py` cannot emit a 4.0 DocumentSpec. That is recorded as open issue `OI-01` and is an alpha entry condition, not a reason to relax the 4.0 schema.

## 5.1 Change log (contract set)

| Version | Date | Change | Proposal |
|---|---|---|---|
| 4.0.0 | 2026-11-05 | W0 initial freeze | W0 |
| 4.1.0 | 2026-11-05 | `location_id` story grammar adds first/even page headers and footers; artifact `schema_version` stays `4.0` | `changes/CP-W2-001-location-story.md` |
| 4.2.0 | 2026-11-05 | `location_id` element set adds `sdt`; body/cell/header-level SDT content discovered as PROTECTED positions; `sdt_edit` stays false; frozen pending 07 post-implementation review | `changes/CP-W2-002-sdt-location.md` |

## 6. Compatibility statement

W0 adds files only. No v3.5.9 Python module, script, schema, or test is modified. The 186-test baseline is re-run unchanged as a gate. See `compatibility-v3.5.9.md`.
