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

- `sdt[i]`: the i-th (0-based) **direct `w:sdt` child** of the current container. Containers: `<w:body>`, a `w:sdtContent` (for nested SDT), or a table cell `tc`.
- Inside an SDT container, paragraphs/tables are indexed among its `w:sdtContent` **direct children**: `body.sdt[0].p[1]`, `body.sdt[0].tbl[0].r[2].c[1].p[0]`.
- Nested SDT: `body.sdt[0].sdt[1].p[0]`.
- A bare container address `body.sdt[0]` is a valid location (story + one element) and is used by protected regions.

Examples: `body.sdt[0].p[0]`, `body.tbl[1].r[0].c[0].sdt[0].p[0]` (cell-level SDT), `sec[0].header.p[0]` unchanged.

### 3.2 Discovery semantics (Contract 02)

1. The paragraph iterator MUST expose every `w:p` inside a body-level (or cell-level) `w:sdtContent`, with the locations above and `scope` derived from the enclosing story (body-level → `body`, header → `header_footer`, cell → `table`).
2. Every slot discovered inside a body/cell-level SDT MUST be `candidate_type: "control_or_field"`, hence `protection_status: "PROTECTED"` + `confirmation_tier: "PROTECTED_DO_NOT_TOUCH"` (existing Contract 02 §7 rules — no enum change).
3. `template.capabilities.sdt_edit` stays `false`. A FillPlan operation targeting any slot inside an SDT is rejected as `PROTECTED_SLOT_VIOLATION` (precondition `not_protected` already covers it — no executor change).
4. Protected regions: one entry per container with content, `kind: "sdt"`, `location_id: "body.sdt[i]"`, `severity: "blocking"`, evidence naming paragraph/table counts.
5. W3-3 behaviour is **kept**: compatibility capped at ≥L3, `SDT_BODY_UNSUPPORTED` retained with reworded detail ("discovered as protected positions; not fillable while sdt_edit=false"), high `SDT_BODY_ENUMERATION_GAP` warning becomes `SDT_BODY_PROTECTED_ONLY` (medium) once discovery works.

### 3.3 Identity, fingerprint, QA

- `slot_id`/`slot_key` canonical strings unchanged; new locations only add new IDs. Existing IDs stable (regression-tested).
- Fingerprint: `w:sdt`/`w:sdtContent` nodes already participate in `structural_hash` (element tree); `w:t` text already excluded, so protected hash/structural hash are stable across no-op fills. No fingerprint algorithm change.
- FORMAT/CONTENT QA will now also scan SDT paragraphs (broader coverage, no status-semantics change).

### 3.4 Out of scope (explicitly deferred)

Filling SDT content (in-place `w:sdtContent` text replacement with format inheritance) is a **capability** work item: requires a verified handler, `sdt_edit=true` flip, adversarial tests (locked SDTs, `w:dataBinding`, multi-run inside sdtContent) — W4 proposal, not this CP.

## 4. Impact

| Artifact | Change | Kind |
|---|---|---|
| `contracts/01-slot-id.md` §3 | element set adds `sdt`; indexing rules | additive |
| `contracts/02-document-spec.md` §7/§8 | SDT discovery semantics (rules above) | additive |
| `schemas/document_spec-4.0.schema.json` | `location_id` pattern adds `sdt` | additive regex |
| `schemas/fill_plan-4.0.schema.json` | `target.location_id` pattern adds `sdt` | additive regex |
| `template_intelligence/slot_id.py`, `tests/contracts/helpers.py` | `LOCATION_RE` widened | additive |
| `engine/ooxml_utils.py` | iterators expose body/cell-level SDT content with new locations | **frozen primitive** — full regression + 07 review |
| `engine/docx_parser.py` | `assess_template_compatibility_level` sees sdt paragraphs via same iterator (no code change expected; verify) | verify |
| `template_intelligence/spec_builder.py` | discovery as control_or_field/PROTECTED; regions kind=sdt; W3-3 rewording | change |
| `tests/contracts/test_slot_id.py`, `tests/test_sdt_detection.py` | grammar vectors; slots now discovered (assert PROTECTED, not `slots == []`) | strengthened |

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
7. Full suite green; contracts suite includes new vectors; 07 post-implementation review PASS recorded; 4.2.0 manifest hashes updated.

## 7. Approval

| Role | Verdict |
|---|---|
| Agent 05 (author) | proposed |
| Agent 07 (independent gate, proposal) | pending — see `reports/w2/`/`reports/w3/` gate record |
| Implementation (W3-4B) | **blocked until proposal gate = PASS** |
