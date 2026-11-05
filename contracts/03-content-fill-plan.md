# Contract 03 — ContentPlan / FillPlan

- Contract version: **1.0.0**
- Status: **FROZEN (W0, 2026-11-05)**
- Owners: Agent 02 (ContentPlan), Agent 03 (FillPlan)
- Schemas: `schemas/content_plan-4.0.schema.json`, `schemas/fill_plan-4.0.schema.json`
- Gate: Agent 07

## 1. Separation rule

| Artifact | Answers | MUST NOT contain |
|---|---|---|
| **ContentPlan** | What must be written, for which section, from which sources, against which slots | DOCX locations deeper than `slot_id`, operation types, font/style instructions |
| **FillPlan** | Which slot gets which value, in which order, under which preconditions | Prose requirements, unsourced content, new sections/tables |

A ContentPlan without a FillPlan is a plan. A FillPlan without a ContentPlan is allowed only for pure token replacement, where every `source_ref` is `"USER_INPUT"` or a fact id.

The two artifacts MUST NOT be merged. Merging reintroduces the "content and layout decisions in one blob" problem this contract exists to prevent.

## 2. ContentPlan 4.0

### 2.1 Top-level

| Field | Required | Rule |
|---|---|---|
| `schema_version` | yes | const `"4.0"` |
| `plan_id` | yes | `^CP_[0-9A-Za-z_-]{1,32}$` |
| `template_id` | yes | `^T_[0-9a-f]{12}$`; must match the DocumentSpec used |
| `sections` | yes | array, minItems 1 |
| `facts` | yes | array, may be empty |
| `completeness` | yes | §2.4 |
| `warnings` | optional | array of `{code, detail}` |

### 2.2 `sections[]`

| Field | Required | Rule |
|---|---|---|
| `section_id` | yes | `^SEC_[0-9A-Za-z_-]{1,32}$`; unique |
| `purpose` | yes | non-empty string |
| `target_slots` | yes | array of `slot_id`, minItems 1, unique |
| `requirements.must_include` | optional | array of strings |
| `requirements.target_length` | optional | `{min ≥ 0, max ≥ min}` or null |
| `requirements.min_sources` | optional | integer ≥ 0 |
| `source_refs` | optional | array of non-empty strings |
| `fact_refs` | optional | array of `fact_id` |

Rules:

1. Every `target_slots` entry MUST exist in the DocumentSpec.
2. A slot MUST NOT be targeted by two sections with contradicting `target_length` or `must_include` requirements.
3. `target_length` is a planning target. It MUST NOT be interpreted as authorization to change template formatting.

### 2.3 `facts[]` (SSOT)

| Field | Required | Rule |
|---|---|---|
| `fact_id` | yes | `^F_[0-9A-Za-z_-]{1,32}$`; unique |
| `label` | yes | non-empty string |
| `value` | yes | string or number |
| `unit` | yes | non-empty string; `"none"` when dimensionless |
| `source` | yes | non-empty string; URL, file reference, or `UNVERIFIED` / `MODEL_GENERATED` |
| `verification_status` | yes | `VERIFIED` / `UNVERIFIED` / `MODEL_GENERATED` |
| `used_by_slots` | yes | array of `slot_id`, may be empty |

Rules:

1. A fact with `source: "UNVERIFIED"` or `"MODEL_GENERATED"` MUST have `verification_status` equal to that value, not `VERIFIED`.
2. A slot that receives a value MUST be listed in exactly one fact's `used_by_slots` or be marked literal by FillPlan (`value_ref: null`).
3. Numeric aggregation MUST use the existing `ssot_engine` Decimal rules; this contract does not redefine arithmetic.

### 2.4 `completeness`

| Field | Required | Rule |
|---|---|---|
| `required_slots` | yes | array of `slot_id` |
| `optional_slots` | yes | array of `slot_id` |
| `allow_missing` | yes | array of `{slot_id, reason}` |

Rules: `required_slots` and `optional_slots` are disjoint; `required_slots` ⊆ DocumentSpec slots; every `allow_missing.slot_id` MUST be a required slot and carry a non-empty reason. A required slot missing from FillPlan with no `allow_missing` entry is a blocking error.

## 3. FillPlan 4.0

### 3.1 Top-level

| Field | Required | Rule |
|---|---|---|
| `schema_version` | yes | const `"4.0"` |
| `task_id` | yes | `^TASK_[0-9A-Za-z_-]{1,64}$` |
| `template_id` | yes | must match DocumentSpec |
| `mode` | yes | `STRICT` / `STANDARD` |
| `baseline` | yes | §3.2 |
| `operations` | yes | array, minItems 1 |
| `global_policy` | yes | §3.5 |
| `warnings` | optional | array |

### 3.2 `baseline`

| Field | Required | Rule |
|---|---|---|
| `template_sha256` | yes | 64 lowercase hex; must match DocumentSpec |
| `spec_schema_version` | yes | const `"4.0"` |
| `fingerprint_id` | yes | must match `DocumentSpec.fingerprint_ref.fingerprint_id` |
| `allowed_slot_ids` | yes | array of slot ids; the only positions whose content may change |

`allowed_slot_ids` is the authorization mask. It MUST be a subset of DocumentSpec slots and a superset of every `operations[].slot_id`. The executor MUST reject any operation whose slot is not in this list.

### 3.3 `operations[]`

| Field | Required | Rule |
|---|---|---|
| `op_id` | yes | `^OP_[0-9A-Za-z_-]{1,32}$`; unique |
| `sequence` | yes | integer ≥ 1; unique; execution order is ascending |
| `type` | yes | `replace_text` / `fill_paragraph` / `fill_cell` / `replace_image` |
| `slot_id` | yes | must exist in DocumentSpec and in `baseline.allowed_slot_ids` |
| `target.location_id` | yes | must equal the slot's `location_id` |
| `target.table_id` | conditional | required for `fill_cell` |
| `target.row`, `target.col` | conditional | required for `fill_cell`, integers ≥ 0 |
| `target.image_role` | conditional | required for `replace_image`: `logo` / `stamp` / `qr` / `illustration` / `photo` |
| `source_ref` | yes | non-empty string; fact id or `USER_INPUT` |
| `value` | conditional | required for `replace_text` / `fill_paragraph` / `fill_cell`; for `replace_image` it is an absolute image path |
| `value_ref` | conditional | `fact_id` or null; if present, `value` MUST be absent or equal the fact value |
| `policy` | yes | const `"STRICT"` |
| `preconditions` | yes | array, minItems 1, unique, from §3.4 |
| `depends_on` | optional | array of `op_id`; must not form a cycle |
| `overflow` | yes | §3.6 |

### 3.4 Preconditions

Allowed values:

`slot_exists`, `not_protected`, `capacity_ok`, `source_verified`, `template_sha_match`.

Rules:

1. `STRICT` operations MUST include `slot_exists`, `not_protected`, `template_sha_match`.
2. `fill_cell` MUST include `capacity_ok` when the slot has a `hard_limit`.
3. `source_verified` is required when `source_ref` is a fact with `verification_status` ≠ `VERIFIED`.
4. The executor MUST evaluate every precondition before mutation; an unmet precondition is `BLOCKED`, not a warning.
5. `not_protected` MUST evaluate **both** the slot's `protection_status` and every `DocumentSpec.protected_regions` entry whose `location_id` is the target location or an ancestor prefix of it. A fillable slot inside a protected region is still protected; the region wins.

### 3.5 `global_policy`

| Field | Required | Rule |
|---|---|---|
| `allow_structure_change` | yes | const `false` in this contract version |
| `deny_operations` | yes | array from `modify_page_margin`, `modify_section_properties`, `modify_global_styles`, `rebuild_table`, `move_existing_image`, `delete_protected_content`, `insert_row`, `insert_paragraph`, `merge_cells` |
| `styles` | yes | const `"DENY"` |
| `page_setup` | yes | const `"DENY"` |

`allow_structure_change: true` is reserved for a future contract version. A FillPlan containing it is invalid today.

### 3.6 `overflow`

| Field | Required | Rule |
|---|---|---|
| `measured_chars` | yes | integer ≥ 0 |
| `limit_source` | yes | `explicit_charlimit` / `fixed_height_cell` / `none` |
| `limit_value` | conditional | integer ≥ 0 when `limit_source` ≠ `none`; null otherwise |
| `strategy` | yes | const `"REJECT"` |

Hard rules:

1. Overflow MUST be decided before mutation.
2. When `measured_chars > limit_value`, the operation MUST be rejected with `CAPACITY_EXCEEDED`.
3. The engine MUST NOT shrink font size, change margins, reduce spacing, rebuild a table, or remove content to make text fit.
4. The only recovery is: Agent produces a shorter content and a new FillPlan.

### 3.7 Execution order

The executor processes operations by ascending `sequence`. `depends_on` may only point to lower sequences. A dependency on a failed operation fails the dependent operation. The executor MUST NOT reorder operations by type; type batching is forbidden because it can change pagination semantics.

### 3.8 Write boundary and ledger

1. The executor MUST write only to the transaction staging path (`tx.stage()`). The final delivery path MUST NOT appear in FillPlan or be written directly.
2. Every operation MUST produce a `fill_ledger` record: `{op_id, slot_id, location_id, source_ref, value_sha256, result, before_text_sha256, after_text_sha256}`.
3. A failed operation MUST be recorded with its error code; the ledger MUST NOT omit failed operations.
4. QA reads the committed artifact plus the ledger; it MUST NOT trust an in-memory result object.

## 4. Forbidden patterns (both artifacts)

| Pattern | Verdict |
|---|---|
| FillPlan operation with no `source_ref` | Reject (`SOURCE_REF_MISSING`) |
| FillPlan op on a `PROTECTED` slot | Reject (`PROTECTED_SLOT_VIOLATION`) |
| FillPlan op outside `allowed_slot_ids` | Reject (`UNAUTHORIZED_SLOT_TARGET`) |
| FillPlan with `allow_structure_change: true` | Invalid schema |
| FillPlan with unknown `type` | Invalid schema |
| ContentPlan targeting a slot that does not exist | Reject (`UNKNOWN_SLOT`) |
| ContentPlan fact with no source | Reject (`FACT_SOURCE_MISSING`) |
| Any automatic font/size/margin correction for overflow | Reject (`FORMAT_REPAIR_FORBIDDEN`) |
| ContentPlan containing `value` for a slot not in `target_slots` | Reject (`PLAN_SLOT_MISMATCH`) |

## 5. Producer / consumer compatibility

| Producer | Consumer | Requirement |
|---|---|---|
| Agent (LLM) | ContentPlan | MUST declare facts and sources; MUST NOT invent numeric values |
| ContentPlan | FillPlan | Every targeted slot with a fact MUST become an operation with `value_ref` |
| FillPlan | Executor | Must pass schema + §3 rules + DocumentSpec cross-validation |
| Executor | QAReport | Must record every op result in `fill_ledger`; QA reads ledger + artifact |

## 6. Examples

- `examples/content-plan/cases.json`: `minimal_valid`, `full_valid`, `missing_required`, `type_error`, `boundary_conflict` (fact references an unknown slot).
- `examples/fill-plan/cases.json`: `minimal_valid`, `full_valid`, `missing_required`, `type_error`, `boundary_conflict` (duplicate sequence; `allow_structure_change: true`).

## 7. Change log

| Version | Change |
|---|---|
| 1.0.0 | Initial frozen contract (W0); structure changes denied in STRICT |
