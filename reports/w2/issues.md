# W2 Issue Register

- Version: 1.0
- Date: 2026-11-05
- Rule: closed items stay listed with their resolution.

| ID | Severity | Status | Owner | Summary |
|---|---|---|---|---|
| W1-N1 | High | **CLOSED** | Agent 05 + 01 | First/even page header/footer location grammar; CP-W2-001, 4.1.0, Agent 07 PASS |
| W2-I1 | High | OPEN | Agent 01 + 05 | Body-level `w:sdt` wrapping a paragraph is invisible to `doc.paragraphs`; no slot/protected region. Needs a future location-grammar contract change. |
| W2-I2 | Medium | OPEN (environment) | Agent 04 | PyMuPDF/OCR/matplotlib unavailable; pixel/OCR/chart checks stay UNVERIFIED |
| W2-I3 | Low | OPEN | Agent 05 | Legacy CLIs do not emit ToolEnvelope 4.0 |
| W2-I4 | Low | OPEN (docs) | Project owner | AGENTS.md still names 4.0.0 as the frozen contract baseline; current set is 4.1.0 |
| W2-I5 | Low | OPEN (test fixture) | Agent 06 | class_04 relative image path vs CLI absolute-path contract (test resolves it) |
| W2-I6 | Process | **CLOSED** | Orchestrator | Earlier parallel writes on one worktree violated AGENTS §4.5; remediated by stopping parallel writes and re-running independent review/fixtures/fixes sequentially |

## Closed W2 defects

| # | Defect | Fix | Regression |
|---|---|---|---|
| D1 | Merged-cell physical column index used dense indexing | `_resolve_cell` physical mapping | `test_w2_defects.py::test_slot_in_column_after_horizontal_merge_is_filled` |
| D2 | Nested-table plan targeted outer cell | Parse last `.tbl[n].r[r].c[c]`; nested table map | `test_generated_plan_fills_nested_cell_not_outer_cell` |
| D3 | `replace_image` left placeholder text | Surgical token removal with text-consumer guard | `test_replace_image_removes_placeholder_token` |
| D4 | Authorized image resize failed structural fingerprint | Exclude `wp:extent`/`a:ext` cx/cy from structural hash | `test_extent_change_keeps_structural_hash` |
