# W0 Open Issue Register

- Register version: 1.0
- Date: 2026-11-05
- Rule: no resolved item is removed; it is marked `CLOSED` with its resolution.

## Summary

| ID | Severity | Blocks W0 | Blocks alpha | Owner | Target | Status |
|---|---|---|---|---|---|---|
| OI-01 | High | No | **Yes** | Agent 01 | W1 | OPEN |
| OI-02 | Medium | No | No | Agent 04 | W2 | OPEN (environment) |
| OI-03 | High | No | No (beta gate) | Agents 01–04 | W1/W2 | OPEN |
| OI-04 | Low | No | No | Agent 05 | Beta | OPEN |
| OI-05 | Medium | No | No | Agents 04–05 | W1 | OPEN |
| OI-06 | Low | No | No | Agent 03 | Beta | OPEN |
| G-01 | Blocking (contract) | Yes | — | Agent 05 | W0 | **CLOSED** |
| G-02 | Blocking (contract) | Yes | — | Agent 04 | W0 | **CLOSED** |
| G-03 | High (clarification) | Yes | — | Agent 03 | W0 | **CLOSED** |
| G-04 | High (clarification) | Yes | — | Agent 03 | W0 | **CLOSED** |

## OI-01 — `analyze_template.py` cannot emit DocumentSpec 4.0

- **Evidence:** the CLI emits a 7-key summary (`scripts/analyze_template.py:39-47`), validated by `document_spec-legacy-cli.schema.json`. It lacks `template`, `document`, `structure`, `slots`, `protected_regions`, `capacity_profiles`, `layout_constraints`, `fingerprint_ref`.
- **Impact:** alpha cannot demonstrate template understanding. OI-01 is a hard alpha blocker.
- **Constraint:** the 4.0 schema must not be relaxed to accept the legacy summary.
- **Acceptance:** CLI output validates against `document_spec-4.0.schema.json` on at least 6 fixtures; legacy 3.0 output remains available via a compatibility path or version flag.
- **Owner:** Agent 01. **Target:** W1.

## OI-02 — Visual pixel QA and OCR unavailable in this environment

- **Evidence:** `fitz` (PyMuPDF), `matplotlib`, `rapidocr_onnxruntime`, `paddleocr`, `pytesseract` are all missing. WPS `kwpsconvert.exe` is available.
- **Impact:** `VISUAL_PIXEL` and `OCR` can only be `UNVERIFIED`; page-count QA remains available through WPS.
- **Rule:** never report `PASSED` for a check that could not run.
- **Owner:** Agent 04. **Target:** W2. **Status:** environment observation, not a code defect.

## OI-03 — No runtime validators or gate wiring in W0

- **Evidence:** W0 ships contracts and test-only reference checkers. `semantic_*` functions live in `tests/contracts/helpers.py`, not in the engine.
- **Impact:** cross-field rules (policy binding, slot uniqueness, region containment, overflow) are proven expressible but not enforced at runtime.
- **Acceptance:** runtime validators under `content_intelligence/` and `qa/gate.py`; `transaction.py` refuses commit when a required check was not executed.
- **Owner:** Agents 01–04. **Target:** W1 (validators) / W2 (gate wiring).

## OI-04 — Legacy CLIs do not emit ToolEnvelope 4.0

- **Evidence:** `inspect_document.py` emits `{routing, specs}`; `analyze_template.py` emits a summary; `run_qa.py` emits a QA report; `generate_document.py` emits a transaction record.
- **Impact:** the orchestrator needs per-tool adapters until beta.
- **Acceptance:** new tools use the envelope; old tools migrate in beta with compatibility tests.
- **Owner:** Agent 05. **Target:** Beta.

## OI-05 — `logic_qa → workflow → qa_engine` dependency inversion

- **Evidence:** `engine/logic_qa.py:14` imports `workflow`, and `workflow` imports `qa_engine` for visual QA rounds.
- **Impact:** changing logic QA can cascade into workflow and QA modules owned by different agents.
- **Acceptance:** move `is_heading_paragraph` to `alignment.py` (or a neutral `structure_utils.py`), remove the `logic_qa → workflow` edge, keep 186 baseline green.
- **Owner:** Agents 04–05. **Target:** W1.

## OI-06 — FillPlan `policy` vs `mode` naming overlap

- **Evidence:** plan-level `mode` is STRICT/STANDARD, while every operation has `policy: "STRICT"`.
- **Impact:** readers may think STANDARD allows non-strict operations. It does not: policy is operation safety; mode is delivery eligibility.
- **Acceptance:** rename or document explicitly in beta; no semantic change now.
- **Owner:** Agent 03. **Target:** Beta.

## Closed during W0 gate

### G-01 — COMMIT vs UNVERIFIED eligibility

- **Resolution:** Contract 05 now allows `COMMIT` for `UNVERIFIED` only with `data.qa_eligible: true` and non-empty `data.missing_checks`. Contract 04's STANDARD publish path and Contract 05's next_action are consistent.
- **Evidence:** `tests/contracts/test_tool_envelope.py::test_unverified_commit_requires_qa_eligible`.
- **Status:** CLOSED.

### G-02 — QA policy spoofing

- **Resolution:** QAReport 4.0 requires `task_mode` and `gate_mode`; `policy_source` must equal `"{task_mode}/{gate_mode}"`.
- **Evidence:** `tests/contracts/test_qa_report.py::test_policy_source_must_match_task_and_gate_mode`.
- **Status:** CLOSED.

### G-03 — Protected region bypass

- **Resolution:** Contract 03 §3.4 rule 5 defines `not_protected` as slot status plus enclosing protected regions.
- **Status:** CLOSED (contract); runtime test in W2.

### G-04 — Direct final-path write

- **Resolution:** Contract 03 §3.8 mandates staging-only writes, per-operation ledger, and QA reading the artifact.
- **Status:** CLOSED (contract); runtime test in W2.
