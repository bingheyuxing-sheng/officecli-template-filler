# W4-9 出口评审与证据包（v4.1.0）

- 评审日期：2026-11-06
- 软件版本：**4.1.0**
- 契约集：**4.3.0**（新增 Contract 06，纯加法）
- 产物 `schema_version`：仍为 **4.0**
- 代码基线：`1f2685c`（tag `v4.1.0`）；tag 后仅追加分发状态文档提交
- 评审性质：主智能体证据包，**未由独立 Agent 07 进程复跑**；独立性缺口见 §6

---

## 1. 范围

已交付：

1. Contract 06 与 3 个 W4 Schema。
2. `template_gate/` 证据、四态、状态机、报告、补充材料、Gate Store、Validator。
3. 7 个加法错误码。
4. `scripts/template_gate.py` CLI（analyze/report/resolve/confirm/reject/status）。
5. `GENERATE / REPAIR / REFORMAT / REVIEW` 执行入口强制校验；legacy `--data` 同样拒绝未确认模板。
6. SKILL.md Step 1.5 工作流。
7. W4-1～W4-9 测试。

非范围：

- SDT 内填充（`sdt_edit=false`，仍为 PROTECTED）。
- EXCEL_GENERATE / PROOFREAD / POLISH / MERGE / RENDER 的模板闸门（保持原行为）。
- 已安装 Skill 副本 `.trae/skills/officecli-template-filler` 同步（仍为 v4.0.0，见 §6）。

---

## 2. 自动化测试证据

| 项 | 命令 | 结果 |
|---|---|---|
| 全量回归 | `py -3.15 -m unittest discover -s tests -p "test_*.py"` | **Ran 532 tests in 186.599s — OK**（0 failure / 0 error / 0 skip；仅有 ResourceWarning 与测试构造的重复 Content_Types 警告） |
| 契约测试 | `py -3.15 -m unittest discover -s tests/contracts -t tests -p "test_*.py"` | **Ran 72 tests in 1.116s — OK** |
| 静态检查 | `py -3.15 -m ruff check . --output-format concise` | **All checks passed** |
| W4 定向 | `test_template_evidence` / `state` / `report` / `incremental` / `store` / `validator` / `enforcement` / `e2e` / contract schema | 8 + 6 + 5 + 8 + 6 + 10 + 6 + 2 + 2 = **53 项通过** |

新增测试未删除、未跳过、未降低既有断言；原有 479 项基线保留并与 W4 新增合计 532 项。

---

## 3. 闸门有效性证据

| 场景 | 结果 |
|---|---|
| 无 Gate Record，`execute_fill_plan` | `BLOCKED` + `TEMPLATE_GATE_REQUIRED`，不产生输出 |
| 无 Gate Record，`execute_repair_plan`（Python API） | 抛 `TemplateGateError`，`TEMPLATE_GATE_REQUIRED` |
| 无 Gate Record，`execute_review_plan`（REVIEW） | 抛 `TemplateGateError`，`TEMPLATE_GATE_REQUIRED` |
| 无 Gate Record，legacy `generate_document.py --data` | 退出码 2 + `TEMPLATE_GATE_REQUIRED`，不产生输出 |
| PROOFREAD（无模板） | 不触发闸门，正常产出 |
| 有 CONFIRMED 记录 | 正常执行并提交 |
| 模板修改后 | `TEMPLATE_GATE_STALE` |
| 任务类型变化 | `TEMPLATE_GATE_STALE` |
| 记录被篡改 | `TEMPLATE_GATE_CONFIRMATION_REQUIRED` |
| 阻断项未解决 | `TEMPLATE_EVIDENCE_INCOMPLETE` |
| 证据冲突 | `TEMPLATE_EVIDENCE_CONFLICT` |

Gate Record 绑定：模板 SHA-256、DocumentSpec digest、四类指纹、evidence digest、analysis/parser/policy 版本、task type、user statement、HMAC token、expires_at、resolved_evidence。

---

## 4. 契约与兼容性

- 契约 01–05 语义与 Schema 未修改；`document_spec-4.0`、`content_plan-4.0`、`fill_plan-4.0`、`qa_report-4.0` 保持原字段。
- 新增 Contract 06 与 3 个独立 Schema，`schema_version` 均为 `1.0`。
- `contracts/README.md` 已更新为 4.3.0，并注明独立 W4 审查待完成。
- `analyze_template.py --spec-version` 默认值仍为 3；`generate_document.py --data` 行为除 gate 外保持不变。
- Gated 模式在无确认记录时不再执行，这是 W4 的预期行为变化，已在 CHANGELOG/契约 06 中显式记录。

---

## 5. 发布包

- 路径：`dist/officecli-template-filler-v4.1.0.zip`
- 大小：992,825 字节
- 条目：234
- SHA-256：`6451954c14258fb78b17f7b6eb9938a5d1ac490cbb73ec5e88fb423068c7f71a`
- 核对：不含 `.git/`、`dist/`、`__pycache__`、`.pyc`、真实语料；包含 `template_gate/`、Contract 06、3 个 Schema、W4 测试与审计/实施记录。
- 详细清单：`reports/w4/w4-package-manifest.md`

---

## 6. 已知限制与独立性缺口

1. **独立审查缺口（阻断正式 PASS）**：本次证据包由主智能体编排生成，未由独立 Agent 07 进程复跑；不能表述为 Agent 07 正式 PASS。
2. **已安装 Skill 副本落后**：`.trae/skills/officecli-template-filler` 仍为 v4.0.0；在副本同步前，通过该副本运行不会经过新闸门。同步需要用户授权。
3. **补充材料记录校验**：带补充材料的确认记录通过 `evidence_digest` 与记录内 `resolved_evidence` 回放校验；补充文件本身不复制入仓，因此无法在 validator 中重新读取原始补充文件内容。模板 SHA、Spec digest、指纹与任务类型仍强绑定。
4. **真实语料未用于 W4 闸门复跑**：W4 测试使用合成 fixture；W3 的 46 份真实语料结果仍有效，但未在 W4 闸门链路重跑。
5. **分发状态**：`main` 已 push 到 `1f2685c`；annotated tag `v4.1.0` 已 push 并解引用到 `1f2685c`；GitHub Release 已创建为 **Draft**（`isDraft=true`，未 Publish），资产已上传并校验。由于本评审为 `CONDITIONAL_PASS` 且独立审查未完成，未执行 Publish。
6. **既有未提交文档改动**：`references/engine-internals.md` 的 W3 后文档精简改动在 W4 开始前已存在，本次未触碰；提交时需与 W4 变更区分。

---

## 7. 最终状态

**CONDITIONAL_PASS**

条件：

1. 由独立 Agent 07（或独立进程）复跑全量测试、契约测试与 W4 绕过测试，并出具 PASS/CONDITIONAL_PASS/FAIL。
2. 用户授权后同步 `.trae/skills/officecli-template-filler` 到 v4.1.0。
3. 若需正式发布，在独立审查通过后执行 `gh release edit v4.1.0 --draft=false`（或先改为 Pre-release）；当前 Release 为 Draft，不得表述为已正式发布。

实现层面的 W4-0～W4-9 交付物已完成，全量测试与静态检查通过；上述条件属于独立验收与分发门禁，不影响本次代码实现的完成度。
