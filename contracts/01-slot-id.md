# Contract 01 — Slot ID Specification

- Contract version: **1.2.0**
- Status: **FROZEN (4.2.0, 2026-11-05; CP-W2-001 + CP-W2-002)**
- Owner: Agent 01 (Template Intelligence)
- Co-sign: Agent 02, Agent 03, Agent 04
- Gate: Agent 07

## 1. Purpose

A slot is a fillable position identified by the template analysis. `slot_id` is its stable, deterministic identity. It MUST survive repeated analysis of the same template on any machine, and it MUST NOT change because of run order, Python version, locale, or hash randomization.

`slot_id` identifies **a position in a template version**, not a business meaning. Two different templates never share a `slot_id` namespace.

## 2. Inputs

Every slot MUST carry these four inputs:

| Input | Type | Rule |
|---|---|---|
| `template_sha256` | string | Lowercase hex, exactly 64 chars; SHA-256 of the template file bytes |
| `location_id` | string | OOXML path per §3 |
| `matched_text` | string | The exact placeholder text found at the location (may be empty only for blank internal-fact slots) |
| `occurrence` | integer | 1-based index among identical `(location_id, normalized_text)` matches, ordered by span start ascending |

## 3. Location grammar

```
location_id := story ( "." element "[" index "]" )*
story       := "body" | "footnotes" | "endnotes" | "comments"
             | "sec[" n "].header"
             | "sec[" n "].footer"
             | "sec[" n "].first_page_header"
             | "sec[" n "].first_page_footer"
             | "sec[" n "].even_page_header"
             | "sec[" n "].even_page_footer"
element     := "p" | "tbl" | "r" | "c" | "txbx_p" | "sdt"
index       := 0-based non-negative integer
```

Examples: `body.p[3]`, `body.tbl[1].r[2].c[1].p[0]`, `sec[1].header.p[0]`,
`sec[1].first_page_header.p[0]`, `sec[0].even_page_footer.tbl[0].r[1].c[0].p[0]`,
`footnotes.p[4]`, `body.sdt[0].p[0]`, `body.tbl[0].r[0].c[0].sdt[0].p[0]`,
`sec[0].header.sdt[0].p[0]`, `body.sdt[0].sdt[1].p[0]`.

### 3.1 `sdt` element (CP-W2-002)

- `sdt[i]` addresses the i-th (0-based) **direct `w:sdt` child** of the current container.
- Containers: `<w:body>`, a header/footer story root (`w:hdr` / `w:ftr`), a table cell
  `w:tc`, and a `w:sdtContent` element (for nested content controls).
- Paragraphs and tables inside a container are indexed **only among direct
  `w:sdtContent` children**. The traversal MUST NOT descend into `w:txbxContent` from
  the container step: textbox paragraphs keep their `txbx_p[i]` locations under the
  enclosing story so that existing ids are not stolen by de-duplication. Nested tables
  are reached through their own `tbl/r/c` segments.
- A nested control is addressed container-relative: `body.sdt[0].sdt[1].p[0]`.
- A bare container address (`body.sdt[0]`, `sec[0].header.sdt[0]`,
  `body.tbl[0].r[0].c[0].sdt[0]`) is a valid `location_id` and is used by
  `protected_regions`.
- Content inside an SDT is **protected**, never a fillable slot, while
  `template.capabilities.sdt_edit` is `false` (Contract 02 §7).

The grammar MUST match the `location_id` values produced by the v4 iterator
`iter_all_document_paragraphs_with_Wait_context()`, which is a **superset** of the
v3.5.9 story set (body / nested tables / headers / footers / textboxes / footnotes /
endnotes / comments) and additionally exposes body, header/footer, cell and nested
SDT content. No parallel addressing scheme is permitted.

## 4. Normalization of `matched_text`

Apply, in order:

1. Unicode **NFKC** normalization.
2. Replace `\r\n` and `\r` with `\n`.
3. Replace every run of whitespace (including full-width space U+3000 after NFKC) with a single ASCII space `U+0020`.
4. Strip leading and trailing spaces.
5. **No** case folding, no punctuation rewriting, no token-marker removal.

`{{项目名称}}` and `  {{项目名称}}  ` normalize to the same text. `{{ProjectName}}` and `{{projectname}}` do **not**.

## 5. Canonical string and IDs

```
canonical_slot_id := "v1|" + template_sha256 + "|" + location_id + "|" + normalized_text + "|" + occurrence
slot_id           := "S_" + lowercase_hex( sha256_utf8(canonical_slot_id) )[0:12]

canonical_slot_key := "v1|" + location_id + "|" + normalized_text + "|" + occurrence
slot_key           := lowercase_hex( sha256_utf8(canonical_slot_key) )[0:16]
```

Rules:

- `slot_id` MUST use `hashlib.sha256`; `hash()`, `uuid`, timestamps, `random`, and locale-dependent functions are forbidden.
- `slot_key` is version-independent: it stays the same when the template content changes but the position and text do not. It is used only for template-upgrade lineage, never as a fill target.
- Every slot object in DocumentSpec 4.0 MUST carry both `slot_id` and `slot_key`.

Grammar:

```
slot_id  =~ ^S_[0-9a-f]{12}(-c[2-9][0-9]*)?$
slot_key =~ ^[0-9a-f]{16}$
```

## 6. Occurrence

`occurrence` disambiguates identical text at the same location.

- It is 1-based.
- It is assigned by sorting all matches with the same `(location_id, normalized_text)` by **span start ascending**; ties (equal spans cannot occur because spans are distinct character ranges) use document order.
- Removing the first occurrence renumbers later ones. This is acceptable: occurrence is part of a template analysis run, not a durable business key. Consumers MUST reference `slot_id`, never `(location_id, occurrence)` directly.

## 7. Uniqueness and collisions

- Within one DocumentSpec, `slot_id` MUST be unique. A duplicate is a **blocking analysis error** `SLOT_ID_CONFLICT`; analysis MUST fail rather than silently renumber.
- A 12-hex truncation can collide across different canonical strings. On collision, resolve deterministically by sorting the colliding canonical strings lexicographically and appending `-c2`, `-c3`, ...; the first keeps the bare form. Emit warning `SLOT_ID_COLLISION_RESOLVED` with both canonical strings.
- Collision resolution MUST be reproducible across runs; it MUST NOT depend on dict iteration order.

## 8. Invalidation

A slot becomes invalid when any of the following is true:

| Condition | Code |
|---|---|
| `location_id` no longer resolves in the current package | `SLOT_LOCATION_UNRESOLVED` |
| The template SHA-256 differs from the slot's namespace | `SLOT_TEMPLATE_MISMATCH` |
| `matched_text` no longer exists at the location | `SLOT_TEXT_MISSING` |
| The slot sits inside a structure that became unsupported (e.g. new SDT) | `SLOT_STRUCTURE_UNSUPPORTED` |

Invalid slots:

1. MUST NOT appear in `DocumentSpec.slots`.
2. MUST appear in `DocumentSpec.unsupported_features` with `{code, location_id, detail}`.
3. MUST produce a warning with the same code and location.

An invalid slot MUST NOT be silently dropped without evidence.

## 9. Template upgrade and lineage

- A new template file produces a new `template_sha256`, therefore a new `slot_id` namespace. Old IDs MUST NOT be reused for new content.
- `slot_key` enables lineage: a v4 producer **MAY** emit `template.parent_sha256` and a `lineage` map in the analysis report (not in `DocumentSpec.slots`).
- Lineage mapping rules:
  - Exactly one old and one new slot share a `slot_key` → map them.
  - More than one → `SLOT_LINEAGE_AMBIGUOUS`; no automatic mapping.
  - None → `SLOT_LINEAGE_UNRESOLVED`; treat as new slot.
- Lineage is advisory. It MUST NOT be used to fill an old slot into a new template without a fresh DocumentSpec.

## 10. Conformance vectors

Normative vectors live in `examples/slot-id/cases.json`. Fixed vectors for `template_sha256 = "0"*64`:

| Case | Location | Text | Occurrence | Expected |
|---|---|---|---|---|
| basic | `body.p[0]` | `{{项目名称}}` | 1 | `S_d6df35f1e6cd`, key `57c748583854c867` |
| whitespace | `body.p[0]` | `  {{项目名称}}  ` | 1 | same as basic |
| occurrence | `body.p[0]` | `{{项目名称}}` | 2 | `S_850805ac6187` |
| upgrade | `body.p[0]` | `{{项目名称}}` | 1 | `S_38c98af8fe17` with template `"1"*64`, same key |
| table | `body.tbl[1].r[2].c[1].p[0]` | `【合计金额】` | 1 | `S_42824f695c11`, key `b1f98c512b1f670e` |

## 11. Invalid inputs

| Input | Result |
|---|---|
| `occurrence = 0` or negative | Reject (`SLOT_OCCURRENCE_INVALID`) |
| `template_sha256` uppercase or length ≠ 64 | Reject (`SLOT_TEMPLATE_SHA_INVALID`) |
| `location_id` not matching §3 | Reject (`SLOT_LOCATION_INVALID`) |
| Empty normalized text with no internal-fact evidence | Reject (`SLOT_TEXT_EMPTY_UNEVIDENCED`) |
| Duplicate `slot_id` in one spec | Analysis fails (`SLOT_ID_CONFLICT`) |

Blank internal-fact slots (负责人/联系电话/内部编号) are allowed to have empty `matched_text` **only** when the analysis also records `candidate_type: "internal_fact"` and the label in `matched_text` (the label itself is the matched text; the value is empty). An empty `matched_text` with no label is invalid.

## 11.1 Change log

| Version | Change |
|---|---|
| 1.0.0 | W0 initial freeze |
| 1.1.0 | CP-W2-001: story grammar adds `first_page_header`, `first_page_footer`, `even_page_header`, `even_page_footer`; canonical string format unchanged |
| 1.2.0 | CP-W2-002: element set adds `sdt`; container/direct-children rules for body, header/footer, cell and nested SDT; bare container address accepted; canonical string format unchanged; iterator conformance sentence revised to the v4 superset (gate amendment B4) |

## 12. Conformance tests

`tests/contracts/test_slot_id.py` MUST:

1. Reproduce every vector in `examples/slot-id/cases.json` with a reference implementation.
2. Prove whitespace normalization and occurrence separation.
3. Prove template upgrade changes `slot_id` but preserves `slot_key`.
4. Prove grammar acceptance/rejection.
5. Prove collision suffix ordering is deterministic.

No production implementation is delivered in W0; the test file is the executable form of this contract.
