# W5 GitHub 远程同步预检与执行方案

- 制定时间：2026-11-07（Asia/Shanghai）
- 制定基线：本地 `main` @ `37ec46f`；远程 `main` @ `bd9a2d6`
- 文档性质：**只读预检 + 同步方案建议**。本报告不构成 Push 授权。
- 最终结论：**READY_FOR_SYNC_PLAN**

> `READY_FOR_SYNC_PLAN` 表示同步方案完整、所有已知阻断项均有明确处理方案，**不代表可以直接 Push**。Push 仍需 G1.5 正式人工批准、R3 修正与版本对齐完成、全量测试通过以及明确的人工授权。

---

## 1. 当前 Git 状态

### 1.1 本地

| 项 | 实测值 |
|---|---|
| 仓库根目录 | `<repo_root>` |
| 当前分支 | `main` |
| 本地 HEAD | `37ec46f78eefd75da065a911371c864bb01b7dff` |
| HEAD 标题 | `fix(backends): harden validation and immutable capability results` |
| 上游 | `origin/main` |
| 跟踪状态 | `main...origin/main [ahead 4]` |
| 已跟踪工作区 | 干净：无暂存修改、无未暂存修改 |
| 未跟踪文件 | `dist/`、`reports/w5/` |
| 进行中的 merge/rebase/cherry-pick | 无 |
| Stash | 无 |
| 工作树数量 | 1 |
| 子模块 | 无 |

### 1.2 未跟踪文件明细

```text
dist/
  officecli-template-filler-v4.1.0.zip
  officecli-template-filler-v4.1.1.zip
  officecli-template-filler-v4.1.2.zip

reports/w5/
  w5-architecture-audit.md
  w5-capability-matrix.md
  w5-target-architecture.md
  w5-migration-plan.md
  w5-g15-final-review.md
  w5-github-sync-plan.md      ← 本报告
  be95e82-review.patch
```

分类：

- `dist/`：本地发布产物，仓库政策已明确不在源码仓库保留，**不得提交**。
- `reports/w5/*.md`：W5-A 架构/审计/门禁文档，**候选归档**。
- `be95e82-review.patch`：可由 `git show be95e82` 重建的审查 diff 产物，**不建议入库**。

### 1.3 本地分支与 tag

本地分支：

```text
main
docs/v4.0.0-post-release
docs/v4.0.1-libreoffice-evidence
release/v4.0.0-stable
release/v4.0.1
```

本地 tag 到 `v4.1.2`；**没有** `v4.2.0` tag。

### 1.4 远程

| 项 | 实测值 |
|---|---|
| remote | `git@github.com:bingheyuxing-sheng/officecli-template-filler.git` |
| 远程 `HEAD` | `bd9a2d6db5e09d927f33604049a79b0f7691202d` |
| 远程 `refs/heads/main` | `bd9a2d6db5e09d927f33604049a79b0f7691202d` |
| 远程分支 | `main`、`docs/v4.0.0-post-release`、`docs/v4.0.1-libreoffice-evidence`、`release/v4.0.0-stable`、`release/v4.0.1` |
| 远程 tag | 已有 `v4.1.2`；无 `v4.2.0` |

本次使用 `git ls-remote` 读取远程实时状态，未执行 `git fetch`，未改变任何远程跟踪引用。

---

## 2. 本地与远程提交关系

| 项 | 结果 |
|---|---|
| 本地 HEAD | `37ec46f` |
| 远程 HEAD | `bd9a2d6` |
| 共同祖先 | `bd9a2d6`（即远程 `main` 本身） |
| 本地领先 | 4 |
| 远程领先 | 0 |
| 是否分叉 | 否 |
| 是否可 fast-forward | 是 |
| 需要人工处理的提交关系 | 无 |

本地独有的 4 个提交（按父到子）：

```text
bd9a2d6 (origin/main, tag v4.1.2)
  └─ d342fe5  W5-B0
      └─ d4d3c19  W5-B1
          └─ be95e82  W5-B1-R
              └─ 37ec46f  B1-R2  ← HEAD
```

远程没有本地缺少的提交。正常情况下，后续 Push 只需在现有历史之上 fast-forward，不需要 merge/rebase。

---

## 3. 四个待同步 Commit 的逐项审查

### 3.1 `d342fe5` — W5-B0

| 项 | 内容 |
|---|---|
| 标题 | `feat(backends): officecli writer backend with run-scoped fill routing` |
| 文件数 / 增删 | 13 文件，+1154 / −83 |
| 主要文件 | `engine/officecli_writer.py`（新增）、`document_engine/fill_executor.py`、`document_engine/pipeline.py`、`scripts/generate_document.py`、`tests/test_officecli_writer.py`、`tests/real_corpus_eval.py` |
| 附带修改 | `template_gate/store.py` HMAC 修复、`tests/test_template_gate_store.py` 回归测试、版本声明 4.1.2 → 4.2.0 |
| 冻结资产 | 未修改 `contracts/`、`schemas/` |
| 无关修改 | HMAC 修复与 B0 功能同提交，提交说明和 CHANGELOG 已披露；不构成数据风险，但无法单独 revert |
| 敏感文件 | 无密钥、无私钥、无本机用户路径、无二进制 |
| 结论 | 适合保留并同步；不重写历史，不拆分为独立 HMAC 提交 |

### 3.2 `d4d3c19` — W5-B1

| 项 | 内容 |
|---|---|
| 标题 | `feat(backends): W5-B1 backend adapter skeleton (base/result/reason codes)` |
| 文件数 / 增删 | 9 文件，+1340 / −1 |
| 主要文件 | `document_backends/{__init__,base,result}.py`、`tests/w5/{__init__,test_b1_base,test_b1_registry,test_b1_result}.py`、`config/error-codes.json`、`CHANGELOG.md` |
| 冻结资产 | 未修改 `contracts/`、`schemas/`；错误码注册表只增 |
| 无关修改 | 无 |
| 敏感文件 | 无 |
| 结论 | 适合保留并同步 |

### 3.3 `be95e82` — W5-B1-R

| 项 | 内容 |
|---|---|
| 标题 | `fix(backends): W5-B1 review fixes R1-R4 (generic envelope codes, ValidationResult)` |
| 文件数 / 增删 | 8 文件，+471 / −33 |
| 主要文件 | `document_backends/{__init__,base,result}.py`、`tests/w5/{test_b1_base,test_b1_registry,test_b1_result}.py`、`config/error-codes.json`、`CHANGELOG.md` |
| 冻结资产 | 未修改 `contracts/`、`schemas/`；错误码注册表新增 3 个通用 `BACKEND_*` 码 |
| 无关修改 | 无 |
| 敏感文件 | 无 |
| 结论 | 适合保留并同步 |

### 3.4 `37ec46f` — B1-R2

| 项 | 内容 |
|---|---|
| 标题 | `fix(backends): harden validation and immutable capability results` |
| 文件数 / 增删 | 6 文件，+256 / −23 |
| 主要文件 | `document_backends/{__init__,base,result}.py`、`tests/w5/{test_b1_base,test_b1_result}.py`、`CHANGELOG.md` |
| 冻结资产 | 未修改 `contracts/`、`schemas/`、`config/error-codes.json` |
| 无关修改 | 无 |
| 敏感文件 | 无 |
| 结论 | 适合保留并同步 |

### 3.5 四提交合计

```text
21 个唯一文件，+3164 / −83
无二进制文件
contracts/ 与 schemas/ 相对 bd9a2d6 零差异
```

---

## 4. 文件归属审计

### 4.1 业务代码

| 文件 | 所属 | 说明 |
|---|---|---|
| `engine/officecli_writer.py` | B0 | OfficeCLI 写入后端 |
| `document_engine/fill_executor.py` | B0 | `writer="officecli"` 路由与整篇回退 |
| `document_engine/pipeline.py` | B0 | writer 参数透传 |
| `scripts/generate_document.py` | B0 | `--writer` CLI，默认仍为 `python-docx` |
| `template_gate/store.py` | B0 附带 | HMAC 密钥按原始字节读取 |
| `document_backends/__init__.py` | B1 | 包导出 |
| `document_backends/base.py` | B1 | `DocumentBackend`、Target/Op/Capability |
| `document_backends/result.py` | B1 | `BackendResult`、`OpOutcome`、`ValidationResult`、`ReasonCode` |
| `engine/__init__.py` | B0 | 版本号 4.1.2 → 4.2.0 |
| `references/python-docx-engine.md` | B0 | 版本声明 |
| `SKILL.md` | B0 | 版本声明 |
| `CHANGELOG.md` | B0/B1/B1-R/B1-R2 | 变更记录 |
| `config/error-codes.json` | B1/B1-R | 错误码只增注册 |

### 4.2 测试

| 文件 | 所属 |
|---|---|
| `tests/test_officecli_writer.py` | B0 |
| `tests/real_corpus_eval.py` | B0（对照模式） |
| `tests/test_template_gate_store.py` | B0（HMAC 回归） |
| `tests/contracts/test_legacy_compat.py` | B0（版本期望） |
| `tests/w5/__init__.py` | B1 |
| `tests/w5/test_b1_base.py` | B1/B1-R/B1-R2 |
| `tests/w5/test_b1_registry.py` | B1/B1-R |
| `tests/w5/test_b1_result.py` | B1/B1-R/B1-R2 |

### 4.3 文件归属结论

- 四个提交不包含 `dist/`、发布 ZIP、缓存、日志、临时文件或二进制。
- 未跟踪的 `reports/w5/` 不在四个提交内，属于独立归档决策。
- 没有“仅存在于远程”的文件；远程 `main` 是本地祖先，且四个提交无删除操作。

---

## 5. 冻结资产差异审计

### 5.1 `contracts/` 与 `schemas/`

```text
git diff --stat bd9a2d6..37ec46f -- contracts schemas
（空）
```

结论：与远程基线相比零差异；未发现未经批准的契约、Schema、枚举或必填规则变更。

### 5.2 `config/error-codes.json`

| 指标 | 结果 |
|---|---|
| 远程基线条目数 | 34 |
| 本地 HEAD 条目数 | 56 |
| 删除条目 | 0 |
| 既有条目内容修改 | 0 |
| 新增条目 | 22 |
| 新增条目 `introduced_in` | 全部为 `4.2.0` |

新增 22 条：

```text
EXECUTION_FAILED
OFFICECLI_WRITE_FAILED
OFFICECLI_READBACK_FAILED
OFFICECLI_NORMALIZE_FAILED
OFFICECLI_BINARY_MISSING
OFFICECLI_VERSION_UNSUPPORTED
BACKEND_VALIDATE_UNAVAILABLE
TOKEN_SPANS_RUNS
TOKEN_NOT_UNIQUE
LOCATION_UNSUPPORTED
CELL_MULTIPLE_PARAGRAPHS
OPERATION_TYPE_UNSUPPORTED
CAPABILITY_NOT_ROUTABLE
BATCH_ROLLED_BACK
READBACK_MISMATCH
NORMALIZE_FAILED
STAGE_CHECK_FAILED
BACKEND_VALIDATE_FAILED
BACKEND_SINGLE_WRITER_VIOLATION
BACKEND_BATCH_FAILED
BACKEND_READBACK_FAILED
BACKEND_NORMALIZE_FAILED
```

结论：注册表为纯加法变更，符合“只增不改”约束；原有 34 条语义未被覆盖或删除。

---

## 6. 敏感文件审计

### 6.1 四个提交

| 检查项 | 结果 |
|---|---|
| API Key / Token / 密码 / 私钥 / 证书 | 未发现 |
| `.env` / `.pem` / `.key` / `.pfx` / `.p12` | 未发现 |
| 本地绝对路径 | 未发现（代码中的 `~\AppData\Local\OfficeCLI\officecli.exe` 是运行时默认探测器，不是用户私密路径） |
| 用户隐私数据 / 真实文档内容 | 未发现 |
| 临时文件 / 调试日志 / 构建缓存 | 未发现 |
| 二进制 / ZIP / `dist/` | 未发现 |
| 大文件 | 未发现 |

### 6.2 待归档报告

归档前需要做两项清洗：

1. **本机绝对路径替换为 `<repo_root>`**：
   - `reports/w5/w5-architecture-audit.md` 第 4 行。
   - `reports/w5/w5-g15-final-review.md` 第 27、232 行。
2. **不纳入 `reports/w5/be95e82-review.patch`**：该文件是可由 `git show be95e82` 重建的 diff 产物，37,976 字节，不包含额外证据价值。

结论：未发现需要阻止同步的敏感信息；唯一需要处理的是报告中的本机路径。

---

## 7. W5-A 报告归档建议

### 7.1 文件完整性

| 文件 | 存在 | 内容判断 |
|---|---|---|
| `w5-architecture-audit.md` | 是 | 架构审计完整；记录 D1/D2 决策与 E1–E9 约束；含 1 处本机路径 |
| `w5-capability-matrix.md` | 是 | 能力对照表完整；基于 `bd9a2d6 + 未提交工作树` 的历史快照 |
| `w5-target-architecture.md` | 是 | 设计提案完整；含 E1–E9 映射；部分签名已被 B1-R/B1-R2 演进 |
| `w5-migration-plan.md` | 是 | 迁移计划 + B0/B1/B1-R/B1-R2 实施记录完整；末尾仍写“等待 G1.5 最终人工批准” |
| `w5-g15-final-review.md` | 是 | G1.5 独立审查完整；建议 `PASS`，但未获人工批准 |

### 7.2 与当前实现的偏差

`w5-target-architecture.md` 是 W5-A 时点的设计提案，以下内容已被后续实现演进：

| 文档写法 | 当前实现 |
|---|---|
| `BackendOp.preconditions: list[str]` | `BackendOp` 不含 `preconditions`，不携带授权语义 |
| `batch()/readback() -> BatchOutcome` | 均返回 `BackendResult` |
| `validate() -> BackendResult` | `validate() -> ValidationResult`（R2 四态） |
| `normalize()` 为提交阶段规范化 | 实现保持一致，但“batch 是唯一 mutation 入口”应限定为“唯一业务操作 mutation 入口” |

这不是归档阻断项，但归档时必须标明其为历史设计提案，避免被误读为当前接口说明。

### 7.3 归档建议

| 类别 | 文件 | 理由 |
|---|---|---|
| **必须纳入** | `w5-architecture-audit.md`、`w5-capability-matrix.md`、`w5-target-architecture.md`、`w5-migration-plan.md` | W5-A 正式交付物，记录 D1/D2 与 E1–E9 |
| **必须纳入** | `w5-g15-final-review.md` | G1.5 门禁证据，记录 R1–R5 审查与测试结果 |
| **建议纳入** | `w5-github-sync-plan.md` | 本同步方案，后续执行的依据 |
| **建议新增** | `reports/w5/README.md` | 报告索引与历史状态说明，防止把 W5-A 设计提案误读为当前实现 |
| **不应纳入** | `be95e82-review.patch` | 可由 Git 重建的 diff 产物 |
| **不应纳入** | `dist/*.zip` | 发布产物，仓库政策不保留 |

### 7.4 推荐目录结构

保持与 `reports/w0`–`reports/w4` 一致的扁平结构：

```text
reports/w5/
  README.md
  w5-architecture-audit.md
  w5-capability-matrix.md
  w5-target-architecture.md
  w5-migration-plan.md
  w5-g15-final-review.md
  w5-github-sync-plan.md
```

不创建子目录，不移动文件。

### 7.5 推荐归档顺序

1. 先完成 R3 最小修正（Commit 1）。
2. 再完成版本元数据对齐（Commit 2）。
3. 最后归档 W5 报告（Commit 3），确保归档的是最终状态。
4. Commit 3 内文件顺序：W5-A 四份 → G1.5 审查 → 仓库审计 → 同步方案 → `README.md` 索引。

---

## 8. 版本元数据一致性矩阵

| 文件 | 当前版本声明（实测） | 是否一致 | 建议 |
|---|---|---|---|
| `README.md` | L7/L11 `v4.1.2`；L15 测试基线 535；L210 `v4.1.2` 本地构建包 | **否** | 改为 `v4.2.0（未发布/开发中）`；测试基线改为最终实测值；保留 v4.1.2 历史行；不声称 4.2.0 已打包 |
| `CHANGELOG.md` | L9 `Unreleased`；L11“软件版本与契约集保持不变（4.1.2 / 4.3.0）”；L27 全量 648 | **否** | 标题改为 `v4.2.0（未发布）`；L11 改为软件 4.2.0 / 契约集 4.3.0 / `schema_version` 4.0；测试数改为最终值；保留 v4.1.2 历史段 |
| `SKILL.md` | L6/L74 `v4.2.0`，契约集 4.3.0 | 是 | 不改 |
| `engine/__init__.py` | L3/L187 `4.2.0` | 是 | 不改 |
| `references/python-docx-engine.md` | L1 `v4.2.0`，契约集 4.3.0 | 是 | 不改 |
| `tests/contracts/test_legacy_compat.py` | L22 期望 `4.2.0` | 是 | 不改 |
| `AGENTS.md` | L6 “软件已发布 v4.0.0、契约基线 4.2.0”；L60 测试基线 479 | **否** | 建议改为软件 4.2.0（未发布）、契约集 4.3.0、测试基线最终值；属于治理文件，需明确批准 |
| `config/error-codes.json` | 新增条目 `introduced_in: 4.2.0` | 是 | 不改 |

### 8.1 判断

1. **4.2.0 是当前预期开发版本**：`d342fe5` 提交说明明确写 “Version bump 4.1.2 -> 4.2.0”；engine、SKILL、references、兼容测试已一致。
2. **4.1.2 应保留为历史发布版本**：README/CHANGELOG 的 v4.1.2 段落不删除、不重写；新增 4.2.0 未发布说明。
3. **CHANGELOG 需要新增/改名 4.2.0 条目**：当前 `Unreleased` 内容即为 4.2.0 内容；改标题并在正文声明 4.2.0。
4. **发布语义变化**：4.2.0 是 MINOR 开发版本，新增可选 OfficeCLI 后端和 B1 内部 API；当前无 tag、无 Release、未打包，不得写成“已发布”。
5. **版本修复应独立 Commit**：与 R3 代码修正、W5 报告归档分开，便于回滚与审查。

---

## 9. 推荐 Commit 划分

### Commit 1：R3 输入边界最小修正

- 建议 message：

```text
fix(backends): reject invalid per_op containers and keys
```

- 修改文件：
  - `document_backends/result.py`
  - `tests/w5/test_b1_result.py`
  - `CHANGELOG.md`（4.2.0 段 `Fixed` 增加一条，测试数更新为实测值）
- 修改内容：
  1. `BackendResult.success()` / `failure()` 的 `per_op or {}` 改为 `per_op={} if per_op is None else per_op`，让空 list/tuple/字符串进入构造器并被拒绝。
  2. `__post_init__` 要求 `per_op` 键为非空字符串，删除 `str(key)` 强制转换：
     ```python
     if not isinstance(key, str) or not key:
         raise ValueError("per_op keys must be non-empty strings, got %r" % (key,))
     frozen_ops[key] = value
     ```
  3. 新增 2 个测试方法：
     - `test_factories_reject_empty_non_mapping_per_op`：`[]`、`()`、`""` 均 `ValueError`。
     - `test_per_op_rejects_non_string_or_empty_keys`：`1`、`None`、`()`、`""`、混合键 `{1: op, "1": op}` 均 `ValueError`。
- 目的：关闭 G1.5 报告中 R3 的两项残留边界。
- 独立提交理由：代码/测试行为变更，应与文档版本对齐、报告归档分开审查与回滚。
- 依赖：无；应在 Commit 2 之前完成。
- 测试要求：`tests/w5`、`tests/contracts`、全量套件、Ruff 全部通过；预期 `tests/w5` 104 → 106、全量 648 → 650，以实测为准。
- 风险：仅影响非法输入；`BackendResult` 无生产调用方；低风险。

### Commit 2：版本元数据对齐

- 建议 message：

```text
docs(release): align version metadata to 4.2.0
```

- 修改文件：
  - `README.md`
  - `CHANGELOG.md`
  - `AGENTS.md`（需明确批准）
- 修改内容：
  - README：v4.1.2 状态段改为 v4.2.0（未发布/开发中）；测试基线改为 Commit 1 后的实测值；保留 v4.1.2 历史行；不声称 4.2.0 已打包。
  - CHANGELOG：`Unreleased` 改为 `v4.2.0（未发布）`；L11 改为软件 4.2.0 / 契约集 4.3.0 / `schema_version` 4.0；测试数改为最终值；保留 v4.1.2 历史段。
  - AGENTS.md：L6 软件版本/契约集、L60 测试基线改为当前值。
- 目的：消除 4.1.2 与 4.2.0 并存的矛盾，明确 4.2.0 未发布。
- 独立提交理由：纯文档，不改变代码行为，便于单独回滚。
- 依赖：Commit 1 完成后使用最终测试数。
- 测试要求：`tests/contracts` 必须通过（版本断言）；全量套件在 Push 前统一执行。
- 风险：文档误写“已发布”会造成发布语义错误；必须使用“未发布/开发中”。

### Commit 3：W5 报告归档

- 建议 message：

```text
docs(w5): archive architecture and gate review reports
```

- 新增纳入：
  - `reports/w5/w5-architecture-audit.md`
  - `reports/w5/w5-capability-matrix.md`
  - `reports/w5/w5-target-architecture.md`
  - `reports/w5/w5-migration-plan.md`
  - `reports/w5/w5-g15-final-review.md`
  - `reports/w5/w5-github-sync-plan.md`
  - `reports/w5/README.md`（索引）
- 路径清洗：把 2 个报告中的本机绝对路径替换为 `<repo_root>`。
- **不纳入**：`reports/w5/be95e82-review.patch`、`dist/` 下任何 ZIP。
- 目的：把 W5-A/B1/B1-R/B1-R2 的审计、设计、迁移和门禁记录纳入版本控制。
- 独立提交理由：纯文档归档，体量大但与代码行为无关，便于单独审查。
- 依赖：Commit 1、2 完成后执行。
- 测试要求：不涉及代码；执行 `git diff --check` 与路径/密钥扫描；Push 前全量测试统一复跑。
- 风险：W5-A 目标架构含历史签名漂移，必须通过 `reports/w5/README.md` 标注“历史设计提案，当前实现见 B1-R2”。

### 9.1 不建议的 Commit 划分

- 不建议把 R3 修正、版本对齐、报告归档合并为一个大 Commit：审查范围过大，回滚粒度差。
- 不建议把 `dist/` 或 `be95e82-review.patch` 混入任何 Commit。
- 不建议通过 rebase/amend 拆分 `d342fe5` 中的 HMAC 修复：会重写已有历史，违反本阶段约束。

---

## 10. 推荐同步步骤

> 以下步骤是后续执行建议，本任务不执行。

1. **完成 Commit 1（R3 修正）**  
   修改 `document_backends/result.py`、`tests/w5/test_b1_result.py`、`CHANGELOG.md`；运行 `tests/w5`、`tests/contracts`、全量套件、Ruff；记录实际数量与退出码。
2. **完成 Commit 2（版本对齐）**  
   修改 README、CHANGELOG、AGENTS.md；运行 `tests/contracts` 确认版本断言；更新测试计数为 Commit 1 后的实测值。
3. **完成 Commit 3（报告归档）**  
   清洗本机路径；新增 `reports/w5/README.md` 索引；执行 `git diff --check` 与敏感路径扫描。
4. **远程复核**  
   `git ls-remote origin refs/heads/main` 必须仍为 `bd9a2d6`；若远程变化，停止并重新审计。
5. **Push 前最终验证**  
   `git status` 确认无已暂存文件、无 `dist/` 被加入；全量测试与 Ruff 通过；确认没有 `v4.2.0` tag 或 Release 被误创建。
6. **执行 Push**  
   在 G1.5 正式人工批准与明确 Push 授权后，执行 `git push origin main`。只推 `main`，使用普通 fast-forward；禁止 `--force`、`--force-with-lease`、推 tag、推其他分支。
7. **Push 后验证**  
   `git ls-remote origin refs/heads/main` 必须等于本地 HEAD；记录远程 SHA、推送时间、测试结果与执行者。

---

## 11. Push 前置条件

全部满足才可 Push：

- [ ] G1.5 已获得正式人工批准（当前未批准）。
- [ ] R3 两项输入边界最小修正已完成并通过独立复验。
- [ ] 版本元数据已统一为 4.2.0（未发布），README/CHANGELOG/AGENTS 不再声明 4.1.2 为当前版本。
- [ ] W5-A 报告归档范围已由人工确认。
- [ ] 归档报告中的本机绝对路径已清洗为 `<repo_root>`。
- [ ] `reports/w5/be95e82-review.patch` 与 `dist/` 未被加入任何 Commit。
- [ ] `tests/w5`、`tests/contracts`、全量套件、Ruff 全部通过，并记录实际数量与退出码。
- [ ] 远程 `main` 在 Push 前仍为 `bd9a2d6`，无新远程提交。
- [ ] `git status` 无意外已暂存文件；`git diff --cached --stat` 为空。
- [ ] 已获得明确的 `git push origin main` 授权。
- [ ] 确认不会创建/推送 `v4.2.0` tag 或 GitHub Release（除非另行批准）。

---

## 12. 未解决风险

| # | 风险 | 等级 | 处理方案 |
|---|---|---|---|
| 1 | `d342fe5` 捆绑 HMAC 修复，无法单独 revert | 低 | 保留历史；在同步报告中如实标注；不 rebase/amend |
| 2 | 4.2.0 尚无 tag/Release，文档若误写“已发布”会造成发布语义错误 | 中 | Commit 2 明确写“未发布/开发中”；不创建 tag |
| 3 | README/CHANGELOG/AGENTS 版本与测试数不一致 | 中 | Commit 2 统一；Commit 1 后使用实测计数 |
| 4 | W5-A 目标架构含历史签名漂移 | 低 | `reports/w5/README.md` 标注历史提案；不把其当当前接口说明 |
| 5 | 2 份报告含本机绝对路径 | 低-中 | Commit 3 前替换为 `<repo_root>`；提交前扫描 |
| 6 | `reports/w5/be95e82-review.patch` 可能被误提交 | 低 | 明确排除；Commit 3 只 `git add` 指定 Markdown 文件 |
| 7 | `dist/` 可能被 `git add -A` 误提交 | 中 | 禁止 `git add -A`；提交前检查 `git status`；`dist/` 保持未跟踪 |
| 8 | 远程可能在同步前出现新提交 | 中 | 每次 Push 前 `git ls-remote`；若远程变化，停止并重新审计 |
| 9 | 分支保护或权限拒绝 | 低-中 | Push 前确认权限；若被拒绝，停止并报告，不绕过 |
| 10 | 全量测试耗时异常（历史记录 31248s，含环境挂起） | 低 | 以 `Ran 648 tests / OK / exit 0` 为结果；Push 前重新跑并记录墙钟时间 |
| 11 | 未检查 GitHub 分支保护规则 | 低-中 | Push 前由人工确认；不尝试绕过 |

---

## 13. 明确的停止条件

满足以下任一条件时，必须停止，不得继续 Commit 或 Push：

1. 本报告完成后：立即停止，等待人工审查与明确授权。
2. 远程 `main` 不再是 `bd9a2d6`，或出现本地缺少的远程提交。
3. 发现本地/远程分叉、历史异常、丢失提交或无法解释的工作区修改。
4. 发现密钥、Token、私钥、用户隐私数据或真实文档内容进入待提交文件。
5. `contracts/`、`schemas/` 或错误码注册表出现未经批准的修改。
6. R3 修正后测试未全部通过，或测试数量/退出码与报告不一致。
7. 版本元数据仍存在 4.1.2 / 4.2.0 冲突。
8. W5-A 报告归档范围或本机路径清洗未获人工确认。
9. G1.5 未获正式人工批准，或 Push 未获明确授权。
10. 任何需要 `--force`、`--force-with-lease`、rebase、reset、删除 tag 或重写历史的场景。

**本阶段不创建 Commit、不 Push、不修改代码、不启动 B2/B3。等待人工审查和明确授权。**
