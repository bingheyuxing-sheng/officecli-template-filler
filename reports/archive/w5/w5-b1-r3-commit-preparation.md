# W5-B1-R3 独立提交准备报告

- 报告日期：2026-11-07
- 基线：`main` @ `37ec46f`；远程 `origin/main` @ `bd9a2d6`
- 准备对象：`document_backends/result.py`、`tests/w5/test_b1_result.py`
- 审查性质：只读 diff 核对 + 测试复跑；未执行 `git add`、commit 或 push
- 结论：**CONDITIONAL_READY**（文本上可独立提交；当前工作区不稳定，全量证据尚未隔离，暂不建议执行提交）

---

## 1. 修改摘要

### 1.1 `document_backends/result.py`（+17 / −6）

| 位置 | 修改 | 目的 |
|---|---|---|
| `BackendResult.__post_init__` | 新增 `if not isinstance(key, str) or not key: raise ValueError(...)`；删除 `str(key)` | 键必须为非空字符串；禁止不同原始键转换为同一字符串后静默覆盖 |
| 注释 | 把 R3 注释更新为“键必须非空字符串、值必须为 OpOutcome、绝不转换键” | 让构造期契约与实现一致 |
| `BackendResult.success()` | `per_op or {}` 改为 `if per_op is None: per_op = {}` | 只有 `None` 转为空 dict；空 list/tuple/字符串等必须进入统一 Mapping 校验 |
| `BackendResult.failure()` | 同上 | 两个工厂保持完全相同的输入契约 |

### 1.2 `tests/w5/test_b1_result.py`（+98 / −0）

新增 `PerOpInputBoundaryTests`，5 个测试方法：

| 测试方法 | 覆盖 |
|---|---|
| `test_none_becomes_an_empty_mapping_for_both_factories` | `success(None)` / `failure(None)` 均为空 Mapping |
| `test_factories_accept_only_mappings` | `{}`、合法 Mapping 接受；`[]`、`()`、`""`、非空字符串、`set()`、`0`、`False`、`object()` 拒绝 |
| `test_direct_construction_uses_the_same_contract` | 直接构造与两个工厂契约一致 |
| `test_keys_must_be_non_empty_strings` | `"op-1"` 等接受；`1`、`None`、`()`、`""`、`0` 拒绝 |
| `test_mixed_or_multiple_invalid_keys_are_rejected_without_collapse` | `{1: a, "1": b}`、混合键、多非法键整体拒绝，不静默覆盖 |

未删除、跳过或弱化任何既有测试。

---

## 2. 与 R3 修复报告一致性

| 检查项 | 结果 |
|---|---|
| 修改文件与 `w5-b1-r3-fix-review.md` 一致 | **是**：仅两个文件 |
| 生产代码只改 `result.py` 的工厂与键校验 | **是** |
| 测试只新增 `PerOpInputBoundaryTests` | **是** |
| 未修改公开方法签名 | **是** |
| 未引入新错误码/契约变更 | **是** |
| 未修改 `base.py`、`config/error-codes.json`、contracts、schemas | **是** |

---

## 3. 隔离核对

当前工作树还包含其他任务的文件（详见 `w5-worktree-isolation-review.md`）：

```text
 M CHANGELOG.md
 M README.md
 M document_backends/result.py          ← R3
 M tests/test_e2e_v4.py
 M tests/test_fixture_matrix.py
 M tests/test_template_gate_e2e.py
 M tests/test_template_gate_enforcement.py
 M tests/test_transaction_gate.py
 M tests/test_w2_defects.py
 M tests/w5/test_b1_base.py
 M tests/w5/test_b1_result.py            ← R3
?? tests/support.py
```

结论：

- **R3 的文本 diff 可隔离**：`git diff -- document_backends/result.py tests/w5/test_b1_result.py` 只包含本报告 §1 的内容。
- **其他改动不属于 R3**：README/CHANGELOG、6 个测试文件、`tests/support.py`、`test_b1_base.py` 均为外部并发改动，归属 REVIEW。
- **不得使用 `git add -A` / `git add .`**：会把外部改动混入 R3 提交。
- **本任务未执行任何暂存/提交操作。**

---

## 4. 测试结果

| # | 命令 | 测试数 | 通过 | 失败 | 错误 | 跳过 | 退出码 | 说明 |
|---|---|---:|---:|---:|---:|---:|---:|---|
| 1 | `py -3.15 -m unittest discover -s tests/w5 -t . -p "test_*.py"` | 109 | 109 | 0 | 0 | 0 | 0 | 当前工作树；含外部 `test_b1_base.py` 一行改动，但 R3 测试文件本身未混入外部修改 |
| 2 | `py -3.15 -m unittest discover -s tests/contracts -t tests -p "test_*.py"` | 72 | 72 | 0 | 0 | 0 | 0 | 通过 |
| 3 | `py -3.15 -m unittest discover -s tests -p "test_*.py"` | 653 | 653 | 0 | 0 | 0 | 0 | R3-only 测试集（外部测试重构前）；当前混合树重跑因外部测试重构被排除 |
| 4 | `py -3.15 -m ruff check .` | — | — | — | — | — | 0 | `All checks passed!` |

原始摘要（已确认部分）：

```text
Ran 109 tests in 0.008s
OK
W5_EXIT=0

Ran 72 tests in 1.307s
OK
CONTRACTS_EXIT=0

Ran 653 tests in 223.268s
OK
FULL_EXIT=0

ruff 0.17.3
All checks passed!
RUFF_EXIT=0
```

说明：

- W5 109 项与 R3 报告一致（104 基线 + 5 新增）。
- 当前 W5 运行包含外部 `tests/w5/test_b1_base.py` 的一行断言调整；该文件不属于 R3，不能计入 R3 的独立证据。
- 全量 653/653 来自 10:13 前的 R3-only 测试集（外部测试重构尚未开始）；10:18 的混合树全量运行因外部测试重构被中止，未计入。因此 R3 的全量证据可用，但当前工作树的全量结果不能归因于 R3。

---

## 5. 是否能够安全地独立提交

### 5.1 文本层面

**可以。** 只要暂存以下两个文件，提交内容就是纯 R3：

```text
document_backends/result.py
tests/w5/test_b1_result.py
```

### 5.2 证据层面

**R3 自身的证据完整，但当前工作区不适合执行提交。** 原因：

1. R3-only 测试集已通过：W5 109、契约 72、全量 653、Ruff。
2. 当前工作区在 10:09–10:17 期间持续被外部任务修改，尚未稳定。
3. 外部测试重构与 `test_b1_base.py` 改动会污染当前混合树的全量结果；10:18 的混合树全量运行已中止，未计入。
4. 外部改动尚未确认授权与提交边界。

### 5.3 结论

- **可以准备**独立提交：两个文件的 diff 清晰，R3-only 测试证据完整。
- **不建议现在执行**提交；应先完成工作区隔离与外部任务授权确认，再以精确两文件暂存方式创建提交。
- 本任务未执行 `git add`、commit、push。

---

## 6. 风险与建议

| 风险 | 等级 | 建议 |
|---|---|---|
| `git add -A` 混入 README/CHANGELOG/外部测试 | 高 | 只允许精确指定两个文件 |
| 外部测试重构改变全量结果归因 | 中 | 等待隔离后重跑全量 |
| `tests/w5/test_b1_base.py` 外部改动被误认为 R3 | 中 | 明确排除；不纳入 R3 提交 |
| 并行任务继续写入 | 中 | 提交前再次检查 `git status` |
| R3 未提交导致批准对象不稳定 | 中 | 获授权后以独立提交固化 |

---

## 7. 结论

**CONDITIONAL_READY**

- 两个 R3 文件的修改与修复报告一致，文本上可独立提交。
- 当前工作树包含未确认归属的外部文档/测试改动，全量证据尚未隔离，因此不满足“现在即可安全提交并归档证据”的条件。
- 建议先完成工作区隔离与外部任务授权确认，再以精确两文件暂存方式创建 R3 独立提交，并在提交后重新执行全量测试。
