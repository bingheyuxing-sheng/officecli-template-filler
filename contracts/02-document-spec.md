# Contract 02 — DocumentSpec 4.0

- Contract version: **1.2.0**
- Status: **FROZEN (4.2.0, 2026-11-05; CP-W2-001 + CP-W2-002)**
- Owner: Agent 01 (Template Intelligence)
- Consumers: Agent 02 (ContentPlan), Agent 03 (FillPlan executor), Agent 04 (Fidelity QA)
- Schema: `schemas/document_spec-4.0.schema.json` (draft 2020-12)
- Gate: Agent 07

## 1. Purpose

`DocumentSpec 4.0` is the only template-understanding artifact consumed by v4.0. It MUST answer, for every fillable position: what it is, whether it may be filled, what its style baseline is, how much room it has, and whether any structure around it is unsupported.

It MUST NOT contain generated business content. It describes the template only.

## 2. Producer and consumer rules

| Role | Rule |
|---|---|
| Producer (v4) | MUST emit `schema_version: "4.0"` and satisfy this schema |
| Producer (v3.5.9) | Emits 3.0; MUST satisfy `document_spec-legacy-3.0.schema.json`; MUST NOT claim 4.0 |
| Consumer (ContentPlan) | MAY read `slots`, `protected_regions`, `warnings`; MUST NOT infer slots from `structure` |
| Consumer (FillPlan executor) | MUST validate every `target.location_id` against `slots[].location_id` |
| Consumer (Fidelity QA) | MUST treat `fingerprint_ref` + `slots[]` as the only authorized-change mask |

**Open issue OI-01**: `scripts/analyze_template.py` currently emits a reduced summary and cannot produce 4.0. W0 validates the actual output against the legacy CLI schema; the 4.0 producer is a W1 deliverable and an alpha entry condition. The 4.0 schema is **not** relaxed to accommodate this.

## 3. Top-level object

| Field | Required | Type | Rule |
|---|---|---|---|
| `schema_version` | yes | string | const `"4.0"` |
| `template` | yes | object | §4 |
| `document` | yes | object | §5 |
| `structure` | yes | object | §6 |
| `slots` | yes | array | §7, may be empty |
| `protected_regions` | yes | array | §8, may be empty |
| `capacity_profiles` | yes | array | §9, may be empty |
| `layout_constraints` | yes | array | §10, may be empty |
| `fingerprint_ref` | yes | object | §11 |
| `unsupported_features` | yes | array | §12, may be empty |
| `warnings` | yes | array | §12, may be empty |
| `errors` | yes | array | §12, may be empty |
| legacy keys | optional | see §13 | Must remain valid if present |

Array fields MUST be present even when empty. Missing arrays are schema errors, because "no slots" and "analysis did not run" must never look alike.

## 4. `template`

| Field | Required | Rule |
|---|---|---|
| `template_id` | yes | `^T_[0-9a-f]{12}$`; derived from `template_sha256` (`T_` + first 12 hex) |
| `template_sha256` | yes | 64 lowercase hex |
| `parent_sha256` | optional | 64 lowercase hex; used for upgrade lineage |
| `compatibility` | yes | `L1` / `L2` / `L3` / `L4` |
| `protection_mode` | yes | `STRICT` (default) / `STANDARD` |
| `capabilities` | yes | eight required booleans, §4.1 |

### 4.1 `capabilities`

All eight keys are required:

`text_fill`, `table_fill`, `image_replace`, `nested_table`, `field_update`, `sdt_edit`, `smartart_edit`, `visual_render`.

`false` means the engine MUST refuse the corresponding operation and report it, not attempt it. A capability is `true` only when the engine has a verified handler and a test. It is not a marketing flag.

## 5. `document`

| Field | Required | Rule |
|---|---|---|
| `sections` | yes | array, minItems 1 |
| `page_size` | optional | string or null (`"A4"`, `"Letter"`, ...) |
| `orientation` | optional | string or null (`"portrait"`, `"landscape"`, `"mixed"`) |

`sections[]`:

| Field | Required |
|---|---|
| `section_index` | yes (integer ≥ 0) |
| `page_width_twips`, `page_height_twips` | optional (integer or null) |
| `orientation` | optional (integer or null; raw OOXML value) |
| `margins.{top,bottom,left,right}` | optional (integer twips or null) |
| `header_distance_twips`, `footer_distance_twips` | optional (integer or null) |

## 6. `structure`

`structure.paragraphs[]`: `location_id` (required), `scope` (required), `style_name`, `effective_sz_half_pt`, `font_east_asia`, `text_preview` (optional).

`structure.tables[]`: `table_id` (required), `scope` (required), `depth` (required integer ≥ 0), `rows`, `cols`, `headers[]`, `cell_type_counts{}`.

`structure.images[]`: `location_id` (required), `object_type` (required enum: `inline_blip`, `anchored_blip`, `vml`, `svg`, `chart`, `smartart`, `ole_object`), `rId`, `width_cm`, `height_cm`, `partname`, `content_type`, `ref_count`.

`structure` is an inventory. It MUST NOT be used to decide fillability; `slots` and `protected_regions` are authoritative.

## 7. `slots[]`

| Field | Required | Rule |
|---|---|---|
| `slot_id` | yes | Contract 01 grammar |
| `slot_key` | yes | 16 lowercase hex |
| `location_id` | yes | Contract 01 grammar |
| `scope` | yes | `body` / `table` / `header_footer` / `textbox` / `footnote` / `endnote` / `comment` |
| `candidate_type` | yes | `explicit_token` / `red_run_clue` / `internal_fact` / `control_or_field` |
| `matched_text` | yes | string; may be empty only per Contract 01 §11 |
| `span` | yes | `{start, end}` integers, `0 ≤ start < end`; for blank internal-fact slots the span of the label |
| `occurrence` | yes | integer ≥ 1 |
| `semantic_role` | yes | string or null |
| `style_reference` | optional | `{style_name, effective_sz_half_pt, font_east_asia}` |
| `capacity` | optional | §7.1 |
| `protection_status` | yes | `FILLABLE` / `CONDITIONAL` / `PROTECTED` |
| `confirmation_tier` | yes | `AUTO_DERIVE_OR_BIND` / `DEFAULT_FILL_WITH_NOTICE` / `MUST_ASK_USER` / `PROTECTED_DO_NOT_TOUCH` |

Consistency rules:

1. `protection_status: PROTECTED` ⟺ `confirmation_tier: PROTECTED_DO_NOT_TOUCH`. A mismatch is invalid.
2. `candidate_type: control_or_field` MUST be `PROTECTED`.
3. `candidate_type: internal_fact` MUST be `MUST_ASK_USER`.
4. `slot_id` MUST be unique within the document.
5. `matched_text` MUST appear at the declared span in the referenced location, or the slot is invalid per Contract 01 §8.

### 7.1 `capacity`

| Field | Required | Rule |
|---|---|---|
| `max_chars_per_line` | optional | integer ≥ 0 or null |
| `estimated_lines` | optional | integer ≥ 0 or null |
| `confidence` | yes | `low` / `medium` / `high` |
| `method` | yes | non-empty string naming the calculation |
| `hard_limit` | optional | `{kind: "explicit_charlimit" / "fixed_height_cell", value: integer ≥ 0}` or null |

Capacity is **evidence**, not an authority. A slot may be rejected for capacity only when `hard_limit` is present or the caller declared an explicit limit in FillPlan. Estimated capacity MUST NOT alone block an operation.

### 7.2 SDT discovery (CP-W2-002)

1. Every paragraph with non-whitespace text discovered inside a `w:sdt` container (body, header/footer story,
   table cell, or nested container; see Contract 01 §3.1) MUST be reported as a slot
   with `candidate_type: control_or_field`, `protection_status: PROTECTED` and
   `confirmation_tier: PROTECTED_DO_NOT_TOUCH`. The whole trimmed paragraph is the
   protected unit; no `explicit_token`, `red_run_clue` or `internal_fact` slot may be
   emitted inside SDT content. Empty or whitespace-only SDT paragraphs remain in
   `structure.paragraphs` (so the container is visible) but do not produce a slot:
   there is no protected text to name.
2. The same rule applies to paragraphs whose stable location hides the enclosing
   control (textbox paragraphs keep `txbx_p[i]` inside an SDT): they are still inside
   an SDT and MUST be `PROTECTED`.
3. `template.capabilities.sdt_edit` MUST stay `false` unless a verified in-place
   `w:sdtContent` handler and its tests exist. A FillPlan operation targeting such a
   slot is rejected as `PROTECTED_SLOT_VIOLATION` (Contract 03 §3.4).
4. Discovery MUST NOT change `location_id`/`slot_id` values for content outside SDT
   containers. Analysis stays deterministic across repeated runs.

## 8. `protected_regions[]`

| Field | Required | Rule |
|---|---|---|
| `region_id` | yes | `^PR_[0-9]{3,}$` |
| `kind` | yes | `fixed_title` / `header` / `footer` / `field` / `sdt` / `logo` / `stamp` / `repeated_header` / `other` |
| `location_id` | yes | Contract 01 grammar |
| `evidence` | yes | non-empty string (why this region is protected) |
| `severity` | optional | `blocking` / `warning`; default `blocking` |

Regions are absolute: an operation targeting a protected region MUST be rejected even if a slot exists there. Overlapping regions are allowed; the strictest severity wins.

### 8.1 `kind: "sdt"` semantics (CP-W2-002)

1. One region per SDT container with content, addressed by the container itself:
   `body.sdt[i]`, `sec[n].<hf>.sdt[i]`, or the cell form
   `body.tbl[r].c[c].sdt[i]` (Contract 01 §3.1).
2. `severity` MUST default to `blocking`; `evidence` MUST name the container location
   and the direct paragraph/table counts inside it.
3. Because region matching is prefix-based, the container region covers every slot
   discovered deeper inside it, including table-cell and nested-container paths.
   Exception: a textbox paragraph keeps its stable `txbx_p[i]` location, which is not
   a prefix extension of the SDT container; it is protected by the slot rule in §7.2.2
   (PROTECTED status), not by the container region. This exception is deliberate:
   re-addressing textboxes would change existing `slot_id` values.
4. Empty SDT containers are disclosed by analysis warnings but do not produce a
   region (there is no content to protect).

## 9. `capacity_profiles[]`

| Field | Required | Rule |
|---|---|---|
| `profile_id` | yes | `^CAP_[0-9]{3,}$` |
| `location_id` | yes | Contract 01 grammar |
| `available_width_twips` | yes | integer ≥ 0 |
| `available_height_twips` | optional | integer ≥ 0 or null |
| `effective_sz_half_pt` | optional | string or null |
| `confidence` | yes | `low` / `medium` / `high` |
| `method` | yes | non-empty string |

A profile with `confidence: low` MUST NOT produce a hard rejection.

## 10. `layout_constraints[]`

| Field | Required | Rule |
|---|---|---|
| `constraint_id` | yes | `^LC_[0-9]{3,}$` |
| `kind` | yes | `page_break` / `section_break` / `repeated_header` / `cant_split` / `floating_anchor` / `fixed_table_layout` / `other` |
| `location_id` | yes | Contract 01 grammar |
| `value` | optional | string / number / boolean / null |
| `source` | yes | non-empty string (`"template"` or an evidence reference) |

Constraints describe what must remain true after filling. They are checked by Fidelity QA, not by the filler.

## 11. `fingerprint_ref`

| Field | Required | Rule |
|---|---|---|
| `fingerprint_id` | yes | `^FP_[0-9]{3,}$` |
| `structural_hash` | yes | 64 lowercase hex |
| `style_hash` | yes | 64 lowercase hex |
| `protected_hash` | yes | 64 lowercase hex |
| `layout_hash` | yes | 64 lowercase hex |
| `baseline_path` | optional | string or null |

The four hashes are canonical, content-independent digests (excluding authorized slot text). `baseline_path` points to a persisted baseline for cross-run comparison. A fingerprint MUST NOT be a raw ZIP hash.

## 12. `unsupported_features[]`, `warnings[]`, `errors[]`

All three are arrays of objects:

- `unsupported_features`: `{code, detail, location_id?}`. `code` is a non-empty string (e.g. `SMARTART_EDIT_UNSUPPORTED`, `SLOT_LOCATION_UNRESOLVED`).
- `warnings`: `{code, severity, detail, location_id?}`; `severity` ∈ `low` / `medium` / `high`.
- `errors`: same shape. A non-empty `errors` array means the analysis is unusable for filling.

Rule: every unsupported structure that could affect filling MUST appear in `unsupported_features`. Silence is not evidence of support.

## 13. Legacy compatibility keys

When present, these keys MUST remain faithful to the v3.5.9 shape and are read-only for v4 consumers: `compatibility`, `sections`, `paragraphs`, `candidate_hits`, `table_profiles`, `image_profiles`.

They MUST NOT be used as the primary v4 input. `slots` replaces `candidate_hits`; `structure` replaces `paragraphs` / `table_profiles` / `image_profiles`.

## 14. Semantic validation beyond JSON Schema

The schema cannot express these; `tests/contracts/test_document_spec.py` MUST check them:

1. Unique `slot_id`; unique `region_id`; unique `profile_id`; unique `constraint_id`.
2. `slot.location_id` appears in `structure.paragraphs[].location_id` or `structure.tables[].table_id`.
3. `PROTECTED` ⟺ `PROTECTED_DO_NOT_TOUCH`.
4. `control_or_field` → `PROTECTED`; `internal_fact` → `MUST_ASK_USER`.
5. `template.template_id` equals `T_` + first 12 chars of `template_sha256`.
6. `template.parent_sha256`, when present, must differ from `template_sha256`.
7. `fingerprint_ref` hashes are 64 hex and not all zeros.
8. Empty `errors` array for any spec used by FillPlan; non-empty means `BLOCKED`.

## 15. Examples

`examples/document-spec/cases.json` contains: `minimal_valid`, `full_valid`, `missing_required`, `type_error`, `boundary_conflict`. The last case is schema-valid but semantically invalid (duplicate slot id) and must be rejected by §14 rule 1.

## 16. Change log

| Version | Change |
|---|---|
| 1.0.0 | Initial frozen contract (W0) |
| 1.1.0 | CP-W2-001: `location_id` values now include `sec[n].first_page_header`, `first_page_footer`, `even_page_header`, `even_page_footer`; no field added, artifact `schema_version` stays `"4.0"` |
| 1.2.0 | CP-W2-002: §7.2 SDT discovery (control_or_field → PROTECTED, no fillable token inside SDT, textbox ancestors included); §8.1 `kind: "sdt"` region semantics (one blocking container region with counts); `sdt_edit` stays `false`; no field added, artifact `schema_version` stays `"4.0"` |
