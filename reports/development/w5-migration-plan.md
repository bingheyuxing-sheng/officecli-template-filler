# W5 迁移计划（Migration Plan）

- 文档性质：**实施计划，待人工确认；确认前不启动任何代码变更。**
- 生成日期：2026-11-06（W5-A 审计阶段）
- 配套文档：[w5-architecture-audit.md](w5-architecture-audit.md)（现状与证据）、[w5-target-architecture.md](w5-target-architecture.md)（目标设计，本计划的任务均指向该设计）、[w5-capability-matrix.md](w5-capability-matrix.md)（能力清单）
- 执行约束：AGENTS.md §14（任务六要素）、§15（阶段门禁）；每任务完成必须附测试证据，未附证据不得标记验收。

---

## 0. 前置任务 B0：工作树基线整理（先于一切编码）

**问题**：当前 main 工作树含约 590 行未提交的 OfficeCLI writer 变更（audit §1.3：`engine/officecli_writer.py`、`tests/test_officecli_writer.py` untracked + 11 文件 modified）。W5-B 在脏基线上开工会使 W5 变更与既有变更无法区分、无法回滚。

**任务**：
1. 全量回归 + contracts 回归，取得该变更的测试证据（基线声明 532+ / 70，以实际运行结果为准）；
2. 以独立功能提交入库（建议消息：`feat(backends): officecli writer backend with run-scoped fill routing`）；
3. W5-B 在干净基线上开 `document_backends/` 层。

**出口条件**：`git status` 干净（dist/ 归档除外）；全量测试证据入 reports/w5/。
**回滚**：不适用（纯提交流程；若测试失败则修复后重提，禁止带病提交）。
**决策点（需人工）**：是否允许 B0 提交，或指示其他处理方式（如 squash 到 W5-B 首个提交）。

### B0.1 基线证据（已预采集，2026-11-06，G0 等待期只读操作）

任务 1 已在 G0 暂停期间完成（只读，未提交、未改任何代码）：

| 命令（cwd=仓库根，解释器 `py -3.15`） | 结果 |
|---|---|
| `py -3.15 -m unittest discover -s tests -p "test_*.py"` | **Ran 544 tests in 227.055s — OK**（退出码 0，0 失败/0 错误） |
| `py -3.15 -m unittest discover -s tests/contracts -t tests -p "test_*.py"` | **Ran 72 tests in 1.185s — OK**（退出码 0） |

说明：全量实测 544（SKILL.md 树状图声称 532，差异来自未提交的 `test_officecli_writer.py` 与 `test_template_gate_store.py` 增量，已在工作树内）；契约实测 72（W4-0 记录 70，+2 来自 `test_legacy_compat.py` 修改）。**未提交工作树当前处于全绿状态，具备 B0 提交条件**；剩余仅任务 2（提交动作本身）待 G0 批准。

### B0.2 提交前检查与提交记录（G0 批准后执行，2026-11-06）

**人工决策批准范围**：D1（审计判定接受）、D2（能力组串行路由接受）、新增冻结约束 E7（路由可解释）/E8（阶段间状态可验证）/E9（事务级完整回滚）；B0 有条件批准——通过六项只读检查后执行独立提交。

**六项检查结果**：

| # | 检查项 | 结果 |
|---|---|---|
| 1 | 分支/工作区状态 | ✅ 分支 `main`，与 origin/main 同步（0 ahead/0 behind）；11 modified + 2 untracked 源文件 + dist/、reports/w5/（排除项） |
| 2 | 变更文件范围 | ✅ 13 个文件（11 修改 + 2 新增），`git diff --stat`：1154 插入 / 83 删除 |
| 3 | 无关修改/调试/敏感信息/意外删除 | ✅ `git diff` 全量扫描：无 print/pdb/TODO/FIXME/密钥/绝对路径残留；fill_executor 的 79 行删除为旧内联 mutation 循环**原样提取**至 `_apply_operations_in_memory`（非弱化）。**披露**：变更集含 `template_gate/store.py` HMAC 密钥 bytes 修复（+1 回归测试，CHANGELOG Unreleased Fixed 节已记录，属同一发布单元）——已在提交 body 中披露 |
| 4 | 提交范围严格限定 B0 | ✅ 暂存仅 13 个指定文件；`dist/`（3 个发布归档）与 `reports/w5/`（W5-A 文档）保持未跟踪、未入暂存 |
| 5 | 测试证据对应待提交代码 | ⚠️→✅ CHANGELOG 原文"542 项（新增 7 项）"与实测不符（实测 544 = 535 基线 + 9 新增，其中 2 项依赖 officecli 二进制、缺失时跳过——原作者数字来自无二进制环境）。已修正 CHANGELOG 为实测值 544/9 并注明跳过条件后提交 |
| 6 | diff --stat / diff --check / 清单 | ✅ `git diff --check` 通过（仅既有 CRLF 警告，无空白错误）；文件清单见下 |

**提交记录**：

| 项 | 值 |
|---|---|
| commit | **`d342fe5`**（`d342fe5a0f396f077da0d6938909c17749dbaf29`） |
| 消息 | `feat(backends): officecli writer backend with run-scoped fill routing`（含 body：run-scoped 路由/w14 恢复/store 修复披露/版本 4.2.0/测试证据） |
| 文件 | CHANGELOG.md, SKILL.md, document_engine/fill_executor.py, document_engine/pipeline.py, engine/__init__.py, engine/officecli_writer.py（新增）, references/python-docx-engine.md, scripts/generate_document.py, template_gate/store.py, tests/contracts/test_legacy_compat.py, tests/real_corpus_eval.py, tests/test_officecli_writer.py（新增）, tests/test_template_gate_store.py |
| 统计 | 13 files changed, 1154 insertions(+), 83 deletions(-) |
| 提交前测试 | 全量 544 通过（227.055s）/ 契约 72 通过（1.185s），退出码 0 |
| 提交后复验 | **全量 544 通过（235.106s）+ 契约 72 通过（1.291s）**，均在提交后同树状态（HEAD=`d342fe5`）复跑，测试证据与已提交代码严格对应（B0.1 的全量运行先于 CHANGELOG 计数修正，本复验闭合该时序缺口）；`git status` 仅剩 dist/、reports/w5/ 未跟踪 |

**B0 出口条件达成**：基线已入库（`git status` 无源代码未提交项）；测试证据已记录于本节。**B0 完成，暂停等待人工检查提交结果；未获批准不开始 B1。**

---

### B1 执行记录（G1 批准后执行，2026-11-06）

G1 人工审查批准 B0 提交并授权 B1（10 项执行要求 + 8 项出口交付物）。B1 严格限定为 Adapter 基础骨架：无 Router、无探针基础设施、无后端实现、不迁移任何 KEEP_PY 能力、零契约修改。

#### 交付物 1：模块设计说明

`document_backends/` 三个模块（B1 范围），其余四个（officecli_backend/python_backend/capability_registry/operation_router）按计划归 B2–B5：

- `base.py` — 抽象接口按 **FillPlan 4.0 操作模型**设计（契约 03），不照搬 CLI 动词。**无 add/remove/move/swap**（`allow_structure_change=false` 下无合法调用者）；`batch()` 是唯一 mutation 入口，BackendOp 不携带任何授权词汇（preconditions/保护区/容量由执行器前置完成，后端无法"顺手扩大范围"）。`CapabilityRecord` 把"未验证不得标记为支持"做成构造期不变量。
- `result.py` — 四类错误分类学 + 15 个 reason code 词汇（全部注册进 error-codes.json，无平行状态词汇）。`BackendResult` 不变量：成功必无 reason、失败必有 reason、detail 截断 300 字符（防文档内容泄漏进报告）；`OpOutcome` 强制 FAILED 携带 reason、SHA-256 字段 64 位 hex 校验（E5 前后状态记录）。
- `__init__.py` — 仅公共导出。

#### 交付物 2：接口定义与类型约束

| 类型 | 关键约束（构造期强制） |
|---|---|
| `BackendTarget(template_path, staged_path, fmt)` | fmt ∈ {docx, xlsx}；路径非空；**template ≠ staged**（模板只读基准，AGENTS §1.1.1） |
| `BackendOp(op_id, slot_id, kind, location_id, token, value)` | kind ∈ OPERATION_KINDS（契约 03 四种）；op_id/slot_id/location_id 非空；**文本类 op 必须携带 token**，仅 replace_image 可省略 |
| `CapabilityRecord(capability_id, backend, available, verified, verified_by, verified_at, risk_level, reason)` | **available=True ⇒ verified=True ∧ verified_by≠∅**（要求 7）；verified=True ⇒ verified_by≠∅；capability_id 匹配 `^[a-z0-9]+(\.[a-z0-9_]+)+$`（对照表命名空间）；risk_level ∈ {low,medium,high} |
| `CapabilityReport(backend, records)` | records 元组化（防御调用方 list 突变）；lookup 未声明 → KeyError |
| `DocumentBackend` ABC | 5 抽象动词：name/capabilities/batch/readback/normalize/validate；batch 文档字符串明示"永不写 template_path" |
| `BackendResult(backend, ok, reason_code, detail, per_op)` | ok∧reason 互斥（双向校验）；per_op 拷贝入不可变 dict |
| `OpOutcome(status, reason_code, before/after_sha256)` | status ∈ {SUCCESS,FAILED,SKIPPED}；FAILED 必带 reason；SKIPPED 区分"未执行"与"失败" |
| `BackendError(reason_code, detail)` | B2/B3 的类型化 raise 通道；经 envelope_code_for 翻译，无吞没 |

#### 交付物 3：reason_code 清单（15 个，四类）

| ReasonCode | 类别 | is_failure | envelope_code |
|---|---|---|---|
| OFFICECLI_BINARY_MISSING | INFRASTRUCTURE | false | —（组回退 python，披露） |
| OFFICECLI_VERSION_UNSUPPORTED | INFRASTRUCTURE | false | —（同上） |
| BACKEND_VALIDATE_UNAVAILABLE | INFRASTRUCTURE | false | —（检查记 UNVERIFIED，E6） |
| TOKEN_SPANS_RUNS | DOCUMENT | false | —（P4 证据：CLI 合并 runs） |
| TOKEN_NOT_UNIQUE | DOCUMENT | false | — |
| LOCATION_UNSUPPORTED | DOCUMENT | false | — |
| CELL_MULTIPLE_PARAGRAPHS | DOCUMENT | false | — |
| OPERATION_TYPE_UNSUPPORTED | DOCUMENT | false | — |
| CAPABILITY_NOT_ROUTABLE | BACKEND | false | —（registry 无 verified 条目） |
| BATCH_ROLLED_BACK | BACKEND | true | OFFICECLI_WRITE_FAILED |
| READBACK_MISMATCH | BACKEND | true | OFFICECLI_READBACK_FAILED |
| NORMALIZE_FAILED | BACKEND | true | OFFICECLI_NORMALIZE_FAILED |
| STAGE_CHECK_FAILED | BACKEND | true | STAGE_CHECK_FAILED（E8） |
| BACKEND_VALIDATE_FAILED | BACKEND | true | BACKEND_VALIDATE_FAILED |
| BACKEND_SINGLE_WRITER_VIOLATION | BACKEND | true | BACKEND_SINGLE_WRITER_VIOLATION（E4） |

**BUSINESS 类刻意为空**：业务拒绝（授权/容量/保护）由执行器既有码承担（INVALID_FILL_PLAN 等），后端层不重定义——测试 `test_backend_reason_categories_are_used` 显式断言此边界。

reason→envelope 映射定稿（B1 卡"不双轨"要求）：细粒度 cause 进 `data.routing`（E7），粗粒度 envelope_code 维持 B0 已发布的对外输出面（E2 兼容）。

#### 交付物 4：error-codes 注册表增量（34 → 53，只增不改）

19 个新条目，全部 `introduced_in: "4.2.0"`、owner AGENT03（后端适配层属 Document Engine 域）、severity/rollback 语义与 is_failure 一致（失败类 rollback_required=true；回退类 false；唯一 blocking 码 BACKEND_SINGLE_WRITER_VIOLATION 且 retryable=false，符合契约测试"blocking 不得自动重试"）：

- **B0 缺口闭合（4）**：`EXECUTION_FAILED`（B0 执行器已写入 envelope errors[] 但未注册——契约 05 §9 违规态）、`OFFICECLI_WRITE_FAILED`、`OFFICECLI_READBACK_FAILED`、`OFFICECLI_NORMALIZE_FAILED`（B0 abort_reason 字符串，未注册）。
- **15 个 reason code**（上表）。
- 既有 34 码零改动；registry 通过 error_code_registry-4.0.schema.json 校验（契约测试全绿）。

**范围外观察（记录不处理）**：QA 环境域的 RENDER_PDF_NOT_PRODUCED / OCR_UNAVAILABLE / RENDER_BACKEND_UNAVAILABLE / CJK_FONT_UNAVAILABLE 等 data 层码同样未注册，属 AGENT04/QA 域缺口，不在 B1（后端适配骨架）范围，建议后续单独登记。

#### 交付物 5：单元测试报告

`tests/w5/`（新目录，tests/contracts 同款包结构）三个文件 **61 项测试**：

| 文件 | 覆盖 |
|---|---|
| test_b1_result.py | catalog 完备性/无孤行/注册交叉校验/四类语义/failure↔envelope 映射/BackendResult 全不变量/OpOutcome SHA 校验/BackendError |
| test_b1_base.py | Target fmt+模板≠暂存/Op kind+token 规则/**CapabilityRecord 未验证不可用**/Report lookup/ABC 不可实例化+最小实现冒烟 |
| test_b1_registry.py | B0 缺口闭合断言（4 码必在）/B1 增量集合恰等于缺口∪词汇/8 必填字段/唯一性/blocking 不重试/失败类必回滚/回退类不回滚 |

实测：`py -3.15 -m unittest discover -s tests/w5 -t . -p "test_*.py"` → **Ran 61 tests in 0.004s — OK**（首轮 2 失测试缺陷已修：BUSINESS 断言语义改为显式排除 + backend=" " 空串用例改 ""）；ruff check（E4/E7/E9/F/B，line-length 120）→ **All checks passed!**。

#### 交付物 6：与现有项目兼容性检查

| 检查 | 证据 |
|---|---|
| 全量回归 | `py -3.15 -m unittest discover -s tests -p "test_*.py"` → **Ran 605 tests in 216.162s — OK**（基线 544 + 新增 61，**零失败零跳过**） |
| 契约回归 | `py -3.15 -m unittest discover -s tests/contracts -t tests -p "test_*.py"` → **Ran 72 tests — OK**（含 registry schema/唯一性/grandfathered/blocking-not-retryable） |
| E1 契约保护 | contracts/01–06、schemas/、DocumentSpec/SlotID/FillPlan/Gate/FillLedger/QAReport/Transaction **零修改**（git status 佐证） |
| E2 兼容 | 无任何既有文件行为变更；error-codes.json 只增；B0 envelope 输出面（EXECUTION_FAILED/OFFICECLI_*）拼写不变、语义获得注册表背书 |
| 引入隔离 | document_backends/ 为惰性新包（无任何既有模块 import 它）；engine/__init__.py 未触碰（单写入者制度遵守） |

#### 交付物 7：变更文件清单

| 文件 | 状态 | 内容 |
|---|---|---|
| document_backends/__init__.py | 新增 | 公共导出面 |
| document_backends/base.py | 新增 | 抽象接口 + Target/Op/Capability 模型（~250 行） |
| document_backends/result.py | 新增 | 结果模型 + reason 词汇（~290 行） |
| config/error-codes.json | 修改 | +19 条目（只增） |
| tests/w5/__init__.py | 新增 | 包标识 |
| tests/w5/test_b1_result.py | 新增 | 28 测试 |
| tests/w5/test_b1_base.py | 新增 | 25 测试 |
| tests/w5/test_b1_registry.py | 新增 | 8 测试 |
| CHANGELOG.md | 修改 | Unreleased 节补 B1 条目 + Tests 行 544→605 |

reports/w5/（本文档）与 dist/ 按人工要求**不入提交**。

#### 交付物 8：回滚方案

代码回滚 = 删除 document_backends/ 与 tests/w5/ + 回退 config/error-codes.json 尾部 19 条目（单文件 diff，无既有条目改动）。回滚后恢复 34 码/544 测试基线，无残留依赖（惰性包，无既有调用方）。**不回滚**的情形：若仅注册表语义需调整，单文件增量修正即可，骨架互不影响。

**B1 出口条件逐项核对**：✅ 模块设计说明 / ✅ 接口+类型约束 / ✅ reason_code 清单 / ✅ 注册表 / ✅ 单元测试报告 / ✅ 兼容性检查 / ✅ 变更清单 / ✅ 回滚方案。

**B1 提交记录**：commit **`d4d3c19`**（9 files changed, 1340 insertions(+), 1 deletion(-)；范围 = document_backends/×3 + tests/w5/×4 + config/error-codes.json + CHANGELOG.md；`dist/`、`reports/w5/` 未混入）。提交后复验：契约 72 通过（1.258s）+ tests/w5 61 通过——均在 HEAD=`d4d3c19` 树状态实测。**B1 完成，暂停等待人工审查（G1.5）；未获批准不进入 B2/B3。**

---

### B1-R 审查修正记录（G1.5 结论 R1–R5，2026-11-06，commit `be95e82`）

G1.5 人工审查：架构方向通过，R1–R4 定向修正后放行 B2/B3。**调用方先行分析**：`document_backends` 仅被自身与 tests/w5 引用（无引擎/执行器 import），全部变更受控。执行边界遵守：冻结契约零修改、无既有错误码删除、无 Router、无 KEEP_PY 迁移、B0/B1 提交历史未动、独立提交、每项修正配测试、无既有测试删除或弱化（registry "恰好集合"断言随设计演进扩展，强度不降）。

#### 1. 修正前后设计对照

| 项 | 修正前（d4d3c19） | 修正后（be95e82） |
|---|---|---|
| R1 envelope 映射 | BATCH_ROLLED_BACK→OFFICECLI_WRITE_FAILED 等三个 OfficeCLI 专属码硬编码进通用 catalog | 三码改映射**通用** BACKEND_BATCH/READBACK/NORMALIZE_FAILED；`OFFICECLI_ENVELOPE_ALIASES` 提供 officecli 路径的 B0 拼写解析（E2）；`envelope_code_for(reason, backend=None)` 按后端归属解析 |
| R2 验证语义 | `validate() -> BackendResult`；BACKEND_VALIDATE_UNAVAILABLE 是 is_failure=False 的 reason——但成功结果禁带 reason，语义冲突 | 独立 `ValidationResult` 四态模型（PASSED/FAILED/UNAVAILABLE/UNVERIFIED）；`validate() -> ValidationResult`；BackendResult 职责不变（R2.5） |
| R3 per_op 可变性 | frozen dataclass 内普通 dict（浅不可变，内容可被外部改写） | `MappingProxyType` 深只读 + `to_dict()` 序列化通道（OpOutcome/BackendResult/ValidationResult 三者） |
| R4 能力证据 | 仅 verified_by 非空 tuple + verified⇒verified_by | 证据项非空字符串、去重、verified_at ISO-8601 含时区、报告 backend 一致性、capability_id 唯一 |

#### 2. 错误码映射表（修正后全量，通用层无 OfficeCLI 依赖）

| ReasonCode | 类别 | 默认 envelope（通用） | backend="officecli" 时（E2 别名） | backend="python-docx" 时 |
|---|---|---|---|---|
| BATCH_ROLLED_BACK | BACKEND/失败 | BACKEND_BATCH_FAILED | OFFICECLI_WRITE_FAILED | BACKEND_BATCH_FAILED |
| READBACK_MISMATCH | BACKEND/失败 | BACKEND_READBACK_FAILED | OFFICECLI_READBACK_FAILED | BACKEND_READBACK_FAILED |
| NORMALIZE_FAILED | BACKEND/失败 | BACKEND_NORMALIZE_FAILED | OFFICECLI_NORMALIZE_FAILED | BACKEND_NORMALIZE_FAILED |
| STAGE_CHECK_FAILED | BACKEND/失败 | STAGE_CHECK_FAILED | 同左（无别名） | 同左 |
| BACKEND_VALIDATE_FAILED | BACKEND/失败 | BACKEND_VALIDATE_FAILED | 同左 | 同左 |
| BACKEND_SINGLE_WRITER_VIOLATION | BACKEND/失败 | BACKEND_SINGLE_WRITER_VIOLATION | 同左 | 同左 |
| 9 个回退类 reason（INFRASTRUCTURE/DOCUMENT + CAPABILITY_NOT_ROUTABLE） | — | None（仅入 E7 routing 记录） | — | — |

注册表增量：B1 的 19 条 + R1 的 3 条 = **22 条 4.2.0 条目**（34→56 码，只增不改）；OFFICECLI_* 三码保留注册（B0 执行器现役输出面）。ToolEnvelope 契约未动：B0 执行器继续直接发 OFFICECLI_* 码；别名解析仅在 B2/B5 的 officecli 路由接线时使用。

#### 3. ValidationResult 状态定义

| 状态 | 语义 | reason_code | detail | 防护的违规 |
|---|---|---|---|---|
| PASSED | 验证**已执行**且无 schema 错误 | 禁止携带 | 可空 | — |
| FAILED | 验证已执行且发现问题 | 必为 BACKEND_VALIDATE_FAILED | 必非空（明确失败原因，R2.3） | — |
| UNAVAILABLE | 该后端**没有**验证器 | 必为 BACKEND_VALIDATE_UNAVAILABLE | 必非空（追溯，R2.4） | 无验证器伪装通过（R2.2） |
| UNVERIFIED | 有验证器但**未执行**（工具缺失） | 必为非失败类 reason（如 OFFICECLI_BINARY_MISSING）；失败类 reason 归 FAILED | 必非空（追溯，R2.4） | 未执行报告为 PASSED（R2.1） |

构造期全不变量强制；`test_not_executed_states_never_collapse_into_passed` 钉死两非通过态与 PASSED 的区分。

#### 4. 新增测试清单（24 项，tests/w5 61→85）

| 类别 | 测试（文件） |
|---|---|
| R1 归属（6） | test_failure_reasons_map_to_generic_backend_codes / test_officecli_backend_resolves_backward_compatible_spellings / **test_python_backend_never_reports_officecli_codes**（R1.5）/ **test_same_failure_is_attributed_per_backend**（R1.6 同型失败双后端归属）/ test_generic_codes_and_aliases_are_registered / test_alias_table_covers_all_generic_failure_codes（test_b1_result.py） |
| R2 状态转换（10） | 四态恰好性 / PASSED 工厂 / PASSED 禁 reason / FAILED 必 VALIDATE 码+detail / UNAVAILABLE 追溯 / UNVERIFIED 追溯 / **UNVERIFIED 拒绝失败类 reason** / 非执行态永不塌缩为 PASSED / 冻结性 / 序列化（test_b1_result.py ValidationResultTests） |
| R3 深不可变（3） | test_per_op_is_read_only（setitem/delitem TypeError + 变异方法不存在）/ test_result_serializes_through_to_dict（json.dumps 经 to_dict）/ test_op_outcome_to_dict_keeps_null_reason（test_b1_result.py） |
| R4 证据（5） | 证据项非空字符串 / 证据去重 / verified_at ISO-8601+时区（含 Z 与三种非法形）/ 报告拒绝外来 backend 记录 / 报告拒绝重复 capability_id（test_b1_base.py CapabilityEvidenceTests） |

registry 测试同步演进（非弱化）：`test_b1_additions_are_all_present` 期望集 = 缺口 4 ∪ 15 reason ∪ 3 通用码（仍为恰好集合断言）；`test_failure_reason_additions_require_rollback` 补 3 个 BACKEND_* 码。

#### 5–6. 回归结果（实测，HEAD=`be95e82` 树）

| 套件 | 命令 | 结果 |
|---|---|---|
| 全量 | `py -3.15 -m unittest discover -s tests -p "test_*.py"` | **Ran 629 tests in 351.326s — OK**（0 失败 0 错误 0 跳过；605→629） |
| 契约 | `py -3.15 -m unittest discover -s tests/contracts -t tests -p "test_*.py"` | **Ran 72 tests — OK** |
| tests/w5 | `py -3.15 -m unittest discover -s tests/w5 -t . -p "test_*.py"` | **Ran 85 tests — OK**（提交前 0.006s / 提交后复验均绿） |
| ruff | `py -3.15 -m ruff check document_backends tests/w5` | **All checks passed!** |

首轮 3 处测试侧缺陷已修（FakeBackend capabilities 的 backend 与报告不一致——恰被 R4 新校验捕获，属修正生效的自证；mappingproxy 无 clear/update 方法断言方式调整；assertIsFalse 拼写）。

#### 7. 提交文件清单

**commit `be95e82`**：8 files changed, 471 insertions(+), 33 deletions(-) —— document_backends/{__init__,base,result}.py、config/error-codes.json、tests/w5/{test_b1_base,test_b1_registry,test_b1_result}.py、CHANGELOG.md。`dist/`、`reports/w5/` 未混入。

#### 8. 回滚方案

单提交回退 `git revert be95e82` 即恢复 d4d3c19 状态（56→53 码、85→61 测试）；无跨提交依赖（B0 执行器不 import document_backends）。仅注册表微调亦可单文件增量修正。

#### R5：后续实施约束登记（B2–B5 生效，不扩展现 B1 接口）

1. **BackendTarget 路径安全归属**：template_path ≠ staged_path 仅是构造期快速防线；**实际路径安全由 Transaction/路径校验层保证**——暂存区唯一可写、模板只读、ZIP 配额与路径穿越防护由 DocumentTransaction + package_guard 承担。B2/B3 后端不得在 Backend 内部自建路径安全逻辑，也不得绕过暂存区直接写其他路径。
2. **单一写入者归属统一事务**：E4 的锁定与生命周期由**统一 DocumentTransaction** 管理——后端只写 target.staged_path，不得各自维护独立事务、独立文件锁或第二个写入通道；B5 路由器必须经 Transaction 获取"当前写入者"身份，officecli resident 的 close 纪律在执行器层统一调度。

**B1-R 完成。暂停等待 G1.5 最终人工批准；未获批准不启动 B2/B3。**

---

### B1-R2 边界强化记录（G1.5 最终审查补充修正，2026-11-07，commit `37ec46f`）

范围严格限定 R2/R3/R4 边界；R1 通用映射、`OFFICECLI_ENVELOPE_ALIASES`、ToolEnvelope、契约集 4.0.0 与 W0 冻结资产零改动（diff 佐证）；未实现 B2/B3、未创建 Router；未 amend 既有提交。

#### 1. 修改文件清单（6 文件，+256/−23）

| 文件 | 变更 |
|---|---|
| document_backends/result.py | +57/−（R2 类型与原因码白名单、R3 per_op 值类型） |
| document_backends/base.py | +49/−（R4 真实 ISO-8601 解析、空白证据拒绝） |
| document_backends/__init__.py | +2（导出 `VALIDATION_UNVERIFIED_REASONS`） |
| tests/w5/test_b1_result.py | +125（R2 6 类 + R3 4 类边界测试） |
| tests/w5/test_b1_base.py | +42（R4 6 类边界测试） |
| CHANGELOG.md | +4/−（条目与测试计数同步 648/104） |

#### 2. 修改内容说明

**R2（ValidationResult 类型与状态约束）**
1. `status` 必须为 `ValidationStatus` 成员——因 `ValidationStatus` 是 str-Enum，`"PASSED" == ValidationStatus.PASSED` 为真，故用 `isinstance` 而非相等判断，字符串无法绕过四态分支；
2. `reason_code` 必须为 `ReasonCode` 成员或 None（字符串/任意对象拒绝）；
3. 新增 `VALIDATION_UNVERIFIED_REASONS = {OFFICECLI_BINARY_MISSING, OFFICECLI_VERSION_UNSUPPORTED}` 白名单——UNVERIFIED 只接受“验证工具不可用”语义；`TOKEN_SPANS_RUNS`（文档结构回退）、`CAPABILITY_NOT_ROUTABLE`（路由决策）、`BACKEND_VALIDATE_UNAVAILABLE`（属 UNAVAILABLE 状态）、失败类 reason 全部拒绝；
4. UNAVAILABLE 与 UNVERIFIED 语义互斥（交叉传入即 ValueError）；
5. PASSED 禁带 reason_code（保留）；`to_dict()` 行为不变（四态均可 json 序列化）。

**R3（BackendResult.per_op 类型约束）**
1. `per_op` 必须为 Mapping（非 Mapping 显式 ValueError）；
2. 每个值必须是 `OpOutcome`（dict/str/None/int/list 全部拒绝）；
3. copy-on-construction 保留（构造后修改源映射/清空不影响结果）；
4. `MappingProxyType` 只读保留（setitem/delitem TypeError，无 clear/update）；
5. `OpOutcome` 冻结性由测试证明（属性赋值 FrozenInstanceError）；
6. `to_dict()` 保留，三种 status 的 per_op 均可 `json.dumps`。

**R4（Capability 时间戳与证据）**
1. `verified_at` 改用 `datetime.fromisoformat` 真实解析（去掉形状正则），`Z` 归一化为 `+00:00` 以兼容 3.10；
2. 必须携带明确时区（`tzinfo.utcoffset()` 非空），无时区/仅日期一律拒绝；
3. 非法日期（13 月、2 月 30 日、0 月）、非法时间（24:00:01、23:60、秒 61）、越界偏移（+99:00、−25:00）全部拒绝；
4. 合法 UTC `Z`、`+08:00`、`-05:00`、含微秒形式均接受；
5. `verified_by` 每项必须非空且非纯空白（空格/制表/换行）；
6. 唯一性检查与 CapabilityReport 的 backend 一致性、capability_id 去重检查保持不变。

**边界诚实性说明**：真实 ISO-8601 解析器接受 `24:00:00`（标准允许的当日终点表示），因此“非法时间”用例使用 `24:00:01`，并在测试中显式接受 `24:00:00`——以标准语义为准，而非为凑断言引入非标准限制。

#### 3. 新增测试说明（19 项：tests/w5 85 → 104）

| 类别 | 测试 |
|---|---|
| R2（6） | 字符串 `"PASSED"` 拒绝 / 任意非法状态对象（None、1、object()、list、dict）拒绝 / 字符串 reason_code 拒绝 / 任意 reason 对象拒绝 / UNVERIFIED 白名单恰好性与正例 / UNVERIFIED 拒绝 7 类不符合语义原因 / UNAVAILABLE↔UNVERIFIED 互斥 / 四态 to_dict 序列化 |
| R3（4） | 非 OpOutcome 值 5 类拒绝 / 非 Mapping 3 类拒绝 / 源映射构造后增改删不影响结果 / per_op 值不可变（FrozenInstanceError）+ 三状态 json 序列化 |
| R4（6） | 非法日期 3 例 / 非法时间 3 例（另显式接受 24:00:00）/ 越界偏移 2 例 / 无时区 3 例 / 合法 UTC+偏移 4 例 / 空白证据 4 例 |
| 保留 | 原有 85 项全部继续通过，无删除、无弱化 |

#### 4–6. 测试与静态检查结果（实测，HEAD=`37ec46f` 树）

| 项 | 命令 | 结果 |
|---|---|---|
| tests/w5 | `py -3.15 -m unittest discover -s tests/w5 -t . -p "test_*.py"` | **Ran 104 tests — OK**（提交前/提交后复验均绿） |
| 全量 | `py -3.15 -m unittest discover -s tests -p "test_*.py"` | **Ran 648 tests in 339.725s — OK**（0 失败 0 错误 0 跳过；629→648） |
| 契约 | `py -3.15 -m unittest discover -s tests/contracts -t tests -p "test_*.py"` | **Ran 72 tests — OK** |
| ruff | `py -3.15 -m ruff check document_backends tests/w5` | **All checks passed!** |

#### 7. git diff --stat（提交内容）

```text
 CHANGELOG.md                  |   4 +-
 document_backends/__init__.py |   2 +
 document_backends/base.py     |  49 +++++++++++++----
 document_backends/result.py   |  57 +++++++++++++++----
 tests/w5/test_b1_base.py      |  42 ++++++++++++++
 tests/w5/test_b1_result.py    | 125 ++++++++++++++++++++++++++++++++++++++++++
 6 files changed, 256 insertions(+), 23 deletions(-)
```

#### 8. git status（提交后）

```text
?? dist/            ← 未跟踪，未入提交
?? reports/w5/      ← 未跟踪，未入提交
```

冻结资产边界检查：`git diff --stat 37ec46f -- contracts schemas` 为空；`git diff be95e82 -- contracts schemas engine document_engine template_intelligence content_intelligence template_gate qa scripts` 为空。`config/error-codes.json` 本轮零修改（无新码需求）。

**提交记录**：commit **`37ec46f`**（`fix(backends): harden validation and immutable capability results`，6 files, +256/−23；未 amend `be95e82`）。回滚：`git revert 37ec46f` 单提交恢复 be95e82 态（104→85 测试），无跨提交依赖。

**B1-R2 完成。暂停等待 G1.5 最终人工批准；未获批准不启动 B2/B3。**

---

## 1. 任务序列总览

```text
B0 基线整理
 └─ B1 result.py + base.py 骨架
     ├─ B2 officecli_backend（迁移+扩展+探针+白名单）
     │    └─ B4 capability_registry + environment 探测（依赖 B2 探针）
     ├─ B3 python_backend（可与 B2 并行）
     │    └─ B5 operation_router + fill_executor 接入（依赖 B2/B3/B4）
     │         └─ B6 主链集成验证 + W5-D 写入路径审查（依赖 B5）
     │              └─ B7 W5-E 对照测试 T01–T10（依赖 B5/B6）
     │                   └─ B8 W5-F 接口收敛 + 文档定稿（依赖 B4/B7）
```

每个 B 任务 = 独立提交 + 独立测试证据 + 下一任务前可回滚（删除新增文件/回退单文件 diff，不影响既有基线）。

---

## 2. 任务卡

### B1 `document_backends/` 骨架：`base.py` + `result.py`

| 项 | 内容 |
|---|---|
| 目标 | 落地 §3.1/§3.2 设计：`BackendTarget`/`BackendOp`/`DocumentBackend` 抽象、`BackendResult`、reason_code 枚举 |
| 文件 | 新增 `document_backends/__init__.py`、`base.py`、`result.py`；`config/error-codes.json` 增量注册 reason_code（只增） |
| 关键决策 | reason_code 与现有 `OFFICECLI_*_FAILED` envelope 错误码的关系在此时定稿（映射表，不双轨）；ToolEnvelope 若对 `writer_fallback` 封闭 → 提 CP |
| 测试 | 单元：reason_code 枚举完备性、BackendResult 冻结性、抽象类不可实例化；契约：error-codes schema 校验通过 |
| 出口条件 | 接口评审通过（对照 target-architecture §3.1 逐方法）；错误码 registry 流程完成 |
| 回滚 | 删除 document_backends/ 新文件 + 回退 error-codes.json 单文件 diff |

### B2 `officecli_backend.py`（迁移 officecli_writer + 扩展）

| 项 | 内容 |
|---|---|
| 目标 | target-architecture §3.3 全表 |
| 文件 | 新增 `document_backends/officecli_backend.py`；`engine/officecli_writer.py` 改为 re-export（**import 路径与全部公开符号不变**，E2） |
| 迁移（行为不变） | binary 发现/版本/batch/读回/close/validate/w14 规范化（officecli_writer L57-342）；`tests/test_officecli_writer.py` 断言全数保留 |
| 扩展① 位置映射 | header/footer/first_page 系 → `/header[N]`/`/footer[N]`（P5 scope 证据）；未支持 story 显式 `LOCATION_UNSUPPORTED` |
| 扩展② 批量读回 | open→N×get→close 窗口，替代逐 op 起停（audit 6.7）；close 纪律不放松 |
| 扩展③ 探针 | 版本探针 + 能力探针（run-scoped set / paragraph 单 run set / cell scope / header scope / validate 各一实测项，带时间戳，版本绑定缓存） |
| 扩展④ 白名单 | 允许动词 = {set, batch, get, validate, close}；add/remove/move/swap/raw*/add-part/merge/import 在构造层即拒绝 |
| 安全要求 | subprocess 列表参数（无 shell 拼接）、`--json`、非零退出码=错、超时、stderr 保留进 detail、无静默吞错（现 writer 已满足，测试固化） |
| 测试 | 迁移测试全绿 + 新增：header/footer 映射、批量读回窗口、白名单拒绝（每个禁用动词一例）、探针（含 fake binary → `OFFICECLI_BINARY_MISSING`） |
| 出口条件 | 旧 import 路径回归通过；探针在本机实测输出进 registry 格式；禁用动词有测试证明 |
| 回滚 | 回退 re-export 改动即恢复原状 |

### B3 `python_backend.py`（薄适配）

| 项 | 内容 |
|---|---|
| 目标 | target-architecture §3.4：按 kind 分派到现有实现；**零行为差** |
| 文件 | 新增 `document_backends/python_backend.py` |
| 不变式 | 不重写 ooxml_utils/table_engine/style_engine/image_engine；`normalize()` no-op；`validate()` 返回 UNAVAILABLE |
| 测试 | **逐字节等价**：≥3 组 fixture（单文本/单元格/图片混合 FillPlan）双跑——python_backend.batch vs 现有执行器 python 路径——产物 SHA256 相等 |
| 出口条件 | 等价性证据成立 |
| 回滚 | 删除新文件 |

### B4 `capability_registry.py` + 环境探测 + `capabilities` 查询

| 项 | 内容 |
|---|---|
| 目标 | target-architecture §3.5：实测驱动注册表 + `qa/environment.py` 新增 `officecli_runtime`（required=false）+ `capabilities` 输出入口 |
| 文件 | 新增 `document_backends/capability_registry.py`；`qa/environment.py` 增量（单探测项）；registry JSON 落 `config/` 还是运行时生成——B4 时定稿（倾向运行时+缓存，避免仓库硬编码 available 状态） |
| 规则 | verified 只能由 probe/现有测试/T 对照置位且 `verified_by` 可追溯；CLI 版本变化缓存失效；对照表文档与 registry 冲突时以实测为准并回写 |
| 降级策略 | officecli 缺失 → 能力组显式回退 python + envelope/QA 披露，不阻断任务、不伪装（E6） |
| 测试 | 探测可用/不可用双路径（环境能力既有测试模式）；伪造 registry 条目被拒；版本失效重探 |
| 出口条件 | `capabilities --json` 输出与本机实测一致；qa 环境报告含 officecli_runtime 项 |
| 回滚 | 删除新文件 + 回退 environment.py 单文件 diff |

### B5 `operation_router.py` + fill_executor 接入（W5-C 核心）

| 项 | 内容 |
|---|---|
| 目标 | target-architecture §3.6/§3.7/§4：能力组路由、组级回退、串行阶段、Ledger backend 记录；**RoutingDecision 结构化产物（E7）** |
| 文件 | 新增 `document_backends/operation_router.py`；`document_engine/fill_executor.py` 第 4b 步（L1523-1560）改为调用 router；`FillLedger` 调用点传 backend 进 result |
| 前置核对 | **`contracts/03-content-fill-plan.md` §3.8 result 措辞**：开放 → 零契约变更实施；封闭 → 提 CP 停下等批（E1） |
| 路由行为 | 文本组（officecli，组内任一 op 不可表达→整组 python）；单元格组/图片组（python）；stages 串行、组内单后端、全程单 tx（E4） |
| E7 落实 | RoutingDecision 每能力组记录 `{capability_id, operation_types, chosen_backend, reason_code, registry 探测快照, fallback_allowed, final_outcome}`；envelope 新增 `data.routing`；降级必带 reason_code（禁止静默降级/静默后端切换） |
| E8 落实 | 每阶段出口 = `close + normalize + stage_check`；stage_check 结果写 final_outcome；前一阶段未通过 → 不进入下一阶段（事务中止路径） |
| 兼容 | `--writer` 参数保留；默认 python-docx 不变；`writer=officecli` 时若 router 判定全部组走 python → envelope 如实记录（`writer_backend=python-docx` + reason），不算失败 |
| 测试 | ① 单后端单组：现网行为等价；② 混合 FillPlan 双阶段执行，Ledger 逐 op backend 正确；③ 无 gate 构造任务被 `TEMPLATE_GATE_REQUIRED` 拒（gate 不被 router 绕过）；④ 事务二次门禁不变；⑤ E7：任意 FillPlan 断言 routing 六字段齐备 + 降级 reason_code 非空且与探测一致；⑥ E8：阶段 1 注入损坏 → 断言阶段 2 未执行、事务中止；⑦ 全量回归 |
| 出口条件 | 路由决策可解释（E7 六字段）；阶段间检查生效（E8）；Ledger op 级 backend 可见；全量（544+）无回归 |
| 回滚 | 回退 fill_executor 单文件 diff + 删除 router；registry/后端保留（未接线无害） |

### B6 主链集成验证 + W5-D 写入路径审查

| 项 | 内容 |
|---|---|
| 目标 | 全链 gate→router→backend→Ledger→QA→tx 回归；Legacy 边界确认；**E8 阶段间状态可验证的集成证据** |
| 范围 | ① v4 主链端到端（analyze→gate→plan→execute→QA→commit）；② Legacy `--data` 行为冻结对比（B5 前后产物等价）；③ repair/review/reformat/excel 四路径回归（应零变化——证明 W5 未误伤）；④ envelope 输出字段兼容对比 |
| E8 落实 | 端到端断言多阶段任务每个 stage_check 有独立记录且顺序执行；构造前一阶段检查失败场景断言后续阶段未启动 |
| W5-D 结论 | 写入路径审查记录：安全链已在 W4-7 收敛、mutation 实现层现状、统一入口归属（主链 router / Legacy 冻结 / 四路径 python 单后端） |
| 测试 | tests/w5/ 集成用例 + 上述四组对比证据 |
| 出口条件 | 四组对比全部等价/符合预期；E8 阶段检查记录在端到端运行中可验证；审查记录入报告 |
| 回滚 | 无代码回滚需求（验证型任务）；发现缺陷回对应 B 任务 |

### B7 W5-E 真实文档对照测试 T01–T10（质量验收）

| 项 | 内容 |
|---|---|
| 目标 | 任务书 §六：**不以"文件能打开"为验收标准**，双后端产物逐维度对照 |
| 基础设施 | `tests/real_corpus_eval.py --writer` 框架（已有）+ `tests/fixtures/generate_fixtures.py`（29.8KB 现成 fixture 工厂，扩展 T 系列所需形态） |
| 场景 | T01 段落读取 / T02 段落修改（样式保留）/ T03 跨 Run / T04 表格单元格（含合并）/ T05 图片（关系完整性）/ T06 页眉页脚 / T07 复杂模板（Slot 授权范围）/ T08 已有文档修正（原文保护）/ T09 xlsx（值/公式/样式）/ T10 失败回滚 |
| 对照维度 | 原始件 → 双后端产物：XML 结构 diff、样式差异（结构指纹 + 版式指纹）、图片/关系完整性、文本完整性（逐字）、QAReport 结论、（officecli 组）结构指纹**必须不变**（W3-9 已证授权填充不变指纹——沿用该守门员） |
| 判定规则 | 达基线 → registry 置 verified、对照表更新；未达基线 → **保留 python**，证据记录进对照表，不放宽（E3） |
| E9 落实 | **T10 扩展为真实失败注入矩阵**（E9 的验收载体）：binary 缺失 / batch 失败 / 读回不符 / normalize 失败 / stage_check 失败——每项断言：交付输出不存在或与执行前逐字节一致、暂存件已清理、原始模板 SHA 不变、Ledger/事务记录显式 FAILED 错误码；**部分成功不得出现在交付文件** |
| 交付 | `tests/w5/` 套件 + `reports/w5/w5-test-report.md`（逐场景结论矩阵） |
| 出口条件 | 十场景全有双后端结论；**E9 失败注入矩阵全绿**（失败场景安全恢复证明）；QA 能检查最终交付件 |
| 回滚 | 对照结论只影响 registry/文档，无代码回滚 |

### B8 W5-F Agent 接口收敛 + W5 文档定稿

| 项 | 内容 |
|---|---|
| 目标 | target-architecture §9：统一入口 + SKILL.md 精简 + 报告集齐 |
| 文件 | 新增 `scripts/office_template.py`（动词：capabilities/inspect/analyze/confirm/execute/verify/status）；SKILL.md 重写（只留七要素）；references/ 增量外迁细节；`w5-final-acceptance.md` |
| 兼容 | 旧 12 脚本全部保留（E2）；`analyze` 合并 template_gate analyze+report 但旧子命令不删 |
| 测试 | 统一入口各动词冒烟（含 gate 拒绝路径）；工作流文档演练（用户→inspect→analyze→confirm→execute→verify→交付） |
| 出口条件 | Agent 无需手动编排底层模块（工作流验证）；专项规则按需加载验证；确认机制经统一入口正常 |
| 回滚 | 删除 office_template.py + SKILL.md 回退 |

---

## 3. 阶段门禁与暂停点

| 门禁 | 通过条件 | 判定人 | 状态 |
|---|---|---|---|
| G0（本计划确认） | 人工确认本计划 + target-architecture（D1/D2 接受；E7/E8/E9 新增冻结；B0 有条件批准） | **人工** | **✅ 已通过（2026-11-06）** |
| G1（B0 后） | 人工检查 B0 提交结果（`d342fe5`） | **人工** | **✅ 已通过（2026-11-06；批准提交，store.py 修复保留独立问题追溯记录、不计入 Backend 功能成果）** |
| G1.5（B1 后） | 人工审查 B1 骨架（接口/reason 词汇/注册表/测试证据，见"B1 执行记录"八项交付物） | **人工（当前暂停点）** | ⏸ 等待人工审查，**未通过不得开始 B2/B3** |
| G2（B5 后） | 全量回归 + Ledger backend 可见 + gate 不可绕过证据 + E7 routing 六字段 + E8 阶段检查生效 | 主智能体（可选独立审查） | 待启动 |
| G3（B7 后） | T01–T10 全结论 + E3 判定落档 + **E9 失败注入矩阵全绿** | 独立审查（Agent 07 角色） | 待启动 |
| G4（B8 后） | 文档与代码一致性 + w5-final-acceptance | 独立审查 | 待启动 |

任一门禁不过 → 停在该阶段，缺陷回对应任务卡；**禁止带未闭合缺陷进入下一任务**。

## 4. 风险登记册（实施期滚动维护）

| 风险 | 触发条件 | 缓解 | 回退 |
|---|---|---|---|
| 契约 03 result 措辞封闭 | B5 前核对 | CP 提案流程，未批不动 | Ledger backend 改记 envelope 级（现状），能力降级但不破坏 E1 |
| OfficeCLI 版本行为漂移（P3 已发生一例） | 探针版本比对失败 | 缓存失效重探；verified 降级 | 能力组回 python |
| header/footer 写入 w14 恢复缺口 | T06 对照指纹异常 | B2 扩展时 w14 恢复已覆盖全 part（现 writer L294 即如此）；T06 实证 | 该能力回 python，registry 降级 |
| 组级回退后双阶段行为复合缺陷 | B5 混合 FillPlan 测试 | 阶段边界 close+normalize 强制；逐阶段 QA | 文档级回退模式还原（L1530 形态） |
| 双写入者事故 | 阶段间未 close | Router 串行 + close 纪律测试 + 文件锁守卫 | 不适用（设计上禁止，测试断言） |
| 环境无 officecli 的机器跑 W5 测试 | CI/他人环境 | B2/B4 测试设 skip-if-unavailable 并**显式标记 skip 计数**（不假装通过） | — |

## 5. 回归要求（每 B 任务必跑）

```powershell
py -3.15 -m unittest discover -s tests -p "test_*.py"        # 全量（基线以 B0 实测为准）
py -3.15 -m unittest discover -s tests/contracts -t tests -p "test_*.py"   # 契约 70
```

- 新增测试只增不删；现有断言禁止弱化（AGENTS §8.2）。
- 涉及发布/公共契约/主链/QA/事务的变更（B5/B8）须附完整运行记录（命令、环境、总数、通过/失败/跳过、耗时）。

## 6. 交付物清单（对照任务书 §九）

| 交付物 | 状态 | 产生任务 |
|---|---|---|
| reports/development/w5-architecture-audit.md | ✅ 已交付 | W5-A |
| reports/development/w5-capability-matrix.md | ✅ 已交付（T 系列后更新 verified 列） | W5-A/B7 |
| reports/development/w5-target-architecture.md | ✅ 已交付（本计划配套设计） | W5-A |
| reports/development/w5-migration-plan.md | ✅ 本文件 | W5-A |
| document_backends/ | 待实施 | B1–B5 |
| tests/w5/ | 待实施 | B6/B7 |
| reports/w5/w5-test-report.md | 待实施 | B7 |
| reports/w5/w5-final-acceptance.md | 待实施 | B8 |

**文档-代码一致性规则**：任何报告不得先于其描述的代码存在（任务书 §九）；B7/B8 报告只能引用已合入测试证据。

---

**状态：W5-A 完成（审计/对照表/目标设计/迁移计划四件齐备）。G0 人工确认前，不启动任何 W5-B 代码任务。**
