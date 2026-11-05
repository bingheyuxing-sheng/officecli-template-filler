# Change Proposal CP-W2-002 — Body-level SDT location grammar and protected discovery

- Proposal ID: CP-W2-002
- Contract set: 4.1.0 → **4.2.0** (MINOR, additive grammar; artifact `schema_version` stays `"4.0"`)
- Date: 2026-11-05
- Author: Agent 05 (Architecture & Integration)
- Gate: Agent 07 (mandatory before any code change; AGENTS §3.2)
- Related: audit P1-01, W2-I1, W3-3 (shipped fail-closed pre-scan, commit `ba22da8`), W3 task book item 4

## 1. Problem

A `w:sdt` directly under `<w:body>` (or inside a table cell) wrapping paragraphs/tables is invisible to python-docx's `doc.paragraphs`, so the v3.5.9 enumerator — which the whole v4 chain builds on — cannot address it. W3-3 made this *fail-closed* (compatibility capped at L3, `SDT_BODY_UNSUPPORTED` disclosed), but the content inside remains **undiscoverable**: no slots, no protected-region entries with valid locations, no way for a FillPlan to even name the position.

Real government/enterprise forms (W3-9 candidates C3/C6) commonly use body-level SDT content controls, so this blocks realistic template coverage.

## 2. Root cause and options

The location grammar (Contract 01 §3, extended by CP-W2-001) enumerates `p | tbl | r | c | txbx_p` but has no production for `sdt`. This is a contract-expression gap, not a mapping bug: no existing path can name a body-level SDT paragraph.

| Option | Verdict |
|---|---|
| A. Add `sdt[i]` path element; enumerator exposes SDT-wrapped content as **protected, addressable** positions | **Accepted.** Additive; keeps W3-3 disclosure; makes rejection precise instead of blind |
| B. Keep content undiscoverable, only disclose | Rejected. L3 cap + count is not a position; FillPlan/QA cannot bind to it; audit called this out |
| C. Make SDT slots fillable now | Rejected. No verified in-place SDT mutation handler exists; violates `sdt_edit=false` capability honesty and AGENTS §6.5 |

## 3. Decision (normative)

### 3.1 Grammar (Contract 01 §3)

```
element := "p" | "tbl" | "r" | "c" | "txbx_p" | "sdt"
```

- `sdt[i]`: the i-th (0-based) **direct `w:sdt` child** of the current container. Containers: `<w:body>`, a header/footer story root, a `w:sdtContent` (for nested SDT), or a table cell `tc`.
- **Story coverage (gate amendment B2):** containers are scanned in body AND header/footer stories (`sec[n].header.sdt[i].p[j]`, `sec[n].first_page_footer.sdt[i].p[0]`, ...) AND table cells. A header/footer body-level SDT must not remain a fail-open gap.
- Inside an SDT container, paragraphs/tables are indexed among its `w:sdtContent` **direct children only** (gate amendment B3): the traversal MUST NOT descend into `w:txbxContent` or nested `w:tbl` cell paragraphs from the container step — those are reached by their own path segments. This keeps the iterator's `id()`-based de-duplication (`engine/ooxml_utils.py:435-440`) from stealing textbox paragraphs and changing existing slot ids.
- Nested SDT: `body.sdt[0].sdt[1].p[0]`.
- A bare container address `body.sdt[0]` is a valid location (story + one element) and is used by protected regions.

Examples: `body.sdt[0].p[0]`, `body.tbl[1].r[0].c[0].sdt[0].p[0]` (cell-level SDT), `sec[0].header.sdt[0].p[0]`, `sec[1].even_page_footer.sdt[0].tbl[0].r[0].c[0].p[0]`; `sec[0].header.p[0]` unchanged.

### 3.2 Discovery semantics (Contract 02)

1. The paragraph iterator MUST expose every `w:p` inside a body-level (or cell-level) `w:sdtContent`, with the locations above and `scope` derived from the enclosing story (body-level → `body`, header → `header_footer`, cell → `table`).
2. Every slot discovered inside a body/cell-level SDT MUST be `candidate_type: "control_or_field"`, hence `protection_status: "PROTECTED"` + `confirmation_tier: "PROTECTED_DO_NOT_TOUCH"` (existing Contract 02 §7 rules — no enum change).
3. `template.capabilities.sdt_edit` stays `false`. A FillPlan operation targeting any slot inside an SDT is rejected as `PROTECTED_SLOT_VIOLATION` (precondition `not_protected` already covers it — no executor change).
4. Protected regions: one entry per container with content, `kind: "sdt"`, `location_id: "body.sdt[i]"`, `severity: "blocking"`, evidence naming paragraph/table counts.
5. W3-3 behaviour is **kept**: compatibility capped at ≥L3 and `SDT_BODY_UNSUPPORTED` retained with reworded detail ("discovered as protected positions; not fillable while sdt_edit=false"). Gate amendment B1: the warning rename to `SDT_BODY_PROTECTED_ONLY` (medium) applies **only to the discovery-success path**; a failed pre-scan (`scan_error`) keeps the high-severity `SDT_BODY_ENUMERATION_GAP` and `SDT_BODY_SCAN_INCOMPLETE` disclosure unchanged (fail-closed, `spec_builder.py:1161`).

### 3.3 Identity, fingerprint, QA

- `slot_id`/`slot_key` canonical strings unchanged; new locations only add new IDs. Existing IDs stable (regression-tested).
- Fingerprint: `w:sdt`/`w:sdtContent` nodes already participate in `structural_hash` (element tree); `w:t` text already excluded, so protected hash/structural hash are stable across no-op fills. No fingerprint algorithm change.
- FORMAT/CONTENT QA will now also scan SDT paragraphs (broader coverage, no status-semantics change).

### 3.4 Out of scope (explicitly deferred)

Filling SDT content (in-place `w:sdtContent` text replacement with format inheritance) is a **capability** work item: requires a verified handler, `sdt_edit=true` flip, adversarial tests (locked SDTs, `w:dataBinding`, multi-run inside sdtContent) — W4 proposal, not this CP.

## 4. Impact

| Artifact | Change | Kind |
|---|---|---|
| `contracts/01-slot-id.md` §3 | element set adds `sdt`; indexing rules; story coverage incl. header/footer; **and the "MUST match the v3.5.9 iterator" sentence is revised to "MUST match the v4 iterator, which is a superset of the v3.5.9 story set" (gate amendment B4)** | additive |
| `contracts/02-document-spec.md` §7/§8 | SDT discovery semantics (rules above) | additive |
| `schemas/document_spec-4.0.schema.json`, `schemas/fill_plan-4.0.schema.json` | **no edit required**: the location patterns already accept any `[a-z_]+` element name (gate review fact-check; the earlier "pattern adds sdt" claim was wrong) | none |
| `template_intelligence/slot_id.py`, `tests/contracts/helpers.py` | `LOCATION_RE` widened to name `sdt` explicitly (code-side grammar is stricter than the schema today) | additive |
| `engine/ooxml_utils.py` | iterators expose body/cell/header-level SDT content with new locations; direct-children-only, no txbxContent descent (B3) | **frozen primitive** — full regression + 07 review |
| `engine/docx_parser.py` | `assess_template_compatibility_level` sees sdt paragraphs via same iterator (no code change expected; verify) | verify |
| `template_intelligence/spec_builder.py` | discovery as control_or_field/PROTECTED; regions kind=sdt; W3-3 rewording with B1 split | change |
| `tests/contracts/test_slot_id.py`, `tests/test_sdt_detection.py` | grammar vectors; slots now discovered (assert PROTECTED, not `slots == []`); scan_error path keeps high warning | strengthened |

## 5. Compatibility

- MINOR: old documents validate; old locations/slot_ids unchanged; iterator only **adds** contexts.
- Risk: consumers that assumed "body.p[i] enumerates all paragraphs" — none verified in repo; full 428-test regression is the gate.
- `--spec-version 3` legacy output shape unchanged (summary keys fixed).

## 6. Test requirements (acceptance for W3-4B)

1. Grammar vectors: `body.sdt[0].p[0]`, `body.sdt[0].sdt[1].p[0]`, `body.tbl[0].r[0].c[0].sdt[0].p[0]`, `body.sdt[0]` accepted; `body.sdt[0]` bare paragraph path forms rejected.
2. W3-3 fixtures now yield PROTECTED slots with stable ids + `kind: sdt` blocking regions; compatibility still L3-capped.
3. FillPlan targeting an SDT slot → validator/executor `PROTECTED_SLOT_VIOLATION`, zero mutation, template bytes unchanged.
4. Locked (`w:lock="sdtContentLocked"`) and plain SDTs both discovered.
5. Slot-id stability: two runs identical; existing vectors unchanged (regression).
6. Fingerprint: structural hash equal before/after a no-op authorized fill elsewhere.
7. Header/footer story SDT (`sec[0].header.sdt[0].p[0]`) discovered, PROTECTED, region emitted (gate amendment B2).
8. Textbox paragraphs keep their existing `txbx_p[i]` locations and slot ids when a document also contains body-level SDT with a nested textbox (gate amendment B3: no txbxContent descent from the container step).
9. Scan-failure path still yields high `SDT_BODY_ENUMERATION_GAP` + `SDT_BODY_SCAN_INCOMPLETE` after the rename (gate amendment B1).
10. Full suite green; contracts suite includes new vectors; 07 post-implementation review PASS recorded; 4.2.0 manifest hashes updated.

## 7. Approval

| Role | Verdict |
|---|---|
| Agent 05 (author) | proposed; gate amendments B1-B4 + schema fact-check folded in (revision 2) |
| Agent 07 (independent gate, proposal) | **CONDITIONAL_PASS** (`reports/w3/07-cp-w2-002-gate-review.md`): implementation may start once B1-B4 are folded into this text (done in revision 2); implementation completion requires a second 07 review |
| Implementation (W3-4B) | unblocked (proposal gate satisfied); gated again by 07 post-implementation review before 4.2.0 freeze |

## 8. Revision log

| Rev | Change |
|---|---|
| 1 | Initial proposal (commit `143cb74`) |
| 2 | Gate review folded: B1 warning-rename split; B2 header/footer story coverage; B3 direct-children-only, no txbxContent descent; B4 Contract 01 iterator sentence revision; §4 corrected — schema location regexes already generic, no schema edit needed |
