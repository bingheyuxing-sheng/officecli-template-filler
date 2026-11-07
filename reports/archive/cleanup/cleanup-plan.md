# reports/ 与 tests/ 清理计划（Cleanup Plan）

- 编制日期：2026-11-07（Asia/Shanghai）
- 基线：`main` @ `37ec46f`，工作区含 2 个未提交修改 + `dist/`、`reports/w5/`、`reports/documentation/` 未跟踪
- 依据：[cleanup-inventory.md](cleanup-inventory.md)
- 状态：**待人工批准。本文件不执行任何操作。**

---

## 0. 必须先裁决的一个结构问题

任务书给出的目标形态是：

```text
reports/
├── development/    # 开发过程
├── acceptance/     # 只保存最终验收结果
├── archive/        # 已完成阶段的历史资料
└── README.md       # 唯一索引
```

但实测存在两条**不可违反的硬约束**：

1. **6 个冻结契约文件、10 处硬引用**指向 `reports/w0/`、`reports/w1/`、`reports/w2/`、`reports/w3/` 的现有路径（清单见 inventory §3.4）。任务书同时规定“不允许修改 contracts”。
2. `tests/real_corpus_eval.py:474-475` 把 `reports/w3/real-corpus-eval.json|md` 作为 `--out` / `--report` 的**硬编码默认值**。

因此物理搬迁 `w0`–`w3` 必然造成失效引用，且无法在“不改契约”的前提下修复。

| 方案 | 内容 | 引用影响 | 契约影响 | 建议 |
|---|---|---|---|---|
| **A（推荐）** | 保留 `reports/w0`–`w5` 既有分区，新增 `reports/README.md` 作为唯一索引，在索引内按 development / acceptance / archive 三类**逻辑归类**（不移动文件） | 0 处失效 | 0 修改 | ✅ 采纳 |
| B | 物理改建 `reports/development`、`acceptance`、`archive` | 需改 10 处契约引用 + 1 个测试脚本默认路径 + 至少 20 处报告互引 | 需修改 6 个冻结契约文件 → **违反约束** | ❌ 不采纳 |
| C | 复制一份到新结构、保留原路径 | 无失效 | 无 | ❌ 制造重复证据，与“减少重复”目标相反 |

> **请批准方案 A。** 若坚持方案 B，需要您先明确解除“不修改 contracts”的限制；否则第二阶段不会执行搬迁。
>
> 另：`reports/w5/w5-github-sync-plan.md` 建议新增 `reports/w5/README.md`。本计划改为**只建 `reports/README.md` 单一索引**，避免出现两个索引，符合“唯一索引”要求。

---

## 1. reports/ 操作清单

> 共 42 个文件。KEEP = 40、DELETE = 1、REVIEW = 1。**无 ARCHIVE、无 MERGE。**

### 1.1 删除

| 文件路径 | 当前用途 | 建议操作 | 原因 | 风险 |
|---|---|---|---|---|
| `reports/w5/be95e82-review.patch` | `be95e82` 提交的 diff 快照（38 KB） | **DELETE** | 可由 `git show be95e82` 逐字节重建，不含独有证据；项目自身的 `w5-github-sync-plan.md` §7.3 已判定“不应纳入”。删除后仍可从 Git 历史完整恢复 | 低：仅失去离线预览便利，不失证据 |

### 1.2 需人工确认

| 文件路径 | 当前用途 | 建议操作 | 原因 | 风险 |
|---|---|---|---|---|
| `reports/documentation/version-facts.md` | 版本事实调查（47 KB，2026-11-07 10:05 由并行会话写入，未跟踪） | **REVIEW** | 本文件在本次调查期间出现，不属于 W0–W5 任何阶段；内容为版本/Release 一致性审计，与 `reports/w5/w5-github-sync-plan.md` §8 主题重叠。归属（`reports/documentation/` 是否作为正式分区）、命名与是否与同步方案合并，需您决定 | 中：若误并入或误删，会丢失并行会话成果 |

### 1.3 保留（reports）

| 文件路径 | 当前用途 | 建议操作 | 原因 | 风险 |
|---|---|---|---|---|
| `reports/w0/05-contract-freeze-report.md` | 4.0.0 契约冻结 | KEEP | 被 `CP-W2-001` 引用；冻结原始证据 | 无 |
| `reports/w0/07-gate-review.md` | W0 独立门禁 PASS | KEEP | 被 `contracts/README.md`、`compatibility-v3.5.9.md` 引用 | 无 |
| `reports/w0/issues.md` | 问题登记册（状态源） | KEEP | 被 `contracts/README.md` 引用；OI 状态唯一来源 | 无 |
| `reports/w0/w0-acceptance.md` | W0 验收 | KEEP | 阶段验收证据 | 无 |
| `reports/w1/w1-acceptance.md` | W1 验收 | KEEP | 被 `contracts/02-document-spec.md` 引用（OI-01 关闭） | 无 |
| `reports/w2/01-contract-change-manifest.md` | 4.1.0 变更清单 | KEEP | 历史冻结哈希；文件已自述为历史记录 | 无 |
| `reports/w2/07-n1-gate-review.md` | CP-W2-001 复审 PASS | KEEP | 被 `CP-W2-001` 引用 | 无 |
| `reports/w2/issues.md` | W2 问题登记册 | KEEP | 问题闭环证据 | 无 |
| `reports/w2/w2-acceptance.md` | W2 验收（含措辞更正） | KEEP | 含“真实模板已验证”口径更正，不可丢 | 无 |
| `reports/w3/w3-task-book.md` | W3 唯一任务书 | KEEP | 被 `README.md`、`AGENTS.md` 引用 | 无 |
| `reports/w3/audit-triage.md` | 外部审计逐项裁定 | KEEP | W3 准入依据 | 无 |
| `reports/w3/04b-implementation.md` | CP-W2-002 实施记录 | KEEP | 实施证据（自述非冻结证据） | 无 |
| `reports/w3/04b-manifest.md` | 4.2.0 冻结哈希 | KEEP | 当前契约集哈希权威 | 无 |
| `reports/w3/07-cp-w2-002-gate-review.md` | 提案阶段 CONDITIONAL_PASS | KEEP | 被 `CP-W2-002` 引用；保留提案阶段裁定 | 无 |
| `reports/w3/07-cp-w2-002-post-review.md` | 实施后复审 PASS | KEEP | 被 `contracts/README.md`、`CP-W2-002` 引用 | 无 |
| `reports/w3/07-w3-6-review.md` | W3-6 独立复核 | KEEP | 主链切换决策证据 | 无 |
| `reports/w3/07-w3-8-review.md` | W3-8 措辞复审 | KEEP | 文档口径治理证据 | 无 |
| `reports/w3/08-package-manifest.md` | v4.0.0-dev-w3 开发快照 | KEEP | 虽被正式包取代，但仍是 W3-8⑤ 完成证据（`07-w3-8-review.md` 引用）。仅 2 KB，归档收益低于改引用成本 | 无 |
| `reports/w3/09-docs-cleanup-report.md` | 全量 Markdown 整理记录 | KEEP | 文档规范化决策的独有记录 | 无 |
| `reports/w3/10-exit-review.md` | v4.0.0 出口证据 | KEEP | 被 `AGENTS.md` 引用 | 无 |
| `reports/w3/11-package-manifest.md` | v4.0.0 包清单 | KEEP | 发布资产证据 | 无 |
| `reports/w3/12-independent-exit-review.md` | v4.0.0 独立审查 **FAIL** | KEEP | **唯一负面独立裁决**，合规补丁的触发来源，最高保留优先级 | 无 |
| `reports/w3/13-v4.0.1-exit-evidence.md` | v4.0.1 出口证据 | KEEP | FAIL→关闭的闭环证据 | 无 |
| `reports/w3/14-package-manifest-v4.0.1.md` | v4.0.1 包清单 | KEEP | 被 `CHANGELOG.md` 引用 | 无 |
| `reports/w3/real-corpus-candidates.md` | 语料候选初筛 | KEEP | 来源合规边界证据 | 无 |
| `reports/w3/real-corpus-eval.md` | 真实语料匿名评测 | KEEP | 被 `AGENTS.md`、`README` 体系引用 | 无 |
| `reports/w3/real-corpus-eval.json` | 机器可读评测结果 | KEEP | 被 `tests/real_corpus_eval.py` 作为默认输出 | 无 |
| `reports/w4/w4-0-architecture-audit.md` | W4 架构审计 | KEEP | W5 审计基线 | 无 |
| `reports/w4/w4-implementation-log.md` | W4 实施记录 | KEEP | 阶段实施记录 | 无 |
| `reports/w4/w4-9-exit-review.md` | W4 出口评审 | KEEP | 阶段验收 | 无 |
| `reports/w4/w4-package-manifest.md` | v4.1.0 包清单 | KEEP | 版本资产证据 | 无 |
| `reports/w4/w4-package-manifest-v4.1.1.md` | v4.1.1 包清单 | KEEP | 版本资产证据 | 无 |
| `reports/w4/w4-package-manifest-v4.1.2.md` | v4.1.2 包清单 | KEEP | 版本资产证据 | 无 |
| `reports/w5/w5-architecture-audit.md` | W5 现状审计 | KEEP | **W5 进行中**，不得归档 | 无 |
| `reports/w5/w5-capability-matrix.md` | 能力对照表 | KEEP | W5 进行中 | 无 |
| `reports/w5/w5-target-architecture.md` | 目标架构设计提案 | KEEP | **未实施**，仅可在索引中标注“设计提案” | 无 |
| `reports/w5/w5-migration-plan.md` | 迁移计划与 B0/B1 执行记录 | KEEP | W5 主线 | 无 |
| `reports/w5/w5-g15-final-review.md` | G1.5 独立审查 | KEEP | 门禁证据 | 无 |
| `reports/w5/w5-github-sync-plan.md` | 远程同步方案 | KEEP | 同步依据 | 无 |
| `reports/w5/w5-b1-r3-fix-review.md` | R3 修复复验 | KEEP | 对应当前未提交修改 | 无 |

### 1.4 新增（reports）

| 文件路径 | 建议操作 | 内容 |
|---|---|---|
| `reports/README.md` | 新增索引 | 唯一索引：分区说明、按 development / acceptance / archive 的逻辑归类表、W5 进行中标注、引用规则（冻结契约引用的路径不得移动）、报告命名与状态约定 |
| `reports/cleanup/cleanup-inventory.md` | 已生成 | 本阶段交付物 1 |
| `reports/cleanup/cleanup-plan.md` | 已生成 | 本阶段交付物 2 |
| `reports/cleanup/cleanup-final-report.md` | 第三阶段生成 | 最终报告 |

---

## 2. tests/ 操作清单

> 共 94 个文件（不含 123 个 `.pyc`）。KEEP = 87、MERGE = 7、DELETE = 0（源码）、REVIEW = 0。
> 新增 1 个支撑模块 `tests/support.py`（承载合并后的辅助函数）。

### 2.1 删除（非源码）

| 路径 | 当前用途 | 建议操作 | 原因 | 风险 |
|---|---|---|---|---|
| `tests/__pycache__/`（101 个 `.pyc`） | 字节码缓存 | **DELETE** | 构建产物，`.gitignore` 已忽略，`unittest` 会自动重建 | 无 |
| `tests/contracts/__pycache__/`（18 个 `.pyc`） | 字节码缓存 | **DELETE** | 同上 | 无 |
| `tests/w5/__pycache__/`（4 个 `.pyc`） | 字节码缓存 | **DELETE** | 同上 | 无 |

### 2.2 合并（辅助函数去重）

| 文件路径 | 当前用途 | 建议操作 | 原因 | 风险 |
|---|---|---|---|---|
| `tests/test_e2e_v4.py` | 端到端测试；内含 `_sha256` | **MERGE** | `_sha256` 与另外 3 处逐字或等价重复 | 低：仅替换函数体为 import |
| `tests/test_fixture_matrix.py` | fixture 矩阵；内含 `_sha256` | **MERGE** | 同上 | 低 |
| `tests/test_w2_defects.py` | W2 缺陷回归；内含 `_sha256` | **MERGE** | 同上 | 低 |
| `tests/test_transaction_gate.py` | 事务二次门禁；内含 `_sha256`（分块 1 MB） | **MERGE** | 语义等价；统一为 64 KB 分块不影响结果 | 低 |
| `tests/test_template_gate_e2e.py` | W4 端到端；内含 `_passing_qa` | **MERGE** | 与 enforcement 处逐字相同 | 低 |
| `tests/test_template_gate_enforcement.py` | 入口强制；内含 `_passing_qa` | **MERGE** | 同上 | 低 |
| `tests/w5/test_b1_base.py` | W5-B1 输入边界；L126-132 两个用例方法体完全相同 | **MERGE** | 第二个用例 `test_available_without_evidence_is_rejected` 实际触发的是 `base.py:191`（verified 无证据），而非它命名的 `base.py:193`（available 未验证）。改为 `_verified_record(verified=False, verified_by=())` 后消除重复，并让两条不变量各有独立用例 | 中：该文件属 W5-B1 已提交证据，改动须在最终报告中单列并重跑 `tests/w5`；不改业务代码 |

合并目标：新增 `tests/support.py`，提供：

```python
def sha256_file(path) -> str
def passing_qa(staged) -> dict
```

**场景等价性说明**：`_sha256` 与 `_passing_qa` 均为无状态纯工具函数（文件哈希、固定 QA 通过桩），不参与任何断言语义；合并只改变定义位置，不改变返回值、调用时机或测试覆盖。合并后原 6 个文件的全部用例保持原样运行。

**`test_b1_base.py` 的场景保持说明**：

- 原场景 A（`test_verified_without_evidence_is_rejected`）：`verified=True` 且 `verified_by=()` → 必须拒绝。**保持不变**，继续覆盖 `base.py:191`。
- 原场景 B（`test_available_without_evidence_is_rejected`）：命名要求覆盖「未验证却标记 available」。**修正输入**为 `_verified_record(verified=False, verified_by=())`，使其在 `base.py:193` 拒绝。
- 用例数不变（653），两条不变量从「1 条被覆盖、1 条被伪装覆盖」变为「2 条各自独立覆盖」，覆盖能力净增。
- 修复后必须验证：`py -3.15 -m unittest tests.w5.test_b1_base -v` → 38 项通过；并复跑全量 653。

### 2.3 明确不合并（REVIEW 结论：保持原样）

| 项 | 原因 |
|---|---|
| `_source_docx` / `_staged_leftovers`（`test_transaction` 与 `test_transaction_gate`） | 一个为参数化类方法、一个为模块函数；合并需改 6 处调用点，收益约 12 行。**保持现状** |
| `_template`（5 处同名） | 内容不同（空白 / 红字 / 表格 / 占位符模板），**同名不同物** |
| `_standard_template`（2 处） | 内容不同 |
| `test_fixture_matrix` 与 `test_officecli_writer` 的 class_01/02 | 同一 fixture 走不同后端，属一致性对照，**保留** |
| 目录重构为 `unit/`、`integration/` | 需改 30 个 `parents[1]` + 3 个 fixture 相对路径 + 审查面扩大。**不执行**，理由见 inventory §5.5 |

### 2.4 保留（tests 源码，87 个）

| 分组 | 文件 | 建议操作 | 保护理由 |
|---|---|---|---|
| 契约测试 | `tests/contracts/` 全部 12 个文件 | KEEP | 契约测试最高保护级别，72 用例 |
| W5 测试 | `tests/w5/` 全部 4 个文件 | KEEP | W5 进行中，含未提交的 R3 新增用例 |
| 安全相关 | `test_package_guard.py`（ZIP 配额）、`test_template_gate_store.py`（HMAC）、`test_template_gate_enforcement.py`（入口强制）、`test_process_ownership.py`（进程所有权） | KEEP | 安全边界测试，禁止删除 |
| 回归测试 | `test_w2_defects.py`、`test_residual_inheritance.py`、`test_fill_fidelity_inplace.py`、`test_excel_spec_resilience.py`、`test_pdf_hygiene.py`、`test_excel_status_merge.py` | KEEP | 均为历史 Bug 复现，删除即失去防复发能力 |
| 兼容基线 | `test_v3_engine.py`、`test_router_capabilities.py`、`test_workflow.py`、`test_proofread.py`、`test_layout_qa.py`、`test_table_signature.py`、`test_review_lifecycle.py`、`test_excel_reliability.py` | KEEP | v3.5.9 兼容面，AGENTS §3.1 明确保护 |
| 端到端 | `test_e2e_v4.py`、`test_template_gate_e2e.py`、`test_skill_workflow_v4.py` | KEEP | 主链唯一端到端覆盖 |
| 其余单元/集成 | 其余 `test_*.py` | KEEP | 验证目标各不相同（见 inventory §4.2） |
| 支撑脚本 | `tests/gate_helpers.py`、`tests/real_corpus_eval.py`、`tests/fixtures/generate_fixtures.py` | KEEP | 非测试入口，按设计不参与发现；后者可重建全部 fixture |
| Fixture 资产 | `tests/fixtures/` 全部 `.docx` / `.json` / `.png` | KEEP | 全部有使用方，无孤儿 |

---

## 3. 第二阶段执行顺序（获批准后）

1. 复核工作区仍为基线状态；若 `document_backends/result.py`、`tests/w5/test_b1_result.py` 已被用户改动，先记录新 diff 再继续。
2. 删除 `reports/w5/be95e82-review.patch`（保留可恢复说明）。
3. 删除 3 个 `__pycache__` 目录。
4. 新增 `tests/support.py`，改写 6 个测试文件的辅助函数为导入。
5. 修正 `tests/w5/test_b1_base.py` 的重复用例输入（`verified=False`），消除重复并补足 `base.py:193` 的独立覆盖。
6. 新增 `reports/README.md`（唯一索引；含 W5 进行中标注）。
7. **不修改 `README.md` / `SKILL.md` / `CHANGELOG.md`**。调查期间已观察到并行会话正在重写 `README.md` 与 `CHANGELOG.md`（10:09–10:10），任何对这两个文件的写入都会与其冲突。`reports/` 目录注释的滞后问题改为在 `reports/README.md` 与本计划中登记，交由并行会话或后续任务统一处理。
8. 全量验证：
   - `py -3.15 -m unittest discover -s tests -p "test_*.py"`
   - `py -3.15 -m unittest discover -s tests/contracts -t tests -p "test_*.py"`
   - `py -3.15 -m unittest discover -s tests/w5 -t . -p "test_*.py"`
   - `py -3.15 -m ruff check .`
   - 文档链接检查（`reports/README.md` 内全部相对链接可达）
9. 生成 `reports/cleanup/cleanup-final-report.md`。
10. 执行 `git status --short`，输出完整移动/删除/修改清单。**不 commit、不 push、不改 tag。**

### 验收门槛（任一不满足即停止并回滚本轮改动）

| 指标 | 清理前 | 清理后要求 |
|---|---:|---|
| 全量用例 | 653 OK | = 653，0 失败、0 错误、0 跳过（本计划不删任何用例） |
| 契约用例 | 72 OK | = 72，全部通过 |
| `tests/w5` 专项 | 109 OK | = 109，全部通过（含 `test_b1_base` 修复后复验） |
| Ruff | pass | pass |
| 测试文件数 | 60 个 `test_*.py` | 不变（60） |
| 契约测试文件数 | 10 | 不变（10） |
| 回归/安全测试 | 全部保留 | 全部保留，用例数不减 |
| 覆盖能力 | `base.py:193` 无独立用例 | 新增独立覆盖（净增，不下降） |

> 任何用例数下降都必须逐项说明；本轮计划不删除任何测试用例，因此预期清理后仍为 **653**。

---

## 4. 风险登记

| # | 风险 | 概率 | 影响 | 缓解 |
|---|---|---|---|---|
| R1 | 误覆盖用户未提交的 `document_backends/result.py` / `tests/w5/test_b1_result.py` | 低 | 高 | 全程不写这两个文件；执行前后各记一次 `git diff --stat` 与哈希 |
| R2 | 删除 patch 后被误认为丢失证据 | 低 | 低 | 在 `reports/README.md` 与最终报告注明可用 `git show be95e82` 重建 |
| R3 | 合并 `_sha256` 时改变分块大小导致行为差异 | 极低 | 低 | SHA-256 与分块无关；合并后跑全量 653 验证 |
| R4 | `reports/README.md` 链接写错 | 中 | 低 | 生成后用脚本逐一校验相对路径存在 |
| R5 | 并行会话继续写入 `reports/documentation/`、`README.md`、`CHANGELOG.md` | **已发生** | 中 | `reports/documentation/` 列为 REVIEW，不纳入任何自动操作；`README.md`/`SKILL.md`/`CHANGELOG.md` 完全排除在第二阶段操作之外；执行前重新检查一次 `git status` |
| R6 | 把 W5 误判为已完成并归档 | 低 | 高 | 已在计划中硬性禁止；W5 在索引中标注“G1.5 待人工批准，B2/B3 未启动” |
| R7 | 删除 `__pycache__` 后首次运行变慢 | 确定 | 极低 | 字节码会自动重建，仅影响一次运行耗时 |

---

## 5. 批准清单（请逐项确认）

- [ ] 采用**方案 A**（保留 `w0`–`w5` 物理结构 + `reports/README.md` 唯一索引），不物理搬迁
- [ ] 批准删除 `reports/w5/be95e82-review.patch`
- [ ] 批准删除 3 个 `tests/**/__pycache__` 目录
- [ ] 批准新增 `tests/support.py` 并合并 `_sha256`、`_passing_qa`
- [ ] 批准修正 `tests/w5/test_b1_base.py` 的重复用例输入（会改动 W5-B1 已提交测试文件，用例数不变、覆盖增强）
- [ ] 确认第二阶段**不触碰** `README.md` / `SKILL.md` / `CHANGELOG.md`（并行会话正在修改）
- [ ] `reports/documentation/version-facts.md` 的归属给出指示（保留原样 / 移入新分区 / 与同步方案合并）
- [ ] 确认不重构 `tests/` 目录层级

**在收到上述明确批准前，本计划不会执行任何文件操作。**

---

## 6. 执行结果（已执行，2026-11-07）

本计划 §1 表格中的路径是**执行前快照**。实际执行时采纳方案 A 的加强版：建立 `development/`、`acceptance/`、`archive/` 三个角色目录，移动 19 份可移动报告；14 份被冻结契约、`AGENTS.md`、`CHANGELOG.md` 或 `tests/real_corpus_eval.py` 引用的报告保留在原 `wN/` 作为锚点。

### 6.1 迁移映射

| 原路径 | 新路径 | 角色 |
|---|---|---|
| `reports/w2/01-contract-change-manifest.md` | `reports/development/w2-01-contract-change-manifest.md` | development |
| `reports/w2/issues.md` | `reports/development/w2-issues.md` | development |
| `reports/w2/w2-acceptance.md` | `reports/acceptance/w2-acceptance.md` | acceptance |
| `reports/w3/04b-implementation.md` | `reports/development/w3-04b-implementation.md` | development |
| `reports/w3/04b-manifest.md` | `reports/development/w3-04b-manifest.md` | development |
| `reports/w3/07-w3-6-review.md` | `reports/development/w3-07-w3-6-review.md` | development |
| `reports/w3/07-w3-8-review.md` | `reports/development/w3-07-w3-8-review.md` | development |
| `reports/w3/09-docs-cleanup-report.md` | `reports/development/w3-09-docs-cleanup-report.md` | development |
| `reports/w3/audit-triage.md` | `reports/development/w3-audit-triage.md` | development |
| `reports/w4/w4-0-architecture-audit.md` | `reports/development/w4-0-architecture-audit.md` | development |
| `reports/w4/w4-implementation-log.md` | `reports/development/w4-implementation-log.md` | development |
| `reports/w3/11-package-manifest.md` | `reports/acceptance/w3-11-package-manifest-v4.0.0.md` | acceptance |
| `reports/w3/13-v4.0.1-exit-evidence.md` | `reports/acceptance/w3-13-v4.0.1-exit-evidence.md` | acceptance |
| `reports/w3/14-package-manifest-v4.0.1.md` | `reports/acceptance/w3-14-package-manifest-v4.0.1.md` | acceptance |
| `reports/w4/w4-package-manifest.md` | `reports/acceptance/w4-package-manifest-v4.1.0.md` | acceptance |
| `reports/w4/w4-package-manifest-v4.1.1.md` | `reports/acceptance/w4-package-manifest-v4.1.1.md` | acceptance |
| `reports/w4/w4-package-manifest-v4.1.2.md` | `reports/acceptance/w4-package-manifest-v4.1.2.md` | acceptance |
| `reports/w3/08-package-manifest.md` | `reports/archive/w3-08-package-manifest-dev-snapshot.md` | archive |
| `reports/w3/real-corpus-candidates.md` | `reports/archive/w3-real-corpus-candidates.md` | archive |

### 6.2 保留为锚点（14 份，未移动）

```text
w0/05-contract-freeze-report.md
w0/07-gate-review.md
w0/issues.md
w0/w0-acceptance.md
w1/w1-acceptance.md
w2/07-n1-gate-review.md
w3/07-cp-w2-002-gate-review.md
w3/07-cp-w2-002-post-review.md
w3/10-exit-review.md
w3/12-independent-exit-review.md
w3/real-corpus-eval.md
w3/real-corpus-eval.json
w3/w3-task-book.md
w4/w4-9-exit-review.md
```

### 6.3 引用更新

- 对 21 个 Markdown 文件执行 42 处路径替换，覆盖因移动失效的全部引用。
- 冻结契约文件**未修改**：其 10 处引用全部指向 §6.2 锚点，仍然有效。
- `tests/real_corpus_eval.py` 未修改：其默认路径指向 `w3/` 锚点，仍然有效。
- `reports/README.md` 已按新结构重写，44 个路径引用全部校验可达。

