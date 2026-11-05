# W0 Contract Freeze Report — Agent 05

- Report ID: W0-FREEZE-05
- Contract set: **4.0.0**
- Freeze date: 2026-11-05
- Author: Agent 05 (Architecture & Integration)
- Independent gate: `reports/w0/07-gate-review.md`
- Decision: **FROZEN** (formal, not conditional)

## 1. Scope delivered

| Artifact | Count | Location |
|---|---|---|
| Contract documents | 6 (index + 5 contracts) + compatibility matrix | `contracts/` |
| JSON Schemas (4.0) | 6 | `schemas/` |
| Legacy compatibility Schemas | 2 | `schemas/` |
| System policy data | 2 | `config/` |
| Positive/negative examples | 6 case files | `examples/` |
| Contract tests | 11 files (2 support + 9 test modules), **70 tests** | `tests/contracts/` |
| Dev dependency manifest | 1 | `requirements-dev.txt` |

No v3.5.9 file was modified. `git status` shows only untracked additions; `git diff --name-only` is empty.

## 2. Frozen decisions

### D-01 Slot identity includes occurrence

The architecture review proposed:

```
sha256(template_sha256 | location_id | normalized_text)[:12]
```

W0 adds `occurrence` to the canonical string:

```
sha256(template_sha256 | location_id | normalized_text | occurrence)[:12]
```

Reason: the same token can appear twice in one paragraph (`{{姓名}} 与 {{姓名}}`). Without occurrence, both positions get the same id and violate uniqueness. The review's formula was underspecified, not wrong in principle.

### D-02 Collision handling is deterministic

12 hex (48 bits) is kept for readability. On collision, canonical strings are sorted lexicographically and suffixed `-c2`, `-c3`, …; the first keeps the bare id. Collision is a warning (`SLOT_ID_COLLISION_RESOLVED`), not a failure. Uniqueness within one spec is a blocking rule.

### D-03 `slot_key` enables template-upgrade lineage

`slot_key = sha256(location_id | normalized_text | occurrence)[:16]` is template-independent. It is never a fill target; it only maps old slots to new ones after a template upgrade. Ambiguity is reported, never guessed.

### D-04 DocumentSpec 4.0 is a superset, not a replacement

New required blocks (`template`, `document`, `structure`, `slots`, `protected_regions`, `capacity_profiles`, `layout_constraints`, `fingerprint_ref`, `unsupported_features`, `warnings`, `errors`) coexist with optional legacy keys (`compatibility`, `sections`, `paragraphs`, `candidate_hits`, `table_profiles`, `image_profiles`). This keeps `review_engine`'s dependency on `docx_parser` from breaking during migration.

Legacy output is validated by two explicit compatibility schemas:

- `document_spec-legacy-3.0.schema.json` for `extract_document_spec()`.
- `document_spec-legacy-cli.schema.json` for `analyze_template.py`.

The current CLI output passes the legacy CLI schema. It is **not** DocumentSpec 4.0. OI-01 records that gap; the 4.0 schema was not weakened to hide it.

### D-05 ContentPlan and FillPlan are strictly separated

- ContentPlan: sections, requirements, facts, sources, completeness. No DOCX operations.
- FillPlan: operations, targets, preconditions, baseline authorization, overflow. No prose requirements.
- There is no merged "payload" artifact, and no DocumentIR.

### D-06 Structure changes are denied in this contract version

FillPlan `allow_structure_change` is `const false`; `styles` and `page_setup` are `const "DENY"`. The operation set is limited to `replace_text`, `fill_paragraph`, `fill_cell`, `replace_image`. Overflow strategy is `const "REJECT"`; automatic font/margin shrinking is forbidden.

### D-07 QA policy is system-owned and bound to the task

`required_checks` must equal the set in `config/qa-policy.json`. To prevent a caller from selecting a weaker policy, QAReport 4.0 requires:

```
policy_source == task_mode + "/" + gate_mode
```

So a GENERATE/STRICT task cannot present a `REVIEW/REPLICA` report. The binding is checked by the contract tests; runtime enforcement is OI-03 (W1/W2).

### D-08 ToolEnvelope applies to new tools only

Existing v3.5.9 CLIs are not retrofitted in W0; their output shapes remain unchanged (OI-04). New v4 tools must use `tool_envelope-4.0.schema.json`.

### D-09 QA and delivery boundary

- `UNVERIFIED` can never be `PASSED`.
- `COMMIT` is allowed for `SUCCESS`, or for `UNVERIFIED` only with `data.qa_eligible: true` and an explicit `missing_checks` disclosure.
- STRICT policy requires `PASSED`; STANDARD may publish `UNVERIFIED` with disclosure. This is an intentional policy difference, not a bypass.

### D-10 Errors are registered, not renamed

Existing codes keep their v3.5.9 spelling. New codes declare severity, retryability, rollback requirement, human-intervention requirement, owner, message template and introduction version. Blocking codes are prohibited from being auto-retryable.

## 3. Cross-contract verification

| Check | Result |
|---|---|
| All 8 schemas are valid JSON Schema 2020-12 | 8/8 |
| Every schema has 5 example categories | 5/5 per schema |
| Valid examples pass their schema | 11/11 |
| Invalid examples fail their schema | 6/6 |
| Semantic-invalid examples pass schema but fail semantic rules | 5/5 |
| DocumentSpec ↔ ContentPlan slot references | pass |
| DocumentSpec ↔ FillPlan targets, baseline, fingerprint | pass |
| FillPlan ↔ ContentPlan fact/value_ref consistency | pass |
| QAReport ↔ qa-policy required sets | pass |
| QAReport ↔ policy_source binding | pass |
| ToolEnvelope ↔ error registry codes | pass |
| Slot ID vectors reproduce exactly | 5/5 |
| Legacy library output validates against 3.0 schema | pass |
| Legacy CLI output validates against CLI schema | pass |
| Legacy output rejected by 4.0 schema | pass (proves separation) |

## 4. Test evidence

| Suite | Command | Result |
|---|---|---|
| Contract tests | `py -3.15 -m unittest discover -s tests/contracts -t tests` | **70 passed** |
| Full suite | `py -3.15 -m unittest discover -s tests -p 'test_*.py'` | **256 passed** (186 baseline + 70 contract) |
| Environment | `jsonschema 4.26.0`, Python 3.15.0 | installed |

The 186 pre-existing tests pass unchanged. No test was modified.

## 5. Freeze manifest

SHA-256, first 16 hex (full digest can be recomputed with `Get-FileHash -Algorithm SHA256`):

| File | SHA-256 (16) |
|---|---|
| `contracts/README.md` | `0381C17EC62036F7` |
| `contracts/01-slot-id.md` | `5DFCB191C6E49FBB` |
| `contracts/02-document-spec.md` | `DC947418109BDD9A` |
| `contracts/03-content-fill-plan.md` | `C98A1730917634FF` |
| `contracts/04-qa-report.md` | `9F36349643D5613E` |
| `contracts/05-tool-envelope-error-codes.md` | `E67CD6175D0B014F` |
| `contracts/compatibility-v3.5.9.md` | `858D24A4C88FF5EE` |
| `schemas/document_spec-4.0.schema.json` | `0F8FB05D26790ABB` |
| `schemas/document_spec-legacy-3.0.schema.json` | `31175645BDE255CD` |
| `schemas/document_spec-legacy-cli.schema.json` | `8D00E4668B7EEBFB` |
| `schemas/content_plan-4.0.schema.json` | `EFC3712F86078AE7` |
| `schemas/fill_plan-4.0.schema.json` | `9CF7AC492CDE1796` |
| `schemas/qa_report-4.0.schema.json` | `B08D4EBFB5E88042` |
| `schemas/tool_envelope-4.0.schema.json` | `8D121C455849670B` |
| `schemas/error_code_registry-4.0.schema.json` | `94CA8D5C616B90D8` |
| `config/qa-policy.json` | `72B9A4EA2F9C8AF3` |
| `config/error-codes.json` | `3E58ACEF1E9B572D` |
| `examples/slot-id/cases.json` | `750FE072AA2467A0` |
| `examples/document-spec/cases.json` | `5A235A0640908183` |
| `examples/content-plan/cases.json` | `C35B2F4B959CDEC5` |
| `examples/fill-plan/cases.json` | `1DCFC36517EBF26C` |
| `examples/qa-report/cases.json` | `DC160D5049A5C4BE` |
| `examples/tool-envelope/cases.json` | `DD00CCB7924C4E4E` |
| `tests/contracts/*.py` (11 files) | see `07-gate-review.md` appendix |
| `requirements-dev.txt` | `6055265F529496ED` |

## 6. Change process after freeze

1. Owner writes a Change Proposal (issue id, field, reason, affected consumers).
2. Affected owners co-sign: DocumentSpec (01), plans (02/03), QA (04), integration (05).
3. Agent 07 reviews for contradiction and bypass paths.
4. Version bump: additive = MINOR, breaking = MAJOR.
5. Update manifest hashes in this report.
6. Code follows the contract, never the reverse.

## 7. Known gaps (carried forward)

See `reports/w0/issues.md`. Summary:

- `OI-01` **alpha blocker**: `analyze_template.py` cannot emit DocumentSpec 4.0.
- `OI-02` environment: no PyMuPDF / matplotlib / OCR; pixel QA and OCR must stay `UNVERIFIED`.
- `OI-03` W0 ships no runtime validators; contract tests use a reference checker.
- `OI-04` legacy CLIs do not emit ToolEnvelope.
- `OI-05` `logic_qa → workflow → qa_engine` dependency inversion.

Freeze decision: **FROZEN as 4.0.0**. The gaps above are implementation/alpha conditions, not contract defects, and none was removed by lowering a requirement.
