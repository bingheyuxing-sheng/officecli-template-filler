# W2 Contract Change Manifest — CP-W2-001

- Contract set: 4.0.0 → **4.1.0** (MINOR, additive)
- Change: `location_id` story grammar adds first/even page headers and footers
- Approval: Agent 05 (author); Agent 07 gate `07-n1-gate-review.md`
- Artifact `schema_version`: remains `"4.0"`

> Historical manifest for contract set **4.1.0**. The current set is **4.2.0**; current hashes are in `reports/development/w3-04b-manifest.md`. The hashes below pin the reviewed 4.1.0 bytes, not the current files.

## Changed artifacts (SHA-256, first 16 hex)

| File | 4.1.0 hash |
|---|---|
| `contracts/README.md` | `3747A998954AC4B7` |
| `contracts/01-slot-id.md` | `6A573FEC4F261705` |
| `contracts/02-document-spec.md` | `8E7BE33DAE1AA727` |
| `contracts/changes/CP-W2-001-location-story.md` | `041E4421B46979DC` |
| `schemas/document_spec-4.0.schema.json` | `E04ED7A44016061A` |
| `schemas/fill_plan-4.0.schema.json` | `AC264CB272A7A85B` |
| `template_intelligence/slot_id.py` | `689A5BF4F27C61FE` |
| `template_intelligence/spec_builder.py` | `2D4962C501161B3A` |
| `qa/pipeline.py` | `AAFBDB75E7D52046` |
| `tests/contracts/helpers.py` | `E33E1ABB378DF6CA` |
| `tests/contracts/test_slot_id.py` | `B3C742403B0461C1` |
| `tests/test_e2e_v4.py` | `270E34EA7CD10997` |
| `examples/slot-id/cases.json` | `94F78B82A9FA2EA5` |
| `examples/document-spec/cases.json` | `EEDFF0B9521213F9` |

> The four hashes quoted by Agent 07 in the first review (`3747A998…`, `6A573FEC…`, `E04ED7A4…`, `AC264CB2…`) match the lead artifacts above. The remaining entries are the implementation/test files touched by the same change. Recompute with `Get-FileHash -Algorithm SHA256` before release; this manifest is the 4.1.0 baseline.

## Unchanged artifacts

All other W0 artifacts (`schemas/content_plan-4.0.schema.json`, `schemas/qa_report-4.0.schema.json`, `schemas/tool_envelope-4.0.schema.json`, `schemas/error_code_registry-4.0.schema.json`, `config/*`, `examples/*` except the new vector below, and the W0 contract tests other than the two listed) are unchanged.

## Example additions (follow-up 1)

- `examples/slot-id/cases.json`: new valid vector `first_page_header`:
  - inputs: `template_sha256 = "0"*64`, `location_id = "sec[0].first_page_header.p[0]"`, `matched_text = "{{页眉标题}}"`, `occurrence = 1`
  - expected: `slot_id = "S_d11f7ff0c600"`, `slot_key = "6a9ad32917a886ab"`
- `examples/document-spec/cases.json` `full_valid`: adds the same slot, its structure paragraph, and a fixed protected region `PR_003` at `sec[0].first_page_header.p[1]` (kind `header`, evidence explicitly naming `first_page_header`).

## Issue closure

- **W1-N1: CLOSED** by this proposal. The former `SLOT_STRUCTURE_UNSUPPORTED` fallback for first/even stories is removed for these four names; they are now first-class locations.
