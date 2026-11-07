# reports/ 索引

> 本文件是 `reports/` 的**唯一索引**。
> 整理日期：2026-11-07；Git 基线 `main` @ `37ec46f`（未提交任何变更）。
> 目录结构：`development/`、`acceptance/`、`archive/` 按角色归档；`w0/`–`w4/` 仅保留冻结契约与入口脚本引用的**锚点文件**；`w5/`、`documentation/` 为进行中/并行维护区域。

## 1. 目录结构

```text
reports/
├── README.md                本索引
├── development/             开发过程：任务书、审计、实施记录、评审、问题登记、变更清单
├── acceptance/              最终验收：验收报告、出口证据、独立裁决、发布包清单、评测结果
├── archive/                 已被取代、仅供历史追溯的快照
├── w0/  w1/  w2/  w3/  w4/  冻结引用锚点（不移动，见 §5）
├── w5/                      W5 进行中（G1.5 待人工批准，B2/B3 未启动）
├── documentation/           跨阶段版本事实与 Release 说明（并行维护）
└── cleanup/                 本次目录治理的清单、计划与最终报告
```

## 2. development/（开发过程）

### 2.1 已归档到 `development/`

| 文件 | 阶段 | 内容 |
|---|---|---|
| `development/w2-01-contract-change-manifest.md` | W2 | CP-W2-001 变更清单（4.1.0 历史哈希） |
| `development/w2-issues.md` | W2 | W2-I1～I6 问题登记册 |
| `development/w3-04b-implementation.md` | W3 | CP-W2-002 实施记录 |
| `development/w3-04b-manifest.md` | W3 | 契约集 4.2.0 冻结哈希（当前契约集权威） |
| `development/w3-07-w3-6-review.md` | W3 | W3-6（GENERATE 切 v4）独立复核 |
| `development/w3-07-w3-8-review.md` | W3 | W3-8 文档措辞抽查 |
| `development/w3-09-docs-cleanup-report.md` | W3 | 全量 Markdown 整理记录 |
| `development/w3-audit-triage.md` | W3 | 外部技术审计逐项裁定 |
| `development/w4-0-architecture-audit.md` | W4 | W4 架构审计（执行入口与证据缺口） |
| `development/w4-implementation-log.md` | W4 | W4-0～W4-8 实施记录 |

### 2.2 锚点位置（同为 development 角色，因外部引用不移动）

| 文件 | 阶段 | 内容 |
|---|---|---|
| `w0/05-contract-freeze-report.md` | W0 | 契约集 4.0.0 冻结证据 |
| `w0/07-gate-review.md` | W0 | W0 独立门禁审查 PASS |
| `w0/issues.md` | W0 | OI-01～OI-06 问题登记册 |
| `w2/07-n1-gate-review.md` | W2 | CP-W2-001 复审 PASS |
| `w3/07-cp-w2-002-gate-review.md` | W3 | CP-W2-002 提案阶段 CONDITIONAL_PASS |
| `w3/07-cp-w2-002-post-review.md` | W3 | CP-W2-002 实施后复审 PASS |
| `w3/w3-task-book.md` | W3 | W3 唯一修复任务书 |

## 3. acceptance/（最终验收）

### 3.1 已归档到 `acceptance/`

| 文件 | 阶段 | 内容 |
|---|---|---|
| `acceptance/w2-acceptance.md` | W2 | W2 验收；含“真实模板已验证”措辞更正 |
| `acceptance/w3-11-package-manifest-v4.0.0.md` | W3 | v4.0.0 发布包清单 |
| `acceptance/w3-13-v4.0.1-exit-evidence.md` | W3 | v4.0.1 出口证据（关闭 B1） |
| `acceptance/w3-14-package-manifest-v4.0.1.md` | W3 | v4.0.1 发布包清单 |
| `acceptance/w4-package-manifest-v4.1.0.md` | W4 | v4.1.0 包清单 |
| `acceptance/w4-package-manifest-v4.1.1.md` | W4 | v4.1.1 包清单 |
| `acceptance/w4-package-manifest-v4.1.2.md` | W4 | v4.1.2 包清单 |

### 3.2 锚点位置（同为 acceptance 角色，因外部引用不移动）

| 文件 | 阶段 | 内容 |
|---|---|---|
| `w0/w0-acceptance.md` | W0 | W0 最终验收 |
| `w1/w1-acceptance.md` | W1 | W1 实施与验收（OI-01 关闭证据） |
| `w3/10-exit-review.md` | W3 | v4.0.0 出口证据与发布门禁 |
| `w3/12-independent-exit-review.md` | W3 | v4.0.0 独立出口审查，裁定 **FAIL**（合规补丁触发源） |
| `w3/real-corpus-eval.md` | W3 | 真实语料匿名聚合评测 |
| `w3/real-corpus-eval.json` | W3 | 同上的机器可读结果（`tests/real_corpus_eval.py` 默认输出） |
| `w4/w4-9-exit-review.md` | W4 | W4-9 出口评审（v4.1.0） |

## 4. archive/（历史快照）

| 文件 | 原位置（已移动） | 归档理由 |
|---|---|---|
| `archive/w3-08-package-manifest-dev-snapshot.md` | `w3/08-package-manifest.md`（已移动） | v4.0.0-dev-w3 开发快照，已被正式包清单取代；仍作为 W3-8⑤ 完成证据 |
| `archive/w3-real-corpus-candidates.md` | `w3/real-corpus-candidates.md`（已移动） | 语料初筛记录，评测结果已由 `w3/real-corpus-eval.*` 交付 |

## 5. 锚点说明与不可移动清单

`w0/`–`w4/` 中保留的 14 个文件**不是遗漏**，而是被仓库内不可修改的引用指向，移动会造成断链：

| 锚点 | 引用来源 |
|---|---|
| `w0/05-contract-freeze-report.md` | `contracts/changes/CP-W2-001-location-story.md` |
| `w0/07-gate-review.md` | `contracts/README.md`、`contracts/compatibility-v3.5.9.md` |
| `w0/issues.md` | `contracts/README.md` |
| `w0/w0-acceptance.md` | `contracts/compatibility-v3.5.9.md` 的 `reports/w0/**` 通配 |
| `w1/w1-acceptance.md` | `contracts/02-document-spec.md` |
| `w2/07-n1-gate-review.md` | `contracts/changes/CP-W2-001-location-story.md` |
| `w3/07-cp-w2-002-gate-review.md` | `contracts/changes/CP-W2-002-sdt-location.md` |
| `w3/07-cp-w2-002-post-review.md` | `contracts/README.md`、`contracts/changes/CP-W2-002-sdt-location.md` |
| `w3/10-exit-review.md` | `AGENTS.md` |
| `w3/w3-task-book.md` | `AGENTS.md` |
| `w3/real-corpus-eval.md` | `AGENTS.md`、`tests/real_corpus_eval.py` |
| `w3/real-corpus-eval.json` | `tests/real_corpus_eval.py` 默认 `--out` |
| `w3/12-independent-exit-review.md` | `CHANGELOG.md` |
| `w4/w4-9-exit-review.md` | `CHANGELOG.md` |

**规则**：解除某个锚点前，必须先取得对应引用方（尤其是冻结契约）的修改授权；否则不得移动。

## 6. 进行中：w5/（不得归档）

`w5/` 记录 OfficeCLI 后端集成与架构收敛。当前状态：**B0/B1/B1-R/B1-R2 已提交，G1.5 等待人工批准，B2/B3 未启动**。

按角色分布（文件清单以目录为准）：

- **架构与设计**：现状审计、能力对照表、目标架构（**设计提案，未实施**，不得当现状阅读）、迁移计划。
- **门禁与审查**：G1.5 最终审查与阻塞处理、R3 修复复验、提交准备、工作树隔离、任务书恢复审查。
- **同步方案**：GitHub 远程同步预检（不构成 Push 授权）。

阅读时必须先确认文档头部的“文档性质”（已实施 / 计划 / 提案 / 审查结论）。

## 7. 并行产物：documentation/

跨阶段的版本事实与 Release 说明，不属于任何单一 W 阶段：

- `documentation/version-facts.md`：版本、Tag、Release 与文档一致性调查。
- `documentation/releases/`：`README.md` 索引 + v3.4.1～v4.1.2 各版本 Release 说明正文。

该目录由并行工作维护，修改前需确认没有并发写入。

## 8. 清理记录：cleanup/

| 文件 | 说明 |
|---|---|
| `cleanup/cleanup-inventory.md` | 清理前完整清单、重复/过期分析、引用关系、测试基线 |
| `cleanup/cleanup-plan.md` | 逐文件 KEEP/MERGE/ARCHIVE/DELETE/REVIEW 计划 |
| `cleanup/cleanup-final-report.md` | 执行结果、目录迁移映射与验证证据 |

## 9. 新增报告约定

1. 已完成阶段的报告写入 `development/`、`acceptance/` 或 `archive/`，文件名以阶段前缀开头（如 `w4-…`）。
2. `w5/` 结束后同样迁移；迁移时在 `archive/` 保留被取代快照，并在本索引登记映射。
3. 每份报告头部必须声明：日期、阶段、输入、结论（PASS / CONDITIONAL_PASS / FAIL / 记录性）、是“当前状态”还是“历史记录”。
4. 不覆盖既有报告来表达新结论；新增修订记录或新文件，并在本索引登记。
5. 不写入外部语料路径、真实文档正文、凭据或个人信息。
6. 新增/移动报告后，必须复查 §5 的锚点清单与仓库内引用。
