# reports/ 与 tests/ 清理前完整清单（Cleanup Inventory）

- 调查日期：2026-11-07（Asia/Shanghai）
- 调查对象：`d:\docs\officecli-template-filler`（分支 `main`，HEAD `37ec46f`）
- 调查性质：**只读**。本阶段未删除、未移动、未重命名、未修改任何 `reports/`、`tests/` 或业务代码文件。
- 调查方法：
  1. 递归文件清单（路径、大小、最后修改时间）；
  2. 逐文件读取头部、职责说明与关键结论；
  3. 全仓库引用检索（Markdown、Python、JSON、配置文件）；
  4. 内容相似度比对（按非空行集合计算 Jaccard 相似度）；
  5. 实际执行全量测试、契约测试与 Ruff。

---

## 1. Git 工作区基线（保护记录）

在执行任何操作前记录的原始状态：

```text
HEAD        : 37ec46f78eefd75da065a911371c864bb01b7dff
分支        : main（tracking origin/main，ahead 4）
已跟踪修改  : M document_backends/result.py
              M tests/w5/test_b1_result.py
未跟踪      : ?? dist/
              ?? reports/w5/
              ?? reports/documentation/   ← 调查期间由并行会话写入，见 §3.4
Stash       : 无
Tag         : v3.4.1-archive … v4.1.2（15 个，未改动）
```

**保护决定**：上述两个已跟踪修改属于 W5-B1-R3 输入边界修复（见 `reports/w5/w5-b1-r3-fix-review.md`），全程不覆盖、不 stash、不 reset、不 commit。`dist/` 与 `reports/documentation/` 为用户/并行会话产物，不纳入任何清理操作。

**调查期间观察到的并发变更**（10:09–10:10，非本任务所为）：

```text
 M README.md        （全文重写，+391/-…）
 M CHANGELOG.md     （全文重写，+852/-…）
```

这两处由另一个并行会话的版本事实整理工作写入。本任务全程未读取后回写、未暂存、未还原它们；第二阶段也不得修改这两个文件（原计划中的“目录注释更新”已因此撤回，见 cleanup-plan §3）。


---

## 2. 目录汇总

| 目录 | 文件数 | 体积 | 其中已跟踪 | 其中未跟踪 |
|---|---:|---:|---:|---:|
| `reports/` | 42 | 534.9 KB | 33 | 9 |
| `tests/` | 94（不含 `.pyc`） | 989.7 KB | 94 | 0 |
| `tests/**/__pycache__/` | 123 个 `.pyc` | — | 0 | 0（已被 `.gitignore` 忽略） |

`reports/` 按周分区：w0 = 4、w1 = 1、w2 = 4、w3 = 18、w4 = 6、w5 = 8（未跟踪）、documentation = 1（未跟踪）。
`tests/` 按层分区：根目录 49 个 `.py`、`contracts/` 12 个 `.py`、`w5/` 4 个 `.py`、`fixtures/` 1 个生成脚本 + 28 个资产文件。

---

## 3. reports/ 完整清单

### 3.1 逐文件清单

「引用数」= 仓库内其他文件（含 contracts、AGENTS、README、CHANGELOG、其他报告）显式提到该路径的次数。

| # | 文件 | 类型 | 大小 | 修改时间 | 阶段 | 对应任务 / 用途 | 内容重复 | 已被取代 | 引用数 | 历史价值 |
|---:|---|---|---:|---|---|---|---|---|---:|---|
| 1 | `w0/05-contract-freeze-report.md` | MD | 8.9 KB | 11-05 19:30 | W0 | 契约集 4.0.0 冻结报告（Agent 05） | 否 | 否（自身标注为历史冻结证据） | 3 | 高：契约冻结原始证据 |
| 2 | `w0/07-gate-review.md` | MD | 10.1 KB | 11-05 19:30 | W0 | W0 独立门禁审查（Agent 07，PASS） | 否 | 否 | 4 | 高：被 contracts/README 与 compatibility 引用 |
| 3 | `w0/issues.md` | MD | 6.1 KB | 11-05 19:30 | W0 | 开放问题登记册（OI-01～OI-06 状态源） | 否 | 否（持续维护状态源） | 5 | 高：问题闭环唯一来源 |
| 4 | `w0/w0-acceptance.md` | MD | 5.3 KB | 11-05 19:30 | W0 | W0 最终验收 | 否 | 否 | 1 | 高：阶段验收 |
| 5 | `w1/w1-acceptance.md` | MD | 7.4 KB | 11-05 19:31 | W1 | W1 实施与验收（数据链可执行） | 否 | 否 | 4 | 高：被 Contract 02 引用（OI-01 关闭证据） |
| 6 | `w2/01-contract-change-manifest.md` | MD | 2.8 KB | 11-05 19:31 | W2 | CP-W2-001 变更清单（4.1.0 哈希） | 否（版本化清单） | 哈希已被 4.2.0 取代，文本已声明 | 1 | 中高：4.1.0 冻结证据 |
| 7 | `w2/07-n1-gate-review.md` | MD | 3.4 KB | 11-05 18:51 | W2 | CP-W2-001 复审（PASS，取代先前 CONDITIONAL_PASS） | 否 | 否 | 1 | 高：被 CP-W2-001 引用 |
| 8 | `w2/issues.md` | MD | 1.9 KB | 11-05 19:12 | W2 | W2 问题登记册（W2-I1～I6） | 否 | 否 | 3 | 高：问题闭环 |
| 9 | `w2/w2-acceptance.md` | MD | 8.1 KB | 11-05 19:33 | W2 | W2 验收（含“真实模板已验证”措辞更正） | 否 | 否 | 4 | 高：含重要口径更正 |
| 10 | `w3/w3-task-book.md` | MD | 12.9 KB | 11-05 19:31 | W3 | W3 唯一修复任务书 | 否 | 否 | 6 | 高：被 README/AGENTS 引用 |
| 11 | `w3/audit-triage.md` | MD | 3.7 KB | 11-05 19:31 | W3 | 外部技术审计逐项裁定 | 否 | 否 | 4 | 高：审计准入依据 |
| 12 | `w3/04b-implementation.md` | MD | 11.0 KB | 11-05 19:31 | W3 | CP-W2-002 实施记录（明确自身非冻结证据） | 否 | 否 | 1 | 高：实施证据 |
| 13 | `w3/04b-manifest.md` | MD | 3.1 KB | 11-05 19:38 | W3 | 契约集 4.2.0 冻结哈希清单 | 否 | 否 | 5 | 高：当前契约集哈希权威 |
| 14 | `w3/07-cp-w2-002-gate-review.md` | MD | 5.0 KB | 11-05 19:31 | W3 | CP-W2-002 提案阶段裁定 CONDITIONAL_PASS | 否 | 复审 PASS 已覆盖，但文件自述保留提案阶段裁定 | 2 | 高：被 CP-W2-002 引用 |
| 15 | `w3/07-cp-w2-002-post-review.md` | MD | 2.0 KB | 11-05 18:51 | W3 | CP-W2-002 实施后复审 PASS | 否 | 否 | 4 | 高：冻结前置条件 |
| 16 | `w3/07-w3-6-review.md` | MD | 3.8 KB | 11-05 19:31 | W3 | W3-6（GENERATE 主链切 v4）独立复核 PASS | 否 | 否 | 0 | 中：单点决策证据 |
| 17 | `w3/07-w3-8-review.md` | MD | 2.4 KB | 11-05 19:31 | W3 | W3-8 文档措辞抽查复审 PASS | 否 | 否 | 0 | 中：口径治理证据 |
| 18 | `w3/08-package-manifest.md` | MD | 2.0 KB | 11-05 20:04 | W3 | v4.0.0-dev-w3 开发快照清单 | 结构相似于 11/14，但为不同产物 | 被 `11-package-manifest.md` 取代为当前交付物 | 2 | 中：W3-8⑤ 完成证据（07-w3-8 引用） |
| 19 | `w3/09-docs-cleanup-report.md` | MD | 10.9 KB | 11-05 20:00 | W3 | 全量 Markdown 编辑整理记录 | 否 | 否 | 0 | 中：文档规范化决策 |
| 20 | `w3/10-exit-review.md` | MD | 6.0 KB | 11-05 21:10 | W3 | v4.0.0 出口证据与发布门禁 | 否 | 否 | 4 | 高：被 AGENTS 引用 |
| 21 | `w3/11-package-manifest.md` | MD | 2.3 KB | 11-05 21:21 | W3 | v4.0.0 发布包清单 | 结构相似，产物不同 | 否 | 2 | 高：v4.0.0 资产证据 |
| 22 | `w3/12-independent-exit-review.md` | MD | 23.7 KB | 11-05 21:42 | W3 | v4.0.0 独立出口审查（裁定 FAIL） | 否 | 否 | 2 | **高：唯一负面独立裁决，必须保留** |
| 23 | `w3/13-v4.0.1-exit-evidence.md` | MD | 4.9 KB | 11-05 22:34 | W3 | v4.0.1 合规补丁出口证据（关闭 B1） | 否 | 否 | 0 | 高：FAIL→关闭闭环 |
| 24 | `w3/14-package-manifest-v4.0.1.md` | MD | 2.2 KB | 11-05 22:33 | W3 | v4.0.1 发布包清单 | 结构相似，产物不同 | 否 | 2 | 高：v4.0.1 资产证据 |
| 25 | `w3/real-corpus-candidates.md` | MD | 2.8 KB | 11-05 19:32 | W3 | W3-9 语料候选初筛（自述“不是已交付语料包”） | 否 | 评测结果见 real-corpus-eval | 2 | 中：来源与合规边界证据 |
| 26 | `w3/real-corpus-eval.md` | MD | 2.7 KB | 11-05 22:33 | W3 | 真实语料匿名聚合评测报告 | 否 | 否 | 5 | 高：被 AGENTS/README 体系引用 |
| 27 | `w3/real-corpus-eval.json` | JSON | 75.3 KB | 11-05 22:33 | W3 | 同上的机器可读结果 | 否 | 否 | 2 | 高：被 `tests/real_corpus_eval.py` 作为默认输出路径 |
| 28 | `w4/w4-0-architecture-audit.md` | MD | 32.0 KB | 11-06 16:42 | W4 | W4 架构审计（执行入口/证据缺口） | 否 | 否 | 3 | 高：W5 审计基线 |
| 29 | `w4/w4-implementation-log.md` | MD | 6.1 KB | 11-06 16:42 | W4 | W4-0～W4-8 实施记录 | 否 | 否 | 0 | 高：阶段实施记录 |
| 30 | `w4/w4-9-exit-review.md` | MD | 6.0 KB | 11-06 16:42 | W4 | W4-9 出口评审（v4.1.0） | 否 | 否 | 2 | 高：阶段验收 |
| 31 | `w4/w4-package-manifest.md` | MD | 1.3 KB | 11-06 16:42 | W4 | v4.1.0 包清单 | 结构相似，产物不同 | 否 | 1 | 中高：版本证据 |
| 32 | `w4/w4-package-manifest-v4.1.1.md` | MD | 1.3 KB | 11-06 16:42 | W4 | v4.1.1 包清单 | 结构相似，产物不同 | 否 | 0 | 中高：版本证据 |
| 33 | `w4/w4-package-manifest-v4.1.2.md` | MD | 1.2 KB | 11-06 19:57 | W4 | v4.1.2 包清单 | 结构相似，产物不同 | 否 | 0 | 中高：版本证据 |
| 34 | `w5/w5-architecture-audit.md` | MD | 38.6 KB | 11-06 23:10 | W5-A | W5 现状审计（OfficeCLI 探针 P1–P9） | 否 | 否 | 3 | 高：W5 设计输入 |
| 35 | `w5/w5-capability-matrix.md` | MD | 14.8 KB | 11-06 23:11 | W5-A | 能力对照表（需实测证据） | 否 | 否 | 2 | 高：verified 列来源 |
| 36 | `w5/w5-target-architecture.md` | MD | 24.6 KB | 11-06 23:28 | W5-A | **设计提案，未实施** | 否 | 否 | 2 | 高：目标设计（不得当现状读） |
| 37 | `w5/w5-migration-plan.md` | MD | 43.7 KB | 11-07 00:28 | W5-A/B1 | 迁移计划与 B0/B1/B1-R/B1-R2 执行记录 | 否 | 否 | 2 | 高：W5 执行主线 |
| 38 | `w5/w5-g15-final-review.md` | MD | 28.6 KB | 11-07 09:33 | W5-B1 | G1.5 最终独立审查（建议 PASS，人工决定） | 否 | 否 | 1 | 高：门禁证据 |
| 39 | `w5/w5-github-sync-plan.md` | MD | 23.6 KB | 11-07 09:51 | W5 | 远程同步预检与方案（READY_FOR_SYNC_PLAN） | 否 | 否 | 0 | 高：同步依据 |
| 40 | `w5/w5-b1-r3-fix-review.md` | MD | 9.8 KB | 11-07 09:58 | W5-B1-R3 | R3 输入边界修复独立复验 | 否 | 否 | 0 | 高：对应当前未提交修改 |
| 41 | `w5/be95e82-review.patch` | PATCH | 38.0 KB | 11-07 00:16 | W5-B1 | `be95e82` 的 diff 快照 | **与 `git diff be95e82^ be95e82` 逐字节一致（已实测验证）** | 是（Git 历史为权威源） | 1 | 低：无独有证据 |
| 42 | `documentation/version-facts.md` | MD | 47.4 KB | 11-07 10:05 | 并行会话 | 版本事实调查（Releases/Tags/文档一致性） | 否 | 否 | 0 | **待定**：调查期间由并行会话写入，未跟踪 |

> 上表共 42 行，与快照时点 `reports/` 实际文件总数一致。

### 3.1A 快照后并行新增文件（本任务未创建，纳入索引管理）

以下 21 个文件由并行会话在 10:12–10:18 写入，补充登记以便索引完整。全部按 **KEEP** 处理，未读取后回写、未移动。

**`reports/documentation/`（16 个新增）**

| 文件 | 阶段/范围 | 用途 | 建议 |
|---|---|---|---|
| `documentation/releases/README.md` | 跨版本 | Release 说明改写与发布记录索引 | KEEP |
| `documentation/releases/v3.4.1-archive.md` | v3.4.1 | 归档版本说明 | KEEP |
| `documentation/releases/v3.4.2.md` | v3.4.2 | 版本说明 | KEEP |
| `documentation/releases/v3.5.2.md` … `v3.5.9.md`（7 个） | v3.5.x | 逐版本说明 | KEEP |
| `documentation/releases/v4.0.0-dev.1.md` | v4.0.0-dev.1 | 预发布说明 | KEEP |
| `documentation/releases/v4.0.0.md` | v4.0.0 | 稳定版说明 | KEEP |
| `documentation/releases/v4.0.1.md` | v4.0.1 | 稳定版补丁说明 | KEEP |
| `documentation/releases/v4.1.0.md` | v4.1.0 | Draft 版本说明 | KEEP |
| `documentation/releases/v4.1.1.md` | v4.1.1 | 预发布说明 | KEEP |
| `documentation/releases/v4.1.2.md` | v4.1.2 | 当前最新发布说明 | KEEP |

（`documentation/version-facts.md` 已在快照清单 #42 登记，此处不重复计数。）

**`reports/w5/`（5 个新增，W5 进行中）**

| 文件 | 用途 | 结论 | 建议 |
|---|---|---|---|
| `w5/w5-g1.5-b1-final-review.md` | G1.5 正式审查准备与 B1 最终验收 | CONDITIONAL_PASS | KEEP |
| `w5/w5-g1.5-blocker-resolution.md` | G1.5 三项遗留阻塞处理 | CONDITIONAL_PASS 保持 | KEEP |
| `w5/w5-b1-r3-commit-preparation.md` | R3 独立提交准备 | CONDITIONAL_READY | KEEP |
| `w5/w5-taskbook-recovery-review.md` | W5 任务书 §八 恢复检索 | BLOCKED（未恢复） | KEEP |
| `w5/w5-worktree-isolation-review.md` | 工作区隔离审查 | 需隔离外部改动 | KEEP |

> 上述文件涉及“外部改动归属”，其中 `w5-worktree-isolation-review.md` 把本清理任务的测试改动标记为 REVIEW（不混入 R3 提交）。该判定与本任务“不 commit”的约束一致，两者不冲突。

### 3.2 重复文件分析

按非空行集合计算 Jaccard 相似度，仅以下组合超过 12%：

| 组合 | 相似度 | 判定 |
|---|---:|---|
| `w4/w4-package-manifest.md` ↔ `w4/w4-package-manifest-v4.1.1.md` | 47.4% | **非重复**：同一模板的不同版本产物，哈希/大小/条目数/构建日期均不同 |
| `w4/w4-package-manifest-v4.1.2.md` ↔ `w4/w4-package-manifest-v4.1.1.md` | 38.5% | 同上 |
| `w4/w4-package-manifest.md` ↔ `w4/w4-package-manifest-v4.1.2.md` | 31.7% | 同上 |
| `w3/11-package-manifest.md` ↔ `w3/08-package-manifest.md` | 31.1% | **非重复**：dev 快照 vs 正式发布，产物与提交不同 |
| `w3/14-package-manifest-v4.0.1.md` ↔ `w3/11-package-manifest.md` | 29.2% | 同上 |
| `w3/14` ↔ `w3/08` | 25.5% | 同上 |

**结论：`reports/` 中不存在重复任务书、重复审查报告或重复验收报告。** 全部 42 个文件中，仅 1 个（`be95e82-review.patch`）可由 Git 历史无损重建，属于唯一“内容冗余”项。相似度高的 6 份 package manifest 是**同一交付流程在不同版本上的独立证据**，合并会丢失版本可追溯性。

### 3.3 过期 / 被取代分析

| 文件 | 状态判定 | 依据 |
|---|---|---|
| `w3/08-package-manifest.md` | 作为“当前交付物”已过期；作为历史证据有效 | 自身与 `07-w3-8-review.md` 均声明 v4.0.0-dev-w3 被正式包取代；但它是 W3-8⑤ 的完成证据 |
| `w2/01-contract-change-manifest.md` | 哈希已过期（4.1.0）；文本已声明当前为 4.2.0 | 文件头部有“Historical manifest”注记 |
| `w0/05-contract-freeze-report.md` | 哈希已过期（4.0.0）；文本已声明 | 文件头部有“Historical record”注记 |
| `w3/07-cp-w2-002-gate-review.md` | 裁定阶段已过去（CONDITIONAL_PASS）；文件自述保留 | 后续 `07-cp-w2-002-post-review.md` 为 PASS |
| `w5/w5-target-architecture.md` | **不是过期，是未实施** | 文件自述“设计提案，待人工确认；尚未实施” |
| `w5/*` 全部 | **不是已完成阶段** | W5 当前暂停在 G1.5，B2/B3 未启动 |

> 关键判定：**W5 处于进行中（G1.5 待人工批准）**，任何把 `reports/w5/` 标记为“已完成阶段历史资料”的操作都是错误的。

### 3.4 引用关系

#### 被冻结契约引用（**不可修改契约，移动即断链**）

| 契约文件 | 引用路径 | 行号 |
|---|---|---:|
| `contracts/02-document-spec.md` | `reports/w1/w1-acceptance.md` | 26 |
| `contracts/compatibility-v3.5.9.md` | `reports/w0/**` | 25 |
| `contracts/compatibility-v3.5.9.md` | `reports/w0/07-gate-review.md` | 63 |
| `contracts/README.md` | `reports/w0/issues.md` | 51 |
| `contracts/README.md` | `reports/w0/07-gate-review.md` | 70 |
| `contracts/README.md` | `reports/w3/07-cp-w2-002-post-review.md` | 93 |
| `contracts/changes/CP-W2-001-location-story.md` | `reports/w2/07-n1-gate-review.md` | 108 |
| `contracts/changes/CP-W2-001-location-story.md` | `reports/w0/05-contract-freeze-report.md` | 111 |
| `contracts/changes/CP-W2-002-sdt-location.md` | `reports/w3/07-cp-w2-002-gate-review.md` | 97 |
| `contracts/changes/CP-W2-002-sdt-location.md` | `reports/w3/07-cp-w2-002-post-review.md` | 98 |

共 **6 个冻结契约文件、10 处硬引用**，全部指向 `w0/`、`w1/`、`w2/`、`w3/` 的现有路径。

#### 被代码引用（硬编码默认路径）

| 文件 | 行号 | 内容 |
|---|---:|---|
| `tests/real_corpus_eval.py` | 474 | `--out` 默认 `reports/w3/real-corpus-eval.json` |
| `tests/real_corpus_eval.py` | 475 | `--report` 默认 `reports/w3/real-corpus-eval.md` |

#### 被治理/入口文档引用（下表为**调查时点**状态；`README.md`/`CHANGELOG.md` 正在被并行会话改写）

| 文件 | 引用 |
|---|---|
| `AGENTS.md` | `reports/w3/w3-task-book.md`、`reports/w3/real-corpus-eval.md`、`reports/w3/10-exit-review.md` |
| `README.md` | `reports/w3/w3-task-book.md`；目录说明写“`reports/` # W0–W3 验收、门禁与问题记录”（已滞后于 W4/W5） |
| `SKILL.md` | 目录说明写“`reports/` # W0–W4 acceptance, gate and issue records”（未含 W5） |
| `CHANGELOG.md` | `reports/w3/12-independent-exit-review.md`、`reports/w3/14-package-manifest-v4.0.1.md` |

#### 报告之间的引用

- `w0/w0-acceptance.md` → `w0/05`、`w0/07`、`w0/issues`
- `w2/w2-acceptance.md` → `w2/issues`
- `w3/10-exit-review.md` → `w3/11`、`w3/12`
- `w3/13-v4.0.1-exit-evidence.md` → `w3/14`
- `w4/w4-implementation-log.md` → `w4/w4-0`、`w4/w4-9`
- `w5/w5-migration-plan.md` → `w5` 其余 4 份
- `w5/w5-github-sync-plan.md` → `w5` 全部 + `be95e82-review.patch`

**无入站引用的报告（refs = 0）**：`w3/07-w3-6-review.md`、`w3/07-w3-8-review.md`、`w3/09-docs-cleanup-report.md`、`w3/13-v4.0.1-exit-evidence.md`、`w4/w4-implementation-log.md`、`w4/w4-package-manifest-v4.1.1.md`、`w4/w4-package-manifest-v4.1.2.md`、`w5/w5-b1-r3-fix-review.md`、`w5/w5-github-sync-plan.md`。
零引用**不等于**无价值：它们分别是单点决策、版本资产与最新门禁证据，均属独有记录。

---

## 4. tests/ 完整清单

### 4.1 汇总

| 项 | 数量 |
|---|---:|
| 测试文件（`test_*.py`） | 60（根 47 + contracts 10 + w5 3） |
| 测试方法 | 653（根 472 + contracts 72 + w5 109） |
| 非测试支撑脚本 | 3（`gate_helpers.py`、`real_corpus_eval.py`、`fixtures/generate_fixtures.py`） |
| 包标记文件 | 2（`contracts/__init__.py`、`w5/__init__.py`） |
| Fixture 资产 | 8 `.docx` + 19 `.json` + 1 `.png` |
| 字节码缓存 | 123 `.pyc`（3 个 `__pycache__` 目录，已被 `.gitignore` 忽略） |

### 4.2 根目录测试（47 个文件 / 472 用例）

| 文件 | 用例 | 验证目标（来自文件自述） | 重复判定 |
|---|---:|---|---|
| `test_v3_engine.py` | 50 | v3.0 综合引擎单元套件（8 项审查项与架构约束） | 独有：v3.5.9 兼容基线，AGENTS §3.1 明确保护 |
| `test_spec_builder.py` | 25 | DocumentSpec 4.0 生产、槽位、指纹、CLI 兼容 | 独有 |
| `test_fill_fidelity_inplace.py` | 18 | 授权填充不得重写 run 结构；残留学与指纹边界 | 独有：真实语料回归 |
| `test_qa_gate.py` | 18 | QAReport 4.0 gate/builder/full-runner（Contract 04） | 独有 |
| `test_fill_executor.py` | 16 | FillPlan 确定性执行、台账与事务边界 | 独有 |
| `test_plan_builder.py` | 15 | ContentPlan / FillPlan 构建与校验（Contract 03） | 与 contracts/test_plans 目标不同（前者生产、后者 schema 消费） |
| `test_package_guard.py` | 15 | ZIP 资源配额（P2-03），小配额注入 | 独有：安全相关 |
| `test_review_lifecycle.py` | 15 | 修订生命周期 T1–T5、快照与恢复 | 独有 |
| `test_sdt_discovery.py` | 15 | CP-W2-002 SDT 容器发现为 PROTECTED 可寻址位置 | 独有：契约实现侧 |
| `test_workflow.py` | 15 | 工作流 gate / profile / checkpoint / TOC | 独有 |
| `test_doc_gap_closure.py` | 13 | 过程文档所述能力的 6 项引擎缺口回归 | 独有：回归 |
| `test_content_and_image_truth.py` | 12 | SVG 双嵌入、矢量缺口、内容一致性、事实来源 | 独有：真实性 P0 |
| `test_environment_capabilities.py` | 12 | 环境能力探测（必需/可选/缺失三态） | 独有 |
| `test_e2e_v4.py` | 11 | W1-F 端到端：模板→spec→plans→执行→QA→提交 | 独有：端到端 |
| `test_image_roles_ocr_render.py` | 11 | 图片角色、OCR 降级、图表渲染状态 | 独有 |
| `test_layout_qa.py` | 11 | 版式指纹容忍内容替换 | 独有 |
| `test_research_logic.py` | 9 | 确定性逻辑检查与研究计划溯源 | 独有 |
| `test_template_gate_validator.py` | 10 | W4-6 Gate Validator 检查与错误码映射 | 独有 |
| `test_transaction.py` | 10 | v3.5 事务层（原子提交、QA 失败中止） | 与 `test_transaction_gate` 目标不同（前者事务本体，后者二次门禁） |
| `test_officecli_writer.py` | 8 | officecli writer 后端一致性（含 2 个 fixture 类） | 复用 fixture，但走不同后端，**非重复** |
| `test_p0_semantic_qa.py` | 8 | 路由、语义 QA profile、严重度、字体、文件锁 | 独有 |
| `test_spec_validator.py` | 17 | DocumentSpec 4.0 校验（Schema + Contract 02 §14） | 独有 |
| `test_sdt_detection.py` | 7 | W3-3 披露与上限（L3），fail-closed | 与 `test_sdt_discovery` 目标不同（披露 vs 发现） |
| `test_fixture_matrix.py` | 7 | W2 六类结构化回归 fixture 矩阵 | 独有：fixture 主入口 |
| `test_reformat_and_pdf.py` | 7 | WPS/LibreOffice PDF 路径与 REFORMAT diff | 独有 |
| `test_template_gate_store.py` | 7 | W4-5 Gate Record 持久化、HMAC、过期 | 独有：安全相关 |
| `test_excel_reliability.py` | 6 | v3.5 M4/M5 Excel 可靠性（含 2 项宿主依赖） | 独有（E2 例外，保留作真机补充） |
| `test_excel_status_merge.py` | 6 | W3-2 公式状态合并，渲染限制不得进入 FAILED | 独有 |
| `test_logic_alignment.py` | 6 | 标题检测归 `engine.alignment`，逻辑 QA 不依赖 workflow | 独有：依赖倒置 |
| `test_pdf_hygiene.py` | 6 | W3-1 PDF 临时副本绝不残留 | 独有：资源清理 |
| `test_template_gate_enforcement.py` | 6 | W4-7 所有正式执行入口拒绝未确认模板 | 独有：安全相关 |
| `test_template_gate_state.py` | 6 | W4-2 确定性状态机与非法迁移 | 独有 |
| `test_process_ownership.py` | 5 | 进程所有权判定（pid+映像名） | 独有：安全相关 |
| `test_router_capabilities.py` | 5 | 路由不得命名引擎无法执行的模式 | 独有 |
| `test_table_signature.py` | 8 | 表格签名 T5，解释模板漂移 | 独有 |
| `test_template_evidence.py` | 8 | W4-1 证据登记、四态分类、冲突检测 | 独有 |
| `test_template_gate_incremental.py` | 8 | W4-4 补充材料、冲突、增量重析 | 独有 |
| `test_template_gate_report.py` | 5 | W4-3 报告结构、Markdown 渲染与 CLI | 独有 |
| `test_w2_defects.py` | 5 | W2 fixture 矩阵发现的 4 个缺陷回归 | **独有回归，必须保留** |
| `test_excel_spec_resilience.py` | 4 | 真实 Excel 不崩溃/不挂起（全量/只读扫描） | 独有：健壮性 |
| `test_residual_inheritance.py` | 4 | 未注册 token 不得阻塞授权填充 | 独有：回归 |
| `test_soffice_profile_isolation.py` | 4 | 每次 soffice 调用独立 `-env:UserInstallation` | 独有 |
| `test_review_findings.py` | 3 | REVIEW 外部 findings → 内联批注，不出独立报告 | 独有 |
| `test_skill_workflow_v4.py` | 3 | SKILL.md 文档主链必须走 v4 plan chain | 独有：文档-实现一致性 |
| `test_template_gate_e2e.py` | 2 | W4-9 block→resolve→report→confirm→generate | 独有：端到端 |
| `test_proofread.py` | 1 | PROOFREAD 单文档修订交付 | 独有 |

### 4.3 contracts/ 测试（10 个文件 / 72 用例）

| 文件 | 用例 | 验证目标 |
|---|---:|---|
| `test_plans.py` | 12 | ContentPlan / FillPlan schema 正反例 |
| `test_slot_id.py` | 9 | 槽位 ID 契约向量 |
| `test_cross_contract.py` | 8 | 跨契约一致性 |
| `test_qa_report.py` | 8 | QAReport schema 与严重度规则 |
| `test_schemas.py` | 8 | 全部 JSON Schema 可解析与元校验 |
| `test_document_spec.py` | 7 | DocumentSpec 4.0 schema 向量 |
| `test_tool_envelope.py` | 7 | ToolEnvelope 与错误码 envelope |
| `test_error_registry.py` | 6 | 错误码注册表唯一性与完整性 |
| `test_legacy_compat.py` | 5 | v3.5.9 公共 API 与旧 schema 兼容 |
| `test_template_gate_schema.py` | 2 | Contract 06 三份 schema |
| `helpers.py` | — | 共享加载/校验工具（非测试） |
| `__init__.py` | — | 包标记 |

**全部为契约测试，属于最高保护级别，任何情况下不得删除或弱化。**

### 4.4 w5/ 测试（3 个文件 / 109 用例）

| 文件 | 用例 | 验证目标 |
|---|---:|---|
| `test_b1_result.py` | 64 | 后端结果不变量、reason 词汇、注册表映射（当前含未提交 R3 新增用例） |
| `test_b1_base.py` | 38 | BackendTarget / BackendOp 输入边界与契约镜像；**含 1 组重复方法体 + 1 个测试名与目标不符（见 §5.1）** |
| `test_b1_registry.py` | 7 | 错误码注册表与 reason code 一致 |
| `__init__.py` | — | 包标记 |

**属于进行中的 W5-B1，不得归档、不得合并进其他目录。**

### 4.5 Fixture 资产

| 类别 | 内容 | 使用方 |
|---|---|---|
| `fixtures/class_01`…`class_06` | 每类：`template.docx`、`content_plan.json`、`fill_plan.json`、`expected/expected.json` | `test_fixture_matrix.py`、`test_officecli_writer.py` |
| `class_04_images/replacement.png` | 图片替换源 | `test_fixture_matrix.py`、`test_w2_defects.py` |
| `class_05_nested_structure/fill_plan_paragraph_level.json` | 段落级计划变体 | `test_fixture_matrix.py:433`、`expected.json` |
| `fixtures/legacy/legacy_ref.docx` / `legacy_out.docx` | v3.5.9 真实产物与参考 | `contracts/test_legacy_compat.py`、`test_qa_gate.py`、`test_environment_capabilities.py` |
| `fixtures/generate_fixtures.py` | 可重建全部 fixture 的生成脚本 | 人工/CI 重建 |

全部 fixture 均有实际使用方，**无孤儿资产**。

---

## 5. tests/ 重复分析

### 5.1 完全重复的测试

用 **AST 归一化方法体**（剥离 docstring、保留结构与常量）对全部 60 个文件、653 个测试方法做哈希比对，结果：

| 检测项 | 结果 |
|---|---|
| 归一化方法体完全相同的分组 | **1 组（同文件内 2 个方法）** |
| 跨文件同名且方法体相同 | 0 |
| 跨文件方法体 Jaccard ≥ 0.9 的近似对 | 0 |

**唯一重复组的详证**：

```text
tests/w5/test_b1_base.py::CapabilityRecordTests
  test_verified_without_evidence_is_rejected   L126-128
  test_available_without_evidence_is_rejected  L130-132
两者方法体完全相同：
  with self.assertRaises(ValueError):
      _verified_record(verified_by=())
```

这不是“两个名字测同一件事”的合理重复，而是**第二个测试没有覆盖其命名的不变量**：

- `document_backends/base.py:191` 的规则是「`verified=True` 且无 `verified_by` → 拒绝」；
- `base.py:193` 的规则是「`available=True` 且未验证 → 拒绝」；
- 两个用例都传 `verified_by=()`，而 `_verified_record` 的默认 `verified=True`，因此两者都在 `base.py:191` 提前抛出，`base.py:193` 这条 W5-B1 requirement 7 的核心防线**实际没有独立用例**。

**判定**：保留两个用例名称（它们对应两条不同不变量），把第二个的输入改为 `_verified_record(verified=False, verified_by=())`，即可消除重复并真正覆盖 `base.py:193`。用例数不变（653），覆盖能力**增强**而非下降。详见 cleanup-plan §2.2。

其他同名方法分布在不同类或不同契约层，逐项核对结论：

| 同名方法 | 位置 | 判定 |
|---|---|---|
| `test_class_01_basic_report` / `test_class_02_complex_table` | `test_fixture_matrix` vs `test_officecli_writer` | 同一 fixture，**不同写入后端**（python-docx vs officecli），一致性对照，保留 |
| `test_codes_are_unique` | `contracts/test_error_registry` vs `w5/test_b1_registry` | 前者校验 envelope 错误码，后者校验 backend reason code，目标不同 |
| `test_duplicate_sequence_is_rejected` | `test_plan_builder` vs `contracts/test_plans` | 生产侧拒绝 vs schema 侧拒绝 |
| `test_high_severity_must_be_blocking` | `test_qa_gate` vs `contracts/test_qa_report` | 语义校验 vs schema 校验 |
| `test_valid_cases` / `test_missing_and_type_errors` | contracts 三个文件内 | 各自独立 schema 的正反例，同构不同物 |

**测试发现覆盖（用 `unittest.TestLoader` 实测）**：

```text
discovered_modules=60  on_disk_test_modules=60
undiscovered=[]        discovered_not_on_disk=[]
discovered_cases=653   naming_outliers=[]
```

即：磁盘上 60 个 `test_*.py` 全部被 `unittest discover -s tests -p "test_*.py"` 加载，无漏收文件，无命名不符合 `test_*.py` 约定的测试文件。

### 5.2 辅助代码重复（可合并）

| 辅助函数 | 位置 | 是否字面相同 | 建议 |
|---|---|---|---|
| `_sha256(path)` | `test_e2e_v4.py:40`、`test_fixture_matrix.py:68`、`test_w2_defects.py:49`、`test_transaction_gate.py:38` | 前三者逐字相同；第四个仅分块大小不同（1 MB vs 64 KB），输出一致 | MERGE 到共享测试工具 |
| `_passing_qa(staged)` | `test_template_gate_e2e.py:28`、`test_template_gate_enforcement.py:44` | 逐字相同 | MERGE |
| `_source_docx` / `_staged_leftovers` | `test_transaction.py:46/52`、`test_transaction_gate.py:79/87` | 形状相同，前者为类方法且参数化 `text` | REVIEW（合并收益低、改调用点多） |
| `_template(directory)` | 5 处（含 `test_fill_fidelity_inplace` 两个同名方法） | **内容不同**：分别构造空白、红字强调、表格、占位符模板 | KEEP（同名不同物） |
| `_standard_template` | `test_template_evidence` vs `test_template_gate_store` | **内容不同** | KEEP |

### 5.3 相似但验证目标不同的（不得合并）

- `test_sdt_detection.py`（披露与上限）vs `test_sdt_discovery.py`（发现与可寻址）——W3-3 与 W3-4B 两阶段，契约不同。
- `test_transaction.py`（事务本体）vs `test_transaction_gate.py`（二次门禁绑定）。
- `test_excel_reliability` / `test_excel_status_merge` / `test_excel_spec_resilience`——M4/M5 基线、W3-2 状态合并、扫描健壮性三者正交。
- `test_qa_gate.py`（运行时 gate）vs `contracts/test_qa_report.py`（schema 契约）。
- `test_fill_executor` / `test_fill_fidelity_inplace` / `test_fixture_matrix`——执行器语义、格式保真回归、fixture 矩阵。

### 5.4 失效 / 弱断言 / 未覆盖测试

| 检查项 | 结果 |
|---|---|
| 失效测试（导入不存在模块、断言已废弃行为） | **0 个**：全量 653 项全部通过 |
| 缺失断言的测试 | **0 个**：`assert*` 密度最低的文件为 `w5/test_b1_base.py`（46 次断言 / 38 用例），差异来自 `assertRaises` 用法，非弱断言 |
| **测试名与验证目标不符** | **1 个**：`test_b1_base.py::test_available_without_evidence_is_rejected` 实际验证的是另一条不变量（详见 §5.1）。这是本次调查发现的唯一测试语义缺陷，修复后覆盖增强 |
| `assertTrue(True)` 类空断言 | **0 个**（`test_transaction.py:168` 的 `pass` 位于 `with self.assertRaises(...)` 块内，用于证明异常在进入上下文前抛出） |
| `@skip` / `expectedFailure` | **0 个**（`test_officecli_writer` 的 2 项 `skipUnless` 在本机满足条件，实际未跳过） |
| 未被测试入口覆盖的测试文件 | **0 个**；`gate_helpers.py`、`real_corpus_eval.py`、`generate_fixtures.py` 为支撑脚本，按设计不参与发现 |
| 与旧版本实现绑定的测试 | `test_v3_engine.py`、`test_router_capabilities.py`、`test_workflow.py` 等为 v3.5.9 兼容基线，AGENTS §3.1 明确禁止删除 |

### 5.5 目录与命名的结构性风险（重要）

当前根目录 47 个 `test_*.py` 平铺。若按 `tests/unit/`、`tests/integration/` 重构：

| 风险 | 量化证据 |
|---|---|
| 路径上跳失效 | **30 个文件**使用 `Path(__file__).resolve().parents[1]` 定位仓库根，下移一层后需全部改为 `parents[2]` |
| Fixture 相对路径失效 | 3 个文件以 `Path(__file__).resolve().parent / "fixtures"` 定位（`test_fixture_matrix.py:44`、`test_officecli_writer.py:38`、`test_w2_defects.py:44`） |
| 顶层辅助模块导入 | `from gate_helpers import ...` 依赖 `-s tests` 作为 `top_level_dir`；`tests/w5` 还各自 `sys.path.insert` |
| 项目约定 | `requirements-dev.txt`、`README.md:197`、`CHANGELOG.md` 均固定 `-s tests -p "test_*.py"`；移动不改变发现结果，但会放大 diff 与审查面 |

**结论**：现有 `根（W0–W2 单元/回归）+ contracts（契约）+ w5（W5-B1）+ fixtures` 的四层划分已经对应真实职责。为套用 `unit/integration/...` 而整体搬迁，需要改动 ≥33 个文件的路径算术，收益是“视觉分类”，代价是审查面与回归风险。

---

## 6. 当前测试数量与结果（清理前基线）

| 项 | 命令 | 结果 |
|---|---|---|
| 全量测试 | `py -3.15 -m unittest discover -s tests -p "test_*.py"` | **Ran 653 tests in 224.723s — OK**（0 失败 / 0 错误 / 0 跳过） |
| 契约测试 | `py -3.15 -m unittest discover -s tests/contracts -t tests -p "test_*.py"` | **Ran 72 tests in 1.309s — OK** |
| W5 专项 | `py -3.15 -m unittest discover -s tests/w5 -t . -p "test_*.py"` | 109 项（含于全量 653 中） |
| Ruff | `py -3.15 -m ruff check .` | **All checks passed!**（exit 0） |
| 覆盖率 | 项目无覆盖率配置（无 pytest、无 coverage 配置、无 CI 工作流） | 不适用；以用例数与关键场景矩阵代替 |

环境：Windows 11 / PowerShell 7 / Python 3.15.0 / `unittest`（**项目不使用 pytest**）/ officecli 1.0.160 已安装（`C:\Users\ASUS\AppData\Local\OfficeCLI\officecli.exe`，因此 2 项集成测试未跳过）。

> 项目不存在 `.github/workflows`，不存在 `pytest.ini`/`pyproject.toml`/`setup.cfg`。固定测试入口来自 `requirements-dev.txt`、`README.md:197`、`CHANGELOG.md` 与各阶段报告的实测命令。第二阶段必须继续使用 `unittest` 命令，不得替换为 pytest。

---

## 6A. 执行阶段并发变更记录（快照之后的差异）

本清单是 **2026-11-07 10:11** 的只读快照。进入第二阶段后观察到并行会话持续写入 `reports/`，因此目录实际内容已多于本清单：

| 时间 | 并发新增 | 目录 |
|---|---|---|
| 10:12–10:14 | `documentation/releases/` 下 17 个版本说明文件（含 `README.md` 索引） | `reports/documentation/releases/` |
| 10:16 | `version-facts.md` 更新 | `reports/documentation/` |
| 10:16–10:18 | 5 个 W5 审查/恢复记录（任务书恢复、工作树隔离、R3 提交准备、G1.5 阻塞解除等） | `reports/w5/` |

处理原则：

1. 上述文件**全部不属于本任务**，未读取后回写、未移动、未删除。
2. 本清单的“42 个文件”仅指快照时点；执行后的目录总数以 `cleanup-final-report.md` 的实测值为准。
3. `reports/README.md` 对这部分的索引采用**角色约定**而非冻结清单，避免索引随并行工作立即过期。

---

## 7. 建议汇总

| 操作 | reports（42 文件） | tests（94 文件） | 合计 |
|---|---:|---:|---:|
| KEEP | 40 | 87 | 127 |
| MERGE | 0 | 7（`_sha256` × 4、`_passing_qa` × 2、`test_b1_base.py` 重复用例修复） | 7 |
| ARCHIVE | 0 | 0 | 0 |
| DELETE | 1（`be95e82-review.patch`） | 0（源码）；另删 3 个 `__pycache__` 目录 / 123 个 `.pyc` | 1 |
| REVIEW | 1（`documentation/version-facts.md`） | 0（`_source_docx` 与目录重构经评估后维持原样） | 1 |

新增（非清理动作，第二阶段执行）：
- `tests/support.py`（承载合并后的测试辅助函数）
- `reports/README.md`（唯一索引）
- `reports/cleanup/cleanup-final-report.md`（第三阶段）

**核心结论**：`reports/` 与 `tests/` 都**不存在需要大规模清理的重复文件**。真正的治理价值集中在：删除 1 个可再生成补丁、清除字节码缓存、建立唯一索引、合并 2 组重复测试辅助函数、修正 1 组重复测试用例（同时补足一条未被独立覆盖的安全不变量）、以及明确“W5 进行中不得归档”的边界。

---

## 8. 执行后目录结构（2026-11-07 收尾）

在用户批准“处理遗留问题 2”后，`reports/` 已从纯逻辑分类升级为**物理角色目录 + 冻结引用锚点**：

```text
reports/
├── README.md                       唯一索引
├── development/    10             开发过程（任务书、审计、实施、评审、问题、变更清单）
├── acceptance/      7             最终验收（验收、出口证据、发布包清单）
├── archive/         2             已被取代的历史快照
├── w0/              4  ┐
├── w1/              1  │
├── w2/              1  ├ 14 个冻结引用锚点（不移动）
├── w3/              7  │
├── w4/              1  ┘
├── w5/             12             W5 进行中（不归档）
├── documentation/  17             版本事实与 Release 说明（并行维护）
└── cleanup/         3             本任务的清单、计划、最终报告
```

- 移动 19 份、保留锚点 14 份、未触碰 `w5/`、`documentation/`、`cleanup/`。
- 因移动失效的 42 处 Markdown 引用已全部更新；冻结契约与 `tests/real_corpus_eval.py` 的引用全部指向锚点，**无需修改**。
- 逐文件映射见 `cleanup-plan.md` §6.1，锚点清单见 §6.2 与 `reports/README.md` §5。

> 因此本清单 §7 中 “ARCHIVE = 0” 是执行前的建议值；最终实际归档 2 份（`archive/`）。

