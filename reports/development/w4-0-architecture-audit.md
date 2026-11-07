# W4-0 Template Understanding Gate 架构审计报告

- 审计日期：2026-11-06
- 审计对象：`d:\docs\officecli-template-filler`（分支 `main`，HEAD `e4439d4`）
- 审计性质：只读。未修改任何业务代码、契约、Schema、SKILL.md 或测试。
- 审计依据：W4 任务书（W4-0）、`AGENTS.md`、`contracts/`、`reports/w0-w3`、实际代码与测试。
- 最终状态：见 §I.5（测试完成后判定）。

---

## A. 项目当前架构

### A.1 目录结构（实际）

```text
officecli-template-filler/
├── AGENTS.md / README.md / SKILL.md / CHANGELOG.md
├── contracts/                  # 冻结契约集 4.2.0 + changes/CP-W2-001, CP-W2-002
├── schemas/                    # 4.0 契约 Schema + 3.0 legacy
├── config/                     # qa-policy / error-codes / package_limits / environment_capabilities
├── engine/                     # v3.5.9 核心：OOXML、表格、图片、Excel、REPAIR/REVIEW/REFORMAT、事务、QA
├── template_intelligence/      # DocumentSpec 4.0 生产、槽位、指纹、校验
├── content_intelligence/       # ContentPlan / FillPlan 构建与校验
├── document_engine/            # FillPlan 执行器、FillLedger、执行管道
├── qa/                         # QAReport 4.0、QA Gate、Pipeline、环境探测
├── scripts/                    # 12 个 CLI 入口
├── tests/                      # 单元/契约/端到端/故障注入
├── reports/                    # W0-W3 验收与证据
└── references/                 # 引擎实现参考
```

### A.2 核心模块职责

| 模块 | 职责 | 关键入口 |
|---|---|---|
| `engine/` | 非破坏式 OOXML 修改、Decimal SSOT、表格/图片/Excel、REPAIR/REVIEW/REFORMAT、事务、进程归属、QA 检查器 | `engine/__init__.py` 导出 100+ 公共符号 |
| `template_intelligence/` | DocumentSpec 4.0 生产、slot_id、四类指纹、语义校验 | `build_document_spec_from_path`、`compute_four_hashes` |
| `content_intelligence/` | ContentPlan/FillPlan 纯函数构建与校验 | `build_content_plan`、`build_fill_plan`、`validate_*` |
| `document_engine/` | FillPlan 确定性执行、暂存、QA、提交 | `execute_fill_plan`、`FillLedger` |
| `qa/` | QAReport 4.0 构建、系统自有检查矩阵、门禁、环境能力 | `qa.pipeline.run_full_qa`、`qa.gate.assert_commit_eligible` |
| `scripts/` | CLI 编排层；所有写文档脚本都使用 `DocumentTransaction` | 见 §D |
| `contracts/` / `schemas/` | 冻结契约与机器可校验结构 | 5 份契约、12 个 Schema |

### A.3 v4 主数据流

```text
template.docx
  → analyze_template.py --spec-version 4
    → DocumentSpec 4.0（slots / protected_regions / capacity / fingerprint_ref / warnings / errors）
      → ContentPlan 4.0（facts / sections）
      → FillPlan 4.0（operations）
        → document_engine.execute_fill_plan
          → validate spec/plan
          → template SHA preflight
          → preconditions / locate
          → mutate（仅内存/暂存）
          → DocumentTransaction.record_gate(QAReport 4.0)
          → tx.commit()（二次门禁 + 原子发布）
          → FillLedger
```

Legacy 路径：`generate_document.py --data` 直接 token 替换，但仍走 `DocumentTransaction` + package/format QA；不经过 v4 plan chain。

### A.4 版本与测试状态

| 项 | 事实 | 证据 |
|---|---|---|
| 软件版本 | `engine.__version__ = "4.0.2"` | `engine/__init__.py:187` |
| 契约集 | 4.2.0 | `contracts/README.md:3,86-93` |
| 产物 Schema | `schema_version = "4.0"` | `schemas/document_spec-4.0.schema.json:23` |
| 分支 | `main` | `git branch --show-current` |
| HEAD | `e4439d4 release(v4.0.2): bump version for the supply-chain cleanup patch` | `git log -1` |
| 工作树 | 2 个已修改文档：`SKILL.md`、`references/engine-internals.md` | `git status --short` |
| Python | 3.15.0（项目解释器 `py -3.15`） | 实测 |
| 依赖 | python-docx 1.2.0、openpyxl 3.1.5、jsonschema 4.26.0、lxml 6.1.3、Pillow 13.0.0 | 实测 |
| 全量测试 | 见 §A.5 | 本次运行 |

### A.5 测试实测

命令（cwd=`d:\docs\officecli-template-filler`）：

```powershell
py -3.15 -m unittest discover -s tests -p "test_*.py"
```

结果：**Ran 479 tests in 173.947s — OK**（0 failure / 0 error / 0 skip；仅有 ResourceWarning 与一次测试构造的 `Duplicate name: '[Content_Types].xml'` UserWarning）。退出码 0。

契约测试：

```powershell
py -3.15 -m unittest discover -s tests/contracts -t tests -p "test_*.py"
```

结果：**Ran 70 tests in 1.193s — OK**，退出码 0。

与历史基线（`reports/acceptance/w3-10-exit-review.md` 的 479 项）一致，无测试删除或弱化。

### A.6 资料冲突与过时描述

| 冲突/过时点 | 证据 | 影响 | 处理 |
|---|---|---|---|
| `engine/__init__.py` 模块 docstring 写 “v3.5.5”，实际 `__version__ = 4.0.2` | `engine/__init__.py:3,187` | 仅文档性，不影响行为 | 记录，不在 W4-0 修改 |
| `.trae/skills/officecli-template-filler` 已安装副本为 `4.0.0`，仓库为 `4.0.2` | 副本 `engine/__init__.py:187` | 若 Agent 运行旧副本，W4 闸门不存在 | W4-8 同步；W4-0 记录 |
| `dist/` 历史归档已被 v4.0.2 清空，README 仍指向 Releases | `CHANGELOG.md:22-23` | 发布说明与仓库状态需在 W4-9 再对齐 | 记录 |
| `README.md` 称 479 项测试，需本次实测确认 | `README.md:14` | 若数字不一致，属于文档缺陷 | 以实测为准 |

---

## B. 现有能力清单

分类：IMPLEMENTED（有实现且有代码/测试证据）、PARTIAL（部分实现或仅底层能力）、DESIGNED（只有设计/文档）、MISSING（未实现）、UNKNOWN（无法确认）。

### B.1 模板解析 20 项

| # | 要素 | 状态 | 实际产出/能力 | 代码证据 | 测试证据 |
|---|---|---|---|---|---|
| 1 | 页面大小与方向 | IMPLEMENTED | `document.sections[]` 的 `page_width_twips/page_height_twips/orientation`；`document.page_size/orientation` | `template_intelligence/spec_builder.py:247-297` | `tests/test_spec_builder.py` |
| 2 | 页边距 | IMPLEMENTED | `sections[].margins.{top,bottom,left,right}` | 同上 | 同上 |
| 3 | 分节结构 | IMPLEMENTED | 每节 `section_index` + 页面/页边距/页眉页脚距离 | 同上 | 同上 |
| 4 | 页眉页脚 | PARTIAL | 段落遍历覆盖 header/footer story；保护区可标记 `header/footer`；无“页眉页脚规则”汇总 | `engine/ooxml_utils.py` 迭代器；`spec_builder.py:746-820` | `tests/test_spec_builder.py`、`test_fixture_matrix.py` |
| 5 | 字体及字号 | PARTIAL | `structure.paragraphs[].effective_sz_half_pt/font_east_asia`；ASCII 字体不单独记录 | `spec_builder.py:300-314`、`engine/style_engine.py` | `tests/test_spec_builder.py` |
| 6 | 标题层级 | PARTIAL | 仅 `style_name` 与 `w:outlineLvl` 可用于判断；spec 不输出显式 heading level | `engine/alignment.py:66-91`、`qa_engine.py:377-395` | `tests/test_layout_qa.py` |
| 7 | 正文段落规则 | PARTIAL | 段落清单 + 样式名 + 文本预览；无“正文规则”聚合 | `spec_builder.py:300-314` | `tests/test_spec_builder.py` |
| 8 | 段落间距/行距 | PARTIAL | 未进入 DocumentSpec；`layout_qa` 指纹与 `repair_engine` profile 已能读取 | `engine/layout_qa.py:92-100`、`engine/repair_engine.py:63` | `tests/test_layout_qa.py`、`test_v3_engine.py` |
| 9 | 表格结构/合并/列宽 | PARTIAL | spec 仅 `rows/cols/headers/cell_type_counts`；`table_style_signature` 有 `tcW/gridSpan/hMerge/vMerge/tcMar` | `spec_builder.py:317-344`、`engine/table_engine.py:152-258` | `tests/test_table_signature.py` |
| 10 | 表格边框/底纹 | PARTIAL | `table_style_signature` 有 `tblBorders` 与 `header_shading`；不进入 spec | `engine/table_engine.py:152-233` | `tests/test_table_signature.py` |
| 11 | 图片及布局 | PARTIAL | `structure.images[]` 有 object_type/rId/宽高/partname/content_type/ref_count；无锚点偏移/层级 | `spec_builder.py:360-448` | `tests/test_image_roles_ocr_render.py` |
| 12 | 文本框及浮动对象 | PARTIAL | 文本框段落可枚举（`txbx_p[i]`），浮动锚点可检测；无几何定位/层级 | `engine/ooxml_utils.py:408-503`、`engine/docx_parser.py:320` | `tests/test_v3_engine.py` |
| 13 | 页码和域代码 | PARTIAL | `w:fldSimple`/`w:instrText` 可识别为 `control_or_field`/保护区；无页码规则聚合 | `engine/docx_parser.py:312,436`、`spec_builder.py:746-820` | `tests/test_sdt_detection.py`、`test_spec_builder.py` |
| 14 | 编号及多级列表 | PARTIAL | `w:numPr` 参与 L2 评估；spec 无编号规则字段 | `engine/docx_parser.py:273-355` | `tests/test_fixture_matrix.py` |
| 15 | 固定内容区域 | PARTIAL | `protected_regions` 覆盖 `fixed_title/header/footer/field/sdt/logo/stamp/repeated_header` | `spec_builder.py:746-820`、`schemas/document_spec-4.0.schema.json:282-295` | `tests/test_sdt_discovery.py` |
| 16 | 可填写区域 | IMPLEMENTED | `slots[]`：slot_id/location_id/candidate_type/span/occurrence/protection_status/confirmation_tier | `spec_builder.py:479-588`、`contracts/02-document-spec.md:95-131` | `tests/test_spec_builder.py`、`tests/contracts/test_document_spec.py` |
| 17 | 保护区域 | IMPLEMENTED | `protected_regions[]` + 前缀覆盖规则 | `spec_builder.py:746-820`、`contracts/02-document-spec.md:152-178` | `tests/test_sdt_discovery.py` |
| 18 | 红色说明文字/占位内容 | IMPLEMENTED | `red_run_clue` candidate + `RED_TEXT_RESIDUAL` QA；语义仍可能是“强调”而非占位 | `engine/docx_parser.py:424-434`、`engine/qa_engine.py` | `tests/test_v3_engine.py` |
| 19 | 内容控件 SDT | IMPLEMENTED | W3-4：SDT 容器 PROTECTED + `sdt_edit=false`；FillPlan 命中拒绝 | `spec_builder.py`、`contracts/02-document-spec.md:133-150` | `tests/test_sdt_detection.py`、`test_sdt_discovery.py` |
| 20 | 公式/OLE 等特殊对象 | PARTIAL | chart/smartart/ole_object 可发现并列入 `structure.images`/`unsupported_features`；不可编辑 | `spec_builder.py:432-447`、`engine/docx_parser.py:477-493` | `tests/test_spec_builder.py`、`test_fixture_matrix.py` |

### B.2 证据、确认、持久化、执行门禁

| 能力 | 状态 | 证据 | 说明 |
|---|---|---|---|
| 解析证据逐属性登记 | MISSING | 无 `evidence` 模块；spec 只有最终值 | 不能记录 source/evidence_type/verification_status |
| 四态（VERIFIED/UNVERIFIED/AMBIGUOUS/CONFLICT） | MISSING | 无模型；现有 QA 四态是结果状态，不是证据状态 | 需要独立模型 |
| 证据冲突检测 | MISSING | 无跨来源比对 | 同一属性冲突无法阻止执行 |
| 未知项阻断清单 | MISSING | 无 blocking 清单/用户问题清单 | 现有 `warnings/errors` 只是文本 |
| 解析报告（用户可读） | MISSING | `analyze_template.py` 只输出 JSON | 无 Markdown/确认提示 |
| 用户确认记录 | MISSING | 无 Gate Record；`resolve_confirmation_gate` 仅返回 tier | 仅 Agent 对话，不持久 |
| 确认绑定模板 SHA | MISSING | 无 gate 记录 | 模板变化无法使确认失效 |
| 解析版本/证据摘要绑定 | MISSING | 无 analysis_version/evidence_digest | 无法检测解析规则变化 |
| 依赖确认的执行门禁 | MISSING | 所有 `execute_*` 入口均无 gate 检查 | 无记录也能执行 |
| 状态机 | MISSING | 只有确认 tier；无 10 状态机 | 允许“跳过确认” |
| 补充材料增量解析 | MISSING | 无 supplement 解析/合并 | 无法安全复用旧证据 |
| 闸门错误码 | MISSING | `config/error-codes.json` 无 `TEMPLATE_GATE_*` | 失败只能 generic error |
| 闸门 Schema/契约 | MISSING | 无 contract 06 / 3 个 schema | 无机器可校验结构 |
| 闸门测试 | MISSING | 无 test_template_gate_* | 无绕过证明 |

### B.3 可复用机制（已存在）

| 机制 | 可用部分 | 证据 |
|---|---|---|
| DocumentSpec 4.0 | 页面/节/段落/表格/图片/slots/protected/fingerprint | `template_intelligence/spec_builder.py` |
| 四类指纹 | structural/style/protected/layout，内容无关 | `template_intelligence/fingerprint.py`、`contracts/02-document-spec.md:206-217` |
| slot_id/location_id | 稳定定位语法，含 SDT/header/footer | `template_intelligence/slot_id.py`、`contracts/01-slot-id.md` |
| 表格签名 | `table_style_signature`：列宽/边框/底纹/合并/边距 | `engine/table_engine.py:152-258` |
| 版式指纹 | 字体/字号/对齐/缩进/行距/段距/表格/图片 | `engine/layout_qa.py:92-201` |
| 事务与二次门禁 | 暂存/QA/`record_gate`/原子提交 | `engine/transaction.py:215-408` |
| QA Gate | 系统自有 required checks、四态、证据规则 | `qa/gate.py`、`config/qa-policy.json` |
| Checkpoint Store | 任务级原子 JSON 持久化模式 | `engine/workflow.py:201-280` |
| ToolEnvelope/错误码 | 输出与错误语义 | `contracts/05-tool-envelope-error-codes.md` |
| 确认 tier | `MUST_ASK_USER`/HOLD 的确定性决策 | `engine/workflow.py:105-166` |

---

## C. 缺失能力清单（P0/P1/P2）

| 优先级 | 缺失项 | 影响 | 对应 W4 阶段 |
|---|---|---|---|
| P0 | Evidence Registry + 四态模型 | 无法逐属性证明“为什么可信” | W4-1 |
| P0 | 阻断项判定与用户问题清单 | 未知项无法暂停执行 | W4-1/W4-3 |
| P0 | Gate Record + 持久化 + HMAC | 确认不能跨会话、不能绑定模板 | W4-5 |
| P0 | Gate Validator | 无有效确认也能执行 | W4-6 |
| P0 | 执行入口强制接入 | CLI/API/legacy 均可绕过 | W4-7 |
| P0 | 闸门测试（含绕过） | 无法证明闸门有效 | W4-1..W4-9 |
| P1 | 状态机 | 状态靠 AI 口述，可能非法跳转 | W4-2 |
| P1 | Analysis Report | 用户无法审查解析结果与阻断项 | W4-3 |
| P1 | 补充材料增量解析 | 只能整份重跑或盲目信任新材料 | W4-4 |
| P1 | 契约 06 + 3 个 Schema + 7 个错误码 | 无机器可校验结构 | W4-1/W4-6 |
| P2 | 解析覆盖率指标 | 有覆盖率也不等于正确性 | W4-3 |
| P2 | 页数/页码规则的可验证汇总 | 依赖 PDF 后端，易误报 | W4-3 |
| P2 | 已安装 Skill 副本同步 | 旧副本可绕过 | W4-8 |

---

## D. 执行入口清单

| 入口 | 类型 | 模块/函数 | 最终写入 | 现有校验 | 可绕过？ | 证据 |
|---|---|---|---|---|---|---|
| `scripts/generate_document.py --data` | CLI | `_run_legacy_data_path` | `DocumentTransaction.stage/commit` | package+format QA；模板 SHA 未作为 gate | **是**（无确认） | `scripts/generate_document.py:39-76` |
| `scripts/generate_document.py --plan` | CLI | `generate_document_v4` → `execute_fill_plan` | `DocumentTransaction` | spec/plan 校验、SHA、QA、二次门禁 | **是**（无确认） | `scripts/generate_document.py:107-136`、`document_engine/fill_executor.py:794-983` |
| `document_engine.execute_fill_plan` | Python API | `fill_executor.py` | `DocumentTransaction` | 同上 | **是**（无确认） | `document_engine/fill_executor.py:794` |
| `scripts/repair_document.py` | CLI | `build_repair_plan` + `execute_repair_plan` | `DocumentTransaction` | package+format QA | **是** | `scripts/repair_document.py:58-76`、`engine/repair_engine.py:362` |
| `engine.execute_repair_plan` | Python API | `repair_engine.py` | 直接 `brk_doc.save(output_docx_path)` | 无事务、无 gate | **是** | `engine/repair_engine.py:362-474` |
| `scripts/review_document.py` | CLI | `build_review_plan` + `execute_review_plan` | `DocumentTransaction` | review integrity+package | **是** | `scripts/review_document.py:89-107`、`engine/review_engine.py:1126` |
| `engine.execute_review_plan` | Python API | `review_engine.py` | 直接保存/调用方路径 | 无 gate | **是** | `engine/review_engine.py:1126-1141` |
| `scripts/reformat_document.py` | CLI | `build_reformat_plan` + `execute_reformat_plan` | `DocumentTransaction` | package+format QA | **是** | `scripts/reformat_document.py:82-100`、`engine/reformat_engine.py:381` |
| `engine.execute_reformat_plan` | Python API | `reformat_engine.py` | 直接保存 | 无 gate | **是** | `engine/reformat_engine.py:381-390` |
| `scripts/proofread_document.py` | CLI | `build_proofread_plan` + `execute_review_plan` | `DocumentTransaction` | review integrity+package | 不应触发（无模板） | `scripts/proofread_document.py:66-84` |
| `scripts/generate_excel.py` | CLI | Excel 填充 | `DocumentTransaction` | Excel QA | 本次不触发 | `scripts/generate_excel.py:105` |
| `scripts/render_document.py` | CLI | PDF 渲染 | `DocumentTransaction` | PDF backend | 本次不触发 | `scripts/render_document.py:49` |
| `scripts/analyze_template.py` | CLI | 只读分析 | 不写文档 | 无 | 不适用 | `scripts/analyze_template.py:33-92` |
| `scripts/inspect_document.py` | CLI | 路由+检查 | 不写文档 | 无 | 不适用 | `scripts/inspect_document.py:25-66` |
| `scripts/run_qa.py` | CLI | QA | 不写文档 | QA policy | 不适用 | `scripts/run_qa.py` |
| `DocumentTransaction` | 内部 | `transaction.py` | `stage/commit` | QA + 二次门禁 | 低层原语；正式内容生产者应在上层 gate | `engine/transaction.py:151-408` |

结论：

- **所有正式内容执行入口当前都没有模板确认检查。**
- `execute_repair_plan` / `execute_review_plan` / `execute_reformat_plan` 可直接保存到调用方路径，因此 gate 必须加在这些函数内部，不能只加在 CLI。
- `execute_fill_plan` 已使用事务，但同样没有 gate；应在模板 SHA 预检后、mutation 前加入。
- 旧版 `--data` 路径必须单独接入，否则会成为显式绕过通道。

---

## E. 架构复用方案

### E.1 可直接复用

| 能力 | 复用方式 |
|---|---|
| `build_document_spec_from_path` | analyzer 的第一证据源；不重写解析器 |
| `compute_four_hashes` | Gate Record 的模板指纹绑定 |
| `slot_id` / `location_id` | 证据对象定位，沿用现有稳定 ID |
| `table_style_signature` / `layout_qa` 指纹 | 补齐段落间距、行距、边框、底纹、列宽、合并证据 |
| `DocumentTransaction` | 保持暂存/QA/原子提交；gate 只在其上游 |
| `qa.gate` | 复用“系统自有 required checks + 结构化拒绝”的校验风格 |
| `WorkflowCheckpointStore` | 复用原子 JSON 持久化模式 |
| `ToolEnvelope` / `error-codes` | 复用错误记录字段与 registry 流程 |
| `resolve_confirmation_gate` | 保留 Agent 层 tier 决策；W4 gate 作为更强的执行层闸门 |

### E.2 需要扩展

| 模块 | 扩展点 | 不改契约 |
|---|---|---|
| `template_intelligence` | 只读调用，不修改 spec 字段 | 是 |
| `engine/table_engine.py` / `layout_qa.py` | 作为证据采集函数被 analyzer 调用 | 是 |
| `engine/__init__.py` | 仅导出新模块所需符号（W4-1 后） | 是 |
| `scripts/template_gate.py` | 新 CLI，不改旧 CLI 默认值 | 是 |

### E.3 必须新建

`template_gate/`（models/evidence/analyzer/validation/report/state/store/validator/errors）、`scripts/template_gate.py`、`config/template-gate-policy.json`、3 个 Schema、`contracts/06-template-understanding-gate.md`、W4 测试文件。

### E.4 不应修改

- `contracts/01`–`05` 的语义与 `schemas/*-4.0.schema.json` 的字段。
- `document_spec-4.0.schema.json`（`additionalProperties: false`）。
- `content_plan` / `fill_plan` / `qa_report` Schema。
- `analyze_template.py` 默认 `--spec-version 3`。
- 现有 v3.5.9 公共 API 行为（除 W4-7 明确接入的 execute_* gate 检查）。
- 现有模板解析算法与 QA 阈值。

---

## F. 推荐架构

```text
┌──────────────────────────────┐
│ Template Analyzer            │
│ - DocumentSpec 4.0           │
│ - table/layout/style probes  │
│ - supplement parser          │
└──────────────┬───────────────┘
               │ EvidenceRecord[]
┌──────────────▼───────────────┐
│ Evidence Registry            │
│ - add/query/conflict/digest  │
│ - VERIFIED/UNVERIFIED/       │
│   AMBIGUOUS/CONFLICT         │
└──────────────┬───────────────┘
               │
┌──────────────▼───────────────┐
│ Validation Engine            │
│ - task_relevant              │
│ - blocking rules             │
│ - coverage/counts            │
└──────────────┬───────────────┘
               │
┌──────────────▼───────────────┐
│ Analysis Report              │
│ - JSON + Markdown            │
│ - blocking questions         │
│ - review_token               │
└──────────────┬───────────────┘
               │ user confirmation
┌──────────────▼───────────────┐
│ Confirmation Store           │
│ - Gate Record                │
│ - SHA/spec/evidence binding  │
│ - HMAC token                 │
└──────────────┬───────────────┘
               │
┌──────────────▼───────────────┐
│ Gate Validator               │
│ - validate_gate              │
│ - require_confirmed_gate     │
└──────────────┬───────────────┘
               │
┌──────────────▼─────────────────────────────────────────────┐
│ execute_fill_plan / execute_repair_plan /                  │
│ execute_review_plan / execute_reformat_plan / legacy CLI   │
└────────────────────────────────────────────────────────────┘
```

组件职责：

- **Template Analyzer**：只读取模板与补充材料，输出证据；不写文档。
- **Evidence Registry**：唯一证据存储与查询；禁止自然语言结论替代结构化证据。
- **Validation Engine**：把证据状态 + 任务相关性转成 blocking 清单。
- **Analysis Report**：用户可读报告与确认提示；不改变证据。
- **Confirmation Store**：持久化 Gate Record；不解释业务内容。
- **Gate Validator**：只做校验，不修复、不猜测；失败即拒绝。
- **执行器**：保持现有逻辑；gate 只在其入口增加一次强制检查。

插入点优先级（侵入性从低到高）：

1. `execute_*` 函数入口（必须）。
2. 旧 CLI 写路径入口（必须）。
3. `DocumentTransaction` 二次门禁（可选加固，不替代 1）。

---

## G. 契约影响分析

### G.1 冻结契约

| 契约 | 结论 | 说明 |
|---|---|---|
| 01 Slot ID | 直接复用 | 证据定位使用现有 `location_id`/`slot_id` |
| 02 DocumentSpec 4.0 | 直接复用，**不修改** | `slots/protected_regions/warnings/errors/unsupported_features/fingerprint_ref` 作为证据源；`additionalProperties: false` 禁止新增字段 |
| 03 ContentPlan/FillPlan | 直接复用，**不修改** | gate 在 FillPlan 执行前，不改变计划结构 |
| 04 QAReport 4.0 | 直接复用，**不修改** | gate 失败发生在 QA 前；QA 四态不变 |
| 05 ToolEnvelope/错误码 | **增量扩展** | 新增 7 个错误码，只增不改；新增码需 registry + 契约变更记录 |

### G.2 新增独立契约

`contracts/06-template-understanding-gate.md`，版本 1.0.0：

- 证据四态与来源规则。
- Gate 状态机与非法跳转。
- Gate Record 字段、绑定与失效。
- 任务类型矩阵与阻断规则。
- Analysis Report 结构。
- Gate Validation 顺序与错误码。
- 执行入口接入要求。
- 版本与兼容性。

### G.3 Schema

- `schemas/template_evidence-1.0.schema.json`
- `schemas/template_gate_record-1.0.schema.json`
- `schemas/template_analysis_report-1.0.schema.json`

### G.4 错误码映射

| 场景 | 错误码 | 现有等价码？ |
|---|---|---|
| 无 Gate Record | `TEMPLATE_GATE_REQUIRED` | 无 |
| 状态 BLOCKED/WAITING/READY/REJECTED | `TEMPLATE_GATE_BLOCKED` | 无 |
| 模板/Spec/证据/版本/任务类型失配 | `TEMPLATE_GATE_STALE` | `TEMPLATE_SHA_MISMATCH` 仅覆盖字节，不复用 |
| 未确认/token 无效 | `TEMPLATE_GATE_CONFIRMATION_REQUIRED` | 无 |
| 证据冲突 | `TEMPLATE_EVIDENCE_CONFLICT` | 无 |
| 未解决阻断项 | `TEMPLATE_EVIDENCE_INCOMPLETE` | 无 |
| 非法状态跳转 | `TEMPLATE_GATE_ILLEGAL_TRANSITION` | 无 |

### G.5 向后兼容

- 契约 01–05、Schema、现有 CLI 默认值、v3.5.9 行为保持不变。
- 新增契约/错误码为 MINOR 加法；契约集 4.2.0 → 4.3.0，软件版本 W4-9 → 4.1.0。
- W4 闸门会改变 gated 模式“无确认即可执行”的默认行为；这是 W4 的目标行为，需在 ADR/契约 06 中明确，不属于静默破坏。
- 非 gated 模式（PROOFREAD、EXCEL_GENERATE、POLISH、MERGE、RENDER）不变。

---

## H. 测试设计

| # | 场景 | 测试文件 | 断言 |
|---|---|---|---|
| 1 | 标准模板完整解析 | `tests/test_template_evidence.py` | 证据齐全、blocking=0 |
| 2 | 字体冲突 | 同上 | `CONFLICT` + blocking |
| 3 | 表格用途不明确 | 同上 | `AMBIGUOUS` + blocking |
| 4 | 红色填写说明 | 同上 | `AMBIGUOUS`，非显式 token 不 VERIFIED |
| 5 | 复杂图片 | 同上 | 角色 `UNVERIFIED`；未计划替换非阻断 |
| 6 | 浮动文本框 | 同上 | 不可定位；被触达才阻断 |
| 7 | SDT | 同上 | `PROTECTED`、`sdt_edit=false` |
| 8 | 公式/OLE | 同上 | 保护保留；编辑请求阻断 |
| 9 | 用户补充参考文档 | `tests/test_template_gate_incremental.py` | 受影响证据 VERIFIED |
| 10 | 用户直接回答 | 同上 | `user_answer` + VERIFIED |
| 11 | 用户选择保留原样 | 同上 | 安全降级；不安全仍阻断 |
| 12 | 用户拒绝补充 | 同上 | 仍 BLOCKED |
| 13 | 用户确认 | `tests/test_template_gate_validator.py` | CONFIRMED + 校验通过 |
| 14 | 未确认直接生成 | `tests/test_template_gate_enforcement.py` | `TEMPLATE_GATE_REQUIRED` |
| 15 | 确认后替换模板 | `tests/test_template_gate_validator.py` | `TEMPLATE_GATE_STALE` |
| 16 | 确认后修改模板 | 同上 | `TEMPLATE_GATE_STALE` |
| 17 | 确认后 Spec 变化 | 同上 | `TEMPLATE_GATE_STALE` |
| 18 | 确认后任务类型变化 | 同上 | `TEMPLATE_GATE_STALE/REQUIRED` |
| 19 | 补充材料与原证据冲突 | `tests/test_template_gate_incremental.py` | `TEMPLATE_EVIDENCE_CONFLICT` |
| 20 | 未知但无关 OOXML 保留 | `test_template_evidence.py` / `enforcement` | 非阻断，披露后执行 |
| 21 | 旧版 CLI 绕过 | `tests/test_template_gate_enforcement.py` | 被拒绝 |
| 22 | Gate Record 篡改/过期 | `tests/test_template_gate_store.py` | token/时效失败 |
| 23 | Python API 直接调用 | `tests/test_template_gate_enforcement.py` | 被拒绝 |
| 24 | 非模板任务不误阻断 | 同上 | PROOFREAD/EXCEL/RENDER 正常 |
| 25 | 证据摘要确定性 | `tests/test_template_evidence.py` | 重复 digest 相同 |

现有测试迁移：约 13 个文件、50 处 `execute_*` 调用需要预置 gate fixture；使用 `tests/gate_helpers.py`，通过 `OFFICECLI_GATE_HOME` 指向临时目录，不删除任何断言。

---

## I. W4 后续实施路线

### I.1 阶段表

| 阶段 | 目标 | 主要文件 | 依赖 | 测试 | 验收 | 回滚 |
|---|---|---|---|---|---|---|
| W4-1 | Evidence Registry + 四态 | `template_gate/models.py`、`evidence.py`、`analyzer.py`、`config/template-gate-policy.json`、`schemas/template_evidence-1.0.schema.json` | W4-0 | 证据登记/冲突/digest/SDT/红字 | 重复分析 digest 稳定；现有测试不破 | 删除新模块 |
| W4-2 | 状态机 | `template_gate/state.py` | W4-1 | 合法/非法跳转 | 仅 CONFIRMED→EXECUTING 合法 | 删除模块 |
| W4-3 | Analysis Report | `template_gate/report.py`、`scripts/template_gate.py`、Report Schema | W4-1/2 | 报告完整性/阻断清单 | 报告可用户审查 | 删除模块/子命令 |
| W4-4 | 补充材料增量 | `template_gate/supplements.py`、analyzer 扩展 | W4-1/2/3 | 参考文档/回答/保留原样/冲突 | 不盲信材料；冲突阻断 | 回退 analyzer |
| W4-5 | Confirmation Store | `template_gate/store.py`、Gate Record Schema | W4-1/2/3 | 持久化/篡改/过期 | 跨会话可用；不写仓库 | 删除 store |
| W4-6 | Gate Validator | `template_gate/validator.py`、`errors.py`、契约 06 | W4-1/2/5 | 10 类失败码 | 无放行分支 | 删除 validator |
| W4-7 | 执行入口接入 | `fill_executor.py`、`repair_engine.py`、`review_engine.py`、`reformat_engine.py`、4 个 CLI、13 个测试文件 | W4-6 | 绕过/非 gated/回归 | 无记录全部拒绝 | 按入口回退 |
| W4-8 | SKILL 集成 | `SKILL.md`、`references/engine-internals.md` | W4-7 | 文档一致性 | 文档与代码一致 | 文档回滚 |
| W4-9 | E2E/发布 | `tests/test_template_gate_e2e.py`、`reports/acceptance/`、版本文件 | 全部 | 15+ 场景/全量 | 可发布 | 保留证据 |

### I.2 顺序理由

- Evidence 是 Report/Gate 的前置，必须先做。
- 状态机可独立于持久化，先做纯函数，降低 W4-5 复杂度。
- Report 与 CLI 可复用 Evidence/State。
- 补充材料依赖稳定证据模型。
- Store 必须在 Validator 前，否则无法校验持久记录。
- 强制执行必须最后接入，避免中间阶段破坏现有测试。
- SKILL 文档在代码稳定后更新，避免文档先行造成误解。

### I.3 风险

| 风险 | 应对 |
|---|---|
| Python API 绕过 | gate 加在 `execute_*` 内部，不只 CLI |
| 旧 `--data` 绕过 | legacy 路径显式预检 |
| 冻结契约冲突 | 独立契约 06/Schema，不改 DocumentSpec |
| 摘要不稳定 | canonical JSON + 稳定 evidence_id |
| 误阻断 | 任务矩阵 + `task_relevant` + 安全保留 |
| 50 处测试改造 | 共享 `tests/gate_helpers.py`，逐文件迁移，不删断言 |
| 旧 Skill 副本 | W4-8 同步，W4-0 记录 |
| 真实语料隐私 | 不读取语料；只引用 W3 聚合报告 |

### I.4 交付物

1. 本审计报告。
2. 契约 06 + 3 个 Schema。
3. `template_gate/` 实现。
4. `scripts/template_gate.py`。
5. 7 个错误码与 policy config。
6. W4-1..W4-9 测试与 E2E。
7. SKILL.md 更新。
8. 版本 4.1.0 / 契约集 4.3.0 发布证据。

### I.5 最终状态

**PASS**

判定依据：

1. 已核实冻结契约集 4.2.0、软件 4.0.2、产物 schema 4.0。
2. 已读取 W3 任务书、W3 出口评审与独立出口评审。
3. 已完成 20 项模板解析能力审计，并给出实现位置与测试证据。
4. 已完成全部正式执行入口盘点，确认 CLI、Python API、legacy `--data` 均可无确认执行。
5. 已识别确认机制、证据管理、持久化、状态机、错误码的全部缺失点。
6. 已完成契约影响与向后兼容分析，明确冻结契约不修改、新增独立契约 06。
7. 已形成 W4-1～W4-9 可执行路线，含文件、测试、验收与回滚。
8. 全量 479 项测试与 70 项契约测试实测通过；本阶段未修改任何业务代码、契约、Schema、SKILL.md 或测试。

存在但不阻断后续规划的非关键缺口（不影响 PASS）：

- `.trae/skills` 已安装副本为 4.0.0，W4-8 需同步。
- `engine/__init__.py` docstring 版本号过时，W4-9 文档一致性阶段修正。
- `dist/` 历史归档状态与 README 措辞需在发布阶段再对齐。
- 页数/页码规则依赖 PDF 后端，W4-3 报告需按“可验证时”披露。
