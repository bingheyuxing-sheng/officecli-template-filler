# 工作区变更归属与报告迁移专项审查

- 审查日期：2026-11-07
- 快照时间：2026-11-07 10:41:31 +08:00；补充核对至 10:50 左右
- 基线：`main` @ `37ec46f`；远程 `origin/main` @ `bd9a2d6`
- 性质：**只读审查**。未修改、删除、移动、暂存任何既有文件；仅新增本报告
- 结论摘要：
  - 19 份报告迁移：**8 EXACT + 11 EQUIVALENT，0 UNMATCHED / 0 INCOMPLETE**
  - `tests/support.py` 重构：**行为等价，测试通过**
  - README/CHANGELOG：**大幅重写，当前版本/发布状态基本准确，但归属与编辑决策仍需人工确认**
  - 56 个未跟踪文件：已分类，外部任务归属均为 **REVIEW**
  - 不建议直接提交当前工作区

---

## 1. 当前工作区总览

```text
HEAD: 37ec46f
远程 main: bd9a2d6
本地领先: 4 个提交；远程领先: 0
暂存区: 空
```

| 类别 | 数量 |
|---|---:|
| 已跟踪已修改/删除文件（工作区 vs HEAD） | 38 |
| 其中：已删除的已跟踪报告 | 19 |
| 其中：R3 修复文件 | 2 |
| 其中：外部文档/测试/报告修改 | 17 |
| 未跟踪文件（快照时） | 56 |
| 其中：报告迁移目标 | 19 |
| 其中：cleanup/documentation/w5 新增文档 | 35 |
| 其中：测试辅助/发布产物 | 4（`tests/support.py` + 3 个 dist ZIP） |
| 独立全量测试 | **653/653 通过，239.586s，0 失败/0 错误/0 跳过，退出码 0；运行期间工作树稳定** |

当前工作区至少包含五个并行工作流：

1. **W5-B1-R3**：`document_backends/result.py`、`tests/w5/test_b1_result.py`。
2. **reports 清理与物理迁移**：19 份报告从 `w2/w3/w4` 迁移到 `development/acceptance/archive`。
3. **tests 辅助函数重构**：新增 `tests/support.py`，6 个测试文件改用共享函数；`test_b1_base.py` 修正重复用例输入。
4. **README/CHANGELOG 版本事实重写**：与 GitHub Releases 状态对齐。
5. **W5 审查报告与 documentation 草稿**：`reports/w5/`、`reports/documentation/`。

---

## 2. 19 份报告迁移完整性

### 2.1 映射与内容一致性

比较方法：

- 旧内容来自 `git show HEAD:<旧路径>`；
- 新内容读取迁移后的实际文件；
- 统一换行、去尾随空白后比较；
- 使用 `difflib.SequenceMatcher` 计算相似度；
- 对比标题/章节数量、增删行数；
- 额外检查 Markdown 链接与旧路径引用。

| # | 旧文件路径 | 新文件路径 | 内容一致性 | 信息保留 | 引用状态 | 结论 |
|---:|---|---|---|---|---|---|
| 1 | `reports/w2/01-contract-change-manifest.md` | `reports/development/w2-01-contract-change-manifest.md` | ratio 0.9975；+1/−1 | 标题 5→5；无缺失章节 | 路径已更新 | **EQUIVALENT** |
| 2 | `reports/w2/issues.md` | `reports/development/w2-issues.md` | 完全相同 | 标题 2→2 | 无变化 | **EXACT** |
| 3 | `reports/w2/w2-acceptance.md` | `reports/acceptance/w2-acceptance.md` | ratio 0.9976；+3/−3 | 标题 11→11 | 3 处路径更新 | **EQUIVALENT** |
| 4 | `reports/w3/04b-implementation.md` | `reports/development/w3-04b-implementation.md` | ratio 0.9991；+1/−1 | 标题 11→11 | 1 处路径更新 | **EQUIVALENT** |
| 5 | `reports/w3/04b-manifest.md` | `reports/development/w3-04b-manifest.md` | 完全相同 | 标题 4→4 | 无变化 | **EXACT** |
| 6 | `reports/w3/07-w3-6-review.md` | `reports/development/w3-07-w3-6-review.md` | 完全相同 | 标题 5→5 | 无变化 | **EXACT** |
| 7 | `reports/w3/07-w3-8-review.md` | `reports/development/w3-07-w3-8-review.md` | ratio 0.9803；+3/−3 | 标题 3→3 | 3 处路径更新 | **EQUIVALENT** |
| 8 | `reports/w3/08-package-manifest.md` | `reports/archive/w3-08-package-manifest-dev-snapshot.md` | ratio 0.9914；+1/−1 | 标题 5→5 | 重命名 + 路径更新 | **EQUIVALENT** |
| 9 | `reports/w3/09-docs-cleanup-report.md` | `reports/development/w3-09-docs-cleanup-report.md` | ratio 0.9890；+9/−9 | 标题 18→18 | 9 处路径更新 | **EQUIVALENT** |
| 10 | `reports/w3/11-package-manifest.md` | `reports/acceptance/w3-11-package-manifest-v4.0.0.md` | ratio 0.9932；+1/−1 | 标题 5→5 | 重命名 + 路径更新 | **EQUIVALENT** |
| 11 | `reports/w3/13-v4.0.1-exit-evidence.md` | `reports/acceptance/w3-13-v4.0.1-exit-evidence.md` | ratio 0.9979；+1/−1 | 标题 8→8 | 路径已更新 | **EQUIVALENT** |
| 12 | `reports/w3/14-package-manifest-v4.0.1.md` | `reports/acceptance/w3-14-package-manifest-v4.0.1.md` | ratio 0.9956；+1/−1 | 标题 5→5 | 路径已更新 | **EQUIVALENT** |
| 13 | `reports/w3/audit-triage.md` | `reports/development/w3-audit-triage.md` | 完全相同 | 标题 5→5 | 无变化 | **EXACT** |
| 14 | `reports/w3/real-corpus-candidates.md` | `reports/archive/w3-real-corpus-candidates.md` | 完全相同 | 标题 4→4 | 无变化 | **EXACT** |
| 15 | `reports/w4/w4-0-architecture-audit.md` | `reports/development/w4-0-architecture-audit.md` | 完全相同 | 标题 33→33 | 无变化 | **EXACT** |
| 16 | `reports/w4/w4-implementation-log.md` | `reports/development/w4-implementation-log.md` | ratio 0.9986；+1/−1 | 标题 11→11 | 1 处路径更新 | **EQUIVALENT** |
| 17 | `reports/w4/w4-package-manifest-v4.1.1.md` | `reports/acceptance/w4-package-manifest-v4.1.1.md` | 完全相同 | 标题 3→3 | 无变化 | **EXACT** |
| 18 | `reports/w4/w4-package-manifest-v4.1.2.md` | `reports/acceptance/w4-package-manifest-v4.1.2.md` | 完全相同 | 标题 3→3 | 无变化 | **EXACT** |
| 19 | `reports/w4/w4-package-manifest.md` | `reports/acceptance/w4-package-manifest-v4.1.0.md` | ratio 0.9937；+1/−1 | 标题 3→3 | 重命名 + 路径更新 | **EQUIVALENT** |

### 2.2 汇总

| 结论 | 数量 |
|---|---:|
| EXACT | 8 |
| EQUIVALENT | 11 |
| MODIFIED | 0 |
| INCOMPLETE | 0 |
| UNMATCHED | 0 |
| REVIEW | 0 |

补充结论：

- **无报告被拆分或合并**：19 个旧文件对应 19 个新文件，1:1。
- **无无来源的新报告**：19 个新报告全部有对应旧文件。
- **无无迁移目标的旧报告**：19 个删除全部有对应新文件。
- 11 个 EQUIVALENT 的差异均为**路径引用更新**（如 `reports/w3/04b-manifest.md` → `reports/development/w3-04b-manifest.md`）；未发现标题、章节、结论或数据被删除。
- 3 个文件有重命名：
  - `08-package-manifest` → `08-package-manifest-dev-snapshot`
  - `11-package-manifest` → `11-package-manifest-v4.0.0`
  - `w4-package-manifest` → `w4-package-manifest-v4.1.0`
- **不是逐字节迁移**：11 个文件有少量路径文本变化；人工审阅时应接受“内容等价、路径更新”的迁移方式。

### 2.3 原位置修改的 8 份报告

以下文件未被移动，只做了路径引用更新（`git diff -U0` 确认均为 1–4 行替换）：

- `reports/w0/05-contract-freeze-report.md`
- `reports/w0/issues.md`
- `reports/w2/07-n1-gate-review.md`
- `reports/w3/07-cp-w2-002-post-review.md`
- `reports/w3/10-exit-review.md`
- `reports/w3/12-independent-exit-review.md`
- `reports/w3/w3-task-book.md`
- `reports/w4/w4-9-exit-review.md`

### 2.4 引用状态

| 检查 | 结果 |
|---|---|
| 19 个新报告的 Markdown 链接 | **0 个缺失** |
| 19 个新报告中指向旧 `reports/w2|w3|w4` 路径的引用 | **0 个缺失** |
| `contracts/` 对已删除报告路径的引用 | **0 个** |
| `tests/` 对已删除报告路径的引用 | **0 个**（`tests/real_corpus_eval.py` 指向的 `reports/w3/real-corpus-eval.*` 仍存在） |
| `README.md` 对已删除报告路径的引用 | **0 个** |
| `reports/cleanup/` 中的旧路径引用 | 39 处，均为迁移记录/执行前快照说明，不是活链接 |

---

## 3. `tests/support.py` 重构审查

### 3.1 新增模块

`tests/support.py`（944 B，未跟踪）只包含两个无状态纯函数：

```python
def sha256_file(path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()

def passing_qa(_staged) -> dict:
    return {"status": "PASSED", "passed": True, "issues": [], "coverage_gaps": []}
```

### 3.2 6 个测试文件的迁移映射

| 文件 | 原辅助 | 迁移后 | 测试数（旧→新） | 结果 |
|---|---|---|---:|---|
| `tests/test_e2e_v4.py` | 本地 `_sha256` + `hashlib` | `from support import sha256_file` | 11→11 | **PASS** |
| `tests/test_fixture_matrix.py` | 本地 `_sha256` | `sha256_file` | 7→7 | **PASS** |
| `tests/test_template_gate_e2e.py` | 本地 `_passing_qa` | `passing_qa` | 2→2 | **PASS** |
| `tests/test_template_gate_enforcement.py` | 本地 `_passing_qa` | `passing_qa` | 6→6 | **PASS** |
| `tests/test_transaction_gate.py` | 本地 `_sha256`（1 MB 分块） | `sha256_file`（64 KB 分块） | 9→9 | **PASS** |
| `tests/test_w2_defects.py` | 本地 `_sha256` | `sha256_file` | 5→5 | **PASS** |

独立执行结果：

```text
test_e2e_v4.py                   11 tests  OK
test_fixture_matrix.py            7 tests  OK
test_template_gate_e2e.py         2 tests  OK
test_template_gate_enforcement.py 6 tests  OK
test_transaction_gate.py          9 tests  OK
test_w2_defects.py                5 tests  OK
合计 40/40 通过，退出码均为 0
```

独立全量复跑：

```text
Ran 653 tests in 239.586s
OK
FULL_EXIT=0
WORKTREE_STABLE=True
```

### 3.3 行为一致性分析

| 检查项 | 结论 |
|---|---|
| Fixture/辅助函数行为 | `sha256_file` 与原 `_sha256` 均为流式 SHA-256；分块 64 KB vs 1 MB 不影响哈希结果。`passing_qa` 返回相同的固定 dict |
| 测试初始化方式 | 未改变；辅助函数均为无状态纯函数 |
| 测试隔离方式 | 未改变；`passing_qa` 每次返回新 dict，无共享可变状态 |
| 共享可变状态 | 未引入；`support.py` 无模块级可变全局 |
| 循环导入 | 无；`support` 只导入 `hashlib`/`typing` |
| 测试发现行为 | `support.py` 不以 `test_*` 命名，不会被收集；标准命令 `-s tests` 与直接执行文件均通过 |
| 遗漏测试场景 | 6 个文件测试方法数全部不变（11/7/2/6/9/5） |
| 已知限制 | `tests/__init__.py` 不存在，因此 `discover -s tests -t .` 本来就不支持；这不是本次重构引入的回归 |

### 3.4 `tests/w5/test_b1_base.py` 的一行修改

```python
- _verified_record(verified_by=())
+ _verified_record(verified=False, verified_by=())
```

原两个用例方法体相同，均命中“verified without evidence”；修改后：

- `test_verified_without_evidence_is_rejected` 继续覆盖 `verified=True, verified_by=()`；
- `test_available_without_evidence_is_rejected` 现在覆盖 `available=True, verified=False, verified_by=()`。

结论：**该修改是测试语义修正，不是 R3 修改，也不属于 `tests/support.py` 合并**。它扩大了有效覆盖，W5 109 项通过。

---

## 4. README 与 CHANGELOG 差异分析

### 4.1 规模与结构

| 文件 | 变更规模 | 章节数 |
|---|---|---|
| `README.md` | 397 行变动 | 27 → 29 |
| `CHANGELOG.md` | 864 行变动 | 63 → 118 |

README 由“技术说明型”改写为“用户使用型”：新增“项目简介 / 这个项目能做什么 / 适用场景 / 使用流程 / 安装方法 / 支持的文档处理任务 / 文档检查与质量保障 / 当前版本 / 版本号说明”。原“设计原则 / 目录结构 / 测试 / 路线图”等标题不再出现，需人工确认相关内容是否已由 `SKILL.md`/`references/` 覆盖。

本节按**版本声明、Release 状态、功能声明、章节结构**四个维度核对，不逐行复述全部 864 行 diff；版本与 Release 状态已用 `gh release view` 实测。

### 4.2 版本与 Release 状态核对

使用 `gh release list` / `gh release view` 实测（2026-11-07）：

| 版本 | 文档声明 | GitHub 实际 | 结论 |
|---|---|---|---|
| v4.0.1 | 公开稳定版，Latest | Latest | **一致** |
| v4.1.2 | Pre-release，已发布 | Pre-release，asset `officecli-template-filler-v4.1.2.zip`，997,540 B | **一致** |
| v4.1.1 | Pre-release | Pre-release | **一致** |
| v4.1.0 | Draft，未公开 | Draft | **一致** |
| 4.2.0 | 开发中，未发布 | 无 tag/Release | **一致** |

v4.1.2 资产 SHA-256：

```text
CHANGELOG L132: c66c652ec177fcc57a3dade003fdd22d2603071405406d87ce39de5a84f23f53
GitHub asset:  sha256:c66c652ec177fcc57a3dade003fdd22d2603071405406d87ce39de5a84f23f53
```

**一致。**

### 4.3 版本体系是否混淆

README L237–L247 与 CHANGELOG L7–L23 均明确区分：

- 软件版本：`v4.1.2`（Pre-release）/ `4.2.0`（开发中）
- 契约集版本：`4.3.0`
- 产物 `schema_version`：`4.0`

未发现把契约集版本当作软件版本、或把 schema_version 当作发布版本的问题。

### 4.4 功能描述与代码证据

| 文档声明 | 代码/测试证据 | 结论 |
|---|---|---|
| 4.2.0 新增可选 officecli 写入后端，默认仍为 python-docx | `engine/officecli_writer.py` 存在；`fill_executor` writer 默认 `python-docx`；`--writer` CLI 存在 | **一致** |
| `document_backends/` 后端接口与结果类型 | `document_backends/{__init__,base,result}.py`；W5 109 测试 | **一致** |
| 未验证能力不能标记为支持 | `CapabilityRecord` 构造期不变量；R4 测试 | **一致** |
| officecli 只覆盖 `.docx` 三类文字操作，其他回退 python-docx | `fill_executor` 的 fallback 逻辑；B0 测试 | **一致** |
| 4.2.0 未发布，无 tag/Release | `git ls-remote` 无 v4.2.0；`gh release list` 无 4.2.0 | **一致** |

### 4.5 发现的问题

1. **文档在审查期间继续变化（REVIEW）**  
   10:41 快照中 README/CHANGELOG 曾写 v4.1.2“准备发布 / 尚未创建 Release”；10:45 左右已改为“Pre-release / 已发布”。当前文本与 GitHub 实际一致，但说明并行文档任务仍在写入。最终版本需等任务稳定后重新核对。
2. **“本地构建包”措辞（低）**  
   README L233 与 CHANGELOG L12 仍称 v4.1.2 为“本地构建包”，但它已经是公开 Pre-release 资产。建议改为“v4.1.2 Pre-release 资产”；不构成事实错误，但措辞滞后。
3. **CHANGELOG 的 tag 推送措辞（REVIEW）**  
   CHANGELOG L96 写“已于 2026-11-07 推送 tag `v4.1.2` 并以 Pre-release 发布”。但远程 tag `v4.1.2` 在本轮审计开始前已存在于 `bd9a2d6`；2026-11-07 新增的是 Pre-release 与资产，不是首次推送 tag。建议改为“tag 已存在；2026-11-07 创建 Pre-release 并上传资产”。
4. **README 删除旧技术章节（REVIEW）**  
   原“设计原则 / 目录结构 / 测试 / 路线图”不再以原名出现。需人工确认这些技术说明是否必须保留在 README，还是已由 `SKILL.md`/`references/` 覆盖。
5. **CHANGELOG 结构大改（REVIEW）**  
   从按版本的技术条目改为“阅读说明 + 版本速览 + 每版用户变化/技术记录/测试/限制”。历史技术内容看起来保留，但需人工确认没有遗漏必要事实。
6. **Release 链接有效性**  
   README 中 v4.0.1/v4.1.1/v4.1.2 链接均指向存在的 Release；v4.1.0 为 Draft，README 未给出公开链接，符合状态。

---

## 5. 56 个未跟踪文件归属清单

> 快照时 56 个；本报告新增后为 57 个。

### 5.1 报告迁移目标（19）

| 文件 | 归属 | 依据 |
|---|---|---|
| `reports/development/w2-01-contract-change-manifest.md` | reports 清理/迁移 | 与旧 `w2/01-...` 内容等价 |
| `reports/development/w2-issues.md` | reports 清理/迁移 | 与旧 `w2/issues.md` 完全一致 |
| `reports/development/w3-04b-implementation.md` | reports 清理/迁移 | 与旧文件内容等价 |
| `reports/development/w3-04b-manifest.md` | reports 清理/迁移 | 完全一致 |
| `reports/development/w3-07-w3-6-review.md` | reports 清理/迁移 | 完全一致 |
| `reports/development/w3-07-w3-8-review.md` | reports 清理/迁移 | 路径更新 |
| `reports/development/w3-09-docs-cleanup-report.md` | reports 清理/迁移 | 路径更新 |
| `reports/development/w3-audit-triage.md` | reports 清理/迁移 | 完全一致 |
| `reports/development/w4-0-architecture-audit.md` | reports 清理/迁移 | 完全一致 |
| `reports/development/w4-implementation-log.md` | reports 清理/迁移 | 路径更新 |
| `reports/acceptance/w2-acceptance.md` | reports 清理/迁移 | 路径更新 |
| `reports/acceptance/w3-11-package-manifest-v4.0.0.md` | reports 清理/迁移 | 重命名 + 路径更新 |
| `reports/acceptance/w3-13-v4.0.1-exit-evidence.md` | reports 清理/迁移 | 路径更新 |
| `reports/acceptance/w3-14-package-manifest-v4.0.1.md` | reports 清理/迁移 | 路径更新 |
| `reports/acceptance/w4-package-manifest-v4.1.0.md` | reports 清理/迁移 | 重命名 + 路径更新 |
| `reports/acceptance/w4-package-manifest-v4.1.1.md` | reports 清理/迁移 | 完全一致 |
| `reports/acceptance/w4-package-manifest-v4.1.2.md` | reports 清理/迁移 | 完全一致 |
| `reports/archive/w3-08-package-manifest-dev-snapshot.md` | reports 清理/迁移 | 重命名 + 路径更新 |
| `reports/archive/w3-real-corpus-candidates.md` | reports 清理/迁移 | 完全一致 |

### 5.2 reports 清理记录（3；本报告新增后为 4）

| 文件 | 归属 | 依据 |
|---|---|---|
| `reports/cleanup/cleanup-inventory.md` | reports 清理 | 全量清单与保护记录 |
| `reports/cleanup/cleanup-plan.md` | reports 清理 | 清理计划，含“待批准”勾选项 |
| `reports/cleanup/cleanup-final-report.md` | reports 清理 | 执行结果与迁移映射 |
| `reports/cleanup/worktree-change-audit.md` | 本报告 | 工作区变更归属与迁移完整性审查（新增后构成第 57 个未跟踪文件） |

### 5.3 documentation 草稿（17）

| 文件 | 归属 | 依据 |
|---|---|---|
| `reports/documentation/version-facts.md` | 文档/版本事实 | 版本、Release、Tag 调查 |
| `reports/documentation/releases/README.md` | 文档/版本事实 | Release 说明草稿索引 |
| `reports/documentation/releases/v3.4.1-archive.md` 等 15 个版本草稿 | 文档/版本事实 | Release 说明草稿，未更新线上 Release |

15 个版本草稿逐项：

```text
releases/v3.4.1-archive.md
releases/v3.4.2.md
releases/v3.5.2.md
releases/v3.5.3.md
releases/v3.5.4.md
releases/v3.5.5.md
releases/v3.5.7.md
releases/v3.5.8.md
releases/v3.5.9.md
releases/v4.0.0-dev.1.md
releases/v4.0.0.md
releases/v4.0.1.md
releases/v4.1.0.md
releases/v4.1.1.md
releases/v4.1.2.md
```

### 5.4 W5 审查报告（12）

| 文件 | 归属 | 依据 |
|---|---|---|
| `reports/w5/w5-architecture-audit.md` | W5 开发 | W5-A 架构审计 |
| `reports/w5/w5-capability-matrix.md` | W5 开发 | W5-A 能力矩阵 |
| `reports/w5/w5-target-architecture.md` | W5 开发 | W5-A 目标架构 |
| `reports/w5/w5-migration-plan.md` | W5 开发 | W5-A 迁移计划 |
| `reports/w5/w5-g15-final-review.md` | W5 开发 | G1.5 审查 |
| `reports/w5/w5-github-sync-plan.md` | 同步预检 | 远程同步方案 |
| `reports/w5/w5-b1-r3-fix-review.md` | W5-B1-R3 | R3 修复审查 |
| `reports/w5/w5-g1.5-b1-final-review.md` | W5-B1 | G1.5/B1 最终审查 |
| `reports/w5/w5-taskbook-recovery-review.md` | W5 审查 | 任务书恢复 |
| `reports/w5/w5-worktree-isolation-review.md` | W5 审查 | 工作区隔离 |
| `reports/w5/w5-b1-r3-commit-preparation.md` | W5-B1-R3 | 提交准备 |
| `reports/w5/w5-g1.5-blocker-resolution.md` | W5-B1 | 阻塞项处理 |

### 5.5 其他（5）

| 文件 | 归属 | 依据 |
|---|---|---|
| `reports/README.md` | reports 清理 | 唯一索引，声明 w5/documentation 并行编写 |
| `tests/support.py` | tests 重构 | 共享测试辅助函数 |
| `dist/officecli-template-filler-v4.1.0.zip` | Release 产物 | 本地构建包 |
| `dist/officecli-template-filler-v4.1.1.zip` | Release 产物 | 本地构建包 |
| `dist/officecli-template-filler-v4.1.2.zip` | Release 产物 | 与 v4.1.2 Release asset 大小一致（997,540 B） |

合计：19（迁移目标）+ 3（cleanup 记录）+ 17（documentation）+ 12（W5 报告）+ 5（其他）= **56**。

### 5.6 归属结论

- **R3 相关未跟踪文件：0 个**（R3 两个文件是已跟踪修改，不是未跟踪）。
- **W5 开发相关**：12 个 W5 报告。
- **reports 清理相关**：19 个迁移目标 + 3 个 cleanup 记录 + 1 个 README = 23 个。
- **README/CHANGELOG 整理相关**：0 个未跟踪文件（两个文件是已跟踪修改）。
- **tests 重构相关**：1 个 `tests/support.py`。
- **Release 产物**：3 个 dist ZIP。
- **临时文件**：未发现明显临时文件/缓存（缓存均被 `.gitignore` 忽略）。
- **来源不明**：0 个；但 **授权未确认** 的外部件为：19 迁移目标、3 cleanup、17 documentation、12 w5、1 README、1 support，共 53 个，全部标记 **REVIEW**。

---

## 6. 文件引用风险

| 风险 | 结果 |
|---|---|
| `contracts/` 引用已删除报告 | **未发现** |
| `tests/` 引用已删除报告 | **未发现**；`reports/w3/real-corpus-eval.*` 仍存在 |
| `README.md` 引用已删除报告 | **未发现** |
| 19 个新报告 Markdown 链接缺失 | **0** |
| 19 个新报告旧路径引用缺失 | **0** |
| `reports/cleanup/` 旧路径引用 | 39 处，均为迁移记录/历史说明，不是活链接 |
| 提交时只暂存删除不暂存新增 | **高风险**：19 份报告会从 Git 删除 |
| `git add -A` | **高风险**：R3、文档、测试、报告迁移、dist 全部混入 |

---

## 7. 独立提交分组建议

> 以下仅为建议，本任务不执行任何暂存或提交。所有分组均需人工批准。

### 组 1：W5-B1-R3 输入边界修复

- 文件：`document_backends/result.py`、`tests/w5/test_b1_result.py`
- 目的：关闭 `per_op or {}` 与 `str(key)` 两项边界。
- 依赖：无。
- 测试：W5 109、契约 72、全量 653、Ruff。
- 是否可独立提交：**可以**（精确两文件）。
- 人工批准：**必须**。

### 组 2：tests 辅助函数重构

- 文件：`tests/support.py` + `tests/test_e2e_v4.py`、`test_fixture_matrix.py`、`test_template_gate_e2e.py`、`test_template_gate_enforcement.py`、`test_transaction_gate.py`、`test_w2_defects.py`
- 目的：把重复的 `_sha256` / `_passing_qa` 合并到无状态辅助模块。
- 依赖：无（不依赖 R3）。
- 测试：6 文件 40/40；全量 653（需在隔离树复跑）。
- 是否可独立提交：**可以**。
- 人工批准：**必须**。

### 组 3：`test_b1_base.py` 重复用例修正

- 文件：`tests/w5/test_b1_base.py`
- 目的：让 `test_available_without_evidence_is_rejected` 真正覆盖“未验证却 available”，消除与上一用例的重复。
- 依赖：无；建议在组 2 之后或独立。
- 测试：W5 109。
- 是否可独立提交：**可以**。
- 人工批准：**必须**（改动已提交的 W5 测试证据）。

### 组 4：reports 历史报告迁移

- 文件：
  - 19 个删除（旧路径）
  - 19 个新增（`development/` 10、`acceptance/` 7、`archive/` 2）
  - 8 个原位路径更新报告
  - `reports/README.md`
- 目的：按 development/acceptance/archive 角色重组 reports，保留原有内容与引用。
- 依赖：删除与新增必须同一提交，避免历史报告从 Git 消失。
- 测试：无代码测试；执行 Markdown 链接检查（0 缺失）。
- 是否可独立提交：**可以，但必须原子提交**。
- 人工批准：**必须**（迁移方案 + 所有路径变更）。

### 组 5：reports 清理记录

- 文件：`reports/cleanup/cleanup-inventory.md`、`cleanup-plan.md`、`cleanup-final-report.md`、`worktree-change-audit.md`
- 目的：记录清理调查、计划与执行结果。
- 依赖：建议在组 4 之后提交，确保记录与实际迁移一致。
- 测试：无。
- 是否可独立提交：**可以**。
- 人工批准：**必须**。

### 组 6：README 与 CHANGELOG 文档调整

- 文件：`README.md`、`CHANGELOG.md`
- 目的：用户化重写、版本/Release 状态对齐、版本体系说明。
- 依赖：建议在组 4/5 后，确认报告路径与 Release 状态稳定。
- 测试：无代码测试；核对 `gh release` 状态与资产 SHA。
- 是否可独立提交：**可以**。
- 人工批准：**必须**（文档编辑方向 + 删除章节确认）。

### 组 7：W5 审查报告归档

- 文件：`reports/w5/` 12 个报告
- 目的：保存 W5-A/B1/R3/G1.5 审查证据。
- 依赖：建议在 R3 提交后归档，确保报告与提交对应。
- 测试：无。
- 是否可独立提交：**可以**。
- 人工批准：**必须**（归档范围 + 是否包含 R3 未提交状态）。

### 组 8：documentation 草稿

- 文件：`reports/documentation/` 17 个文件
- 目的：版本事实调查与 Release 说明草稿。
- 依赖：无；但不应当作已发布文档。
- 测试：无。
- 是否可独立提交：**暂不建议**；先决定是否保留为草稿/归档。
- 人工批准：**必须**。

### 组 9：dist 发布产物

- 文件：`dist/*.zip` 3 个
- 目的：本地构建包。
- 是否可提交：**否**（仓库政策不保留 dist）。
- 处理：保持未跟踪；不得删除。

### 推荐顺序

```text
1. R3（组 1）
2. tests 辅助重构（组 2）
3. test_b1_base 修正（组 3）
4. reports 迁移（组 4，原子）
5. reports 清理记录（组 5）
6. README/CHANGELOG（组 6）
7. W5 报告归档（组 7）
8. documentation 草稿（组 8，需先决策）
```

---

## 8. 未解决问题

1. **外部改动授权未确认（REVIEW）**  
   cleanup、documentation、tests 重构、README/CHANGELOG、reports 迁移均由并行任务产生；本任务只能依据其自述和内容判断，不能确认用户授权。全部标记 REVIEW。

2. **19 份报告迁移不是逐字节一致**  
   8 份 EXACT、11 份 EQUIVALENT（仅路径引用更新）。内容未发现缺失，但需人工接受“路径更新型迁移”。

3. **README/CHANGELOG 在审查期间继续变化**  
   10:41 与 10:45 的 v4.1.2 状态文本不同；当前已与 GitHub Release 对齐，但仍需等并行任务稳定后做最终核对。

4. **`reports/w5/be95e82-review.patch` 已被删除**  
   `cleanup-final-report.md` 记录：删除前已实测与 `git diff be95e82^ be95e82` 逐字节一致，可重建。该文件原本未跟踪，删除不可从 Git 恢复，但内容可从 Git 重建；影响低，标记 REVIEW。

5. **全量测试证据**  
   - 6 个重构测试文件：40/40 通过（本次独立执行）。
   - W5：109/109；契约：72/72；Ruff：通过。
   - 全量：**653/653 通过（239.586s，0 失败/0 错误/0 跳过，退出码 0）**；运行期间 `WORKTREE_STABLE=True`。
   - `cleanup-final-report.md` 另声称两次全量通过（219.676s / 225.079s），与本次独立结果一致。

6. **`tests/__init__.py` 不存在**  
   `discover -s tests -t .` 本来就不支持；不是本次重构引入。标准命令 `-s tests` 与直接执行均通过。

7. **报告迁移与 `dist/` 的提交风险**  
   当前没有暂存任何新增报告；不得执行 `git add -A` 或 `git commit -a`。迁移必须“删除 + 新增 + 路径更新”原子提交。

8. **G1.5 状态**  
   本任务不批准 G1.5；R3 未提交、任务书 §八 仍 BLOCKED、外部改动归属未确认。CONDITIONAL_PASS 不应升级。

---

## 9. 审查边界

- 未修改、删除、移动、暂存任何既有文件。
- 未执行 commit、push、stash、reset、clean。
- 未启动 B2/B3，未批准 G1.5。
- 仅新增本报告 `reports/cleanup/worktree-change-audit.md`。
