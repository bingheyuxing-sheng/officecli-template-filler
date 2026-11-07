# W5-A 现有架构审计报告 — OfficeCLI 后端集成与架构收敛

- 审计日期：2026-11-06
- 审计对象：`d:\docs\officecli-template-filler`（分支 `main`，HEAD `bd9a2d6`，**含未提交工作树变更**，见 §1.3）
- 审计性质：只读。未修改任何业务代码、契约、Schema、SKILL.md 或测试；OfficeCLI 探针在系统临时目录执行并已清理。
- 审计方法：
  1. OfficeCLI 1.0.160 实测（`officecli --version`、`help` 全量拉取、8 组真实 DOCX/XLSX 探针，见 §2.2）；
  2. Python 实现全量代码审计（`engine/`、`document_engine/`、`template_intelligence/`、`content_intelligence/`、`template_gate/`、`qa/`、`scripts/`，共 3 组并行子审计）；
  3. 以 `reports/development/w4-0-architecture-audit.md` 为基线对照，复核其执行入口清单与模块职责在本审计时点仍然成立；
  4. 对照任务书 W5 强制工程约束 E1–E6 逐项核对现状。
- 后续阶段输入：本报告 §8（目标架构）、§9（不建议迁移清单）、§10（W5-B 实施任务）；全量能力对照见 `w5-capability-matrix.md`。

---

## 1. 项目当前架构

### 1.1 目录结构与模块职责（实测确认）

```text
officecli-template-filler/
├── AGENTS.md / README.md / SKILL.md / CHANGELOG.md
├── contracts/                  # 冻结契约集 4.3.0（01-06 + compatibility-v3.5.9）+ changes/CP-W2-001,002
├── schemas/                    # 4.0 契约 Schema ×7 + legacy 3.0 + gate 三件套 + error registry
├── config/                     # qa-policy / error-codes / package_limits / environment_capabilities / template-gate-policy
├── engine/                     # 30 个模块：OOXML 非破坏修改、表格/图片/样式、Excel、REPAIR/REVIEW/REFORMAT、
│                               #   事务、进程归属、QA 检查器、workflow 策略、officecli_writer（未提交，见 §1.3）
├── template_intelligence/     # DocumentSpec 4.0 生产、slot_id、四类指纹、语义校验
├── content_intelligence/       # ContentPlan/FillPlan 纯函数构建与校验（4 种操作类型，见 §1.4）
├── document_engine/           # execute_fill_plan、FillLedger、pipeline（薄封装）
├── template_gate/             # W4 交付：证据、状态机、确认存储、校验器、analyze/report CLI
├── qa/                         # QAReport 4.0、QA Gate、Pipeline、环境能力探测
├── scripts/                    # 12 个 CLI 入口（Agent 直接编排面）
├── tests/                      # 532 项测试 + contracts/ 70 项 + real_corpus_eval.py（--writer 对比评测）
├── reports/                    # W0–W4 验收证据
└── references/                 # engine-internals / workflow-details / python-docx-engine
```

### 1.2 v4 主数据流（含现有 OfficeCLI 可选后端）

```text
template.docx
  → analyze_template.py --spec-version 4  → DocumentSpec 4.0（slots/protected_regions/capacity/fingerprint_ref）
  → template_gate analyze/report/confirm   → Gate Record（CONFIRMED，绑定 SHA/指纹/证据）
  → ContentPlan 4.0（facts/sections）→ FillPlan 4.0（operations，4 种类型）
  → execute_fill_plan（document_engine/fill_executor.py）
       1. 包配额 → 2. spec/plan/content 校验 → 3. SHA preflight → 4. Gate 校验（TEMPLATE_GATE_*）
       → 5. writer 路由（L1523-1540）：
             writer="officecli" 且全部操作可表达 → _apply_operations_via_officecli
                  copy → officecli batch（原子）→ close → get 读回验证 → close
                  → restore_paragraph_identity（撤销 w14 盖章 + 红字清理）
             否则 → _apply_operations_in_memory（python-docx）
       → 6. QA（_run_qa，基于暂存文件独立执行）
       → 7. DocumentTransaction.record_gate → commit()（二次门禁 + 原子发布）
       → FillLedger（op 级记录，无 backend 字段，见 §6.4）→ ToolEnvelope JSON
```

Legacy 路径：`generate_document.py --data`（L39-119）已接入 Gate（W4-7）与 `DocumentTransaction`，token 替换走 `LogicalParagraphView.replace_all_tokens(strip_red=True)` + `sanitize_ooxml_whitespace_and_pagination` + package/format QA。与主链的差异只在"无 FillPlan 授权模型"，写入/QA/事务已统一。

其他执行引擎（repair/review/reformat）各有独立 mutation 实现，均已在 W4-7 于 `execute_*` 入口内部强制 Gate + 经 `DocumentTransaction` 提交。

### 1.3 工作树状态（审计基线的关键事实）

`git status` 显示 OfficeCLI 写入后端**存在于工作树但尚未提交**：

| 变更 | 状态 | 规模 |
|---|---|---|
| `engine/officecli_writer.py` | **untracked（新文件，407 行）** | binary 发现/版本/location→path/run_batch/get_text/close/validate/restore_paragraph_identity |
| `tests/test_officecli_writer.py` | **untracked（新文件）** | location 映射、batch 执行、restore、validate 的测试 |
| `document_engine/fill_executor.py` | modified | +481/-（writer 路由、`_officecli_operation_plan`、`_apply_operations_via_officecli`） |
| `document_engine/pipeline.py` | modified | +2（`writer` 参数透传） |
| `scripts/generate_document.py` | modified | +4（`--writer` CLI 参数，choices=`python-docx|officecli`，默认 python-docx） |
| `tests/real_corpus_eval.py` | modified | +57（`--writer` 对比评测、fallback bucket 分类） |
| 其余 6 文件（CHANGELOG/SKILL/engine/__init__/references/store/2 tests） | modified | 小幅同步 |

结论：**W5 不是从零接入 OfficeCLI，而是把一个已完成开发、经过 1.0.160 验证、但未提交的"受限可选写入后端"（§3.1）收敛为统一后端适配层的一部分。** 审计以工作树状态为基线。W5-B 动工前应先决定这批变更的提交策略（见 §10 任务 0）。

### 1.4 FillPlan 操作模型（路由的对象）

`content_intelligence/plan_builder.py` L135-148：操作类型共 4 种，由槽位特征决定：

| type | 触发条件 | 现有写入实现 |
|---|---|---|
| `replace_text` | 默认文本槽位 | python 内存 / officecli run-scoped set（受限） |
| `fill_paragraph` | 段落型候选/图片占位 token | 同上 |
| `fill_cell` | `location_id` 含 `.tbl[` | python `fill_cell_strict_style`（9 类结构分类前置）/ officecli 单段落单元格 |
| `replace_image` | 图片槽位 | **仅 python** `image_engine`（不在 `_OFFICECLI_OPERATION_TYPES`） |

FillPlan `global_policy`（L343-348）：`allow_structure_change=false`、`styles=DENY`、`page_setup=DENY` + `DENY_OPERATIONS` 清单——这是后端选型的硬约束。

---

## 2. OfficeCLI 能力审计（1.0.160，实测为准）

### 2.1 命令面

26 个动词。与本项目相关的核心集：

| 命令 | 用途 | 对本项目的意义 |
|---|---|---|
| `get` / `query` / `view` | 读节点 / CSS 选择器批量读 | 读取侧候选（T01 对照） |
| `set` | 属性修改 + **find/replace 模式** | 文本替换核心（已接入） |
| `add` / `remove` / `move` / `swap` | 结构操作 | 主链禁用（STRICT）；`add` 仅可能用于表格行克隆对照 |
| `batch` | JSON 数组原子执行（**失败整体回滚**，`atomicRolledBack`） | 已接入；≠项目级事务（见 E4 说明） |
| `validate` | OpenXML schema 校验 | QA 补充检查项候选（语义 ≠ 包完整性，见 §5.3） |
| `raw` / `raw-set` / `add-part` | 原始 XML 兜底 | **不进入主链**（绕过授权模型的通道，明确排除） |
| `import` | CSV/TSV → xlsx | Excel 侧候选（T09） |
| `merge` | `{{key}}` 模板替换 | 语义与 Legacy `--data` 相近，**无授权/容量/QA 语义，不采纳**（§9.4） |
| `open` / `close` / `save` | resident 进程管理 | 已接入（读后必须 close 释放文件锁） |
| `refresh` | TOC/域重算（Word+Windows） | 与 `assess_toc` 相关，未验证，不依赖 |
| `create` / `dump` / `watch` / `plugins` / `mcp` / `skills` | 辅助 | 不进入主链 |

### 2.2 实测探针记录（探针文件已清理）

| # | 实验 | 结果 | 影响 |
|---|---|---|---|
| P1 | `create` + `batch add`（2 段落 + 2×2 表格） | 成功；`add paragraph style=Heading1` 时 **CLI 自动补建 styles.xml 中缺失的样式定义**（advisory warning） | 对 STRICT 模板是潜在未授权 styles 修改；主链不使用 add，风险登记（§6.6） |
| P2 | run-scoped `set find/replace`（`/body/p[2]/r[1]`） | 替换成功，run 数不变 | 复验 W4 结论：run-scoped set 保结构 |
| P3 | paragraph-scoped `set find/replace`，token 完整位于单 run | 替换成功，**4 个 run 保持 4 个**（`['plain token 42 line','AA','ZZ','BB']`） | **比 fill_executor.py L590 注释声明（"paragraph-scoped set merges the paragraph's runs"）更强**——单 run token 场景 paragraph scope 也保结构。注释声明在跨 run 场景才成立（P4） |
| P4 | paragraph-scoped `set find/replace`，token **跨 run**（runs=`['pre{{','X}}post']`） | 替换成功，但 runs 变为 `['preREPLACED','post']` —— token 覆盖的 runs 被合并进起点 run | CLI 可表达跨 run 替换，但结构语义 = "合并 token 涉及的 runs"；Python `LogicalParagraphView` 保留全部 run 边界的无损替换质量基线更高 → 跨 run 场景保留 Python（对照表 #2） |
| P5 | find/replace scope 非法路径（`/body/p[5]` 不存在时） | 错误信息枚举全部合法 scope：`/`、`/body`、`/body/p[N]`、`/body/p[N]/r[K]`、`/body/tbl[N]`、`/body/tbl[N]/tr[R]/tc[C]`、**`/header[N]`、`/footer[N]`**、CSS selector | **CLI 原生支持页眉页脚与单元格级 find/replace**；现有 `location_to_path`（officecli_writer.py L110-148）的 body-only 限制是保守选择而非 CLI 能力边界 → W5-B 扩展候选 |
| P6 | `validate`（docx/xlsx） | 通过，JSON `success` 结构稳定 | QA 补充检查项可用 |
| P7 | batch 中途失败 | `atomicRolledBack: true`，文件不变 | 原子性确认；同时确认 `create` 拒绝覆盖（`file_exists`） |
| P8 | xlsx `set /Data/A1 value` + `set /Data/B2 value="=A1&..."` + bold/numberformat | 全部成功；`get` 返回 `formula`、`cachedValue`、**`computedValue`、`evaluated: true`** | **CLI 内置公式求值引擎**——与 `recalculate_and_verify_excel_formulas` 的验证语义部分重叠（§5.6）；xlsx cell 写入能力确认（T09） |
| P9 | `close` 行为 | resident 持有期间磁盘文件延迟写；close 后释放 | 现有代码每次 `get_text` 后 close 的模式正确但批量读回效率低（§6.7） |

### 2.3 docx / xlsx 元素面（help 摘要）

- **docx**：paragraph（含 run/bookmark/field/hyperlink/picture/sdt/revision/comment/footnote/endnote/formfield/toc/chart/ole 等子元素）、table（row/cell/column）、header/footer、section、style/styles、numbering、textbox、shape、watermark、markdown、raw。属性覆盖 pPr/rPr 全量（含 CJK：wordWrap/autoSpaceDE-DN/kinsoku/`size.cs`/`font.ea`、markRPr 系列）。
- **xlsx**：cell（comment/hyperlink/run）、row/column/sheet/table/namedrange/conditionalformatting ×10、validation、pivottable、chart、picture、sparkline、slicer、autofilter、pagebreak、raw。
- 属性面结论：**机械属性操作的覆盖广度不是瓶颈**；瓶颈在语义与安全层（授权、结构保护、指纹一致性），这正是 Python 侧的不可替代部分。

---

## 3. Python 实现审计（与 OfficeCLI 相关部分）

### 3.1 现有 OfficeCLI 写入后端（未提交，W5 的直接起点）

`engine/officecli_writer.py`（407 行）+ `fill_executor.py` 路由（L575-920、L1523-1560）：

| 能力 | 位置 | 现状 |
|---|---|---|
| binary 发现 / 版本检测 | L57-95 | `OFFICECLI_BINARY` 覆盖 → `shutil.which` → 候选路径；缺失抛 `OfficecliUnavailable` |
| location → DOM path | L110-148 | **仅 body/tbl/r/c/p**；textbox/sdt/footnote/header/footer 一律 `UnsupportedLocation` |
| 原子 batch | L165-192 | 临时 JSON 文件 + `--input` + `--json`；非零退出码 / `success=false` → `OfficecliError`，**不静默吞错** |
| 读回验证 | L195-217 | `get_text` 后逐 op 校验 token 已消失；每次 get 后强制 `close` |
| w14 盖章撤销 | L294-342 | officecli 对**所有 part** 的段落盖 `w14:paraId/textId` → 以模板为基准恢复或删除；段落数变化即拒绝（`OfficecliError`） |
| 红字清理 | L262-287 | CLI 保留 rPr 原样 → 用 python-docx 二次剥离红占位色（复用 `ooxml_utils._is_red_rgb`） |
| schema 验证 | L230-239 | `officecli validate` 封装，close 后返回 payload |
| 操作翻译 | fill_executor L578-701 | 仅 `replace_text/fill_paragraph/fill_cell`（`_OFFICECLI_OPERATION_TYPES`，L575）；**token 必须在单个直接 run 内唯一**；单元格必须单段落 |
| 路由粒度 | fill_executor L1523-1540 | **文档级全有或全无**：任一操作不满足 → 整文档回退 python-docx，fallback_reason 记入 envelope（`writer_backend`/`writer_fallback`） |
| 失败语义 | fill_executor L839/878/918 | `OFFICECLI_WRITE_FAILED` / `OFFICECLI_READBACK_FAILED` / `OFFICECLI_NORMALIZE_FAILED`；**失败不伪装成功、不静默降级**（符合 E6） |
| 质量基线证据 | tests/test_officecli_writer.py + tests/real_corpus_eval.py（`--writer` 双路评测 + `_fallback_bucket` 六类回退原因统计，L286-299） | 已具备 W5-E 对照测试的部分基础设施 |

### 3.2 Python 文档操作能力分类（3 组子审计汇总）

**结论先行**：`engine/` 的 30 个模块中，与 OfficeCLI 存在**机械操作重叠**的是少数几个写入路径；绝大多数是"业务策略逻辑"（模板理解、授权、结构保护、指纹、修订生命周期、QA 语义），属于任务书定义的核心资产，不具备迁移意义。

| 分类 | 模块 | 与 OfficeCLI 关系 |
|---|---|---|
| **业务策略层（不迁移）** | docx_parser（任务路由/L1-L4 分级）、spec_builder、slot_id、fingerprint、plan_builder/validator、template_gate/*、qa/*（gate/pipeline/report/environment）、workflow（确认 tier/TOC）、transaction（事务/二次门禁）、process_guard、package_guard | OfficeCLI 无对应语义；这些层消费文档而不是改写文档 |
| **非破坏写入引擎（质量基线，不迁移）** | ooxml_utils（LogicalParagraphView 跨 run 无损替换、proofErr/xml:space 保护）、table_engine（9 类单元格结构分类、表格签名/恢复）、style_engine（样式继承链解析、红字清理）、image_engine（共享关系分叉、MIME 匹配、SVG 双嵌、替换后验证）、review_engine（w:ins/w:del 修订生命周期、批注、accept/reject/restore/integrity） | CLI 有元素级对应物，但**语义更弱**：find/replace 会合并 runs（P4）、无结构分类、无关系保护、修订能力未经验证。构成 E3 质量基线 |
| **机械写入路径（与 CLI 重叠，路由候选）** | fill_executor `_apply_operation` 的文本/单元格分支；generate_excel 的 token 替换 + openpyxl 写入；generate_document legacy token 替换 | 已由 writer 路由部分收敛（docx 文本类）；xlsx 未收敛（T09 对照） |
| **纯计算/QA（与文档后端无关）** | ssot_engine、consistency_qa、logic_qa、alignment、layout_qa、qa_engine（包完整性/格式/视觉）、research、chart_render、ocr_engine、pdf_backend | 不是"文档操作后端"问题，不在收敛范围 |

### 3.3 环境能力探测缺口

`qa/environment.py` L30-66 的探测矩阵（7 项：docx_parse/docx_write/wps_pdf_render/pdf_page_analysis/pixel_visual_diff/ocr/chart_render）**完全没有 OfficeCLI 探测项**。当前 `officecli_writer.is_available()` 只在运行时被调用，环境报告对"officecli 存在/版本/能力"不可见——违反项目自身"环境能力必须在运行时检测"（AGENTS.md §9.2）的精神。W5-B 的 Capability Registry 必须补此缺口。

### 3.4 执行入口复验（W4-0 §D 基线 + writer 维度增量）

W4-0 审计的 14 个执行入口清单复验成立（全部写入口已过 Gate + `DocumentTransaction`）。W5 新增维度：**mutation 实现者**。

| 入口 | mutation 实现者 | 现状 |
|---|---|---|
| `execute_fill_plan`（v4 主链） | python-docx 或 **officecli**（`--writer` 选择） | 双后端已接入（未提交） |
| legacy `--data` | python-docx（LogicalParagraphView） | 单后端 |
| `execute_repair_plan` | python-docx（repair_engine） | 单后端 |
| `execute_review_plan`（REVIEW/PROOFREAD） | python-docx（review_engine 修订） | 单后端 |
| `execute_reformat_plan` | python-docx（reformat_engine） | 单后端 |
| `generate_excel` | openpyxl | 单后端 |

---

## 4. 能力对照表（核心行；全量见 `w5-capability-matrix.md`）

图例：officecli_support/maturity —— `FULL`（已完整支持）/ `PARTIAL`（部分支持）/ `WEAK`（支持但达不到质量要求）/ `NONE`（不支持）/ `UNTESTED`（未经真实测试）。migration_status —— `MIGRATED`（已迁移）/ `CANDIDATE`（迁移候选）/ `KEEP_PY`（保留 Python）/ `HYBRID`（混合：策略 Python + 机械操作按路由）。

| # | capability_id | current_implementation | officecli | python_dep | quality_risk | recommended | status |
|---|---|---|---|---|---|---|---|
| 1 | `docx.text.replace_single_run` | fill_executor `_apply_operation` L485（python）+ run-scoped set（officecli） | FULL（P2 实测） | 否 | 低（保结构） | officecli | **MIGRATED**（待提交） |
| 2 | `docx.text.replace_cross_run` | ooxml_utils `LogicalParagraphView.replace_span` | PARTIAL（P4：合并 token 覆盖的 runs） | 否 | **高**（run 边界/proofErr 语义丢失） | python | **KEEP_PY**（E3） |
| 3 | `docx.text.fill_paragraph` | style_engine `fill_paragraph_strict_style`（格式继承+红字） | PARTIAL（保结构但无继承策略/红字剥离） | 是（红字二次处理） | 中（红字残留 → QA `RED_TEXT_RESIDUAL`） | officecli + python 规范化 | **MIGRATED**（受限单 run） |
| 4 | `docx.table.fill_cell` | table_engine `classify_cell_structure`(9 类) + `fill_cell_strict_style` | PARTIAL（单段落单元格；无结构分类） | 是 | **高**（hyperlink/image/sdt/nested 单元格误伤） | HYBRID：officecli 仅收单段落安全单元格 | MIGRATED（受限）/其余 KEEP_PY |
| 5 | `docx.image.replace_by_role` | image_engine（角色匹配/共享分叉/MIME/SVG/验证） | NONE（元素在，语义不在） | — | **高**（共享关系误伤） | python | **KEEP_PY** |
| 6 | `docx.header_footer.text_replace` | ooxml_utils 迭代器（header/footer story） | FULL scope（P5）；现有 writer 未映射 | 否 | 中（需 w14 恢复覆盖 + T06 对照） | officecli | **CANDIDATE**（W5-B 扩展） |
| 7 | `docx.tracked_changes.apply` | review_engine `apply_tracked_replacement`（w:ins/w:del 拆 run） | UNTESTED（revision 元素在，能力面未知） | — | **高**（修订生命周期是交付物本体） | python | **KEEP_PY**（T-对照可选，默认不迁） |
| 8 | `docx.tracked_changes.lifecycle` | review_engine accept/reject/restore/integrity | UNTESTED | — | **高** | python | **KEEP_PY** |
| 9 | `docx.spec.extract`（槽位/保护/容量/指纹） | template_intelligence/spec_builder（2000+ 行语义提取） | NONE（query 只有结构数据，无语义） | — | — | python | **KEEP_PY**（核心资产） |
| 10 | `docx.fingerprint.structural/style/protected/layout` | fingerprint.py + layout_qa | NONE（指纹是项目自有概念） | — | — | python | **KEEP_PY** |
| 11 | `docx.package.integrity_qa` | qa_engine `audit_docx_package_integrity`（关系/dangling rId/重复 ID/MIME） | **互补**（validate 是 schema 校验，P6） | — | — | python + officecli validate 作**新增检查项** | HYBRID（W5-C 候选） |
| 12 | `docx.schema.validate` | （无对应 Python 检查） | FULL | — | — | officecli（新增 QA 检查 `OOXML_SCHEMA_VALIDATION`） | **CANDIDATE** |
| 13 | `xlsx.cell.write`（值/公式/格式） | generate_excel + openpyxl | FULL（P8） | 否 | 低-中（T09 未做） | openpyxl（基线） | **KEEP_PY**（迁移收益低；T09 后重评） |
| 14 | `xlsx.formula.recalc_verify` | excel_engine（openpyxl 计算 + soffice 重算） | PARTIAL（内置求值 `evaluated`，P8） | — | 中（求值语义差异未知） | python 基线 + officecli 交叉验证信号 | HYBRID（T09） |
| 15 | `xlsx.row.clone_with_style_formula_shift` | excel_engine `clone_excel_template_row` | NONE（无行克隆+公式平移+合并/验证扩展语义） | — | **高** | python | **KEEP_PY** |
| 16 | `xlsx.import_csv` | （无现成能力） | FULL | — | — | officecli（若 EXCEL_GENERATE 需要） | CANDIDATE（低优先） |
| 17 | `docx.token.replace_legacy`（--data） | generate_document L69-77 | PARTIAL（`merge` 命令语义相近） | — | **高**（merge 无授权/容量/QA/事务语义，绕过全部门禁） | python | **KEEP_PY**（明确拒绝 merge，§9.4） |
| 18 | `docx.table.row.clone_preserving_format` | table_engine `clone_row_preserving_format` | UNTESTED | — | 中 | python | KEEP_PY |
| 19 | `docx.batch.mutation` | （fill_executor 自组织 batch） | FULL（原子，P7） | — | 低（≠项目事务，仍需 tx/QA） | officecli | MIGRATED（语义边界已定义） |
| 20 | `docx.markdown/structure.add` | （主链禁用结构变更） | FULL | — | — | 不使用（STRICT `allow_structure_change=false`） | N/A |

---

## 5. 重复实现清单（A4）

| # | 重复/重叠 | 双侧证据 | 收敛状态与判定 |
|---|---|---|---|
| 5.1 | **DOCX 文本替换两套实现** | python：`ooxml_utils.LogicalParagraphView`（无损、跨 run、proofErr 保护）；officecli：run-scoped find/replace（保结构、单 run） | **已收敛**（writer 路由 + 质量边界：单 run → officecli，跨 run → python）。W5-B 的工作是把路由从"文档级"细化为"能力组级"并纳入统一 registry |
| 5.2 | **xlsx 单元格写入两套实现** | openpyxl（generate_excel/excel_engine）vs officecli cell set（P8 实测可用） | **未收敛**。判定：openpyxl 为质量基线；CLI 迁移收益低（行克隆/公式平移等核心能力仍需 python），仅 T09 对照 + 公式交叉验证有增量价值 |
| 5.3 | **结构校验两个语义** | `audit_docx_package_integrity`（关系/重复 ID/MIME，项目特有）vs `officecli validate`（OpenXML schema） | **非重复，互补**。CLI validate 应作为新增 QA 检查项而非替换 |
| 5.4 | **token 替换 vs officecli merge** | `--data` legacy 路径（gate+tx+QA 全链）vs `officecli merge`（裸替换） | **语义重叠但不可替换**：merge 缺授权/容量/红字/QA/事务语义，采纳即制造 E6 级别的绕过通道。**明确拒绝** |
| 5.5 | **段落读取** | spec_builder 全量遍历（语义提取：槽位/保护/容量）vs officecli query（结构数据） | **非重复**：DocumentSpec 是语义层，query 是数据层。spec 生产不迁移；T01 仅对照读取保真度 |
| 5.6 | **公式验证** | excel_engine 重算（openpyxl+soffice）vs officecli 内置求值（P8 新发现） | **潜在重复但语义待验证**。作为交叉验证信号有价值（W5-C/T09），不替换基线 |
| 5.7 | **多套 mutation 实现分散** | fill（已双后端）/ repair / review / reformat / excel 五条路径各自持有 python mutation 代码 | 这是**收敛不足**而非"Python vs OfficeCLI"问题：五条路径都过 tx+gate（安全已统一），但 mutation 实现未经过统一后端抽象。W5-C 的 Router 若只覆盖 fill 路径，其余四条保持 python 单后端现状（可接受，见 §9.2） |

---

## 6. 技术债务与风险

| # | 债务/风险 | 证据 | W5 处理建议 |
|---|---|---|---|
| 6.1 | **w14 盖章修补链**：每次 officecli 写入后必须 python-docx 二次处理（`restore_paragraph_identity`：全 part paraId/textId 恢复 + 红字剥离），段落数变化即拒绝 | officecli_writer L294-342 | 保留（这是 CLI 行为代价，不是可谈判项）；W5-B 把它定义清楚为 officecli 后端"提交阶段规范化"，纳入后端职责而非执行器补丁 |
| 6.2 | **文档级全有或全无路由**：一个跨 run token 令整文档回退 python，officecli 采纳率受损 | fill_executor L1530-1538；real_corpus_eval `_fallback_bucket` 已在统计回退原因 | W5-C 路由细化：按"能力组"评估（文本组走 officecli、图片组走 python、串行阶段 + 单一事务），并发禁止不变（E4） |
| 6.3 | **OfficeCLI 版本行为漂移**：P3 实测已证明 fill_executor L590 注释与 1.0.160 现行为不完全一致（paragraph scope 单 run 场景保结构） | §2.2 P3 | 能力注册必须**实测驱动**（probe），帮助文本与注释只作线索；registry 带 `verified` 标志与探测时间戳 |
| 6.4 | **FillLedger 无 op 级 backend 字段**：backend 只在 envelope 文档级（`data.writer_backend`） | fill_ledger.py L51-74（契约 03 §3.8 字段集）；fill_executor L1539 | W5-C 需求"所有操作必须记录执行后端"。实现选项 A：backend 写入 `result` dict（开放结构，非契约变更）；选项 B：契约 03 变更提案（走 §3.2 流程）。**推荐 A** |
| 6.5 | **环境探测缺口**：无 officecli 探测项 | qa/environment.py L30-66 | W5-B 在 capability_registry + environment matrix 增加 `officecli_runtime`（required=false，缺失时按策略降级为 python 后端并显式披露） |
| 6.6 | **CLI 自动补建样式**（P1）：add 段落引用未定义 style 时 CLI 会改 styles.xml | §2.2 P1 | 主链不用 add（STRICT 禁结构变更）；登记为后端契约红线：officecli 后端只允许 `set`/`batch set`/`validate`/`get`/`close` |
| 6.7 | **读回效率**：get 每次即起 resident 又 close | officecli_writer L195-217 | W5-B 封装"open→批量 get→close"读回窗口（仍强制 close，防 QA 锁冲突） |
| 6.8 | **未提交工作树**：590+ 行核心变更无版本控制保护 | §1.3 | W5-B 任务 0：决定提交策略（建议：W4-0 风格的功能分支提交后，W5-B 在其上开新层；不与 W5 变更混在一个提交） |
| 6.9 | **fallback_reason 是自由文本**：6 类 bucket 靠字符串匹配（`_fallback_bucket` L286-299） | real_corpus_eval | W5-C 把回退原因结构化为 registry 的 capability_id + reason code |

---

## 7. 风险分析（迁移风险矩阵）

| 风险 | 等级 | 缓解 |
|---|---|---|
| E3 质量倒退（结构指纹被 CLI 隐性改变 → QA 拒绝或模板保护失效） | 高 | 结构指纹 QA 是天然守门员（W3-9 已证明"授权填充不改变指纹"）；officecli 路径每次写后跑指纹对比；T01-T08 全量对照后才扩能力面 |
| E1 契约侵蚀（为适配 CLI 私改 FillPlan/Ledger 字段） | 高 | FillPlan 不动；Ledger backend 走 result dict 增量；涉及契约 03 字段集变化必须走 CP 流程 |
| E4 双写入者（officecli 与 python 在同任务同文档交替写） | 中 | 设计原则固化：**并发禁止；串行分阶段允许但必须同事务、阶段边界显式 close、Ledger 记录每阶段 backend** |
| E6 虚假成功（CLI 失败被吞、validate 缺失被解释为通过） | 中 | 现有 `OFFICECLI_*_FAILED` 错误链保持 fail-closed；registry 探测失败 = capability 不可用 = 回退 python 并披露，不得标记 PASS |
| CLI 不可用/版本漂移导致任务失败 | 中 | required=false 的 officecli 能力；binary 缺失 → 显式降级披露（`writer_backend=python-docx(fallback: officecli unavailable)`），不阻断任务 |
| resident 锁与 QA/soffice 抢文件 | 中 | 现有"用后即 close"纪律保持；W5-B 统一读回窗口 |

---

## 8. 推荐目标架构（W5-B 输入）

### 8.1 设计原则（从审计导出）

1. **演进而非推翻**：现有 officecli_writer + writer 路由是正确的第一版后端边界（授权/容量/事务/QA 留在执行器，CLI 只做已授权 set），W5-B 把它泛化，不重写引擎。
2. **能力注册实测驱动**：帮助文本不可信（6.3），capability 状态来自 probe 实测 + T01-T10 对照证据，带 `verified` 与探测时间。
3. **路由细化但事务不变**：per-document 单 mutation 后端 → per-能力组串行阶段（文本组/图片组），并发永远禁止；batch 原子性 ≠ DocumentTransaction（E4 明确要求保留事务二次门禁）。
4. **Python 保留的是"质量与语义"不是"历史包袱"**：跨 run 无损替换、9 类单元格分类、修订生命周期、共享图片保护、指纹、QA 全部是 E3 基线，迁移即质量倒退。

### 8.2 目标结构

```text
document_backends/
├── __init__.py            # 公共导出（backend 工厂 + registry 入口）
├── base.py                # DocumentBackend 抽象：capabilities/inspect/get/set/add/remove/batch/validate
│                          #   ——接口按 FillPlan 操作模型设计，不机械照搬 CLI 动词
├── result.py              # BackendResult：success/error_code/backend/before/after/reason_code（结构化回退原因）
├── officecli_backend.py   # 迁移自 engine/officecli_writer.py 并扩展：
│                          #   header/footer location 映射（P5 证据）、单元格直接路径、批量读回窗口、
│                          #   validate 封装、能力 probe、允许动词白名单（set/batch/validate/get/close，见 6.6）
├── python_backend.py      # 薄适配层：包装现有 fill_executor python 分支与各引擎 mutation 入口
│                          #   ——不重写 ooxml_utils/table_engine/style_engine/image_engine
├── capability_registry.py # 实测驱动注册表（json 见任务书 B4 结构）+ qa/environment 集成
└── operation_router.py    # FillPlan operations + registry + policy → 路由决策
                           #   per-能力组阶段划分 + per-op fallback reason_code + 后端选择记录

engine/officecli_writer.py  → 保留为兼容 re-export 层（import 路径不变，test/executor 逐步切换）
document_engine/fill_executor.py → 第 4b 步（L1523）改为调用 operation_router；
                                   _apply_operations_via_officecli 逻辑移入 officecli_backend 的执行阶段
FillLedger → result dict 增量记录 backend（选项 A，§6.4）
qa/environment.py → 新增 officecli_runtime 探测项
```

### 8.3 数据流（目标态）

```text
FillPlan ──► operation_router ──► [阶段1: 文本能力组] ──► officecli_backend ──┐
   │                                  │（能力不足→reason_code 记录）              │
   │                                  └► python_backend（同一能力组整体回退）    │
   │                                                                              ▼
   │                                            阶段边界: close + 规范化(w14恢复/红字)
   │                                [阶段2: 图片能力组] ──► python_backend ───────┤
   │                                                                              ▼
   └──授权与保护检查（不变）────────────────────────────► FillLedger(含 backend) ──► QA ──► Transaction commit
```

（阶段 2 仅在 FillPlan 含 `replace_image` 时存在；同一时刻仅一个写入者，全程单事务。）

### 8.4 W5-D/E 的审计输入

- **W5-D 写入路径统一**：安全链（gate→tx→QA）已在 W4-7 收敛全部入口；剩余分散是 mutation 实现层。主链 fill 路径先接 Router；repair/review/reformat/excel 维持 python 单后端（无重复问题，见 5.7），Legacy `--data` 行为冻结不动。**必须用主链的操作不降低现有质量**——对照测试是唯一证据形式。
- **W5-F 接口收敛**：现有 Agent 面是 12 脚本 ×5 步手动编排（SKILL.md Step1/1.5/2/2A/3/4/5）。目标动词集 `analyze / capabilities / inspect / confirm / execute / verify / status` 与现有脚本映射：analyze=template_gate analyze+report（合并）、confirm=template_gate confirm、execute=按 task_mode 分派现有 5 个执行脚本、verify=run_qa、inspect=inspect_document、capabilities=新增（registry 输出）。SKILL.md 只保留任务识别+安全约束+统一命令+确认规则+references 加载规则。

---

## 9. 不建议迁移的模块及理由

| # | 模块 | 理由 |
|---|---|---|
| 9.1 | `ooxml_utils`（LogicalParagraphView） | 跨 run 无损替换是 E3 质量基线；P4 实测证明 CLI 语义为"合并 token 覆盖的 runs"，run 边界与 proofErr/xml:space 保护丢失 |
| 9.2 | `table_engine` / `style_engine` / `image_engine` / `review_engine` | 9 类单元格结构分类、格式继承链、共享图片关系保护、修订生命周期——全部是"支持但不能满足质量要求"或"完全不支持"的语义层（对照表 #4/5/7/8/18） |
| 9.3 | `template_intelligence` / `content_intelligence` / `template_gate` / `qa` / `transaction` / `workflow` / `process_guard` / `package_guard` | 契约与安全资产（E1/E5）；不是文档操作后端问题 |
| 9.4 | `officecli merge` 命令 | 语义与 Legacy `--data` 相近但**缺授权、容量、红字、QA、事务全部语义**；采纳等于制造绕过门禁的通道，违反 E6 与 AGENTS.md §6.1 |
| 9.5 | `officecli raw / raw-set / add-part` | 绕过 FillPlan 授权模型的原始 XML 通道，与 STRICT 模式根本冲突，禁入主链 |
| 9.6 | `officecli add/remove/move/swap`（docx 结构动词） | FillPlan `allow_structure_change=false`；表格行克隆等结构操作由 table/excel engine 的保护性实现承担 |
| 9.7 | xlsx 写入主体（openpyxl） | CLI 能力确认（P8）但核心能力（行克隆+公式平移+合并扩展+重算验证）CLI 无对应；迁移收益低、回归风险高。保留 openpyxl 为基线，officecli 仅评估交叉验证（T09） |
| 9.8 | REPAIR / REVIEW / REFORMAT 引擎的 mutation | 单后端无重复；质量语义（语义对齐、PrChange、修订）未经对照验证前不动（W5-E 可列远期对照项） |

---

## 10. W5-B 具体实施任务清单（待人工确认后执行）

> 前置任务 0（流程性，先于编码）：**决定未提交工作树的提交策略**（§1.3/6.8）。建议：将现有 officecli writer 变更作为独立功能提交（含其 532+ 基线回归证据），W5-B 在干净基线上开 `document_backends/` 层。

| # | 任务 | 交付物 | 出口条件（对应任务书 §二 B2/W5-B） |
|---|---|---|---|
| B1 | `document_backends/` 骨架：`base.py`（DocumentBackend 抽象，按 FillPlan 操作模型：`capabilities/inspect/get/set/batch/validate`）+ `result.py`（BackendResult + 结构化 reason_code） | 新包 + 单元测试 | 接口评审通过；reason_code 枚举注册进 `config/error-codes.json`（增量） |
| B2 | `officecli_backend.py`：迁移 officecli_writer 全部能力 + 扩展①header/footer location 映射（P5）②单元格直接 scope ③批量读回窗口（open→N×get→close，6.7）④能力 probe（版本 + 关键能力实测：run-scoped set / paragraph 单 run set / cell scope / validate）⑤允许动词白名单（6.6） | `engine/officecli_writer.py` 变兼容 re-export；test_officecli_writer 迁移 | 全部现有 officecli writer 测试通过；probe 结果写入 registry；禁止 add/remove/raw 动词有测试证明 |
| B3 | `python_backend.py`：薄适配层包装 fill_executor python 分支（不重写引擎） | 适配层 + 测试 | 与现有 python 路径输出逐字节等价（同 fixture 双跑对比） |
| B4 | `capability_registry.py` + `qa/environment.py` 探测项（`officecli_runtime`，required=false）+ registry JSON 输出（capability/backend/available/verified/fallback/risk_level） | registry + environment 集成 + `capabilities` 查询入口 | 能力状态全部来自实测（无硬编码 FULL）；officecli 缺失 → 显式降级披露而非阻断 |
| B5 | `operation_router.py` + fill_executor 接入：per-能力组路由（文本组/图片组）、结构化 fallback reason_code、FillLedger result dict 记录 backend（选项 A） | router + executor 改造 + real_corpus_eval 对齐 | 路由决策可解释（每个回退带 reason_code）；532+ 全量回归通过；Ledger op 级 backend 可见 |
| B6 | W5-C 主链集成验证：gate→router→backend→Ledger→QA→tx 全链回归 + W5-D 写入路径审查（legacy 边界确认） | tests/w5/ 集成测试 + W5-D 审查记录 | 不绕过 gate（构造无 gate 任务被拒）；事务二次门禁不变；legacy `--data` 行为冻结证据 |
| B7 | W5-E 真实文档对照测试 T01–T10（`tests/w5/`）：基于 real_corpus_eval `--writer` 框架扩展（T01 读取/T02 段落修改/T03 跨 run/T04 表格单元格/T05 图片/T06 页眉页脚/T07 复杂模板/T08 已有文档修正/T09 xlsx/T10 失败回滚），输出 `w5-test-report.md` | 对照测试套件 + 报告 | 每场景双后端产物对比（XML diff/样式/关系/文本完整性/QA 结论）；未达基线的操作保留 python 并记录证据 |
| B8 | W5-F Agent 接口收敛 + 文档：统一 CLI（§8.4 映射）+ SKILL.md 精简 + `w5-target-architecture.md` / `w5-migration-plan.md` / `w5-final-acceptance.md` | 统一入口 + 文档 | Agent 不再手动编排 12 脚本（工作流文档化验证）；文档与代码状态一致 |

建议执行顺序：0 → B1 → B2 → B4 → B3 → B5 → B6 → B7 → B8（B4 依赖 B2 的 probe；B7 依赖 B5/B6；其余可部分并行）。每个任务遵守 AGENTS.md §14 提交六要素与测试证据要求。

---

## 11. W5-A 出口条件核对（任务书 §十）

| 出口条件 | 结果 | 证据 |
|---|---|---|
| 找到所有主要文档操作入口 | ✅ | §1.2/§3.4（W4-0 §D 复验 + writer/mutation 维度增量） |
| 明确 OfficeCLI 和 Python 的职责重叠 | ✅ | §4 对照表 20 项 + §5 重复清单 7 项 |
| 明确不可迁移能力 | ✅ | §9（8 类，逐项理由） |
| 产出审计报告 | ✅ | 本文件 + `w5-capability-matrix.md` |
| 提出 W5-B 具体实施任务 | ✅ | §10（前置 0 + B1–B8，含出口条件） |

**W5-A 到此完成。按任务书要求，暂停等待人工确认后再进入 W5-B。**
