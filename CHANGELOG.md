# 变更记录

本文件记录 officecli-template-filler 各版本的变更。`dist/` 下附带对应版本的打包文件，可直接下载后作为 Agent Skill 安装。

> 说明：v3.3.1、v3.4.0 与 v3.5.0 的打包文件未随仓库提供；仓库中保留的是这些版本之后的归档。v3.5.4 的源码即当前 `main`。

---

## v3.5.4

**主题：进程所有权收紧、事务 QA 补齐与文档/发布一致性修复**

- 进程所有权：移除“基线差集即所有权”的回退路径。只有通过 `note_spawned()` 记录为本任务启动的 PID 才会被终止；任务运行期间新出现但无法证明归属的进程记入 `unowned_pids` 并保持运行，避免并发任务被误杀。`cleanup_editor_sdk.py --stop` 改为只报告、不终止。
- 事务 QA：`generate_document.py` 在提交前同时运行包完整性 QA 与格式 QA；`repair_document.py` 在包完整性 QA 之外新增“对照参考模板”的格式 QA。事务不再把“只跑了一半检查”的结果报成 `PASSED`。
- QA 状态：`run_qa.py` 在存在无法执行的检查时，即使只有占位残留，也返回 `UNVERIFIED`，不再让 `PENDING_HUMAN_REVIEW` 掩盖覆盖缺口。
- 文档修正：修正不存在的 `classify_template_compatibility()`、README 中错误的 `--target` 参数、`regenerate_unique_ooxml_ids` 导入示例、测试数量与 v3.5.3 编排层范围说明；路由表明确标注 `POLISH`/`MERGE`/`REFORMAT` 无处理器。
- 引擎 API：导出 `regenerate_unique_ooxml_ids()`，修复参考文档示例的 ImportError。
- 测试：109 项全部通过。

## v3.5.3

**主题：执行档位、培养方案语义预检、分阶段检查点与渲染/目录降级（编排层更新）**

- 执行档位：`GENERATE` / `EXCEL_GENERATE` 写入前统一选择 `FAST`、`STANDARD` 或 `FULL`；档位只改变处理范围，不降低 Package QA、SSOT 校验、事务提交和覆盖缺口披露要求。
- 模板语义预检：培养方案任务在写入前检查培养层次、目录与正文标题、跨表课程名称/代码、学分学时、学期数、占位图/样例图及过期目录页码，并输出结构化修复计划。
- 课程 SSOT：要求以单一 `curriculum_ssot` 派生毕业要求、课程矩阵、学分学时分配、学期小计和教学进程表，统一使用 `Decimal` 并在写入前完成跨表校验。
- 分阶段检查点：`STANDARD` / `FULL` 按正文、表格、图片、目录依次保存并验证；失败时从最近的有效检查点恢复，禁止整篇无差别重做。
- 渲染与目录降级：每阶段只允许一次有界渲染；失败后清理任务自有进程并降级到包/OOXML/版面指纹 QA。无法刷新目录域时标记 `PENDING_FIELD_UPDATE`，估算页码必须标记 `ESTIMATED`。
- REVIEW 契约修正：格式修复必须配套 `w:*PrChange`；不支持或结构不安全的修改进入批注或 `manual_required`，不再静默修改。
- 校验示例修正：清理验证改为显式 `RuntimeError`，不使用会被 `python -O` 移除的 `assert`。
- 范围说明：本版本新增的是 Skill 编排规范；相关底层引擎已有能力继续复用，尚无执行入口的编排项不得被描述为已实现的引擎功能。
- 测试：106 项全部通过。

## v3.5.2

**主题：Excel 可靠性、版面指纹、进程所有权、PROOFREAD 与合并安全写入（M4–M9）**

- 公式平移：`translate_excel_formula_row_refs()` 改用 `openpyxl` 官方 `Translator`，字符串常量与跨表引用不再被正则误改；结构化引用、外部工作簿、`INDIRECT`/`OFFSET` 显式返回 `UNSUPPORTED_*`，不做猜测性替换。`clone_excel_template_row()` 返回 `{translated, unsupported}`。
- 公式验证状态：每个公式单元格新增 `formula_status`（`VERIFIED` / `FAILED` / `UNSUPPORTED` / `NOT_RECALCULATED`），`unverified_count` 统计后两类，`run_qa.py` 据此报 `UNVERIFIED` 而非 `PASSED`。
- XLSM 对象预检：新增 `engine/excel_objects.py`，扫描 VBA / ActiveX / Power Query / 透视表 / 切片器 / 外部连接 / 图表等部件；`generate_excel.py` 在存在无法保留的对象时以 `OBJECT_LOSS_RISK`（退出码 3）拒绝生成，需 `--allow-object-loss` 才继续。
- 版面指纹 QA：新增 `engine/layout_qa.py`，按页面、段落、表格、图片比较版面，替换正文不会误报；字号/字体漂移报 `LAYOUT_FONT_DRIFT`，对齐缩进报 `LAYOUT_POSITION_DRIFT`，表格列宽比例差 > 5% 报 `LAYOUT_TABLE_DRIFT`。`run_visual_layout_qa()` 已接入该指纹结果。
- 进程所有权：Windows 通过 `GetProcessTimes` 读取进程创建时间，身份改为 `(pid, image, creation_time)`；`EditorSdkSession` 支持 `spawned_pids` 证明归属，无法证明的候选记入 `unreleased_pids` 而不是强杀；`taskkill` 不再带 `/T`；清理日志按任务拆分（`officecli_editor_sdk_cleanup_<task_id>.json` + 最新汇总）。
- PROOFREAD：新增第 8 种模式与 `scripts/proofread_document.py`，单文档校对输出带修订的 `.docx` 与快照；路由关键词覆盖“错别字 / 校对 / 数据错误 / 逻辑问题 / proofread / typo”，不再落入 REFORMAT。
- 合并拓扑：`restore_table_style_from_reference()` 返回 `{topology_ok, restored, skipped, manual_required}`；仅在行列拓扑一致、合并区域内至多一个非空文本、且不含修订/批注锚点时写入 `gridSpan`/`hMerge`/`vMerge`，否则降级 `manual_required`。
- 字体保真修复：段落格式轮廓优先采用 run 的直接字号（Word 的实际解析顺序），修复“模板 12pt 被写成 11pt”的长期偏差。
- 测试：101 项全部通过。

## v3.5.0

**主题：可验证、可回滚、可解释（M1–M3）**

- 事务化交付：`generate_document` / `generate_excel` / `repair_document` / `review_document` / `render_document` 统一改为 `Preflight → 暂存 → QA → 原子提交`；失败路径不产生最终文件、不留 `.tmp` / `.pending`；输出附带 `transaction`（含 preflight、qa_status、committed、abort_reason、输入/输出 SHA-256）。
- 修订动作事务化：`accept_revision` / `reject_revision` / `restore_revision` 走同一事务；未发生改动时不产出文件（`status: NOT_FOUND`）。
- 格式修订：`w:*PrChange` 按 schema 用 `w:rPr` / `w:pPr` / `w:tblPr` / `w:trPr` / `w:tcPr` 包裹旧属性，支持程序化接受/拒绝；修复「旧属性快照被原地改写导致 reject 无效」的缺陷；`audit_review_integrity()` 新增容器结构与跨部件重复修订 ID 检查。
- 修订快照：REVIEW 同时产出 `<deliverable>.review_snapshot.json`；已接受/已拒绝的修订可由 `restore_revision()` 重建，缺快照返回 `SNAPSHOT_MISSING`，定位失效返回 `LOCATION_LOST`，不猜测位置。
- 表格签名：新增 `row_count`、逐行 `{val, hRule}`、`tblLook`、band size、`tblInd`、`tblCellSpacing`；比较新增 `table_row_count`（仅报告）、>15% 行高漂移、`hRule` 漂移、`tblLook` / band 漂移；修复侧同步 `TBLPR_SYNC_TAGS` 与行高覆盖规则。
- 能力注册表：新增 `engine/capabilities.py`；路由返回 `capability {enabled, handler, reason}`，未实现模式返回 `CAPABILITY_NOT_AVAILABLE`；`.pdf` / `.doc` / `.wps` / `.et` 等输入返回 `UNSUPPORTED_INPUT`，`inspect_document.py` 以退出码 2 表示该判定。
- Excel 输入：新增 `scripts/analyze_excel_template.py` 与 `extract_excel_spec()`，Step 2 按容器类型分流。
- 测试：83 项全部通过。

## v3.4.2

**主题：Review 安全性与 QA 诚实性**

- 修订 ID 修正：`action_results` 中的 `revision_ids` 直接记录 `ids.take()` 的真实分配值，不再由计数器反推，报告 ID 与 DOCX 中的 `w:id` 严格一致。
- 结构安全：跟踪修订只在「连续纯文本 Run 组」内进行，`w:hyperlink` / `w:sdt` / `w:fldSimple` 等容器位置绝不移动；含绘图、域代码、脚注引用的 Run 拒绝拆分，降级为批注。
- 定位安全：支持 `location_id` 精确寻址与 `occurrence` 指定第几处；多处匹配且未指定位置时**拒绝自动修改**，写入 `AMBIGUOUS_MULTIPLE_MATCHES` 批注交由人工判断。
- 表格合并：`gridSpan` / `hMerge` / `vMerge` 仍不自动改写（避免破坏业务内容），但若恢复后仍存在合并差异，动作状态为 `PARTIALLY_APPLIED`，并列出 `unresolved_properties`。
- Excel 宏：`.xlsm` 使用 `keep_vba=True`、`keep_links=True` 加载，强制 `.xlsm` 输出；Excel QA 改为对照**原始模板**，不再拿输出与自己比较。
- Excel 公式：内置评估器无法计算的公式计入 `unsupported_formulas` / `unverified_count`，并产生 `FORMULAS_UNVERIFIED` 覆盖缺口；`SUBTOTAL` 按功能码分派（1=AVERAGE、2=COUNT、4=MAX、5=MIN、9=SUM）。
- QA 状态：`run_qa.py` 新增第四态 `UNVERIFIED`——存在无法执行的检查时，整体状态不再报 `PASSED`。
- 测试：50 项全部通过。

## v3.4.1

**主题：格式修复不再静默**

- REVIEW 恢复格式时同步写入 Word 原生格式修订：`w:rPrChange`、`w:pPrChange`、`w:tblPrChange`、`w:trPrChange`、`w:tcPrChange`，标记内保存修改前的属性，人工可在修订窗格逐条接受或拒绝。
- 新增 `list_format_revisions()`；`audit_review_integrity()` 校验格式修订的 id/作者/日期并返回 `format_revision_count`。
- `execute_review_plan()` 输出 `tracked_format_changes` 与每个动作的 `format_revision_ids`。
- 标记严格按 OOXML schema 顺序插入（段落标记 `w:rPr` 先于 `w:pPrChange`），避免 Word/WPS 打开时触发修复提示。
- REPAIR 仍为直接修复，不写修订痕迹。

## v3.4.0

**主题：表格逐单元格一致性 + 修订生命周期**

- 表格字体字号：新增逐单元格字体/字号指纹与差异（`table_cell_font_or_size`），恢复时复制模板的段落标记与运行字体属性，保留原文内容。
- 逐单元格结构：记录 `tcW` / `gridSpan` / `hMerge` / `vMerge` / `tcMar`，差异精确定位到「表格 / 行 / 列 / 属性」，并写回 `tcW` / `tcMar`。
- 修订生命周期：新增 `list_revisions()`、`accept_revision()`、`reject_revision()`、`restore_revision()`。
- 表格样式档案：`save_table_style_profile()` / `load_table_style_profile()` 将模板表格指纹持久化为 JSON。
- 视觉与字体风险：`run_visual_layout_qa()` 报告 `FONT_NOT_INSTALLED`、`RENDER_PAGE_COUNT_MISMATCH`、`RENDER_PAGE_PIXEL_DIFF`；无法验证时记入 `coverage_gaps`。

## v3.3.1

**主题：REVIEW 交付契约与结构化 QA**

- REVIEW 最终交付物必须是可在 Word/WPS 中以修订模式打开的 `.docx`；Markdown/JSON 只能作为内部中间产物。
- 未定位的文本修订不再静默丢弃，转为 Word 原生批注呈现在文档中。
- QA 支持三态 `PASSED` / `FAILED` / `PENDING_HUMAN_REVIEW`，并输出结构化 `issues`、`coverage_gaps`、`unverified_count`。
- 移除业务校验中的 `assert`，改用 `SSOTValidationError`、`QAValidationError`，确保 `python -O` 下校验依然生效。
