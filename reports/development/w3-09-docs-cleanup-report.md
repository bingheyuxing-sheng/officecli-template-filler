# W3 文档清理报告（全量 Markdown 编辑整理）

- Report ID: W3-09-DOCS-CLEANUP
- Date: 2026-11-05
- Scope: 仓库内 34 个既有 `.md` 文件 + 本报告
- Decision: **完成**（仅文档编辑；未提交、未重打包）
- Current state after cleanup: 契约集 **4.2.0**；完整套件 **450 项通过**；Alpha **未宣布**；真实语料 W3-9 **待外部输入**；SDT 填充**不支持**（`sdt_edit=false`）

## 1. 范围与约束

1. 只编辑 `.md` 文件。未修改 `engine/`、`template_intelligence/`、`content_intelligence/`、`document_engine/`、`qa/`、`scripts/`、`tests/`、`config/`、`examples/`、`schemas/`、`dist/`。
2. 保留全部裁决（PASS / CONDITIONAL_PASS / FAIL）、日期、报告 ID、证据路径、测试命令、已知限制与未关闭问题。
3. 历史报告保留原始测试总数与版本号，并增加“历史记录 / 当前状态”说明，避免把 357、385、397、447 误读为当前基线。
4. 契约只做状态措辞修正：未改动 MUST / SHOULD、字段名、枚举、范围、`location_id` 语法、状态名、错误码、示例、版本号或日期。改动范围与清理后哈希记录在 `reports/development/w3-04b-manifest.md`。

## 2. 行数变化（按文件组）

| 文件组 | 文件数 | 清理前 | 清理后 | 变化 |
|---|---|---|---|---|
| 顶层（AGENTS / README / SKILL / CHANGELOG） | 4 | 1309 | 1323 | +14 |
| `references/` | 2 | 578 | 582 | +4 |
| `contracts/`（含 README、compatibility、2 份 CP） | 9 | 1382 | 1384 | +2 |
| `reports/w0/` | 4 | 532 | 526 | −6 |
| `reports/w1/` | 1 | 124 | 126 | +2 |
| `reports/w2/` | 4 | 222 | 210 | −12 |
| `reports/w3/`（不含本报告） | 10 | 552 | 560 | +8 |
| 合计 | 34 | 4699 | 4711 | +12 |

行数净增来自“历史记录 / 当前状态”说明、目录树补全与契约状态修正。`git diff --shortstat` 对 25 个已跟踪文件的结果为 **126 insertions / 114 deletions**（不含本报告）；本报告 132 行。全仓库 35 个 Markdown 合计 **4843 行**。

## 3. 具体清理内容

### 3.1 顶层文档

- `README.md`：目录树补入 `AGENTS.md`、`contracts/`、`config/`、v4 四个包与 `reports/`，避免读者按 v3 结构寻找文件；删除“当前基线 186 项”这一过期现状，改为 450 项；路线图从 v3.5 更新为 v4.0 当前出口条件；修正“报告为通过”语病。
- `SKILL.md`：标题从 v3.5.9 更新为“v4.0 dev / 契约集 4.2.0 / v3.5.9 兼容基线”；目录树补入 v4 包并压缩冗长的逐测试文件列表，测试总数 186 → 450；四段被测字符串全部保留并通过检查。
- `CHANGELOG.md`：修正“dist/ 附带对应版本打包文件”与下方“部分版本缺失”的矛盾，改为“保留部分版本归档”；历史版本测试数保持为当时记录。
- `AGENTS.md`：仅把头部引用块的 Markdown 行尾双空格改为反斜杠硬换行，消除行尾空白；规则文本未改。

### 3.2 `references/`

- `python-docx-engine.md`：标题从 v3.5.5 更新为 v3.5.9 引擎基线 / 4.2.0 契约集；测试数 138 → 450；移除本机绝对路径（示例改为 `<skill_root>`）；6 处示例 `assert` 改为 `RuntimeError`，与“校验不使用 assert”的项目规则一致；修正“格式修订无法用 tracked changes 表达”的过时说法，说明 REVIEW 使用 `w:*PrChange`。
- `engine-internals.md`：补充 v4 迭代器对 SDT 内容的暴露；把 `sdt_control` 说明限定为 legacy v3 表格单元格路径，并声明 v4 FillPlan 将其视为 PROTECTED；视觉 QA 的 PDF 后端改为 WPS 或 LibreOffice；把孤立在 `---` 后的 v3.5.9 条目提升为 H2 小节，消除结构断裂。

### 3.3 `contracts/`

- `02-document-spec.md`：把“OI-01 仍开放、当前不能产出 4.0”改为“OI-01 已于 W1 关闭”，说明 `--spec-version 4` 产出 4.0、默认仍为 3.0，4.0 Schema 未被放宽。规范条款、字段与示例未动。
- `contracts/README.md`：同上，修正 §5 对 `analyze_template.py` 的过期描述。
- `compatibility-v3.5.9.md`：增加状态注记，说明 OI-01/03/05 已关闭、OI-02 仍为环境事实、OI-04 仍为 beta 项，表格保留为 W0 快照。
- `01`、`03`、`04`、`05` 与两份 CP 未改动；`CP-W2-002` 中“428-test regression”属于当时验收条件，保留为历史记录，不当作当前总数。

### 3.4 `reports/`

- `reports/w0/`：问题台账按“关闭项保留并标注解决”的规则，把 OI-01、OI-03、OI-05 标为 CLOSED 并写入 W1/W2 证据；冻结报告、门禁报告与验收报告增加历史记录说明；删除冻结报告与验收报告中重复的 OI 摘要表/列表，改为指向 `reports/w0/issues.md`。
- `reports/w1/w1-acceptance.md`：增加历史状态说明（W1 为 4.0.0 / 357 项，当前 4.2.0 / 450 项）。
- `reports/w2/`：变更清单标注为 4.1.0 历史清单；验收报告标明 4.1.0 / 397 为历史值；删除与 `reports/development/w2-issues.md` 重复的缺陷表（4 行）和遗留问题表（6 行），改为指向该台账，保留 W2-I1 后续由 CP-W2-002 解决的说明。
- `reports/development/w3-task-book.md`：版本基线 4.1.0 → 4.2.0；W3-4 的 07 复核状态从“待二次审查”更新为“提案 CONDITIONAL_PASS、实施后 PASS、4.2.0 冻结”；移除本机绝对路径。
- `reports/development/w3-04b-implementation.md`：冻结状态更新为“已冻结”，保留实施当时“候选/未冻结”的历史说明；447 项标注为实施时数据并补充当前 450；移除本机工作目录。
- `reports/w3/07-cp-w2-002-gate-review.md`、`07-w3-6-review.md`、`07-w3-8-review.md`：增加后续状态（实施后 PASS、F-1 已处理、打包已完成），原裁定与证据不变。
- `reports/archive/w3-08-package-manifest-dev-snapshot.md`：注明该包对应 `b74f059`，本次文档清理未重新打包，包内文档与工作树可能有措辞差异。
- `reports/development/w3-audit-triage.md`：删除与任务书重复的 9 行修复计划表，改为指向 `reports/development/w3-task-book.md`；保留全部审计裁定与证据。
- `reports/archive/w3-real-corpus-candidates.md`：把“SDT 槽位不可发现”的旧描述更新为 4.2.0 下的“发现为 PROTECTED 并拒绝填充”。

## 4. 删除与合并清单

| 文件 | 动作 | 保留的证据 |
|---|---|---|
| `reports/w0/w0-acceptance.md` | 删除重复的 6 行 OI 摘要表 | 明细在 `reports/w0/issues.md` |
| `reports/w0/05-contract-freeze-report.md` | 删除重复的 5 条 OI 列表 | 明细在 `reports/w0/issues.md` |
| `reports/acceptance/w2-acceptance.md` | 删除重复的 4 行缺陷表、6 行遗留问题表 | 明细在 `reports/development/w2-issues.md` |
| `reports/development/w3-audit-triage.md` | 删除重复的 9 行修复计划表 | 明细在 `reports/development/w3-task-book.md` |
| `SKILL.md` | 压缩 9 行逐测试文件枚举为 7 行代表性文件 + 契约套件 | 测试总数与关键入口保留 |
| `README.md` | 替换 v3 目录树为当前目录结构 | 模块说明保留 |
| `references/engine-internals.md` | 合并孤立 v3.5.9 条目为 H2 小节 | 全部条目保留 |

所有删除均为重复摘要或过期现状；没有删除裁决、日期、证据路径、测试命令、未关闭限制或契约规范。

## 5. 验证结果

### 5.1 结构与链接检查

临时脚本扫描全部 Markdown（脚本已删除，不在仓库内）。最终输出：

```text
scanned 35 markdown files
OK: no heading, trailing-whitespace, blank-line or broken-link issues
```

检查项：每个文件恰好一个 H1；非代码块内标题层级不跳级；无行尾空白；无连续 3 个以上空行；所有相对链接目标存在。

### 5.2 完整测试

```powershell
py -3.15 -m unittest discover -s tests -p "test_*.py"
```

结果：**Ran 450 tests in 218.568s — OK**（实测总耗时 219.2s；清理过程中另一次完整运行为 246.066s，同为 OK）。与清理前基线一致，无失败、错误或跳过。

### 5.3 `SKILL.md` 字符串断言

| 检查 | 结果 |
|---|---|
| 包含 `analyze_template.py --input "$INPUT_1" --spec-version 4` | True |
| 包含 `--content-plan` | True |
| 包含 `Legacy token mode` | True |
| 不含 `generate_document.py --template "$INPUT_1" --payload` | True |

### 5.4 契约 diff

`git diff -U0 -- contracts` 仅有 3 个 hunk：Contract 02 §2、`contracts/README.md` §5、`compatibility-v3.5.9.md` 头部状态注记。均为 OI-01 状态措辞，无 MUST/SHOULD、字段、枚举、示例、版本号或日期变化。清理后哈希已追加到 `reports/development/w3-04b-manifest.md`，原冻结哈希保留。

### 5.5 变更范围

`git status --porcelain` 显示 25 个已跟踪 `.md` 修改，加 1 个新增 `.md`（本报告）。没有代码、Schema、测试、配置、示例或 `dist/` 文件出现在变更列表中。

## 6. 发现的规范性问题（未静默修改）

1. **CP-W2-002 §5 的“428-test regression”是当时验收条件**。它不是当前状态，但属于已冻结变更记录，保留原文。当前总数为 450。
2. **FillPlan `mode` 与 operation `policy` 命名接近**（OI-06 / W0 观察 O-01）。语义未变：`policy` 是操作安全，`mode` 是交付资格。仍留待 beta 文档化或重命名。
3. **Contract 03/04/05 的状态行仍写“FROZEN (W0)”**。这三份契约未被 CP-W2-001/002 修改，版本仍为 1.0.0；契约集版本 4.2.0 由 `contracts/README.md` 统一表达。为避免制造虚假版本变更，未改其版本号。
4. **legacy `sdt_control` 表格单元格处理器存在，但 v4 不支持 SDT 填充**。已在 `references/engine-internals.md` 明确限定为 v3 路径，避免与 `sdt_edit=false` 冲突。

## 7. 遗留风险与需要编排者处理的事项

1. **工作区顶层 `d:\docs\AGENTS.md` 仍是 4.0.0 / W2 的旧副本**，不在本次 34 个仓库文件范围内。仓库内 `AGENTS.md` 已声明自身为权威版本，但实际加载给 Agent 的工作区副本可能继续误导。建议同步或删除旧副本。
2. **`dist/officecli-template-filler-v4.0.0-dev-w3.zip` 未重建**（任务明确不重打包）。包内文档对应 `b74f059`，与本轮清理后的 Markdown 存在措辞差异；包清单已注明。
3. **契约在冻结后发生了 3 处状态文字改动**。虽无规范语义变化，且新哈希已记录，若项目要求冻结字节严格不可变，需由 Agent 05 记录 PATCH 说明并由 Agent 07 确认。
4. **W3 出口条件仍未满足**：W3-9 真实语料待外部脱敏输入；P2-01/P2-04 待审计方 Linux/LibreOffice 复跑；SDT 填充不支持；Alpha 未宣布。

## 8. 结论

本次清理只改文档，未触碰代码、Schema、测试、配置、示例或 `dist/`。裁决与证据完整保留，当前状态在顶层文档、契约索引、任务书与报告中一致：**4.2.0 / 450 / Alpha 未宣布 / SDT 不可填 / 真实语料待输入**。完整套件 450 项通过，结构与链接检查通过。
