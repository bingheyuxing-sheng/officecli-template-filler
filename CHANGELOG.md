# 变更记录

本文件记录 officecli-template-filler 各版本的变更。`dist/` 下附带对应版本的打包文件，可直接下载后作为 Agent Skill 安装。

> 说明：v3.3.1 与 v3.4.0 的打包文件未随仓库提供；仓库中保留的是这两个版本之后的归档。

---

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
