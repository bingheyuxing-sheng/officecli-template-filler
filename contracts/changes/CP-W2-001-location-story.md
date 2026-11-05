# Change Proposal CP-W2-001 — Location stories for first/even page headers and footers

- Proposal ID: CP-W2-001
- Contract set: 4.0.0 → **4.1.0** (MINOR, additive)
- Date: 2026-11-05
- Author: Agent 05 (Architecture & Integration)
- Reviewer: Agent 07 (read-only gate)
- Related issue: W1-N1

## 1. Problem

`location_id` (Contract 01 §3) accepts only:

```
sec[n].header | sec[n].footer
```

The v3.5.9 all-story iterator and `DocumentSpec 4.0` producer also encounter
`first_page_header`, `first_page_footer`, `even_page_header`, `even_page_footer`.
Those stories are valid OOXML parts, but the grammar cannot express them.

Observed consequences:

- The producer filters them out (`template_intelligence/spec_builder.py`, previous
  lines with `if name not in ("header", "footer"): continue`).
- Any content there is reported as `SLOT_STRUCTURE_UNSUPPORTED`, even when the
  engine can safely read and write it.
- FillPlan cannot reference the target story.
- QA cannot distinguish the three header variants in a location string.

## 2. Root cause

This is **not** an implementation mapping defect. The current grammar has no
production for those story names, and adding a private field to the payload
would violate Contract 02's closed object (`additionalProperties: false`) and
make the location non-portable.

## 3. Options considered

| Option | Result |
|---|---|
| A. Extend `location_id` with the four additional story names | Accepted. Additive; existing IDs remain valid; no payload field added. |
| B. Keep 4.0.0 and mark first/even headers permanently unsupported | Rejected. The engine already traverses and can fill these stories; declaring them unsupported would be a capability regression. |
| C. Add a private `story_kind` field outside `location_id` | Rejected. Two sources of truth for the same position; breaks FillPlan targeting and fingerprint baselines. |

## 4. Decision

**Option A — MINOR contract change, version 4.1.0.**

The artifact field `schema_version` remains `"4.0"`; this is a contract-language
extension, not a new artifact format. Existing 4.0 documents and slots stay
valid, so no consumer migration is required.

### Normative grammar

```
story := "body" | "footnotes" | "endnotes" | "comments"
       | "sec[" n "].header"
       | "sec[" n "].footer"
       | "sec[" n "].first_page_header"
       | "sec[" n "].first_page_footer"
       | "sec[" n "].even_page_header"
       | "sec[" n "].even_page_footer"
```

Examples:

```
sec[1].first_page_header.p[0]
sec[0].even_page_footer.tbl[0].r[1].c[0].p[0]
```

## 5. Impact

| Area | Change |
|---|---|
| Contract 01 | Grammar and examples extended; version 1.1.0 |
| Contract 02 | No field change; `location_id` values now include the extended stories |
| `schemas/document_spec-4.0.schema.json` | `location_id` regex widened (additive) |
| `schemas/fill_plan-4.0.schema.json` | `target.location_id` regex widened (additive) |
| `template_intelligence/slot_id.py` | `LOCATION_RE` widened |
| `template_intelligence/spec_builder.py` | No longer filters first/even stories; protected-region kind maps to `header` / `footer` with the story name in `evidence` |
| `tests/contracts/helpers.py` | Test grammar mirror widened |
| Existing slots | Unchanged IDs and values (no canonical-string format change) |
| `schema_version` | Stays `"4.0"` |

## 6. Compatibility

- Old IDs remain byte-identical: the canonical string format is unchanged.
- Old documents remain valid: the regex only accepts more values.
- No public Python symbol is renamed.
- 186 v3.5.9 tests and 70 W0 contract tests are re-run as the gate.

## 7. Test requirements

1. Grammar accepts `sec[n].first_page_header.p[0]` and `sec[n].even_page_footer...`.
2. Grammar still rejects malformed forms.
3. Producer emits `slots` for a first-page header token and a `protected_regions`
   entry of kind `header` with evidence naming the story.
4. End-to-end fill of a first-page header slot, with the template unchanged.
5. Fingerprint and QA accept the extended location.

## 8. Approval

| Role | Verdict |
|---|---|
| Agent 05 (author) | APPROVED for 4.1.0 |
| Agent 07 (independent gate) | see `reports/w2/07-n1-gate-review.md` |

No frozen 4.0.0 file is edited silently: the previous versions and their hashes
remain recorded in `reports/w0/05-contract-freeze-report.md`; this proposal is
the formal change record.
