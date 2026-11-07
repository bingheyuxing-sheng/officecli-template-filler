# W3 修复任务书（Remediation Task Book）

- 依据：`reports/development/w3-audit-triage.md`（审计核查裁定）
- 版本基线：契约集 **4.2.0**（W3-4 完成后冻结）；代码 HEAD 含 W0–W2 + W3 修复 + dev 包
- 批准：主智能体；本任务书为 W3 唯一工作清单，未列入项不得顺手实施（AGENTS §5）

## 0. 全局执行规则（含核查方三条约束，均为强制）

| # | 规则 |
|---|---|
| E1 | **SDT 两步走**：先 W3-3（发现即降级 + 披露，禁止 L1 误报），后 W3-4（CP-W2-002 契约扩展）。W3-4 未冻结前，W3-3 的披露行为即为最终防线，不得为等契约而留空 |
| E2 | **宿主机无关测试**：凡涉及 LibreOffice/WPS 的代码路径，验收测试必须用 mock（注入 backend dict / patch `shutil.which` / patch 进程执行），不得把断言建立在测试机是否安装 soffice 上。宿主依赖型旧测试（如 test_excel_reliability 两项）保留不改，作为真机补充验证 |
| E3 | **真实语料必须有标注基线**：W3-9 的每份真实模板须附人工标注（预期槽位、保护区域、格式边界、预期输出、视觉复核结论），否则不得计入准确率/保真率统计 |
| G1 | 单写入者：同一文件被两个任务涉及时按序执行（本任务书已标注冲突对）；同一工作树禁止并发写入（W2-I6 教训） |
| G2 | 每个任务一个 commit；commit 前跑该任务测试 + 全量回归；测试报告记录命令、环境、总数、耗时 |
| G3 | 契约/Schema 变更只走 Change Proposal + Agent 07 审查（AGENTS §3.2）；W3-4、W3-6、W3-8 含 07 强制复核点 |
| G4 | 任何任务不得以“改测试期望”换取通过；失败保留为证据 |

## 1. 任务清单

### W3-1｜PDF 转换临时副本清理（P2-02）

| 项 | 内容 |
|---|---|
| 输入 | `engine/pdf_backend.py:134-160`（已确认缺陷） |
| 修改 | `engine/pdf_backend.py`：`convert_docx_to_pdf` 以 try/finally 保证 `pdf-src-*` 目录在所有返回路径（成功/WPS 失败/LO 失败/UNKNOWN backend）删除；`SOURCE_COPY_FAILED` 分支同样清理。`qa/pipeline.py`、`scripts/render_document.py` 不改（调用方无感知） |
| Owner | Agent 05 |
| 测试 | 新文件 `tests/test_pdf_hygiene.py`（mock backend，E2）：① 成功路径后 out_dir 无 `pdf-src-*`；② 转换失败无残留；③ 复制失败无残留；④ 未知 backend 无残留；⑤ 正常 PDF 产物保留 |
| 验收 | `py -3.15 -m unittest discover -s tests -p "test_pdf_hygiene.py"` + 全量回归 |
| 07 复核 | 不需要（纯缺陷修复，无契约面） |

### W3-2｜Excel 公式状态合并（P2-01）

| 项 | 内容 |
|---|---|
| 输入 | `engine/excel_engine.py:344-435`；审计附录 A2 |
| 修改 | `recalculate_and_verify_excel_formulas`：每公式记录 `builtin_status` / `external_status` / `final_status` 三级溯源。合并矩阵：builtin VERIFIED → VERIFIED（外部分歧只记 detail）；builtin FAILED → FAILED；builtin UNSUPPORTED + 外部可求值 → VERIFIED_EXTERNAL（engine 字段注明）；builtin UNSUPPORTED + 外部 `#NAME?`/错误 → **UNVERIFIED**（保留在 unsupported_formulas 与 unverified_count）；外部无缓存 → NOT_RECALCULATED。外部 FAILED 不得覆盖 builtin UNSUPPORTED |
| Owner | Agent 03（与 W3-5 同文件，须先于 W3-5） |
| 测试 | 新文件 `tests/test_excel_status_merge.py`：patch `shutil.which` 返回伪 soffice + patch `TaskResourceGuard.run_owned_command` + 伪 data_only 工作簿，构造上表 5 组合，断言 final_status 与 unverified_count（E2：本机有/无 soffice 结果一致）。`tests/test_excel_reliability.py` 两项失败测试**不改**，作为真机验证 |
| 验收 | 新测试通过；请求审计方在 LibreOffice 机器复跑该两文件确认转绿 |
| 07 复核 | 不需要（语义修复，QA 状态契约不变） |

### W3-3｜body 级 SDT 发现即披露（P1-01 短期，E1 第一步）

| 项 | 内容 |
|---|---|
| 输入 | 审计附录 A1 复现脚本（可重建）；`template_intelligence/spec_builder.py` |
| 修改 | `spec_builder.py`：新增 body 子树结构预扫描——`w:body` 直接子级 `w:sdt`（含 `w:sdtContent` 内的 `w:p`/`w:tbl`）及 `w:sdt` 包裹表格。命中时：① `template.compatibility` 至少提升为 **L3**（禁止 L1/L2 假评级）；② `unsupported_features += {code: "SDT_BODY_UNSUPPORTED", detail: 计数与首个位置摘要}`；③ `warnings += {code: "SDT_BODY_ENUMERATION_GAP", severity: "high", ...}`。空 SDT（无内容）仅记 low warning。不新增 location、不产出 slots（等 W3-4） |
| Owner | Agent 01 |
| 测试 | 新文件 `tests/test_sdt_detection.py`：① 审计复现结构 → L3 + 两条披露；② 多段 SDT、嵌套 SDT、SDT 内表格各自命中；③ 普通段落内联 `w:sdt`（既有 control_or_field 路径）不重复计数；④ 无 SDT 模板零误报；⑤ spec 仍通过 4.0 Schema 与语义校验 |
| 验收 | 新测试 + `tests/contracts` 70 项 + 全量回归 |
| 07 复核 | 不需要（未触契约；披露码为 DocumentSpec 自由码，W0 冻结报告 §5 允许） |

### W3-4｜CP-W2-002：SDT location 语法与处理策略（E1 第二步）

| 项 | 内容 |
|---|---|
| 输入 | W3-3 已上线的披露行为；`contracts/01-slot-id.md` §3；`engine/ooxml_utils.py` 迭代器 |
| 阶段 A（先行，07 门禁） | 提案 `contracts/changes/CP-W2-002-sdt-location.md`：路径段 `sdt[i]`（容器直接子级序号，含 body/页眉页脚/单元格）；嵌套规则；指纹边界（`w:sdt` 节点入结构哈希）；填充策略——**发现并定位，但 `sdt_edit` 能力保持 false，槽位 `protection_status=PROTECTED`（control_or_field 规则），FillPlan 命中即拒绝（`PROTECTED_SLOT_VIOLATION`）**，直至独立 W4 任务交付可验证的 SDT 内填充。MINOR 版本 4.2.0。Agent 07 审查：提案阶段 **CONDITIONAL_PASS，B1-B4 已折入 rev 2**；实施后二次审查已 **PASS**，4.2.0 冻结 |
| 阶段 B（实施） | `slot_id.py`/两个 Schema location 正则/`ooxml_utils` 迭代器暴露 `body.sdt[i].p[j]`/`spec_builder` 枚举与槽位/`fill_executor` 定位与拒绝路径/`tests/contracts` 语法用例/`examples` 向量/4.2.0 哈希清单 |
| Owner | 阶段 A：05 起草 + 07 审查；阶段 B：01（模板侧）→ 03（执行器侧），串行 |
| 测试 | 语法正反例；SDT 内 token 被枚举为 PROTECTED（control_or_field）槽位；FillPlan 指向该槽位 → `BLOCKED`（`PROTECTED_SLOT_VIOLATION`），模板字节不变；W3-3 的 L3 降级与披露保留为兜底；页眉页脚 story SDT、txbxContent 不抢占、scan_error 保留 high 警告（B1-B3） |
| 验收 | 契约测试 + 全量回归 + 07 复审记录 |
| 07 复核 | **已完成**：提案阶段 CONDITIONAL_PASS（B1–B4 已折入 rev 2），实施后 PASS；4.2.0 已冻结（`07-cp-w2-002-gate-review.md`、`07-cp-w2-002-post-review.md`） |

### W3-5｜soffice profile 隔离与套件稳定性（P2-04）

| 项 | 内容 |
|---|---|
| 输入 | 审计 §2.3 停滞现象；`engine/pdf_backend.py` LibreOffice 分支、`engine/excel_engine.py:398-409` |
| 修改 | 两处 soffice 调用统一追加 `-env:UserInstallation=file:///<每调用独立临时目录>`，避免共享默认配置锁；调用结束后随临时目录回收。保留既有 timeout |
| Owner | Agent 05（pdf_backend，W3-1 后串行）+ 03（excel，W3-2 后串行） |
| 测试 | mock 断言命令数组含 `-env:UserInstallation`（E2）；真机稳定性验证转交审计环境执行 |
| 验收 | 本机能跑通即合入；**最终关闭条件 = 审计方 Linux/LibreOffice 完整套件跑完并留存日志**（G2） |
| 07 复核 | 不需要 |

### W3-6｜Skill 默认 GENERATE 切换 v4（P1-02）

| 项 | 内容 |
|---|---|
| 输入 | `SKILL.md` GENERATE 章节；`scripts/analyze_template.py` 默认值；README 快速开始 |
| 决策（先于改动，07 审查） | **不翻转 `--spec-version` 默认值**（保持 3 以守 §12.2/12.3 兼容面）；改为 SKILL.md 将 GENERATE 主链显式写成：`analyze_template.py --spec-version 4` → DocumentSpec 校验 → Agent 产出 facts/sections → `build_content_plan`/`build_fill_plan` → 校验 → `generate_document.py --spec --plan --content-plan` → QA/门禁。`--data` 路径全文标注 Legacy |
| 修改 | `SKILL.md`、`README.md`；新增 `tests/test_skill_workflow_v4.py`：按 SKILL 步骤序列以 subprocess 走一遍（小型 fixture 模板），断言产物 `schema_version=4.0`、走 executor、非 legacy 键 |
| Owner | 05（文档）+ 02（计划构建指引）+ 03（测试），单 PR |
| 验收 | 新集成测试 + 全量回归；README/SKILL 不再出现“GENERATE 默认走 --payload” |
| 07 复核 | **强制**（默认行为面 + 兼容边界决策） |

### W3-7｜ZIP 输入资源配额（P2-03）

| 项 | 内容 |
|---|---|
| 输入 | `spec_builder.build_document_spec_from_path`、`fill_executor` 模板加载、`analyze_excel_template`/`generate_excel` 入口 |
| 修改 | 新 `engine/package_guard.py`：解析前读 ZIP 中央目录，校验输入字节数、entry 数、单 entry 解压大小、总解压量、压缩比、`word/media/*` 像素总量（Pillow 头部读取）；阈值存 `config/package_limits.json`（新受控文件，05 批准）；超限返回结构化 `PACKAGE_LIMIT_EXCEEDED`（details 记录触限项），不进入解析。仅作用于**用户输入路径**，不作用于本事务暂存产物 |
| Owner | 05（guard+config）+ 06（对抗样本） |
| 测试 | 合成 zip bomb（高压缩比）、超 entry 数、超大单 part、正常模板零误报；CLI 层拒绝含错误码且无半成品 |
| 验收 | 新测试 + 全量回归（既有 fixture 均须通过配额） |
| 07 复核 | 不需要（新增防御，不改既有契约；config 新文件在 PR 中说明） |

### W3-8｜文档与交付一致性（P3-01/02 + 措辞更正）

| 项 | 内容 |
|---|---|
| 修改 | ① 工作区 `AGENTS.md` 复制入仓库根并更新基线段（契约集版本按 W3 推进实况：4.1.0→4.2.0；W1/W2 完成、W3 进行中）；② `CHANGELOG.md` 增 v4.0.0-dev 条目（W0/W1/W2/审计修复，区分契约版本与软件版本）；③ `README.md` v4 章节；④ `reports/acceptance/w2-acceptance.md` 追加“更正记录”节：real-template → 结构化回归 Fixture；补记跨环境未验证；**不改写历史正文**；⑤ 重新打包 skill zip 时包含 AGENTS.md，剔除 dist |
| Owner | 05 |
| 验收 | 包内文件清单核对；文档间版本号一致 |
| 07 复核 | 抽查（措辞更正是否忠实） |

### W3-9｜真实模板语料与标注基线（W3-A，E3）

| 项 | 内容 |
|---|---|
| 输入 | **外部依赖：用户提供的去标识化真实 DOCX**（不同来源/版本 Word/WPS；不得由 Agent 编造或从互联网随意抓取未授权文档） |
| 修改 | `tests/fixtures/real_corpus/<case>/`：`template.docx` + `annotation.json`（人工标注：预期槽位 location+类型、保护区域、格式边界、预期输出摘要、Office 来源与版本）+ `review.md`（人工视觉复核）。评测脚本 `tests/real_corpus_eval.py` 输出：槽位 P/R/F1、漏检率（分结构类别）、未授权差异数（目标 0）、UNVERIFIED 比例、人工介入率。合成与真实两套指标**分开统计，禁止合并**（E3） |
| Owner | 06 建管线；标注由用户提供/确认 |
| 验收 | 语料 ≥ 每来源类别 1 份；评测报告入 `reports/archive/real-corpus-eval.md` |
| 07 复核 | **强制**：W3 出口评审（含全部前 8 项证据） |

## 2. 依赖与执行序

```
W3-1 ─┐
W3-2 ─┼─→ W3-5 ─────────────┐
W3-3 ─→ (07) W3-4A ─→ W3-4B ─┼─→ W3-6(07) ─→ W3-8 ─→ 重打包 → W3-9 ─→ (07) W3 出口评审
W3-7 ─┘
```

- 文件冲突对（必须串行）：`excel_engine.py`（W3-2→W3-5）；`pdf_backend.py`（W3-1→W3-5）；`spec_builder.py`（W3-3→W3-4B）；`SKILL.md`（W3-6→W3-8）。
- 可并行组：{W3-1, W3-2, W3-3, W3-7} 文件互斥，若用多 Agent 须各自隔离工作树，否则按序单树执行。

## 3. W3 出口条件（全部满足才可宣布受控 Alpha）

1. W3-1/2/3/5/7 代码修复完成且测试绿（含 mock 矩阵，E2）；
2. W3-4 契约 4.2.0 冻结（07 两次 PASS）且实施合入，SDT 模板“发现→定位→显式拒绝”闭环；
3. W3-6 默认 GENERATE 走 v4 链，集成测试证明不落回 schema 3；
4. 审计方环境复验：Excel 两测试转绿、完整套件跑完（P2-01/P2-04 关闭条件）；
5. W3-9 真实语料评测报告存在，指标分列合成/真实；
6. AGENTS.md/README/SKILL/CHANGELOG 版本一致，重打包 zip 含清单与 SHA-256；
7. 全量回归 ≥ 当前基线通过，0 项既有测试被删除/弱化；
8. Agent 07 出口评审 PASS（CONDITIONAL_PASS 不得冒充）。
