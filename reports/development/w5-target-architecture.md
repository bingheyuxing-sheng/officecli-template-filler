# W5 目标架构（Target Architecture）

- 文档性质：**设计提案，待人工确认；尚未实施。** 本文件描述的是 W5-B/C/D 完成后的目标形态，与当前代码的差异见 §8。
- 生成日期：2026-11-06（W5-A 审计阶段）
- 输入：[w5-architecture-audit.md](w5-architecture-audit.md)（审计基线）+ [w5-capability-matrix.md](w5-capability-matrix.md)（能力对照）
- 版本基线：软件 4.2.0（`engine/__init__.py`）；契约集 4.3.0（SKILL.md 头部声明）；OfficeCLI 1.0.160（实测）。
- 约束来源：W5 任务书 §八 E1–E6、AGENTS.md §1/§6/§7/§10。

---

## 1. 设计原则（从审计导出，约束后续所有实施决策）

| # | 原则 | 出处 |
|---|---|---|
| P1 | **演进而非推翻**：现有 `engine/officecli_writer.py` + `fill_executor` writer 路由是正确的第一版后端边界（授权/容量/事务/QA 留在执行器，CLI 只做已授权 set）。W5-B 将其泛化为适配层，不重写引擎、不重写契约。 | 审计 §3.1/§8.1 |
| P2 | **能力注册实测驱动**：capability 的 `available/verified` 只能来自 probe 实测与 T01–T10 对照证据；帮助文本与注释仅作线索。W5-A 探针 P3 已证明注释声明可与 CLI 现行为不符。 | 审计 §6.3 |
| P3 | **路由细化但事务不变**：路由粒度从"文档级全有或全无"细化为"能力组串行阶段"；`DocumentTransaction` 的暂存/QA 绑定/二次门禁/原子发布职责一字不动。OfficeCLI batch 原子性 ≠ 项目事务。 | E4/任务书 §四 |
| P4 | **Python 保留的是质量与语义，不是历史包袱**：跨 run 无损替换、9 类单元格分类、修订生命周期、共享图片保护、指纹、QA 是 E3 质量基线（对照表 KEEP_PY 21 项），迁移即倒退。 | 审计 §4/§9 |
| P5 | **fail-closed 永远成立**：binary 缺失、能力不足、batch 失败、读回不符、规范化失败、validate 失败 → 显式错误码或显式回退披露；禁止任何静默降级路径。 | E6 |

---

## 2. 分层总览

```text
┌─────────────────────────────────────────────────────────────────┐
│ 语义与安全层（全部保持 Python，E1 冻结区，W5 不动）                  │
│  template_intelligence / content_intelligence / template_gate     │
│  qa/* / engine.transaction / engine.workflow / process_guard      │
├─────────────────────────────────────────────────────────────────┤
│ 执行器层（W5-C 接入点）                                            │
│  document_engine.fill_executor                                    │
│    校验 → SHA preflight → Gate → 【operation_router】               │
│    → 阶段执行 → FillLedger(含 backend) → QA → tx.commit           │
├─────────────────────────────────────────────────────────────────┤
│ 统一后端适配层（W5-B 新建）          document_backends/             │
│  base.py（抽象） result.py（结果+原因码）                            │
│  officecli_backend.py      python_backend.py                      │
│  capability_registry.py（实测注册）  operation_router.py（路由）      │
├─────────────────────────────────────────────────────────────────┤
│ 物理文档层                                                          │
│  officecli 1.0.160 子进程（set/batch/validate/get/close 白名单动词） │
│  python-docx / openpyxl / lxml（现有引擎，不重写）                    │
└─────────────────────────────────────────────────────────────────┘
```

职责边界一句话：**语义与安全层决定"允许改什么"；Router 决定"由谁改"；Backend 只负责"怎么改"；事务与 QA 永远在 Backend 之上。**

---

## 3. `document_backends/` 模块设计

### 3.1 `base.py` — DocumentBackend 抽象

接口按 **FillPlan 操作模型**设计（审计 §1.4 四种操作类型），不机械照搬 CLI 动词；`add/remove/move` 不进入抽象——FillPlan `allow_structure_change=false`，结构动词无合法调用场景（P5 原则）。

```python
class BackendTarget:
    """一次后端会话的目标三元组：模板（只读基准）、暂存件（唯一可写）、格式。"""
    template_path: str      # 只读；用于规范化基准（w14 恢复）与指纹对照
    staged_path: str       # 唯一可写路径；永远在 DocumentTransaction 暂存区内
    fmt: str               # "docx" | "xlsx"


class BackendOp:
    """Router 下发的最小执行单元，字段由 FillPlan operation 投影而来。"""
    op_id: str
    slot_id: str
    kind: str              # replace_text | fill_paragraph | fill_cell | replace_image
    location_id: str       # 项目 Slot ID 语法（body/header/footer/tbl/...）
    token: str             # 仅文本类：占位符原文
    value: str
    preconditions: list[str]  # 执行器已完成检查的回执，后端不复检业务规则


class DocumentBackend(abc.ABC):
    name: str                          # "officecli" | "python-docx"

    @abc.abstractmethod
    def capabilities(self, fmt: str) -> CapabilityReport: ...

    @abc.abstractmethod
    def batch(self, target: BackendTarget, ops: Sequence[BackendOp]) -> BatchOutcome: ...
        # 唯一 mutation 入口：一组同能力组操作，后端保证原子或全失败明确报错

    def readback(self, target: BackendTarget, paths: Sequence[str]) -> BatchOutcome: ...
        # 批量读回窗口（open→N×get→close），校验 token 消失/值写入

    def normalize(self, target: BackendTarget, red_targets=None) -> BackendResult: ...
        # 提交阶段规范化：officecli=w14 恢复+红字剥离；python=no-op
        # 失败必须报错（NOT_SILENT），不得伪装成功

    def validate(self, target: BackendTarget) -> BackendResult: ...
        # officecli=officecli validate（OpenXML schema，P6）；
        # python=无对应实现 → 返回 UNAVAILABLE（fail-closed，不是 PASS）
```

设计要点：

1. **`BackendOp` 不携带授权语义**：preconditions/保护区域/容量在执行器层已完成，后端无权解释 FillPlan——Backend 永远不能"自行决定修改范围"（W5-C 要求 2/3 的结构性保证）。
2. **`batch` 是唯一写入口**：单一动词避免散落写入路径；两个后端各自的 batch 实现内部仍可分步，但对外要么全部成功、要么带原因码失败。
3. **`validate` 语义不对称是刻意的**：python 后端没有 schema 校验器，返回 `UNAVAILABLE` 而非跳过——QA 侧据此把该检查记为 `UNVERIFIED`，符合四态契约。

### 3.2 `result.py` — BackendResult 与原因码

```python
@dataclass(frozen=True)
class BackendResult:
    ok: bool
    backend: str                    # "officecli" | "python-docx"
    reason_code: str | None         # 结构化原因；ok=True 时为 None
    detail: str                     # 截断的人类可读补充（≤300 字符）
    per_op: dict[str, OpOutcome]    # op_id -> {status, before_sha256, after_sha256}
```

原因码枚举（注册进 `config/error-codes.json`，只增不改；最终以 B1 时 registry 流程核对为准）：

| reason_code | 语义 | 现有等价物 |
|---|---|---|
| `OFFICECLI_BINARY_MISSING` | binary 不可用 | `OfficecliUnavailable`（保留异常，新增机器码） |
| `OFFICECLI_VERSION_UNSUPPORTED` | 版本探针失败 | 新增 |
| `CAPABILITY_NOT_ROUTABLE` | registry 判定该能力组本后端不可用 | `writer_fallback` 字符串（结构化替代，审计 6.9） |
| `TOKEN_SPANS_RUNS` | 跨 run token（P4 证据，officecli 拒绝） | `_fallback_bucket` 字符串匹配 |
| `TOKEN_NOT_UNIQUE` | 多 occurrence/同段多次出现 | 同上 |
| `LOCATION_UNSUPPORTED` | location 无法映射（嵌套容器等） | `UnsupportedLocation` |
| `CELL_MULTIPLE_PARAGRAPHS` | 多段落单元格（officecli 拒绝） | fill_executor L640 |
| `BATCH_ROLLED_BACK` | CLI batch 原子回滚（P7） | `OFFICECLI_WRITE_FAILED` |
| `READBACK_MISMATCH` | 读回发现 token 残留 | `OFFICECLI_READBACK_FAILED` |
| `NORMALIZE_FAILED` | w14/红字规范化失败 | `OFFICECLI_NORMALIZE_FAILED` |
| `BACKEND_VALIDATE_FAILED` | OpenXML schema 校验失败 | 新增 |

> 兼容策略：执行器 envelope 的 `writer_backend/writer_fallback` 字段**保留**（E2 输出格式不变），`writer_fallback` 的值从自由文本改为 `reason_code + detail` 结构（或新增字段承载 reason_code、旧字段保留文本）——B1 时以 ToolEnvelope 契约核对后定稿；若 ToolEnvelope 对该字段封闭，则走 CP 增量提案，不得私改。

### 3.3 `officecli_backend.py`

**迁移自** `engine/officecli_writer.py`（该文件转为兼容 re-export 层，import 路径不变，`test_officecli_writer.py` 断言不删）。

| 职责 | 来源 | W5-B 变化 |
|---|---|---|
| binary 发现/版本/超时/JSON 解析/退出码处理 | officecli_writer L57-192 原样迁移 | 无变化（已满足 B2 要求：subprocess 列表参数、无 shell 拼接、`--json`、非零退出码即错） |
| location → DOM path | L110-148 | **扩展**：`sec[n].header/footer/first_page_header/...` → `/header[N]`、`/footer[N]`（P5 scope 证据）；映射函数须显式枚举支持面，未支持 story 仍抛 `LOCATION_UNSUPPORTED` |
| token → run 解析（单 run 唯一性检查） | fill_executor `_officecli_operation_plan` L578-701 | 迁入 backend 的"计划器"；检查逻辑不变（P2/P4/P5 实测边界），输出结构化 reason_code |
| batch 执行 + 读回 + close | L165-217 + fill_executor L787-920 | 读回改为**批量窗口**（open→N×get→close，审计 6.7）；close 纪律不变 |
| w14 规范化 + 红字剥离 | L242-342 | 迁入 `normalize()`（提交阶段职责，审计 6.1） |
| 能力 probe | 新增 | 版本探针 + 关键能力实测探针（见 3.5）；结果带时间戳 |
| **动词白名单** | 新增 | 只允许 `set`（run/paragraph/cell/header/footer scope）、`batch`、`get`、`validate`、`close`。`add/remove/move/swap/raw/raw-set/add-part/merge/import` **编译期即拒绝**（审计 6.6/§9.4/§9.5），附测试证明 |

### 3.4 `python_backend.py`

**薄适配层，不重写引擎**。`batch()` 内部按 kind 分派到现有实现：

| kind | 分派目标（现有代码，不动） |
|---|---|
| replace_text / fill_paragraph | fill_executor `_apply_operation` python 分支（`LogicalParagraphView` + `style_engine`） |
| fill_cell | `table_engine.classify_cell_structure` + `fill_cell_strict_style` |
| replace_image | `image_engine.replace_image_by_role`（含共享关系保护） |

`normalize()` 为 no-op（python 路径无 w14 盖章问题）；`validate()` 返回 `UNAVAILABLE`。
等价性要求（B3 出口条件）：同一 fixture 双跑（python_backend vs 现有执行器 python 路径），产物**逐字节等价**——适配层不得引入任何行为差。

### 3.5 `capability_registry.py`

注册表条目（与任务书 B4 对齐，字段语义以实测为准）：

```json
{
  "capability": "docx.text.replace_single_run",
  "backend": "officecli",
  "available": true,
  "verified": true,
  "verified_by": ["probe:P2", "test:test_officecli_writer", "T02"],
  "verified_at": "2026-11-06T14:30:00+08:00",
  "fallback": "python",
  "risk_level": "low",
  "reason": "run-scoped set 保留 run 顺序与格式（P2）"
}
```

规则：

1. `verified` 只能被三类证据置 true：探针实测、现有测试、T01–T10 对照；`verified_by` 必填且可追溯。
2. 探针在进程内按需运行（结果缓存 + CLI 版本号绑定，版本变化即失效重探），**不在仓库硬编码任何 `available: true`**。
3. `qa/environment.py` 增加 `officecli_runtime` 探测项（`required: false`；缺失 → 按策略回退 python 后端并在 envelope/QA 显式披露，绝不阻断任务也绝不伪装 officecli 已用——E6）。
4. 对照表（w5-capability-matrix.md）是**登记意图的来源文档**；registry 是**运行时事实**；两者冲突时以 registry 实测为准并回写文档。

### 3.6 `operation_router.py`

路由算法（能力组 = 同 kind 且同后端可表达性的操作集合）：

```text
route(fill_plan, registry) -> RoutingDecision:
    groups = 按能力组划分 fill_plan.operations
             （文本组: replace_text/fill_paragraph；单元格组: fill_cell；图片组: replace_image）
    stages = []
    for group in groups:
        cap = capability_id(group)
        entry = registry.lookup(cap)
        # E7: 每组生成一条路由记录（六字段，禁止缺省）
        record = {capability_id: cap, operation_types: group.types,
                  chosen_backend: None, reason_code: None,
                  registry_probe: entry.snapshot(),   # available/verified/cli_version
                  fallback_allowed: True, final_outcome: None}
        if entry.verified && entry.available:
            record.chosen_backend = entry.backend
            stages.append(Stage(group, record))
        else:
            # 整组回退（非逐 op），回退原因 = entry.reason / CAPABILITY_NOT_ROUTABLE
            record.chosen_backend = "python-docx"
            record.reason_code = CAPABILITY_NOT_ROUTABLE
            stages.append(Stage(group, record))
        # officecli 组内部：计划器逐 op 预检（单 run/唯一性/单段落单元格/位置映射），
        # 任一 op 不可表达 -> 该组整体降级 python（组内原子性，非文档级）
    单写入者检查: stages 串行执行；同组永不混合后端；
    全程单 DocumentTransaction；每阶段出口 = close + normalize + stage_check（E8），
    stage_check 未通过 -> 不进入下一阶段，走事务中止；
    全部记录随 envelope data.routing 输出并落 Ledger（E7）。
```

与现状的关键差异（审计 6.2）：回退粒度 **文档级 → 能力组级**。含图片的 FillPlan 从"整文档回退 python"变为"文本组走 officecli、图片组走 python"，提升采纳率且不违反 E4（串行、单事务、组内单写入者）。

### 3.7 FillLedger 后端记录（选项 A，避免契约变更）

`fill_ledger.record()` 的 `result` 参数本就是开放 dict（`_normalize_result` 仅规范化 status/error_code）。后端信息经 result 增量携带：

```json
{"op_id": "OP_001", "slot_id": "...", "location_id": "...",
 "value_sha256": "...",
 "result": {"status": "SUCCESS", "backend": "officecli", "reason_code": null},
 "before_text_sha256": "...", "after_text_sha256": "..."}
```

**B5 实施前必须核对** `contracts/03-content-fill-plan.md` §3.8 对 result 子对象的措辞：若为开放结构则零契约变更；若为封闭字段集则提交 CP（走 AGENTS §3.2 流程），禁止私改。E5 可追溯性（op→backend→记录）由此闭合。

---

## 4. 目标数据流（W5-C 完成态）

```text
FillPlan（唯一授权来源）
   │
   ▼
operation_router ──registry(实测)──► RoutingDecision{stages, per-stage reason_code}
   │
   ├─[阶段1: 文本能力组]──officecli_backend.batch──┐（组内原子；失败→组降级重跑 python）
   │                                               ├─ close + normalize(w14/红字)
   ├─[阶段2: 单元格能力组]─python_backend.batch ────┤（stage 间串行，E4）
   │                                               ├─（无混合写入窗口）
   └─[阶段3: 图片能力组]───python_backend.batch ────┘
   │
   ▼
FillLedger（每 op 记录 backend + before/after SHA + reason_code）
   │
   ▼
QA（run_full_qa，读暂存件独立执行；officecli validate 可作新增检查项 OOXML_SCHEMA_VALIDATION，
│   缺失/失败 → UNVERIFIED/FAILED，四态不变）
   ▼
DocumentTransaction.record_gate → commit()（二次门禁 + 原子发布，职责不变）
```

失败语义：任一阶段失败 → 该阶段组内要么已原子回滚（officecli batch P7）要么事务中止（python 异常）；执行器按现有 `EXECUTION_FAILED/rollback_required` 路径处理，**不存在后端级部分成功**。

---

## 5. E1–E9 不变式映射（设计级保证 → 验证方式）

> E7/E8/E9 为 W5-A 人工确认（2026-11-06）新增冻结约束，与任务书 E1–E6 同级生效。

| 约束 | 设计保证 | 验证（W5-C/D 测试） |
|---|---|---|
| E1 契约保护 | 契约零修改；Ledger 走 result 增量（3.7，先核对再实施）；reason_code 走 error-codes 只增流程 | contracts/ 套件全绿（实测 72 项）；无任何 schema diff |
| E2 向后兼容 | `--writer` 参数与默认值（python-docx）不变；envelope 输出字段不删；`engine/officecli_writer.py` 转 re-export 保 import 兼容；Legacy `--data` 行为冻结 | test_legacy_compat + 双跑 envelope 字段对比 |
| E3 质量不倒退 | KEEP_PY 21 项不动；CANDIDATE 项必须先过 T01–T10 对照才可置 verified | tests/w5/ 对照套件 + 结构指纹 QA 逐例断言 |
| E4 单写入者 | Router 串行 stages + 组内单后端；阶段边界 close；全程单事务 | 并发写入构造测试（同任务双后端混合 → 拒绝） |
| E5 可追溯性 | op→slot→backend→Ledger→QAReport→交付文件全链字段闭合 | Ledger 抽样断言 backend 字段存在且与 RoutingDecision 一致 |
| E6 无虚假成功 | reason_code 全枚举；validate 缺失=UNAVAILABLE；binary 缺失=显式回退披露 | 故障注入：fake binary/假版本/坏 batch/坏读回，全部断言错误码而非 PASS |
| **E7 能力路由可解释** | RoutingDecision 为一等结构化产物：**每个能力组**记录 `{capability_id, operation_types, chosen_backend, reason_code, registry 探测快照(available/verified/版本), fallback_allowed, final_outcome}`；随 envelope 输出并逐条落 Ledger（`data.routing` + op 级 backend/reason） | B5 测试：任意 FillPlan 断言 routing 记录六字段齐备；降级路径断言 reason_code 非空且与 registry 探测结果一致；禁止静默降级（无记录的 backend 切换 = 测试失败） |
| **E8 阶段间状态可验证** | 每个能力组执行结束 = 阶段边界三步：`close + normalize + stage_check`；stage_check 为轻量中间检查（officecli 组：读回 token 消失 + 结构指纹不变；python 组：现有段落/表格映射完整性），结果记入 RoutingDecision.final_outcome；**前一阶段 check 未通过 → 不进入下一阶段**（抛错进入事务中止路径，非跳过） | B6 测试：阶段 1 注入损坏（如读回残留）→ 断言阶段 2 未执行、事务中止；正常多阶段任务断言每个阶段有独立 check 记录 |
| **E9 事务级完整回滚** | 任一阶段/检查失败 → `DocumentTransaction` 中止路径不变：暂存件清理、交付路径字节不变、原始模板不变；officecli 组内另有 batch 原子回滚（P7）双保险；**部分成功在物理上不可能出现在交付文件** | T10 真实失败注入矩阵：binary 缺失、batch 失败、读回不符、normalize 失败、stage_check 失败——每项断言：输出不存在或与执行前逐字节一致 + 暂存清理 + Ledger/事务记录显式 FAILED 错误码 |

---

## 6. 不改变项清单（W5 明确不动）

1. `contracts/01–06` 全部语义与对应 Schema；
2. `engine/transaction.py`（事务/二次门禁/原子发布）；
3. `template_gate/`（W4 交付的确认机制与执行入口强制检查）；
4. `qa/` 的四态语义、required checks 策略、独立执行原则；
5. 五条执行路径的 Gate+tx+QA 安全链（repair/review/reformat/excel 维持 python 单后端——审计 5.7：单后端无重复，不强行迁移）；
6. Legacy `--data` 行为（含其 Gate 接入）；
7. `ooxml_utils/table_engine/style_engine/image_engine/review_engine` 的实现本体；
8. `analyze_template.py --spec-version` 默认值 3（兼容边界）。

## 7. 明确排除项（红线，附拒绝理由）

| 排除项 | 理由 |
|---|---|
| `officecli merge` | 无授权/容量/红字/QA/事务语义，采纳即制造门禁绕过通道（审计 §9.4） |
| `officecli raw / raw-set / add-part` | 绕过 FillPlan 授权模型的原始 XML 通道（§9.5） |
| `officecli add/remove/move/swap`（主链） | `allow_structure_change=false`；且 add 有自动补建样式副作用（P1） |
| 为 officecli 后端引入"跳过 QA/跳过指纹"的任何参数 | E6 |
| 在 W5-B/C 中顺手重构 repair/review/reformat 引擎 | 超范围；须单独登记（AGENTS §10.7） |

---

## 8. 现状 → 目标差异清单（实施核对用）

| # | 现状（W5-A 时点） | 目标 | 任务 |
|---|---|---|---|
| 1 | `engine/officecli_writer.py`（未提交，文档级能力） | `document_backends/officecli_backend.py`；旧路径 re-export | B2 |
| 2 | 路由：fill_executor L1523 文档级全有或全无 | operation_router 能力组级串行 | B5 |
| 3 | fallback 自由文本（`_fallback_bucket` 字符串匹配） | reason_code 全枚举结构化 | B1/B5 |
| 4 | Ledger 无 op 级 backend | result dict 增量（先核对契约 03 措辞） | B5 |
| 5 | environment 无 officecli 探测 | `officecli_runtime`（required=false） | B4 |
| 6 | location 映射 body-only | header/footer/first_page 系（P5 证据） | B2 |
| 7 | 读回逐 op 起停 resident | 批量读回窗口 | B2 |
| 8 | validate 未接入 QA | 新增检查项 `OOXML_SCHEMA_VALIDATION`（officecli 后端专属，缺失=UNVERIFIED） | B4/C 候选 |
| 9 | Agent 手动编排 12 脚本×5 步 | 统一入口 `python scripts/office_template.py <verb>`（§9） | B8/W5-F |
| 10 | capability 状态散在代码注释 | registry 实测驱动 + capabilities 子命令 | B4 |

## 9. W5-F 统一 Agent 接口设计（W5-E 阶段实施）

统一入口采用 `python scripts/office_template.py <subcommand>`（不引入新二进制，保留全部旧脚本，E2）：

| 统一命令 | 背后映射 | 新增/复用 |
|---|---|---|
| `capabilities [--json]` | document_backends.capability_registry 输出 + qa 环境矩阵 | 新增（B4 交付后可用） |
| `inspect <file>...` | inspect_document.py 薄封装 | 复用 |
| `analyze <file>` | template_gate.py analyze + report **合并为一步**（输出 JSON+Markdown） | 复用+合并 |
| `confirm <analysis> --review-token --user-statement` | template_gate.py confirm | 复用 |
| `execute --task-type ... <现有参数集>` | 按 task_mode 分派 generate/repair/review/reformat/excel 脚本；`--gate-record` 校验不变 | 复用 |
| `verify <file>` | run_qa.py 薄封装 | 复用 |
| `status --task-id` | gate store + checkpoint store 查询（只读聚合） | 新增薄查询 |

SKILL.md 收敛为：适用场景 / 任务识别规则 / 核心安全约束 / 统一 CLI 用法 / 用户确认规则 / 错误处理规则 / references 按需加载规则；契约与实现细节外迁 references/（现有三份 references 结构延续）。

---

## 10. 验收对照（本设计如何被证明落地）

| 设计断言 | 证明载体 | 阶段 |
|---|---|---|
| Backend 无法越权 | BackendOp 不含授权字段 + 无 gate 构造测试被拒 | W5-C |
| 组级回退生效 | 含图片 FillPlan 双阶段执行，Ledger 显示文本组 officecli/图片组 python | W5-C + T05/T07 |
| 质量基线不倒退 | T01–T10 双后端产物 XML/样式/关系/文本完整性/QA 对照全绿；未达标项保留 python 并记录 | W5-D |
| 单写入者 | 并发/混合构造测试拒绝 | W5-C |
| fail-closed | 故障注入矩阵（binary 缺失/版本错/回滚/读回/规范化/validate）全部显式错误码 | W5-B..D |
| 兼容不破 | 全量回归（当前基线 532+，以实际运行结果为准）+ contracts 70 + envelope 字段对比 | 每阶段 |

---

**本文件为设计提案。W5-B 的任何代码实施，以人工对本设计及 [w5-migration-plan.md](w5-migration-plan.md) 的确认为前置条件。**
