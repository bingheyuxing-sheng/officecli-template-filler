# W5-G1.5 最终独立审查报告

- 审查性质：只读独立审查 + 实际测试复跑。
- 审查对象：W5-B1 基础接口、B1-R（R1–R5）、B1-R2 边界强化。
- 审查基线：本地 `main` @ `37ec46f`；远程 `main` @ `bd9a2d6`；本地领先 4、远程领先 0、无分叉。
- 最终建议：**PASS**（是否正式批准由人工决定；本报告不自行批准 G1.5）。
- 本报告未修改任何源代码、契约、Schema、README、CHANGELOG 或测试；未 commit / amend / push；未启动 B2/B3。

---

## 1. 审查范围与 Git 基线

### 1.1 审查范围

| 范围 | 内容 |
|---|---|
| B1 基础接口 | `DocumentBackend` 抽象类、五个抽象动词、FillPlan 操作模型约束、`batch` 唯一业务 mutation 入口、后端自行创造业务操作的可能性 |
| B1-R | R1 通用/OfficeCLI 错误码边界；R2 `ValidationResult` 四态；R3 `per_op` 不可变性；R4 能力证据约束；R5 路径安全与单写入者责任边界 |
| B1-R2 | `ValidationStatus`/`ReasonCode` 类型强制、UNVERIFIED 白名单、UNAVAILABLE/UNVERIFIED 互斥、`per_op` Mapping/OpOutcome 类型、防御性复制、MappingProxyType、ISO-8601 解析、时区强制、非法日期/时间/偏移、空白证据 |
| 测试验收 | `tests/w5`、`tests/contracts`、全量套件、Ruff |
| 冻结资产 | `contracts/`、`schemas/`、`config/error-codes.json`、旧接口兼容、KEEP_PY、Router、B2/B3 |

### 1.2 Git 基线（实测）

| 项 | 值 |
|---|---|
| 仓库根目录 | `D:/docs/officecli-template-filler` |
| 当前分支 | `main` |
| 本地 HEAD | `37ec46f78eefd75da065a911371c864bb01b7dff` |
| 远程 `main` | `bd9a2d6db5e09d927f33604049a79b0f7691202d` |
| 领先/落后 | 本地领先 4，远程领先 0 |
| 共同祖先 | `bd9a2d6` |
| 已跟踪工作区 | 干净（无暂存、无未暂存修改） |
| 未跟踪 | `dist/`、`reports/w5/` |
| 进行中的 merge/rebase/cherry-pick | 无 |

W5 四个本地提交：

```text
bd9a2d6 (origin/main)
  └─ d342fe5  W5-B0
      └─ d4d3c19  W5-B1
          └─ be95e82  W5-B1-R
              └─ 37ec46f  B1-R2  ← HEAD
```

---

## 2. B1 接口审查

### 2.1 抽象接口与五个抽象动词

源码位置：`document_backends/base.py` L242–L295。

`DocumentBackend(ABC)` 的抽象成员为：

| 成员 | 类型 | 源码位置 | 职责 |
|---|---|---|---|
| `name` | abstract property | L265–L268 | 稳定后端名（`officecli` / `python-docx`） |
| `capabilities(fmt)` | abstract method | L270–L272 | 返回 `CapabilityReport` |
| `batch(target, ops)` | abstract method | L274–L276 | 唯一业务 mutation 入口 |
| `readback(target, paths)` | abstract method | L278–L280 | 批量读回窗口 |
| `normalize(target, red_targets)` | abstract method | L282–L285 | 提交阶段规范化 |
| `validate(target)` | abstract method | L287–L295 | 四态 `ValidationResult` |

测试位置：

- `tests/w5/test_b1_base.py` L280–L297：`DocumentBackendAbcTests`，验证抽象类不可实例化、完整实现可实例化、`batch` 返回结构化结果。
- `tests/w5/test_b1_base.py` L254–L277：`_FakeBackend` 提供五个动词的最小合法实现。

正常行为证据：`test_abstract_class_cannot_be_instantiated` 通过；`test_full_implementation_is_instantiable` 通过；`test_batch_returns_a_structured_result` 通过。

拒绝行为证据：`DocumentBackend()` 直接实例化抛出 `TypeError`（L281–L283）。

遗留风险：

- 抽象类只规定必须实现哪些动词，Python 无法阻止未来具体后端新增额外公开方法（例如某些实现自行暴露 `add_*` / `remove_*`）。B2/B3 必须通过实现类公开面审查与测试固化来关闭，不能仅依赖 ABC。
- 当前没有测试以“恰好集合”方式断言 `DocumentBackend` 的抽象动词集合；这是覆盖缺口，不是当前代码缺陷。

### 2.2 FillPlan 操作模型约束

源码位置：

- `document_backends/base.py` L43：`OPERATION_KINDS = ("replace_text", "fill_paragraph", "fill_cell", "replace_image")`。
- `document_backends/base.py` L111–L142：`BackendOp` 仅含 `op_id/slot_id/kind/location_id/token/value`，**没有**授权、保护区域、容量或 policy 字段。
- `document_backends/base.py` L127–L142：拒绝未知 `kind`、空 id、文本操作缺 token、非字符串 value。

测试位置：

- `tests/w5/test_b1_base.py` L69–L113：`BackendOpTests`。
- `test_kinds_mirror_contract_03`（L91–L93）钉死四种操作类型。
- `test_unknown_kind_is_rejected`（L87–L89）拒绝 `delete_paragraph`。
- `test_text_op_requires_token`（L103–L105）与 `test_image_op_may_omit_token`（L107–L109）区分文本/图片操作。

正常行为证据：合法 `replace_text` / `replace_image` 构造成功。

拒绝行为证据：未知 kind、空 id、缺 token、非字符串 value 均抛出 `ValueError`。

遗留风险：

- `BackendOp` 是公开可构造的 dataclass。B1 没有实现后端，因此当前不存在运行时路径；但未来后端实现若自行构造 `BackendOp`，ABC 本身不会阻止。该风险属于 B2/B3 实现审查范围。

### 2.3 `batch` 是否为唯一 mutation 入口

结论：**在“FillPlan 业务操作 mutation”的限定语义下成立**。

源码证据：

- `document_backends/base.py` L249–L252：`batch` 被定义为 “the only mutation entry”，接收一组已授权操作并写入 `target.staged_path`。
- `document_backends/base.py` L7–L13：明确不存在 `add` / `remove` / `move` / `swap` 等结构动词；结构变更由 FillPlan `allow_structure_change=false` 排除。
- `document_backends/base.py` L83–L108：`BackendTarget` 强制 `template_path != staged_path`，后端只应写暂存路径。

测试位置：

- `tests/w5/test_b1_base.py` L60–L62：`test_template_and_stage_must_differ`。
- `tests/w5/test_b1_base.py` L290–L297：`test_batch_returns_a_structured_result`。

正常行为证据：`batch` 返回 `BackendResult`，每个 op 产生 `OpOutcome`。

拒绝行为证据：`template_path == staged_path` 被拒绝；未知操作类型被拒绝。

遗留风险（重要但非阻断）：

- `normalize()` 也写 `target.staged_path`（`base.py` L255–L258 明确定义为“pre-QA normalisation of the staged file”）。因此“`batch` 是唯一 mutation 入口”在字面上不覆盖 `normalize`。准确表述应为：**`batch` 是唯一的业务操作 mutation 入口；`normalize` 是受控的提交阶段规范化写路径**。
- 当前没有测试证明 `normalize` 只能执行固定的 w14 恢复/红字剥离，不能借机做业务修改；其签名只接受 `red_targets`，天然限制了范围，但 B2 实现仍需测试固化。
- 当前没有测试以“恰好集合”方式断言后端公开方法中只有 `batch` 能接收 `Sequence[BackendOp]`；建议 B2/B3 增加白名单测试。

### 2.4 后端是否可自行创造业务操作

结论：**B1 接口层没有提供这样的路径**。

证据：

- `DocumentBackend` 没有 “create op” / “plan” / “authorize” 方法；`BackendOp` 不含授权语义（`base.py` L111–L142）。
- `document_backends` 当前仅被自身测试引用，未被任何生产模块 import（`git grep "document_backends"` 仅命中 CHANGELOG 与包内文件）。
- 没有 Router、没有具体后端实现，因此当前没有运行时可执行路径。

遗留风险：

- 接口层不能强制未来后端不接收或构造任意 `BackendOp`；B2/B3 必须保证 `BackendOp` 只由 Router/Executor 从已授权 FillPlan 投影产生，并在实现类中禁止额外公开写方法。

---

## 3. R1–R5 逐项审查

### 3.1 R1 — 通用错误码与 OfficeCLI 专属错误码边界

| 项 | 内容 |
|---|---|
| 源码位置 | `document_backends/result.py` L166–L190（失败 reason 的通用 envelope）、L193–L204（`OFFICECLI_ENVELOPE_ALIASES`）、L207–L220（`envelope_code_for`） |
| 测试位置 | `tests/w5/test_b1_result.py` L121–L173（`EnvelopeAttributionTests`） |
| 正常行为证据 | `envelope_code_for(BATCH_ROLLED_BACK)` → `BACKEND_BATCH_FAILED`；`envelope_code_for(READBACK_MISMATCH)` → `BACKEND_READBACK_FAILED`；`envelope_code_for(NORMALIZE_FAILED)` → `BACKEND_NORMALIZE_FAILED`（测试 L128–L136） |
| 拒绝/边界证据 | `envelope_code_for(..., "python-docx")` 对所有失败 reason 均不以 `OFFICECLI_` 开头（L146–L153）；`backend="officecli"` 时才解析 B0 拼写（L138–L144）；同一失败双后端归属正确（L155–L162） |
| 注册表证据 | 通用码与 OfficeCLI 别名均已在 `config/error-codes.json` 注册（L164–L173） |
| 遗留风险 | `envelope_code_for` 的 `backend` 参数是调用方传入的字符串；若调用方错误传入 `"officecli"`，仍可把 python 侧失败标成 OfficeCLI 拼写。B2/B5 应把 backend 名绑定到实际后端实例，而不是由外部任意传参。 |

### 3.2 R2 — `ValidationResult` 四态模型

| 项 | 内容 |
|---|---|
| 源码位置 | `document_backends/result.py` L375–L503（`ValidationStatus`、`VALIDATION_UNVERIFIED_REASONS`、`ValidationResult`） |
| 测试位置 | `tests/w5/test_b1_result.py` L349–L497（`ValidationResultTests` + `ValidationStatusTypeTests`） |
| 四态定义 | `PASSED` / `FAILED` / `UNAVAILABLE` / `UNVERIFIED`（L375–L388） |
| 正常行为证据 | `passed()` 无 reason；`failed(detail)` 必带 `BACKEND_VALIDATE_FAILED`；`unavailable(detail)` 必带 `BACKEND_VALIDATE_UNAVAILABLE`；`unverified(tooling_reason, detail)` 保留追溯（测试 L358–L393） |
| 拒绝行为证据 | PASSED 携带 reason 被拒（L363–L365）；FAILED 缺 detail / 错 reason 被拒（L367–L376）；UNAVAILABLE 缺 detail 被拒（L378–L384）；UNVERIFIED 失败类 reason 被拒（L395–L400）；两非执行态不得等于 PASSED（L402–L409） |
| 遗留风险 | 当前 `ValidationResult` 允许 PASSED 携带非空 `detail`（未禁止），语义上不构成“伪装通过”，但会让“PASSED 无附注”的严格性弱于其他状态。B2/B3 可决定是否收紧。 |

### 3.3 R3 — `per_op` 不可变性

| 项 | 内容 |
|---|---|
| 源码位置 | `document_backends/result.py` L248–L283（`OpOutcome`）、L286–L359（`BackendResult.per_op` 与 `to_dict`） |
| 测试位置 | `tests/w5/test_b1_result.py` L209–L299（`BackendResultTests` 中 per_op 相关）、L302–L334（`OpOutcomeTests`） |
| 防御性复制 | 构造时 `dict(self.per_op)` 复制到新 dict，再包 `MappingProxyType`（L324–L331）；源映射构造后增改删不影响结果（测试 L267–L274） |
| 只读证据 | `result.per_op[...] = ...` / `del` 抛 `TypeError`；无 `clear`/`update`（测试 L221–L233） |
| 值不可变证据 | 每个值必须是 `OpOutcome`；对 `status` / `reason_code` 赋值抛 `FrozenInstanceError`（测试 L254–L284） |
| 序列化证据 | `to_dict()` 对 SUCCESS/FAILED/SKIPPED 均可 `json.dumps`（测试 L286–L299） |
| 遗留风险 | `BackendResult.success()/failure()` 使用 `per_op or {}`（result.py L337、L344）；当调用方传入 `[]` 这类“空但非 Mapping”的值时，会被静默替换为 `{}`，绕过构造器中的 “per_op must be a mapping” 检查。空值不携带数据，风险低，但类型契约在工厂路径上不完整。 |
| 遗留风险 | `per_op` 的键在 L330 被 `str(key)` 强制转换；若调用方同时传入 `1` 与 `"1"`，后者会覆盖前者，可能静默丢失一个 op 记录。实际 op_id 来自 FillPlan 字符串，风险低；建议 B2/B3 或后续补丁显式拒绝非字符串键。 |

### 3.4 R4 — `CapabilityRecord` / `CapabilityReport` 证据约束

| 项 | 内容 |
|---|---|
| 源码位置 | `document_backends/base.py` L52–L80（`_validate_verified_at`）、L145–L199（`CapabilityRecord`）、L202–L239（`CapabilityReport`） |
| 测试位置 | `tests/w5/test_b1_base.py` L116–L225（`CapabilityRecordTests` + `CapabilityEvidenceTests`）、L228–L251（`CapabilityReportTests`） |
| 未验证不得 available | `available=True` 必须 `verified=True` 且 `verified_by` 非空（L191–L197）；测试 L122–L132 |
| 证据项校验 | `verified_by` 必须是 tuple；每项必须是非空、非纯空白字符串（L178–L184）；空白项拒绝（测试 L211–L215）；重复项拒绝（L185–L188；测试 L164–L166） |
| 时间戳解析 | `datetime.fromisoformat` 真实解析（L68–L74）；无时区拒绝（L75–L79；测试 L199–L203）；非法日期（L175–L181）、非法时间（L183–L191）、越界偏移（L193–L197）均拒绝 |
| 合法形式 | `Z`、`+08:00`、`-05:00`、含微秒形式接受（测试 L205–L209）；`24:00:00` 按 ISO-8601 合法接受（L191） |
| 报告一致性 | `CapabilityReport` 拒绝外来 backend 记录与重复 `capability_id`（L212–L223；测试 L217–L225）；记录复制为 tuple（L224；测试 L247–L251） |
| 遗留风险 | `verified_by` 的唯一性按原始字符串精确比较；`"probe:P2"` 与 `" probe:P2 "` 会被视为两条不同证据（后者不是纯空白，因此通过）。证据卫生上建议在 B2/B3 统一 trim 后再比较或拒绝首尾空白。 |
| 遗留风险 | `verified_at` 在 `verified=True` 时仍可为 `None`；当前只校验“存在时必须合法”，未强制“已验证必须有时间戳”。任务未要求强制，保留为后续策略项。 |

### 3.5 R5 — 路径安全与单写入者责任边界

| 项 | 内容 |
|---|---|
| 源码位置 | `document_backends/base.py` L83–L108（`BackendTarget`）、L242–L262（`DocumentBackend` docstring） |
| 责任登记 | `reports/w5/w5-migration-plan.md` L239–L243（R5：路径安全归 Transaction；单写入者归统一 `DocumentTransaction`；后端不得自建路径安全逻辑或第二写入通道） |
| 测试位置 | `tests/w5/test_b1_base.py` L47–L66（`BackendTargetTests`），尤其 L60–L62 `test_template_and_stage_must_differ` |
| 正常行为证据 | 合法 `BackendTarget` 可构造；`docx` / `xlsx` 格式受支持（L64–L66） |
| 拒绝行为证据 | 空路径、未知格式、`template_path == staged_path` 均抛出 `ValueError`（L52–L62） |
| 实现边界 | `document_backends` 内没有 lock / flock / DocumentTransaction 代码（`git grep` 仅命中 docstring）；B1 不实现事务，符合“边界登记、B2/B5 实施”的定位 |
| 遗留风险 | 当前只有“模板路径 ≠ 暂存路径”的构造期快速防线；真正的路径穿越、暂存区唯一可写、单写入者锁生命周期尚未在 B1 实现。B2 后端与 B5 Router 必须按 R5 登记执行，不得各自维护锁或第二写入通道。 |

---

## 4. B1-R2 边界验证

| 检查项 | 源码位置 | 测试位置 | 正常证据 | 拒绝证据 | 遗留风险 |
|---|---|---|---|---|---|
| `ValidationStatus` 类型强制 | `result.py` L431–L437 | `test_b1_result.py` L428–L436 | `ValidationResult.passed()` 正常 | 裸字符串 `"PASSED"`、`None`、`1`、`object()`、list、dict 均 `ValueError` | 无 |
| `ReasonCode` 类型强制 | `result.py` L438–L443 | `test_b1_result.py` L438–L449 | 合法 `ReasonCode` 正常 | 字符串、数字、对象、list 均 `ValueError` | 无 |
| UNVERIFIED 白名单 | `result.py` L396–L399、L460–L471 | `test_b1_result.py` L451–L474 | 仅 `OFFICECLI_BINARY_MISSING` / `OFFICECLI_VERSION_UNSUPPORTED` 接受 | 文档回退、路由原因、`BACKEND_VALIDATE_UNAVAILABLE`、失败类 reason 全部拒绝 | 白名单是 frozenset，未来新增工具不可用原因需显式扩展并补测试 |
| UNAVAILABLE / UNVERIFIED 互斥 | `result.py` L455–L469 | `test_b1_result.py` L476–L482 | 各自使用正确 reason 时通过 | 交叉传入即 `ValueError` | 无 |
| `per_op` Mapping 类型 | `result.py` L322–L323 | `test_b1_result.py` L261–L265 | dict / Mapping 正常 | `None`、非空 list、字符串拒绝 | 工厂 `per_op or {}` 对空 list 的绕过（见 §3.3） |
| `OpOutcome` 值类型 | `result.py` L324–L331 | `test_b1_result.py` L254–L259 | 合法 `OpOutcome` 正常 | dict、str、None、42、list 拒绝 | 无 |
| 构造时防御性复制 | `result.py` L324–L331 | `test_b1_result.py` L267–L274 | 源映射清空后结果不变 | — | 无 |
| MappingProxyType 只读 | `result.py` L331 | `test_b1_result.py` L221–L233 | 读取/遍历正常 | setitem/delitem `TypeError`；无 clear/update | 无 |
| ISO-8601 真实解析 | `base.py` L52–L80 | `test_b1_base.py` L168–L209 | `Z`、`+08:00`、`-05:00`、微秒接受 | 空格分隔、缺时区、仅日期、`12345` 拒绝 | 依赖 `fromisoformat` 的版本行为；当前 Python 3.15 实测通过 |
| 时区强制 | `base.py` L75–L79 | `test_b1_base.py` L199–L203 | 带显式偏移/`Z` 通过 | 无时区拒绝 | 无 |
| 非法日期 | `base.py` L68–L74 | `test_b1_base.py` L175–L181 | 合法日期通过 | 13 月、2 月 30 日、0 月拒绝 | 无 |
| 非法时间 | `base.py` L68–L74 | `test_b1_base.py` L183–L191 | `24:00:00` 按标准接受 | `24:00:01`、`23:60`、秒 61 拒绝 | 无 |
| 越界偏移 | `base.py` L68–L79 | `test_b1_base.py` L193–L197 | 合法偏移通过 | `+99:00`、`-25:00` 拒绝 | 无 |
| `verified_by` 空白项 | `base.py` L180–L184 | `test_b1_base.py` L211–L215 | 非空证据通过 | 空格、制表、换行、混合空白拒绝 | 首尾带空白的非空证据仍接受（见 §3.4） |

---

## 5. 测试实际执行结果

执行环境：Windows，`py -3.15`，仓库根目录 `D:/docs/officecli-template-filler`，HEAD `37ec46f`。

| # | 命令 | 测试数 | 通过 | 失败 | 错误 | 跳过 | 退出码 | 结果 |
|---|---|---:|---:|---:|---:|---:|---:|---|
| 1 | `py -3.15 -m unittest discover -s tests/w5 -t . -p "test_*.py"` | 104 | 104 | 0 | 0 | 0 | 0 | `OK` |
| 2 | `py -3.15 -m unittest discover -s tests/contracts -t tests -p "test_*.py"` | 72 | 72 | 0 | 0 | 0 | 0 | `OK` |
| 3 | `py -3.15 -m unittest discover -s tests -p "test_*.py"` | 648 | 648 | 0 | 0 | 0 | 0 | `OK` |
| 4 | `py -3.15 -m ruff check .` | — | — | — | — | — | 0 | `All checks passed!` |

原始输出摘要：

```text
Ran 104 tests in 0.013s
OK
W5_EXIT=0

Ran 72 tests in 2.029s
OK
CONTRACTS_EXIT=0

Ran 648 tests in 31248.375s
OK
FULL_EXIT=0

ruff 0.17.3
All checks passed!
RUFF_EXIT=0
```

说明：

- 全量套件实际完整执行并结束；`unittest` 打印的 31248.375s 包含环境挂起/暂停时间，不代表实际计算耗时，结果以 `Ran 648 tests / OK / FULL_EXIT=0` 为准。
- 第一次全量运行因终端后台化被中止，未计入测试结果；上表第 3 行为重新执行并落盘的完整结果。
- 全量运行中的 `ResourceWarning`（临时目录清理）与 `UserWarning: Duplicate name: '[Content_Types].xml'` 为既有测试噪声，不导致失败；不影响 `OK` 结论。
- 未删除、跳过、弱化任何测试；未修改测试预期。

---

## 6. 冻结契约检查

| 检查项 | 命令/方法 | 结果 |
|---|---|---|
| `contracts/` 无修改 | `git status --porcelain -- contracts schemas config`；`git diff --stat bd9a2d6..HEAD -- contracts schemas` | 工作区无变更；与远程基线差异为空 |
| `schemas/` 无修改 | 同上 | 工作区无变更；差异为空 |
| `config/error-codes.json` 只增 | 对比 `bd9a2d6` 与 HEAD 的 JSON | 34 → 56；删除 0；既有条目修改 0；新增 22 条全部 `introduced_in = "4.2.0"` |
| 注册表完整性 | `tests/w5/test_b1_registry.py` | 104 项 W5 测试通过，其中注册表治理测试全部通过 |
| 错误码字段完整性 | `test_b1_additions_declare_full_semantics` | 新增条目均含 `code/severity/retryable/rollback_required/human_intervention/owner/message_template/introduced_in` |
| 回滚语义 | `test_failure_reason_additions_require_rollback` / `test_fallback_reason_additions_do_not_require_rollback` | 失败类新增码要求回滚；回退类新增码不要求回滚 |

新增 22 条错误码清单：

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

---

## 7. 兼容性检查

| 检查项 | 证据 | 结果 |
|---|---|---|
| 旧公共 API 未被移除 | `tests/contracts/test_legacy_compat.py` L18–L24：`engine.__all__` 逐项存在性检查 | 通过（契约测试 72 项全绿） |
| 引擎版本声明一致 | `engine/__init__.py` L187：`__version__ = "4.2.0"`；兼容测试同步期望 4.2.0 | 通过 |
| 默认写入后端未翻转 | `document_engine/fill_executor.py` L1157：`writer: str = "python-docx"`；`scripts/generate_document.py` L171：`--writer` 默认 `python-docx` | 通过 |
| B0 写入路径未被 B1 改写 | `git diff --stat d342fe5..HEAD -- engine/officecli_writer.py document_engine scripts/generate_document.py template_gate` 为空 | 通过 |
| `document_backends` 惰性、未接入生产 | `git grep "document_backends"` 仅命中 CHANGELOG 与包内文件；无生产 import | 通过 |
| KEEP_PY 能力未提前迁移 | 无 `officecli_backend.py` / `python_backend.py`；`document_backends` 仅 3 个基础文件；B0 的 `engine/officecli_writer.py` 与执行器未被 B1 修改 | 通过 |
| Router 未提前接入 | 无 `operation_router.py`；`document_backends/__init__.py` 仅 docstring 提及未来模块，无实现 | 通过 |
| B2/B3 未提前实施 | `git ls-files` 无 `officecli_backend` / `python_backend` / `capability_registry` / `operation_router` | 通过 |
| 冻结契约未变 | `contracts/`、`schemas/` 与 `bd9a2d6` 差异为空 | 通过 |

---

## 8. 未解决风险

按严重度排序。以下均为**非阻断性**风险；不改变 G1.5 的 PASS 建议，但应在 B2/B3 或后续补丁中处理。

1. **`normalize()` 是第二个写路径（低）**  
   `DocumentBackend` 文档宣称 `batch` 是唯一 mutation 入口，但 `normalize()` 也写 `target.staged_path`。建议将措辞精确为“唯一业务操作 mutation 入口”，并在 B2 中测试 `normalize` 只能执行固定的 w14 恢复/红字剥离。

2. **抽象接口缺少“恰好五个动词”的测试（低）**  
   当前测试验证 ABC 不可实例化和可完整实现，但没有以集合方式断言抽象动词恰好为 `name/capabilities/batch/readback/normalize/validate`。建议 B2 前补一条结构性测试，防止未来无意新增写动词。

3. **`BackendResult` 工厂对空非 Mapping 的绕过（低）**  
   `result.py` L337/L344 使用 `per_op or {}`，`BackendResult.success(per_op=[])` 会绕过 “per_op must be a mapping” 检查。空值不携带数据，风险低；建议改为显式 `per_op if per_op is not None else {}`。

4. **`per_op` 键强制转字符串可能折叠重复键（低）**  
   `result.py` L330 的 `str(key)` 会让 `{1: op_a, "1": op_b}` 发生静默覆盖。建议显式拒绝非字符串键或检测转换后重复。

5. **`verified_by` 首尾空白未归一化（低）**  
   `" probe:P2 "` 与 `"probe:P2"` 被视为不同证据。建议 B2/B3 统一 trim 后再做唯一性比较。

6. **`verified_at` 对已验证记录非强制（低）**  
   `verified=True` 只要求 `verified_by`，不要求 `verified_at`。任务未强制；若证据策略要求时间可比较，应在 B4 能力注册表阶段收紧。

7. **版本元数据不一致（中，非 G1.5 代码门禁）**  
   `engine/__init__.py`、`SKILL.md`、`references/python-docx-engine.md`、`tests/contracts/test_legacy_compat.py` 已是 **4.2.0**；CHANGELOG `Unreleased` L11 仍写“软件版本与契约集保持不变（4.1.2 / 4.3.0）”，README L7–L15 仍为 **v4.1.2**。这不影响 B1 接口正确性，但在远程同步/发布前必须修正，否则远程 `main` 会呈现自相矛盾的版本信息。

8. **W5-A 报告未纳入版本控制（中，非 G1.5 代码门禁）**  
   `reports/w5/w5-architecture-audit.md`、`w5-capability-matrix.md`、`w5-target-architecture.md`、`w5-migration-plan.md` 均为未跟踪文件，仅本地存在。是否入库需人工决定；不影响 B2/B3 启动。

9. **全量测试耗时异常（环境，非代码）**  
   本次全量套件打印 31248.375s，包含环境挂起时间；测试结果为 648 项通过。未发现测试超时、挂起或资源泄漏导致的失败。

---

## 9. G1.5 最终建议

### 9.1 强制条件核对

| 强制条件 | 结果 | 证据 |
|---|---|---|
| `DocumentBackend` 五动词与 FillPlan 操作模型正确 | 满足 | §2.1 / §2.2 |
| `batch` 是唯一业务 mutation 入口 | 满足（限定语义） | §2.3 |
| 后端无自行创造业务操作的接口路径 | 满足 | §2.4 |
| R1 通用/OfficeCLI 错误码边界正确 | 满足 | §3.1 |
| R2 四态模型正确 | 满足 | §3.2 |
| R3 `per_op` 不可变性正确 | 满足 | §3.3 |
| R4 能力证据约束正确 | 满足 | §3.4 |
| R5 路径安全与单写入者责任边界已登记 | 满足（B1 范围） | §3.5 |
| B1-R2 类型强制/白名单/互斥/防御性复制/ISO-8601 全部落实 | 满足 | §4 |
| `tests/w5` 全绿 | 满足 | 104 / 104，退出码 0 |
| `tests/contracts` 全绿 | 满足 | 72 / 72，退出码 0 |
| 全量测试全绿 | 满足 | 648 / 648，退出码 0 |
| Ruff 全绿 | 满足 | `All checks passed!`，退出码 0 |
| `contracts/`、`schemas/` 未修改 | 满足 | §6 |
| `config/error-codes.json` 只增不改 | 满足 | 34 → 56，0 删除，0 既有条目修改 |
| 旧接口兼容性未破坏 | 满足 | §7 |
| KEEP_PY 未提前迁移 | 满足 | §7 |
| Router 未提前接入 | 满足 | §7 |
| B2/B3 未提前实施 | 满足 | §7 |

### 9.2 最终状态

**PASS**

理由：B1 接口、R1–R5、B1-R2 边界、冻结资产、兼容性与全部测试均满足强制条件；未发现阻断 B2/B3 的技术缺陷。§8 的 9 项风险均为低/中级别、非阻断，且大部分属于 B2/B3 实现期或发布前应处理的跟进项。

### 9.3 进入 B2/B3 的附加建议（不阻断）

1. 在 B2 开始前补一条“抽象动词恰好集合”的结构性测试，并把 `normalize()` 的写权限限定写入实现测试。
2. 修正 `BackendResult` 工厂的 `per_op or {}`，显式区分 `None` 与非法空容器。
3. 在 B4 能力注册表实现时统一 `verified_by` 的 trim/唯一性策略，并决定 `verified_at` 是否对已验证记录强制。
4. 远程同步/发布前修正 CHANGELOG 与 README 的 4.1.2/4.2.0 版本声明；该事项不属于 G1.5 代码门禁，但属于发布门禁。
5. 人工决定 `reports/w5/` 四份 W5-A 报告是否入库。

### 9.4 审查边界声明

- 本报告是独立审查建议，**不构成 G1.5 的正式人工批准**。
- 未启动 B2/B3；未修改任何代码、契约、Schema、测试、README 或 CHANGELOG；未执行 commit / amend / push / 删除 / 重命名。
- 最终是否批准 G1.5、是否进入 B2/B3，由人工决定。

---

## 附录：本次审查实际执行的只读检查

```text
git rev-parse --show-toplevel
git branch --show-current
git status --short --branch
git log --oneline --decorate -25
git branch -vv
git remote -v
git worktree list
git stash list
git diff --stat
git diff --cached --stat
git status --porcelain=v1 --ignored --untracked-files=normal
git ls-files
git ls-files document_backends
git diff --stat bd9a2d6..HEAD -- contracts schemas
git diff --name-status bd9a2d6..HEAD -- config
git diff --stat d342fe5..HEAD -- engine/officecli_writer.py document_engine scripts/generate_document.py template_gate
git diff bd9a2d6..HEAD -- tests/contracts/test_legacy_compat.py
git diff bd9a2d6..HEAD -- engine/__init__.py
git grep -n "document_backends" -- ":!tests/w5" ":!document_backends"
git grep -n -E "operation_router|OperationRouter|capability_registry|officecli_backend|python_backend"
git grep -n -E "lock|flock|DocumentTransaction|transaction" -- document_backends
```

测试与静态检查：

```text
py -3.15 -m unittest discover -s tests/w5 -t . -p "test_*.py"        → 104 OK, exit 0
py -3.15 -m unittest discover -s tests/contracts -t tests -p "test_*.py" → 72 OK, exit 0
py -3.15 -m unittest discover -s tests -p "test_*.py"               → 648 OK, exit 0
py -3.15 -m ruff check .                                             → All checks passed!, exit 0
```
