# W5 能力对照表（Capability Matrix）

- 生成日期：2026-11-06（W5-A 审计阶段产物）
- OfficeCLI 基线：1.0.160（实测，探针证据 P1–P9 见 `w5-architecture-audit.md` §2.2）
- 代码基线：main @ `bd9a2d6` + 未提交工作树（OfficeCLI writer 后端，见审计报告 §1.3）
- 使用规则：本表的 `officecli_support/available/verified` 状态**只允许来自实测证据**（探针 P1–P9、W4 期 test_officecli_writer 验证、未来 W5-E 的 T01–T10 对照结果）。帮助文本与注释只能作为线索，不得直接作为 `verified=true` 依据。

## 字段定义

| 字段 | 说明 |
|---|---|
| capability_id | 能力唯一标识（`格式.对象.操作` 命名空间） |
| current_implementation | 当前实现位置（模块/函数/行） |
| officecli_support | OfficeCLI 是否支持：`FULL` / `PARTIAL` / `WEAK`（支持但达不到质量要求）/ `NONE` / `UNTESTED` |
| officecli_maturity | 实际支持程度与证据（探针编号/测试/帮助推断——推断必须标注） |
| python_dependency | 迁移后是否仍依赖 Python（策略层/规范化/回退） |
| quality_risk | 迁移可能造成的质量/安全风险（低/中/高 + 一句话） |
| recommended_backend | 推荐执行后端：`officecli` / `python` / `hybrid`（注明分工）/ `not-applicable` |
| migration_status | `MIGRATED`（已迁移，待提交）/ `CANDIDATE`（候选，W5-E 对照后决定）/ `KEEP_PY`（保留 Python）/ `N/A` |
| evidence | 证据来源（P# 实测 / 测试文件 / W4-0 报告 / help 推断） |

## A. DOCX 文本与段落

| capability_id | current_implementation | officecli_support | officecli_maturity | python_dependency | quality_risk | recommended_backend | migration_status | evidence |
|---|---|---|---|---|---|---|---|---|
| docx.text.replace_single_run | fill_executor `_apply_operation`（python 分支）+ run-scoped set（officecli 分支，L689-699） | FULL | 高：P2 实测保结构；test_officecli_writer 验证 | 否 | 低：run-scoped set 保留 run 顺序/格式 | officecli | **MIGRATED**（未提交） | P2；test_officecli_writer.py |
| docx.text.replace_cross_run | ooxml_utils `LogicalParagraphView.replace_span` | PARTIAL | P4 实测：可替换但合并 token 覆盖的 runs（`['pre{{','X}}post']`→`['preREPLACED','post']`） | — | **高**：run 边界、proofErr、xml:space 语义丢失；结构指纹可能变化 | python | **KEEP_PY**（E3 基线） | P4 |
| docx.text.replace_multi_occurrence | LogicalParagraphView（occurrence 定位，fill_executor `_find_occurrence` L292） | WEAK | find/replace 替换 scope 内全部匹配（fill_executor L652 已知并拒绝） | — | 高：一次性替换全部出现，破坏 occurrence 授权语义 | python | KEEP_PY | fill_executor L652-657 |
| docx.text.fill_paragraph（格式继承+红字清理） | style_engine `fill_paragraph_strict_style` + `normalize_rPr_fonts_and_strip_red` | PARTIAL | set 保 rPr 原样 → 红色占位符残留，需 python 二次剥离 | **是**（红字规范化 `_strip_red_on_runs`） | 中：红字残留触发 QA `RED_TEXT_RESIDUAL`；继承策略缺失 | hybrid：officecli 执行 + python 规范化 | **MIGRATED**（单 run 受限） | officecli_writer L262-287 |
| docx.text.replace_nested_run（textbox/sdt/field 内） | LogicalParagraphView（跨 story 迭代） | NONE | location_to_path 拒绝（L133-139）；P5 scope 枚举无嵌套容器 | — | — | python | KEEP_PY | officecli_writer L110-148 |
| docx.header_footer.text_replace | ooxml_utils header/footer story 迭代器（legacy --data 路径使用） | FULL（scope） | P5：find/replace scope 原生含 `/header[N]`、`/footer[N]`；w14 恢复逻辑已覆盖全部 part | 部分（paraId 恢复） | 中：多 part 位置映射与 CP-W2-001 语法对齐需扩展；未对照测试 | officecli（W5-B 扩展后） | **CANDIDATE**（T06） | P5；officecli_writer L294-342 |
| docx.paragraph.read（结构与文本） | spec_builder 段落遍历 + ooxml_utils 迭代器 | FULL（读取） | P2/P3：get 返回 text/style/effective.*/children 树 | — | 低（读取无破坏） | python（语义提取）/officecli（诊断读取） | 拆分：spec 生产 KEEP_PY；诊断读取 CANDIDATE（T01） | §2.2 P2/P3 |
| docx.paragraph.style_autocreate（add 引用未定义样式） | —（Python 无此行为；STRICT 禁改 styles part） | WEAK（副作用） | P1：CLI add 自动补建样式定义（advisory） | — | **高**（对模板是未授权 styles 修改） | 禁用（后端动词白名单排除 add） | N/A | P1 |

## B. DOCX 表格

| capability_id | current_implementation | officecli_support | officecli_maturity | python_dependency | quality_risk | recommended_backend | migration_status | evidence |
|---|---|---|---|---|---|---|---|---|
| docx.table.fill_cell（单段落安全单元格） | table_engine `classify_cell_structure`(9 类) 前置 + `fill_cell_strict_style`；officecli 分支限单段落（L633-644） | PARTIAL | P5：cell scope `/body/tbl[N]/tr[R]/tc[C]` 原生支持 | **是**（9 类分类仍是 python 安全前置） | 中：无分类直接写有误伤 hyperlink/image/sdt/nested 风险 | hybrid：python 分类 + officecli 写安全子集 | **MIGRATED**（受限单段落） | fill_executor L633-644 |
| docx.table.fill_cell（多段落/复杂单元格） | `fill_cell_strict_style` | NONE | officecli 分支显式拒绝（多段落 cell） | — | 高：双后端语义分歧已由 fallback 规避 | python | KEEP_PY | fill_executor L637-644 |
| docx.table.row.clone_preserving_format | table_engine `clone_row_preserving_format` | UNTESTED | CLI 有 add table-row/set，但无"克隆+保格式+签名恢复"对照 | — | 中-高：未对照 | python（除非 T 系列证明） | KEEP_PY | engine/table_engine.py |
| docx.table.style_signature/restore | `table_style_signature` / `restore_table_style_from_reference` | NONE | 指纹/恢复是项目自有语义 | — | — | python | KEEP_PY | table_engine L152-258 |

## C. DOCX 图片与资源

| capability_id | current_implementation | officecli_support | officecli_maturity | python_dependency | quality_risk | recommended_backend | migration_status | evidence |
|---|---|---|---|---|---|---|---|---|
| docx.image.replace_by_role | image_engine `replace_image_by_role`/`replace_inline_image_in_paragraph`（角色匹配/共享分叉/MIME/SVG/裁剪/验证） | NONE（语义） | CLI 有 picture 元素（help），但无角色匹配、无共享关系保护 | — | **高**：误伤共享关系即破坏模板 | python | **KEEP_PY** | 子审计 #5 |
| docx.image.integrity_verify | `verify_docx_images_integrity` + `count_image_part_references` | NONE | — | — | — | python | KEEP_PY | image_engine |

## D. 修订与批注（REVIEW/PROOFREAD）

| capability_id | current_implementation | officecli_support | officecli_maturity | python_dependency | quality_risk | recommended_backend | migration_status | evidence |
|---|---|---|---|---|---|---|---|---|
| docx.revision.apply_tracked_replacement | review_engine `apply_tracked_replacement` + `_replace_in_run_list`（w:ins/w:del、run 拆分、revision id） | UNTESTED | help 列出 revision/comment 元素；能力面与语义未验证 | — | **高**：修订本身是交付物本体，格式即语义 | python | **KEEP_PY**（可选远期对照） | 子审计 #1；help docx |
| docx.revision.lifecycle（accept/reject/restore/integrity） | review_engine 同名函数 | UNTESTED | — | — | **高** | python | KEEP_PY | review_engine |
| docx.comment.add | `add_paragraph_comment` | UNTESTED | CLI 有 comment 元素 | — | 中 | python | KEEP_PY | review_engine |
| docx.track_changes.toggle | `enable_track_changes`/`is_track_changes_enabled` | UNTESTED | — | — | 中 | python | KEEP_PY | review_engine L84-130 |

## E. 模板理解与计划（语义层）

| capability_id | current_implementation | officecli_support | officecli_maturity | python_dependency | quality_risk | recommended_backend | migration_status | evidence |
|---|---|---|---|---|---|---|---|---|
| docx.spec.extract（slots/protected/capacity/fingerprint） | template_intelligence/spec_builder（~2000 行语义） | NONE | query 只有结构数据，无槽位/保护/容量概念 | — | — | python | **KEEP_PY**（核心资产） | W4-0 §B.1 |
| docx.fingerprint.compute_four_hashes | fingerprint.py | NONE | 项目自有概念 | — | — | python | KEEP_PY | fingerprint.py |
| docx.gate.evidence/state/confirm | template_gate/*（W4 交付） | NONE | — | — | — | python | KEEP_PY | template_gate |
| plan.content/fill.build_validate | content_intelligence/plan_builder、plan_validator | NONE | — | — | — | python | KEEP_PY | plan_builder.py |

## F. Excel（XLSX）

| capability_id | current_implementation | officecli_support | officecli_maturity | python_dependency | quality_risk | recommended_backend | migration_status | evidence |
|---|---|---|---|---|---|---|---|---|
| xlsx.cell.write（value/formula/format/font） | generate_excel + openpyxl | FULL | P8 实测：value/formula/numberformat/bold 全部成功 | 否 | 低-中：批量语义/样式继承未对照 | openpyxl（基线） | **KEEP_PY**（T09 后重评） | P8 |
| xlsx.formula.recalc_verify | excel_engine `recalculate_and_verify_excel_formulas`（openpyxl 计算 + soffice 外算） | PARTIAL | P8：CLI 内置求值（`evaluated/computedValue/cachedValue`） | — | 中：求值器语义/精度差异未知 | python 基线 + officecli 交叉验证信号 | **HYBRID 候选**（T09） | P8 |
| xlsx.row.clone_with_style_formula_shift | excel_engine `clone_excel_template_row` + `shift/translate_excel_formula_row_refs`（含合并/验证/条件格式/表扩展） | NONE | — | — | **高** | python | KEEP_PY | excel_engine |
| xlsx.token.replace（{{key}}/【key】） | generate_excel L45-56（openpyxl） | PARTIAL | `merge` 命令相近但无事务/QA/公式保护语义 | — | 高 | openpyxl | KEEP_PY | scripts/generate_excel.py |
| xlsx.import_csv | —（无现成能力） | FULL | help：`import <file> <parent-path> <source-file>` | — | 低 | officecli（若需要） | CANDIDATE（低优先） | help |

## G. QA / 验证 / 事务 / 环境

| capability_id | current_implementation | officecli_support | officecli_maturity | python_dependency | quality_risk | recommended_backend | migration_status | evidence |
|---|---|---|---|---|---|---|---|---|
| docx.package.integrity_qa（关系/dangling rId/重复 ID/MIME） | qa_engine `audit_docx_package_integrity` | 互补（NONE 直接等价） | officecli validate 是 OpenXML schema 校验（P6），语义不同 | — | — | python（新增 validate 作为补充检查项） | HYBRID | P6 |
| docx.schema.validate | —（无对应 Python 检查） | FULL | P6 实测 | — | 低 | officecli（新增 QA 检查项，fail-closed） | **CANDIDATE**（W5-C） | P6 |
| docx.layout.fingerprint_qa | layout_qa `fingerprint_docx`/`compare` | NONE | 项目自有 | — | — | python | KEEP_PY | layout_qa |
| docx.visual_qa（渲染级） | qa_engine `run_visual_layout_qa` + pdf_backend | NONE | — | — | — | python | KEEP_PY | qa_engine |
| transaction.stage_commit_rollback | engine/transaction（二次门禁/原子发布） | NONE | batch 原子性（P7）≠ 项目事务（QA 绑定/门禁/发布） | — | — | python（**永远**） | KEEP_PY | transaction.py L278-432 |
| environment.officecli_runtime_probe | qa/environment.py（**缺失**） | — | — | — | — | W5-B 新增探测项（required=false） | **GAP→W5-B** | environment.py L30-66 |
| capability.registry（实测驱动注册） | —（缺失；TASK_CAPABILITIES 只有任务模式表） | — | — | — | — | W5-B 新建 `document_backends/capability_registry.py` | **GAP→W5-B** | engine/capabilities.py |
| ledger.op_backend_record | FillLedger（无 backend 字段；envelope 有 writer_backend） | — | — | — | — | result dict 增量记录（非契约变更） | **GAP→W5-C** | fill_ledger.py L51-74 |

## H. 基础设施类（CLI 通道）

| capability_id | current_implementation | officecli_support | officecli_maturity | python_dependency | quality_risk | recommended_backend | migration_status | evidence |
|---|---|---|---|---|---|---|---|---|
| cli.binary_discovery/version | officecli_writer `find_officecli`/`version`（L57-95） | FULL | 实测 1.0.160 | — | 低 | 已实现，迁入 officecli_backend | MIGRATED | §1.3 |
| cli.batch.atomic_mutation | officecli_writer `run_batch`（L165） | FULL | P7 原子回滚确认；`--stop-on-error` 可选 | — | 低（仍需 tx/QA，语义边界已在注释声明） | officecli | MIGRATED | P7 |
| cli.resident.lifecycle | `close`（L219）/get 后强制释放 | FULL | P9 | — | 中（锁冲突风险→纪律化） | officecli_backend 封装统一读回窗口 | MIGRATED（改进项 6.7） | P9 |
| cli.w14_identity_stamp_undo | `restore_paragraph_identity`（L294） | —（CLI 行为代价） | 每次写后必做；段落数变化即拒绝 | **是**（python-docx 规范化） | 中（串行二次处理，定义归属后端提交阶段） | officecli_backend 内置 | MIGRATED | L294-342 |
| cli.merge_command（{{key}} 替换） | — | FULL | help 确认；**拒绝采纳**（无授权/容量/QA/事务语义） | — | **高**（E6 绕过通道） | 禁用 | **REJECTED** | §9.4 |
| cli.raw_xml（raw/raw-set/add-part） | — | FULL | help 确认；**拒绝采纳**（绕过授权模型） | — | **高** | 禁用（动词白名单） | **REJECTED** | §9.5 |
| cli.refresh（域/TOC 重算） | workflow `assess_toc`（自有降级链） | UNTESTED | Word+Windows 限定，未验证 | — | 中 | 不依赖；保持自有 TOC 降级链 | N/A | workflow.py |

## 汇总统计

| 推荐后端 | 能力数 | 说明 |
|---|---|---|
| officecli（MIGRATED） | 5 | 文本单 run 替换、单段落单元格、batch、binary/resident、w14 规范化（全部待提交，§1.3） |
| officecli（CANDIDATE，W5-E 对照后定） | 5 | header/footer 替换（T06）、schema validate 新检查、诊断读取（T01）、xlsx 交叉验证（T09）、CSV import |
| hybrid | 3 | 段落填充（红字规范化）、单元格填充（分类前置）、包完整性+validate 互补 |
| python（KEEP_PY） | 21 | 跨 run 替换、多 occurrence、嵌套容器、图片全量、修订全量、Excel 主体、语义/指纹/QA/事务/门禁 |
| 禁用（REJECTED） | 2 | merge 命令、raw XML 通道 |
| 缺口（W5-B/C 新建） | 3 | officecli 环境探测、capability registry、ledger backend 字段 |

> 本表在 W5-E（T01–T10 真实对照测试）完成后必须逐行更新 `verified` 状态与证据引用；W5-B 实施前任何 `CANDIDATE` 行不得视为既成事实。
