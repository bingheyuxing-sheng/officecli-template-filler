# W4 实施记录（W4-0～W4-8）

- 日期：2026-11-06
- 基线：软件 v4.0.2 → v4.1.0；契约集 4.2.0 → 4.3.0
- 说明：本文件按阶段记录实现范围、证据与验收结果；W4-9 的最终出口见 `reports/w4/w4-9-exit-review.md`。

## W4-0 架构审计

- 交付：`reports/w4/w4-0-architecture-audit.md`
- 结论：`PASS`
- 关键事实：所有正式执行入口（CLI、Python API、legacy `--data`）在 W4 前均无模板确认校验；DocumentSpec 4.0 结构摘要不覆盖段距/行距/边框/底纹/页码/页数；无 evidence registry、Gate Record、状态机或闸门错误码。
- 实测：全量 479 项通过；契约 70 项通过。

## W4-1 Evidence Registry

- 新增：`template_gate/models.py`、`evidence.py`、`analyzer.py`、`errors.py`、`config/template-gate-policy.json`、`schemas/template_evidence-1.0.schema.json`、`contracts/06-template-understanding-gate.md`
- 能力：逐属性证据（object/location/property/value/source/evidence_type/status/task_relevant/blocking/resolutions）；四态；冲突检测；稳定 evidence_id；证据摘要；任务相关性策略；SDT/OLE 保护；红色文字默认 AMBIGUOUS。
- 测试：`tests/test_template_evidence.py` 8 项、`tests/contracts/test_template_gate_schema.py` 2 项，全部通过。
- 验收：同一模板重复分析 digest/analysis_id 稳定；不修改现有 DocumentSpec/Schema。

## W4-2 状态机

- 新增：`template_gate/state.py`、`tests/test_template_gate_state.py`
- 能力：10 状态；仅 `CONFIRMED → EXECUTING` 合法；`BLOCKED/WAITING_USER_INPUT/READY_FOR_REVIEW → EXECUTING` 抛 `TEMPLATE_GATE_ILLEGAL_TRANSITION`；`INVALIDATED → ANALYZING` 可恢复。
- 测试：6 项通过。

## W4-3 Analysis Report

- 新增：`template_gate/report.py`、`schemas/template_analysis_report-1.0.schema.json`、`scripts/template_gate.py`（`report`/`status`）
- 能力：基本信息、页面/样式、结构、解析质量、阻断项 7 字段、确认提示；JSON + Markdown；report digest 排除时间戳。
- 测试：`tests/test_template_gate_report.py` 5 项通过（含 CLI roundtrip）。

## W4-4 补充材料与增量解析

- 新增/扩展：`template_gate/supplements.py`、`analyzer` 的 `--supplement` 钩子、`resolve` 子命令。
- 能力：参考 DOCX 按位置/文本锚点贡献证据；JSON/Markdown 明确地址的答案；用户 `PROVIDE_VALUE`/`USE_REFERENCE`/`PRESERVE_AS_IS`；冲突不自动解决；`reanalyze` 复用既有 resolution。
- 测试：`tests/test_template_gate_incremental.py` 8 项通过。

## W4-5 Confirmation Store

- 新增：`template_gate/store.py`、`schemas/template_gate_record-1.0.schema.json`；CLI `confirm`/`reject`/`status --gate`。
- 能力：Gate Home（`OFFICECLI_GATE_HOME` 覆盖，默认 `~/.officecli-template-filler/gates`）；原子 JSON；HMAC-SHA256；30 天默认 TTL；`resolved_evidence` 回放；不写仓库、不存绝对路径。
- 测试：`tests/test_template_gate_store.py` 6 项通过。

## W4-6 Gate Validator

- 新增：`template_gate/validator.py`；契约 06 与 `contracts/README.md` 升至 4.3.0（待独立审查）。
- 能力：记录存在/ schema/状态/用户确认/HMAC/时效/SHA/spec digest/四类指纹/analysis/parser/policy 版本/任务类型/证据摘要/blocking/冲突检查；7 个错误码映射。
- 测试：`tests/test_template_gate_validator.py` 10 项通过。

## W4-7 执行入口强制接入

- 修改：`document_engine/fill_executor.py`、`document_engine/pipeline.py`、`engine/repair_engine.py`、`engine/review_engine.py`、`engine/reformat_engine.py`、`scripts/generate_document.py`、`repair_document.py`、`review_document.py`、`reformat_document.py`。
- 新增：`tests/gate_helpers.py`（测试 fixture 生成真实 Gate Record）、`tests/test_template_gate_enforcement.py`。
- 迁移：13 个既有测试文件预置 gate fixture 或模块级包装，未删除断言。
- 验证：无记录时 `execute_fill_plan` 返回 `TEMPLATE_GATE_REQUIRED`；`execute_repair_plan`/`execute_review_plan`（REVIEW）抛 `TemplateGateError`；PROOFREAD 不触发；legacy CLI 被拒绝；有记录时正常执行。
- 测试：6 项通过；受影响模块 148 项通过。

## W4-8 SKILL 工作流集成

- 修改：`SKILL.md` 新增 Step 1.5，明确 analyze → report → 用户确认 → confirm → execute 顺序；说明阻断项处理、失效条件、非闸门模式与 `--gate-record`。
- 文档与代码一致性：`tests/test_skill_workflow_v4.py` 继续验证 v4 主链与默认值。
- 未做：`.trae/skills/officecli-template-filler` 已安装副本未同步（需要用户授权后再更新）；当前副本仍为 v4.0.0。

## 提交与文件清单

新增：

- `template_gate/`（10 个模块）
- `scripts/template_gate.py`
- `config/template-gate-policy.json`
- `contracts/06-template-understanding-gate.md`
- `schemas/template_evidence-1.0.schema.json`、`template_gate_record-1.0.schema.json`、`template_analysis_report-1.0.schema.json`
- `tests/test_template_evidence.py`、`test_template_gate_state.py`、`test_template_gate_report.py`、`test_template_gate_incremental.py`、`test_template_gate_store.py`、`test_template_gate_validator.py`、`test_template_gate_enforcement.py`、`test_template_gate_e2e.py`、`tests/contracts/test_template_gate_schema.py`、`tests/gate_helpers.py`
- `reports/w4/`

修改：

- `engine/__init__.py`（版本 4.1.0）
- `document_engine/fill_executor.py`、`pipeline.py`
- `engine/repair_engine.py`、`review_engine.py`、`reformat_engine.py`
- `scripts/generate_document.py`、`repair_document.py`、`review_document.py`、`reformat_document.py`
- `config/error-codes.json`（7 个加法错误码）
- `contracts/README.md`（4.3.0）
- `SKILL.md`、`README.md`、`CHANGELOG.md`、`references/python-docx-engine.md`
- 既有测试文件 13 个（gate fixture/包装）

未修改：

- 契约 01–05 语义与 4.0 Schema
- `analyze_template.py` 默认 `--spec-version 3`
- v3.5.9 公共 API 语义（除 execute_* 的 gate 检查）
