# reports/ 索引

> 本文件是 `reports/` 的**唯一索引**。
> 更新日期：2026-11-07；基线：`main` @ `v4.2.1`。
> 所有新报告必须先确定角色，再写入对应目录；不得再向 `w0/`–`w3/` 新增文件。

## 1. 目录结构

```text
reports/
├── README.md          唯一索引（本文件）
├── current/           当前有效：阶段状态、架构结论、待办与阻塞、验收基线
├── development/       开发过程：任务书、实施记录、技术审计、计划与设计
├── acceptance/        最终验收：阶段验收、出口评审、发布证据、Release 说明
├── archive/           历史快照：被取代的报告、中间审查、历史版本资料
├── anchors/           特殊保护：冻结契约引用的锚点登记（文件原位保留）
└── w0/ w1/ w2/ w3/    仅存放 anchors 登记的 8 个锚点文件
```

## 2. current/（当前有效）

| 文件 | 内容 |
|---|---|
| `current/status.md` | 当前阶段状态（v4.2.1、W0–W5 进度、已完成/进行中） |
| `current/architecture-review.md` | 当前架构结论、分层、主链与剩余结构性技术债 |
| `current/backlog.md` | 当前待办与阻塞项（P0/P1 已清零，20 项 P2） |
| `current/acceptance-baseline.md` | 当前验收基线（测试、CI、发布资产、复现命令） |
| `current/version-facts.md` | 跨版本版本号 / Tag / Release 一致性调查 |

## 3. development/（开发过程）

### 3.1 任务书与阶段计划

| 文件 | 阶段 | 内容 |
|---|---|---|
| `development/w3-task-book.md` | W3 | W3 唯一修复任务书 |
| `development/w5-migration-plan.md` | W5 | 后端迁移计划（B0–B5） |

### 3.2 架构与设计

| 文件 | 阶段 | 内容 |
|---|---|---|
| `development/w4-0-architecture-audit.md` | W4 | W4 架构审计（执行入口与证据缺口） |
| `development/w5-architecture-audit.md` | W5 | W5 现状审计与能力缺口 |
| `development/w5-target-architecture.md` | W5 | 目标架构提案（**未实施**，不得当现状） |
| `development/w5-capability-matrix.md` | W5 | 后端能力对照表 |

### 3.3 实施记录与审计

| 文件 | 阶段 | 内容 |
|---|---|---|
| `development/w2-01-contract-change-manifest.md` | W2 | CP-W2-001 变更清单（4.1.0 历史哈希） |
| `development/w2-issues.md` | W2 | W2-I1～I6 问题登记册 |
| `development/w3-04b-implementation.md` | W3 | CP-W2-002 实施记录 |
| `development/w3-04b-manifest.md` | W3 | 契约集 4.2.0 冻结哈希 |
| `development/w3-07-w3-6-review.md` | W3 | W3-6（GENERATE 切 v4）独立复核 |
| `development/w3-07-w3-8-review.md` | W3 | W3-8 文档措辞抽查 |
| `development/w3-09-docs-cleanup-report.md` | W3 | 全量 Markdown 整理记录 |
| `development/w3-audit-triage.md` | W3 | 外部技术审计逐项裁定 |
| `development/w4-implementation-log.md` | W4 | W4-0～W4-8 实施记录 |
| `development/w5-g1.5-blocker-resolution.md` | W5 | G1.5 阻塞解除记录 |

## 4. acceptance/（最终验收与发布证据）

### 4.1 阶段验收与出口评审

| 文件 | 阶段 | 内容 |
|---|---|---|
| `acceptance/w2-acceptance.md` | W2 | W2 验收（含措辞更正） |
| `acceptance/w3-10-exit-review.md` | W3 | v4.0.0 出口证据与发布门禁 |
| `acceptance/w3-11-package-manifest-v4.0.0.md` | W3 | v4.0.0 发布包清单 |
| `acceptance/w3-12-independent-exit-review.md` | W3 | v4.0.0 独立出口审查（裁定 FAIL，触发合规补丁） |
| `acceptance/w3-13-v4.0.1-exit-evidence.md` | W3 | v4.0.1 出口证据（关闭 B1） |
| `acceptance/w3-14-package-manifest-v4.0.1.md` | W3 | v4.0.1 发布包清单 |
| `acceptance/w4-9-exit-review.md` | W4 | W4-9 出口评审（v4.1.0） |
| `acceptance/w4-package-manifest-v4.1.0.md` | W4 | v4.1.0 包清单 |
| `acceptance/w4-package-manifest-v4.1.1.md` | W4 | v4.1.1 包清单 |
| `acceptance/w4-package-manifest-v4.1.2.md` | W4 | v4.1.2 包清单 |
| `acceptance/w5-package-manifest-v4.2.0.md` | W5 | v4.2.0 包清单 |
| `acceptance/w5-package-manifest-v4.2.1.md` | W5 | v4.2.1 包清单（当前发布） |

### 4.2 Release 说明

`acceptance/releases/` 存放 v3.4.1～v4.1.2 的逐版本 Release 说明正文；v4.2.0 / v4.2.1 的说明以 GitHub Release 与 `CHANGELOG.md` 为准。

| 文件 | 版本 |
|---|---|
| `acceptance/releases/v3.4.1-archive.md` | v3.4.1（归档） |
| `acceptance/releases/v3.4.2.md` | v3.4.2 |
| `acceptance/releases/v3.5.2.md` | v3.5.2 |
| `acceptance/releases/v3.5.3.md` | v3.5.3 |
| `acceptance/releases/v3.5.4.md` | v3.5.4 |
| `acceptance/releases/v3.5.5.md` | v3.5.5 |
| `acceptance/releases/v3.5.7.md` | v3.5.7 |
| `acceptance/releases/v3.5.8.md` | v3.5.8 |
| `acceptance/releases/v3.5.9.md` | v3.5.9 |
| `acceptance/releases/v4.0.0-dev.1.md` | v4.0.0-dev.1 |
| `acceptance/releases/v4.0.0.md` | v4.0.0 |
| `acceptance/releases/v4.0.1.md` | v4.0.1 |
| `acceptance/releases/v4.1.0.md` | v4.1.0 |
| `acceptance/releases/v4.1.1.md` | v4.1.1 |
| `acceptance/releases/v4.1.2.md` | v4.1.2 |

## 5. archive/（历史快照）

| 文件 | 归档理由 |
|---|---|
| `archive/w3-08-package-manifest-dev-snapshot.md` | v4.0.0-dev-w3 开发快照，已被正式包清单取代 |
| `archive/w3-real-corpus-candidates.md` | 语料初筛记录，评测结果已交付 |
| `archive/real-corpus-eval.md` / `.json` | v4.0.0 时期真实语料评测结果（历史证据） |
| `archive/w5/w5-b1-r3-commit-preparation.md` | W5-B1-R3 提交准备记录 |
| `archive/w5/w5-b1-r3-fix-review.md` | W5-B1-R3 修复复验 |
| `archive/w5/w5-g1.5-b1-final-review.md` | G1.5 B1 最终审查快照 |
| `archive/w5/w5-g15-final-review.md` | G1.5 最终审查快照 |
| `archive/w5/w5-taskbook-recovery-review.md` | 任务书恢复审查 |
| `archive/w5/w5-worktree-isolation-review.md` | 工作树隔离审查 |
| `archive/w5/w5-github-sync-plan.md` | GitHub 同步预检方案（已被实际同步取代） |
| `archive/cleanup/cleanup-inventory.md` | 2026-11 目录治理前的完整清单 |
| `archive/cleanup/cleanup-plan.md` | 目录治理计划与迁移映射 |
| `archive/cleanup/cleanup-final-report.md` | 目录治理执行结果 |
| `archive/cleanup/worktree-change-audit.md` | 工作树变更审计 |

> `archive/` 内的路径引用保留写作时点，可能指向已迁移位置；它们是历史证据，不做回溯性改写。

## 6. anchors/（特殊保护）

`anchors/README.md` 登记被冻结契约引用的 8 个文件。这些文件**原位保留**在 `w0/`–`w3/`，因为移动会破坏 `contracts/` 中不可修改的引用：

| 锚点 | 引用来源 |
|---|---|
| `w0/05-contract-freeze-report.md` | `contracts/changes/CP-W2-001-location-story.md` |
| `w0/07-gate-review.md` | `contracts/README.md`、`contracts/compatibility-v3.5.9.md` |
| `w0/issues.md` | `contracts/README.md` |
| `w0/w0-acceptance.md` | `contracts/compatibility-v3.5.9.md` 的 `reports/w0/**` |
| `w1/w1-acceptance.md` | `contracts/02-document-spec.md`（FROZEN） |
| `w2/07-n1-gate-review.md` | `contracts/changes/CP-W2-001-location-story.md` |
| `w3/07-cp-w2-002-gate-review.md` | `contracts/changes/CP-W2-002-sdt-location.md` |
| `w3/07-cp-w2-002-post-review.md` | `contracts/README.md`、CP-W2-002 |

**规则**：解除锚点前必须先修改引用方；若引用方是冻结契约，必须走契约变更提案并升级契约版本。新增报告不得再写入这些目录。

## 7. 新增报告约定

1. **先定角色**：当前有效 → `current/`；过程/审计/任务书 → `development/`；验收/发布证据 → `acceptance/`；被取代或中间快照 → `archive/`。
2. 文件名以阶段或主题前缀开头（如 `w5-…`、`v4.2.1-…`），不使用空格。
3. 每份报告头部声明：日期、阶段、输入、结论（PASS / CONDITIONAL_PASS / FAIL / 记录性）、是“当前状态”还是“历史记录”。
4. 不覆盖既有报告来表达新结论；新增文件并在本索引登记，旧文件移入 `archive/`。
5. 不写入外部语料路径、真实文档正文、凭据或个人信息。
6. 移动报告后必须复查 `anchors/README.md` 与 `git grep "reports/w[0-9]/"`，确认没有新增断链。
