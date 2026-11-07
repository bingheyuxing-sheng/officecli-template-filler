# W2-N1 Gate Review (re-review) — CP-W2-001 location stories

- Reviewer: Agent 07 (independent, read-only)
- Reviewed: `contracts/changes/CP-W2-001-location-story.md`, contract set 4.1.0
- Date: 2026-11-05
- Verdict: **PASS** (supersedes the previous CONDITIONAL_PASS)

## Re-verification evidence

1. **Example vector consistent.** `examples/slot-id/cases.json` `first_page_header` (`sec[0].first_page_header.p[0]`, `{{页眉标题}}`) reproduces `S_d11f7ff0c600` / `6a9ad32917a886ab` via `template_intelligence/slot_id.py` — independently recomputed, and the contract test iterates this case (70/70 pass).
2. **DocumentSpec example valid and non-weakening.** `full_valid` now has the structure paragraph, slot (`scope: header_footer`, `span 0-8`, `FILLABLE`, `AUTO_DERIVE_OR_BIND`) and region `PR_003` (`kind: header`, evidence naming `first_page_header`, `blocking`) at `p[1]`. Schema and semantic checks pass (`test_document_spec.py:12-17`); `boundary_conflict` still requires duplicate-`slot_id` rejection (`:26-30`).
3. **No rule relaxed.** Schema hashes are unchanged from the previous review (`document_spec E04ED7A4…`, `fill_plan AC264CB2…`); only data examples changed. `schema_version` stays `"4.0"`.
4. **Protected-region assertion added.** `test_e2e_v4.py::test_11` now asserts the fixed paragraph `sec[0].first_page_header.p[1]` is protected with `kind == "header"` and evidence containing `first_page_header` (`:348-354`), in addition to the slot not being protected.
5. **Manifest is real.** All 14 hashes in `reports/development/w2-01-contract-change-manifest.md` match `Get-FileHash` output (14/14 OK), including `contracts/02-document-spec.md 8E7BE33D…`, `CP 041E4421…`, `test_e2e_v4 270E34EA…`, `examples/slot-id 94F78B82…`, `examples/document-spec EEDFF0B9…`.
6. **Change record complete.** `contracts/02-document-spec.md` is 1.1.0 / FROZEN 4.1.0 with a §16 change-log entry for CP-W2-001; README and Contract 01 logs unchanged and correct; W1-N1 closed in the manifest.
7. **Other artifacts untouched.** `examples/content-plan C35B…`, `fill-plan 1DCF…`, `qa-report DC16…`, `tool-envelope DD00…` and the 9 other contract test files remain byte-identical to the 4.0.0 freeze manifest.

## Test results (Python 3.15)

| Suite | Result |
|---|---|
| `tests/contracts` | **70 OK** |
| `test_spec_builder.py` | **25 OK** |
| `test_e2e_v4.py` | **11 OK** |
| Full suite | **385 OK** (357 baseline + 28), 85s |

## Residual observations (non-blocking)

- No end-to-end case for `even_page_*`; grammar and protected-region mapping are covered only by code symmetry.
- `full_valid` lists the slot paragraph but not the fixed `p[1]` in `structure.paragraphs`; the producer would list both. No contract rule requires region locations to resolve, so this is example realism only.
- Manifest wording "`examples/*` except the new vector below" is imprecise (two example files changed); content is correct.
- `slot_id.py`, `spec_builder.py`, `qa/pipeline.py` remain untracked, so unrelated edits still cannot be excluded by git diff; the manifest hash pins their reviewed bytes.

## Freeze statement

All follow-ups from the previous review are closed and no blocking issue remains. **4.1.0 MAY be treated as frozen**, with the artifacts pinned by `reports/development/w2-01-contract-change-manifest.md`; release should recompute those hashes as the manifest itself instructs.
