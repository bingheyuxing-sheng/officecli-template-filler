# W5-B1-R3 输入边界修复与独立复验报告

- 报告日期：2026-11-07
- Git 基线：`main` @ `37ec46f78eefd75da065a911371c864bb01b7dff`
- 远程基线：`origin/main` @ `bd9a2d6`
- 结论：**PASS**（仅针对 R3 两项输入边界修复；不构成 G1.5 自动批准）
- 修改范围：`document_backends/result.py`、`tests/w5/test_b1_result.py`
- 未执行：commit、amend、push、rebase、reset、stash、版本元数据修改、报告归档、B2/B3

---

## 1. 任务范围与约束

本次只修复 G1.5 审查发现的两个 R3 输入边界问题：

1. `BackendResult.success()` / `failure()` 使用 `per_op or {}`，使空 list、空 tuple、空字符串等假值非 Mapping 输入绕过类型检查。
2. `BackendResult.__post_init__` 使用 `str(key)` 强制转换键，可能让不同原始键转换成同一个字符串并静默覆盖。

允许修改的文件只有：

```text
document_backends/result.py
tests/w5/test_b1_result.py
```

未修改 README、CHANGELOG、AGENTS.md、SKILL.md、contracts/、schemas/、config/error-codes.json、base.py、其他生产代码或其他测试文件。

---

## 2. 修复前问题分析

### 2.1 Mapping 类型检查绕过

修复前代码：

```python
return cls(backend=backend, ok=True, detail=detail, per_op=per_op or {})
return cls(backend=backend, ok=False, reason_code=reason_code,
           detail=detail, per_op=per_op or {})
```

`per_op=[]`、`per_op=()`、`per_op=""`、`per_op=0`、`per_op=False` 都会被 `or {}` 替换为空 dict，随后通过 `__post_init__` 的 Mapping 检查。结果是：非法容器类型被静默接受，工厂方法与直接构造的输入契约不一致。

### 2.2 键转换碰撞

修复前代码：

```python
frozen_ops[str(key)] = value
```

`{1: outcome_a, "1": outcome_b}` 在转换后都变成键 `"1"`，后写入的值覆盖前一个，导致一个 op 记录静默丢失。

---

## 3. 修复实现

### 3.1 统一构造校验

文件：`document_backends/result.py`，`BackendResult.__post_init__`。

```python
if not isinstance(self.per_op, Mapping):
    raise ValueError("per_op must be a mapping of op_id -> OpOutcome")
frozen_ops: Dict[str, OpOutcome] = {}
for key, value in dict(self.per_op).items():
    if not isinstance(key, str) or not key:
        raise ValueError(
            "per_op keys must be non-empty strings, got %r" % (key,)
        )
    if not isinstance(value, OpOutcome):
        raise ValueError(
            "per_op[%r] must be an OpOutcome, got %r" % (key, type(value).__name__)
        )
    frozen_ops[key] = value
object.__setattr__(self, "per_op", MappingProxyType(frozen_ops))
```

设计要点：

- 键类型契约采用严格非空字符串，与 `BackendOp.op_id` 的现有约束一致。
- 不再调用 `str(key)`；非法键直接拒绝，不做静默转换。
- Mapping 类型检查、键检查、值检查都集中在 `__post_init__`，工厂方法与直接构造共享同一套规则。
- 异常类型继续使用 `ValueError`，与现有项目风格一致。
- 公开方法签名未改变。

### 3.2 工厂方法只处理 None

文件：`document_backends/result.py`。

```python
@classmethod
def success(cls, backend: str, per_op: Optional[Mapping[str, OpOutcome]] = None,
            detail: str = "") -> "BackendResult":
    """Build an ``ok=True`` result."""
    if per_op is None:
        per_op = {}
    return cls(backend=backend, ok=True, detail=detail, per_op=per_op)

@classmethod
def failure(cls, backend: str, reason_code: ReasonCode, detail: str = "",
            per_op: Optional[Mapping[str, OpOutcome]] = None) -> "BackendResult":
    """Build an ``ok=False`` result carrying a structured reason."""
    if per_op is None:
        per_op = {}
    return cls(backend=backend, ok=False, reason_code=reason_code,
               detail=detail, per_op=per_op)
```

只有 `None` 被转换为空 dict；所有其他输入原样进入统一构造校验。

---

## 4. 新增测试

文件：`tests/w5/test_b1_result.py`，新增 `PerOpInputBoundaryTests`（5 个测试方法，使用 `subTest` 覆盖全部边界）。

| 测试方法 | 覆盖内容 |
|---|---|
| `test_none_becomes_an_empty_mapping_for_both_factories` | `success(None)` / `failure(None)` 均得到空 Mapping |
| `test_factories_accept_only_mappings` | `{}`、合法非空 Mapping 接受；`[]`、`()`、`""`、非空字符串、`set()`、`0`、`False`、`object()` 对两个工厂均拒绝 |
| `test_direct_construction_uses_the_same_contract` | 直接构造 `BackendResult(ok=True/False)` 对合法 Mapping 接受，对全部非法容器拒绝，与工厂契约一致 |
| `test_keys_must_be_non_empty_strings` | `"op-1"`、`"op-2"`、`"OP_003"` 接受且键值保持原样；`1`、`None`、`()`、`""`、`0` 对两个工厂均拒绝 |
| `test_mixed_or_multiple_invalid_keys_are_rejected_without_collapse` | `{1: a, "1": b}`、`{"op-1": a, 2: b}`、`{1: a, 2: b}`、`{None: a, "None": b}` 整体拒绝，不发生静默覆盖 |

原有测试未删除、未跳过、未弱化。

---

## 5. 独立复验结果

执行环境：Windows，`py -3.15`，仓库根目录 `<repo_root>`，HEAD `37ec46f`。

| # | 命令 | 测试数 | 通过 | 失败 | 错误 | 跳过 | 退出码 | 完整性 |
|---|---|---:|---:|---:|---:|---:|---:|---|
| 1 | `py -3.15 -m unittest discover -s tests/w5 -t . -p "test_*.py"` | 109 | 109 | 0 | 0 | 0 | 0 | 完整 |
| 2 | `py -3.15 -m unittest discover -s tests/contracts -t tests -p "test_*.py"` | 72 | 72 | 0 | 0 | 0 | 0 | 完整 |
| 3 | `py -3.15 -m unittest discover -s tests -p "test_*.py"` | 653 | 653 | 0 | 0 | 0 | 0 | 完整 |
| 4 | `py -3.15 -m ruff check .` | — | — | — | — | — | 0 | 完整 |

原始摘要：

```text
Ran 109 tests in 0.009s
OK
W5_EXIT=0

Ran 72 tests in 1.236s
OK
CONTRACTS_EXIT=0

Ran 653 tests in 256.163s
OK
FULL_EXIT=0

ruff 0.17.3
All checks passed!
RUFF_EXIT=0
```

说明：

- 第一次 W5 测试运行出现 4 个测试错误，原因是新增测试辅助方法命名为 `_outcome`，与 `unittest.TestCase` 内部 `_outcome` 属性冲突（`_Outcome object is not callable`）。已将辅助方法改名为 `_make_outcome`，这是测试代码自身的命名问题，不涉及生产逻辑；修正后 W5 109 项全部通过。
- 全量套件实际完整执行并结束；输出中的 `ResourceWarning` 为既有临时目录清理噪声，不影响 `OK` 结果。
- 未修改测试预期、未跳过测试、未降低断言强度。

---

## 6. R3 原有不变量回归

| # | 不变量 | 验证 |
|---|---|---|
| 1 | 构造时执行防御性复制 | 既有 `test_per_op_is_copied_into_a_plain_dict` 通过；源映射清空不影响结果 |
| 2 | 外部 Mapping 后续变化不影响结果 | 既有 `test_source_mapping_mutation_does_not_affect_result` 通过 |
| 3 | `BackendResult.per_op` 不可修改 | 既有 `test_per_op_is_read_only` 通过（setitem/delitem `TypeError`，无 clear/update） |
| 4 | 每个 value 必须是 `OpOutcome` | 既有 `test_per_op_rejects_non_opoutcome_values` 通过；新测试继续覆盖 |
| 5 | `to_dict()` 正常工作 | 既有序列化测试通过；新测试不改变 `to_dict()` |
| 6 | `success()` / `failure()` 相同输入约束 | 新增两个工厂的对称拒绝测试通过 |
| 7 | 直接构造与工厂构造相同契约 | 新增 `test_direct_construction_uses_the_same_contract` 通过 |
| 8 | 不影响 `ValidationResult` | 未修改 `ValidationResult` 代码；W5 测试全部通过 |
| 9 | 不影响 `ReasonCode` | 未修改 `ReasonCode` 或 catalog；注册表测试通过 |
| 10 | 不影响其他 `BackendResult` 字段 | 未修改 `backend`/`ok`/`reason_code`/`detail` 逻辑；既有测试通过 |

---

## 7. 范围合规检查

| 检查项 | 结果 |
|---|---|
| 只修改 `document_backends/result.py` | 是 |
| 只修改 `tests/w5/test_b1_result.py` | 是 |
| 未修改 README / CHANGELOG / AGENTS.md / SKILL.md | 是 |
| 未修改 contracts/ / schemas/ | 是 |
| 未修改 config/error-codes.json | 是 |
| 未修改 `document_backends/base.py` | 是 |
| 未修改其他生产代码或测试 | 是 |
| 未新增第三方依赖 | 是 |
| 未改变公开方法签名 | 是 |
| 未引入新错误码 | 是 |
| HEAD 保持 `37ec46f` | 是 |
| 未执行 git add / commit / push / rebase / reset / stash | 是 |

---

## 8. 遗留风险

1. **键类型收紧是有意行为变更**：旧实现接受任意键并 `str()` 转换；现在非字符串/空键直接 `ValueError`。这与 `Mapping[str, OpOutcome]` 类型声明及 `BackendOp.op_id` 的现有约束一致。当前 `BackendResult` 无生产调用方，仅 `tests/w5` 使用，风险低。
2. **本次未更新 CHANGELOG/README/版本元数据**：按任务 E3 留待后续独立任务；因此 4.2.0 文档不一致仍然存在。
3. **本次未修改 `reports/w5/` 原有报告**：R3 修复证据以本报告独立记录。
4. **G1.5 仍未正式批准**：本报告只证明 R3 两项输入边界已修复并通过复验，不构成 G1.5 自动通过，也不构成 Push 授权。
5. **任务书在 §八 处截断**：本报告按已收到的 §一–§七要求执行；如 §八 另有报告格式或路径要求，需人工补充确认。

---

## 9. 结论

**PASS**

- 问题一（`per_op or {}` 假值绕过）已修复：只有 `None` 转为空 Mapping，其余输入统一进入 `__post_init__` 校验。
- 问题二（`str(key)` 转换碰撞）已修复：`per_op` 键必须为非空字符串，非法键整体拒绝，不再发生静默覆盖。
- 新增 5 个边界测试方法，覆盖 `success()`、`failure()`、直接构造、合法/非法容器、合法/非法键、混合键与多非法键。
- 独立复验：W5 109 项、契约 72 项、全量 653 项、Ruff 全部通过，退出码均为 0。
- 未提交、未推送、未修改范围外文件；HEAD 仍为 `37ec46f`。
