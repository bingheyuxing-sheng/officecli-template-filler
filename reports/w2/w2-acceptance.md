# W2 Acceptance Report — Real-World Template Validation & Transaction Hardening

- Report ID: W2-ACCEPT-01
- Date: 2026-11-05
- Contract set: **4.1.0** (CP-W2-001, Agent 07 PASS)
- Decision: **W2 PASS**, with one declared unsupported structure (body-level `w:sdt`)
- Test baseline: **397 passed** (186 v3.5.9 + 70 W0 contracts + 141 W1/W2)

## 1. Exit-condition checklist

| Exit condition | Result | Evidence |
|---|---|---|
| Contract 4.0.0 preserved or formally changed | **PASS** | CP-W2-001, 4.0.0 → 4.1.0 (MINOR, additive); Agent 07 PASS in `07-n1-gate-review.md`; manifest `01-contract-change-manifest.md` |
| Six real-template fixtures | **PASS** | `tests/fixtures/class_01…06`; `test_fixture_matrix.py` 7 tests |
| First/odd/even header/footer location behavior | **PASS** | Contract 01 §3; `test_slot_id` grammar; `test_e2e_v4::test_11`; class_03 covers first-page header + even-page footer |
| Environment capability matrix | **PASS** | `config/environment_capabilities.yaml` + JSON; `qa/environment.py`; 12 tests |
| Transaction-level second gate | **PASS** | `engine/transaction.py` `record_gate` + stale-report binding; 9 tests |
| QA does not depend on Workflow | **PASS** | `engine/logic_qa.py` no longer imports `workflow`; 6 tests |
| 357 baseline preserved | **PASS** | Full suite 397, zero failures |
| Declared template classes pass | **PASS** | Six classes: success + refusal + rollback + unsupported reporting |
| Audit honesty | **PASS** | Unsupported/protected/UNVERIFIED reported; body-level SDT explicitly unsupported |

## 2. Six fixture classes

| Class | Coverage |
|---|---|
| `class_01_basic_report` | Body token + simple table; injected FORMAT failure → `FAILED`, rollback, template SHA unchanged |
| `class_02_complex_table` | `gridSpan`/`vMerge`/`tblHeader` preserved; repeated-header warning region |
| `class_03_header_footer` | First-page header token + even-page footer token; fixed header paragraph protected; flags preserved |
| `class_04_images` | Authorized image replacement + placeholder cleanup; media bytes replaced; fixed text unchanged |
| `class_05_nested_structure` | Generated plan now targets the nested table; nested structure preserved; old outer-table plan rejected |
| `class_06_complex_document` | SDT/field/title protected; unsupported codes; tampering plan → `PROTECTED_SLOT_VIOLATION`, `BLOCKED` |

Each class checks: two-run slot stability, protected regions, FillPlan validation/execution, template bytes, no staged leftovers, expected status/text.

## 3. N1 contract change (W1-N1 closed)

- Grammar now accepts `sec[n].first_page_header`, `first_page_footer`, `even_page_header`, `even_page_footer`.
- `schema_version` remains `"4.0"`; old IDs remain byte-identical.
- Example vectors: `examples/slot-id` (`S_d11f7ff0c600` / `6a9ad32917a886ab`), document-spec `full_valid` slot + `PR_003`.
- Header/footer protection is now **paragraph-level**: the slot paragraph is fillable, fixed neighbour paragraphs remain blocking regions; protected fingerprint excludes only the slot paragraph.
- Agent 07 first review: CONDITIONAL_PASS (examples + manifest missing). Follow-ups closed. Re-review: **PASS**.

## 4. Environment capability matrix

Detected at review time:

| Capability | Required | Status |
|---|---|---|
| `docx_parse` | yes | AVAILABLE |
| `docx_write` | yes | AVAILABLE |
| `wps_pdf_render` | yes | AVAILABLE |
| `pdf_page_analysis` | yes | AVAILABLE (WPS pdfinfo) |
| `pixel_visual_diff` | no | UNAVAILABLE (no PyMuPDF) |
| `ocr` | no | UNAVAILABLE |
| `chart_render` | no | UNAVAILABLE (no matplotlib) |

Required capability unavailable → corresponding check `UNVERIFIED`, report cannot be `PASSED`. Optional missing capabilities only annotate evidence.

## 5. Transaction second gate

`DocumentTransaction.record_gate(report)` validates the same QAReport with `qa.gate.assert_commit_eligible`, binds `task_id`, records `staged_sha256` and `qa_report_sha256`, and `commit()` re-hashes the staged file. Tests prove:

1. ineligible report → commit refused;
2. task-id mismatch → refused;
3. staged file changed after gate → `QA_REPORT_STALE`, no final file;
4. callers that never call `record_gate` keep legacy behavior;
5. executor continues to refuse STRICT/UNVERIFIED.

## 6. Fixture-discovered defects fixed in W2

| # | Defect | Fix |
|---|---|---|
| 1 | Merged-cell physical column index resolved densely | `_resolve_cell` uses physical `table.rows[r].cells[c]` mapping |
| 2 | Nested-table plan targeted the outer cell | Plan parser takes the **last** `.tbl[n].r[r].c[c]`; executor fills the nested table |
| 3 | `replace_image` left `{{图1}}` residue | Surgical token removal unless a separate text op consumes the same slot |
| 4 | Authorized image resize failed structural fingerprint | `wp:extent`/`a:ext` cx/cy excluded from structural hash; layout hash still tracks size |

Each has a regression test in `tests/test_w2_defects.py` (5 tests). Unauthorized paragraph/structure changes still fail FIDELITY.

## 7. Remaining limitations / open issues

| ID | Issue | Severity | Owner | Next |
|---|---|---|---|---|
| W2-I1 | Body-level `w:sdt` wrapping an entire paragraph is not enumerated by `doc.paragraphs`; no slot/protected region is produced. Inline SDT is handled. | High | Agent 01 + 05 | Needs a contract location grammar for `body.sdt_p[i]` or equivalent; not fixed in W2 |
| W2-I2 | PyMuPDF / OCR / matplotlib absent | Medium | Agent 04 | Pixel/OCR/chart checks stay `UNVERIFIED` |
| W2-I3 | Legacy CLIs still do not emit ToolEnvelope 4.0 | Low | Agent 05 | Beta/W3 |
| W2-I4 | `AGENTS.md` still states contract baseline 4.0.0; current frozen set is 4.1.0 | Low | Project owner | Update project rules or record a waiver |
| W2-I5 | `class_04` fixture uses a relative image path; CLI contract requires an absolute path (test resolves it) | Low | Agent 06 | Normalize fixture or document test-only resolution |
| W2-I6 | An earlier W2 wave used three agents on one worktree, contrary to AGENTS §4.5 | Process | Orchestrator | Remediated: stop parallel writes, independent re-review, sequential fixtures/fixes |

## 8. Process and ownership notes

- Contract/schema edits were made only through CP-W2-001, manifest and Agent 07 gate.
- `engine/transaction.py` is owned by Agent 05; the W2 gate implementation was delivered by the Agent 03/04 integration task under orchestrator approval and covered by tests. Ownership exception is recorded here.
- `tests/test_fixture_matrix.py` was adjusted by the fix task to consume fixture expectations instead of a hard-coded `FAILED`; no assertion was deleted or weakened (class_05 now expects success because the nested-table plan is fixed).
- No commit, tag, push, or release was performed. Per AGENTS §16, this is a working-tree stage only.

## 9. Verification commands

```powershell
py -3.15 -m unittest discover -s tests -p "test_w2_defects.py"        # 5 OK
py -3.15 -m unittest discover -s tests -p "test_fixture_matrix.py"    # 7 OK
py -3.15 -m unittest discover -s tests -p "test_environment_capabilities.py" # 12 OK
py -3.15 -m unittest discover -s tests -p "test_transaction_gate.py" # 9 OK
py -3.15 -m unittest discover -s tests -p "test_logic_alignment.py"  # 6 OK
py -3.15 -m unittest discover -s tests -p "test_e2e_v4.py"           # 11 OK
py -3.15 -m unittest discover -s tests -p "test_*.py"                # 397 OK, 157.6s
```

**W2 decision: PASS.** v4.0 now has a contract-governed, transaction-gated, real-template-tested chain. The only declared structural gap is body-level SDT wrapping, which requires a future contract change rather than a private workaround.
