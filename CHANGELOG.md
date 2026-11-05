# 变更记录

本文件记录 officecli-template-filler 各版本的变更。`dist/` 下保留部分版本的打包归档，可直接下载后作为 Agent Skill 安装（缺失与合并情况见下方说明）。

> 说明：v3.3.1、v3.4.0 与 v3.5.0 的打包文件未随仓库提供；仓库中保留的是这些版本之后的归档。v3.5.6 未单独发包，其内容与 v3.5.7 一同发布。

---

## v4.0.0-dev（未发布开发快照）

> **不是正式发布**：无 Git tag、无 GitHub Release、未 push。软件版本仍以 v3.5.9 引擎为兼容基线；以下内容为 v4.0 增量模块与**契约集 4.2.0**（契约版本 ≠ 软件版本，产物 `schema_version` 仍为 `4.0`）。

### Added（新增）

- `template_intelligence/`：DocumentSpec 4.0 生产器、语义校验器、模板指纹；`--spec-version 4` CLI 入口（默认仍为 3.0 兼容输出）。
- `content_intelligence/`：ContentPlan / FillPlan 生成与校验；事实 `source` 溯源、SSOT 引用、容量冲突 `REJECT`。
- `document_engine/`：FillPlan 执行器（仅写事务暂存路径）、填充台账（fill ledger）、保护/授权/容量前置拒绝。
- `qa/`：QAReport 4.0、QA Gate、完整 QA Pipeline、环境能力运行时探测。
- `contracts/`：五份契约 + CP-W2-001（页眉页脚位置语法，4.1.0）+ CP-W2-002（`sdt` 位置语法与 PROTECTED 发现，4.2.0）；对应 Schema、正反示例、契约测试。
- 六类**结构化回归 Fixtures**（程序化构造，不是真实业务模板）；W3-9 真实语料登记表已建立，二进制尚未获取。
- W3 加固：PDF 临时副本清理、Excel 三级状态溯源、SDT fail-closed 披露与 PROTECTED 发现、ZIP 输入配额、soffice 私有 profile。

### Changed（变更）

- `SKILL.md` / `README.md`：GENERATE 文档主链切到 v4 plan chain（`--spec-version 4` → ContentPlan/FillPlan → `--spec/--plan/--content-plan` → QA/门禁）；`--data` 明确标注为 legacy 兼容路径。
- `analyze_template.py` / `generate_document.py`：增量参数 `--spec-version`、`--spec`、`--plan`、`--content-plan`、`--mode`、`--allow-unverified`；既有默认行为未改变。
- `logic_qa → workflow` 依赖倒置：底层 QA 规则不再依赖具体工作流实现。

### Fixed（修复）

- G-01/G-02（W0 门禁）：COMMIT 与 UNVERIFIED 的矛盾、QA 策略来源可伪造。
- W2 执行层四个缺陷：合并单元格列索引、嵌套表格目标、图片替换残留占位文本、授权图片缩放误报。
- W3 审计修复：P1-01（SDT 静默漏检）、P1-02（默认 GENERATE 走 v3 文档）、P2-01（Excel 渲染器错误覆盖 builtin 状态）、P2-02（PDF 源文件副本残留）、P2-03（ZIP 资源限制缺失）；P2-04 已实施 profile 隔离，最终关闭待审计环境复验。

### Known limitations（已知限制）

- 不宣布 Alpha：W3-9 真实语料尚未获取/脱敏/人工标注；真实与合成指标必须分开报告。
- **不支持 SDT 内填充**：`sdt_edit=false`；SDT 内容只作为 PROTECTED 位置被发现和拒绝。
- 本机环境：WPS PDF 后端可用；PyMuPDF、matplotlib、OCR 缺失，相关检查如实 `UNVERIFIED`。
- P2-01/P2-04 的最终关闭条件依赖审计方 Linux/LibreOffice 环境复跑。

### Tests

- 当前全量：**450 项通过**（186 v3.5.9 基线 + 70 契约 + 141 W1/W2 + 53 W3）；无既有测试删除或弱化。
- Python 3.15；命令：`py -3.15 -m unittest discover -s tests -p "test_*.py"`。

---

## v3.5.9

**主题：按角色定位图片、可选 OCR、图形重绘管线、流程闭环与编排辅助（完成评审剩余 P1/P2 项）**

### 图片入口

- `find_images(doc, role=None)`：遍历全部 story 部件，返回 `role` / `evidence` / `owner_part` / `paragraph_index` / `blip_index` / 像素尺寸 / caption。角色判定基于结构信号：页眉页脚 → `logo`（正方形且主色偏红 → `stamp`）、小尺寸方形灰度正文图 → `qr`、caption 含「示意图/流程图/二维码」→ `illustration`/`qr`、大尺寸正文图 → `illustration`。
- `replace_image_by_role()`：只替换唯一匹配项；匹配到 0 个或多个时抛错并列出全部候选位置，避免静默替换错图。
- 修复：`find_images` 对 `w:hdr`/`w:ftr` 根节点改用 `.//w:p`（`.//w:hdr//w:p` 永远匹配不到根节点，此前页眉图片会被漏掉）。

### 可选 OCR

- 新增 `engine/ocr_engine.py`：依次探测 `rapidocr_onnxruntime` → `paddleocr` → `pytesseract` + `tesseract`，把三种完全不同的返回结构统一成文本。
- `audit_image_text()` 输出 `PLACEHOLDER_TEXT_IN_IMAGE`（medium），覆盖 `***`、`XXXX`、`___`、`待填写`、`示例文本`、`此处插入`；矢量部件记 `VECTOR_IMAGE_OCR_UNSUPPORTED`。
- 无后端时返回 `coverage_gaps: ["OCR_UNAVAILABLE"]` 且 `unverified_count: 1`，不谎报通过。
- `run_qa.py --ocr` 显式启用该段；默认不执行，避免无谓依赖。

### 图形重绘

- 新增 `engine/chart_render.py`：`render_chart_image(spec, out_path)` 支持 `table` / `bar` / `pie`，200 dpi 输出 PNG，可接 `replace_image_by_role()` 走标准替换通道（共享引用与 MIME 规则依然生效）。
- 显式状态而非坏图：`INVALID_SPEC`、`RENDER_BACKEND_UNAVAILABLE`（无 matplotlib）、`CJK_FONT_UNAVAILABLE`（中文标签但无 CJK 字体）。只有 `RENDERED` 才产生文件。

### 文档结构

- `SKILL.md` 拆分：引擎实现细节与逐版本演进移入 `references/engine-internals.md`，主文件保留路由、工作流、QA 门禁与图片操作指引。体积 64.7KB → 约 41KB，Agent 上下文开销明显下降。
- 新增 Step 3A「Working with pictures」：按角色定位、OCR 启用方式、图形重绘的降级处理。

### 流程闭环与引擎缺口

- `MUST_ASK_USER`：`extract_document_spec()` 识别空白内部事实字段（负责人、联系电话、编号等），产出 `internal_fact` 槽位，确认门不再拿不到数据源。
- `REVIEW`：`build_review_plan(auto_text_diff=True)` 自动生成模板↔草稿文字修订；跳过占位符、红字、空内部事实字段与 SDT/域/超链接/图片容器。`review_document.py` 默认开启，`--no-auto-text-diff` 关闭。
- `PROOFREAD`：`audit_proofread_candidates()` / `build_proofread_plan()` 把内容冲突、错别字、重复标题与逻辑检查写成批注；`--no-auto-check` 关闭。批注可锚定段落、页眉页脚与表格单元格。
- `SSOT`：`SSOTValidationError` 携带 `code / metric / locations / values` 与 `as_dict()`。
- 包完整性：新增 `w:proofErr` 配对检查 `PACKAGE_PROOFERR_UNBALANCED`（medium）。
- 文件锁：`OUTPUT_FILE_LOCKED.lock_info.cleanup_log` 指向当前任务的清理日志。
- 图形重绘失败结果统一带 `needs_redraw: true`。
- 合计检查支持表头行：首行非数字时跳过表头，不再放弃整列。

### 编排与逻辑辅助

- 新增 `engine/workflow.py`：`resolve_confirmation_gate()`、`resolve_execution_profile()` / `profile_requirements()`、`WorkflowCheckpointStore`、`assess_toc()` / `toc_degradation_chain()`、`run_visual_qa_rounds()`。
- 新增 `engine/logic_qa.py`：重复段落、空章节、编号跳号、日期区间倒挂。
- 新增 `engine/research.py`：研究策略、查询计划、事实来源校验。

### 验证

- 新增 `tests/test_image_roles_ocr_render.py` 11 项：角色分类与证据、按角色过滤、歧义拒绝替换、按角色替换成功、占位模式匹配、无后端缺口、注入 reader 检出占位文字、OCR 未验证态、非法 spec、无渲染后端、无 CJK 字体拒绝出图。
- 新增 `tests/test_doc_gap_closure.py` 13 项、`tests/test_workflow.py` 15 项、`tests/test_research_logic.py` 9 项。
- 全量 **186 项测试通过**。

## v3.5.8

**主题：内容真值与图片真值（修复"假成功/假通过"，补齐评审指出的两个最大盲区）**

### 图片：两处"假成功"已修复

- **SVG 双嵌入残留**：Word 2016+ 插入图标/SVG 时写成 `<a:blip>`（栅格兜底）+ `<asvg:svgBlip>`（真正渲染的 SVG）。旧逻辑只换 `_blob`/`r:embed`，SVG 引用残留，Word 仍显示旧图却报告成功。现在替换时移除 `svgBlip` 扩展（`adjustments: ["svg_fallback_removed"]`），兜底图成为唯一来源。
- **矢量图静默跳过校验**：`verify_docx_images_integrity()` 现在把 SVG/EMF/WMF 记入 `coverage_gaps: VECTOR_IMAGE_UNVERIFIED`，并上抛到 `package_integrity.coverage_gaps` → 整体 `UNVERIFIED`；替换结果携带 `verification: "unverified_vector"`。不再"既不报错也不报缺口"。
- **VML 图片替换**：WPS 页眉 logo、公章、老模板常用 `w:pict` / `v:imagedata`，此前完全不支持。现在走同一套共享引用安全路径（`reference_kind: "vml"`）：独占时原位替换，共享时新建 part 并重绑 `r:id`。
- **引用计数补全**：`count_image_part_references()` 同时统计 `a:blip`、`asvg:svgBlip`、`v:imagedata` 三种引用，避免共享图被误判为独占而破坏其他位置。
- **裁剪框与显示框**：替换时清除 `a:srcRect`（旧裁剪会切掉新图主体）；新增 `fit_mode="fit_image"` 按新图比例重算 `wp:extent`，`preserve_frame`（默认）保留原框并报告。
- **外部链接图片**：`r:link` 不再静默跳过，`EXTERNAL_IMAGE_LINK` 列出所属部件与目标，提示分发会丢图。

### 内容：引擎级一致性校验

- 新增 `engine/consistency_qa.py`，`run_qa.py` 默认执行（`--no-content-qa` 关闭）：
  - `CONTENT_VALUE_CONFLICT`（high）：正文与表格对同一"总计类"标签给出不同数值；
  - `CONTENT_SUBTOTAL_MISMATCH`（high）：表尾合计行 ≠ 上方各行之和（逐列 Decimal 比对）；
  - `CONTENT_LABEL_VALUE_VARIANCE`（medium）：同一非总计标签在正文/跨表出现少量不同值；
  - `CONTENT_TERM_DRIFT`（medium）：名称列中同一实体两种写法（张伟/张玮）；
  - `CONTENT_DATE_FORMAT_MIXED` / `CONTENT_UNIT_STYLE_MIXED`（low）：日期与金额单位写法混用。
- 报告返回 `label_values`（抽取出的 `label → value` 与位置），让"比了什么"可审计。
- `audit_fact_sources()`：SSOT `facts` 缺少 `source` 报 `FACT_SOURCE_MISSING`（high）；`UNVERIFIED` / `MODEL_GENERATED` 计入未验证事实。
- `find_numeric_occurrences()`：PROOFREAD 输出同一数值的全部出现位置与上下文，作为人工判定证据。

### 诚实性修正

- SKILL.md 不再声称可识别"图片内文字"：引擎无 OCR，改为记录 `OCR_UNAVAILABLE`。
- README 已知限制更正：REFORMAT 已有独立入口；补充 OCR、图表重绘、矢量图校验三项真实边界。
- 文档测试数更正为当前值（111 → 138）。

### 验证

- 实测（培养方案样例）：内容 QA 抽取 256 个 `label → value`，命中 0 条误报；示例构造的合计错误与正文/表格冲突均被 high 级捕获。
- 新增 `tests/test_content_and_image_truth.py` 12 项（SVG 双嵌入、引用计数、矢量缺口、VML 替换、裁剪/显示框、合计闭合、正文↔表格冲突、逐行数值不误报、名称漂移、事实溯源、数值出现位置）。全量 **138 项通过**。

## v3.5.7

**主题：REFORMAT 差异清单与带修订应用、WPS/LibreOffice PDF 渲染路径（P1）**

- REFORMAT 执行器：新增 `engine/reformat_engine.py` 与 `scripts/reformat_document.py`。`build_reformat_plan()` 按语义锚点对齐段落/表格，产出结构化差异清单（`current` / `reference_value` / `action` / `reason` / `confidence`）；`execute_reformat_plan()` 只应用 `AUTO_FIX`，每处变更写入 Word 原生格式修订（`w:rPrChange` / `w:pPrChange` / `w:tblPrChange` / `w:trPrChange` / `w:tcPrChange`），人工可逐条接受/拒绝。
- 差异分类：`AUTO_FIX`（匹配且安全）、`REVIEW`（混合 Run / 加粗变化 / 行数漂移）、`KEEP`（新增段落/表格，不与模板硬比）、`UNSUPPORTED`（列数不一致）。plan-only 模式不写任何输出；apply 模式走事务，包完整性 QA 通过且仍有待审项时状态为 `PENDING_HUMAN_REVIEW`。
- 能力注册表：`REFORMAT` 启用（handler `scripts/reformat_document.py`），不再报 `CAPABILITY_NOT_AVAILABLE`；`POLISH` / `MERGE` 仍为声明但禁用。
- PDF 渲染路径：新增 `engine/pdf_backend.py`，自动探测 WPS `kwpsconvert.exe word2pdf`（Windows 优先）与 LibreOffice `soffice`，`OFFICECLI_PDF_BACKEND` 可强制指定。转换在临时副本上进行，避免源文件被预览进程锁定导致失败。
- 页数测量：优先 PyMuPDF，缺失时用 WPS `pdfinfo` 读取真实页数；`run_visual_layout_qa()` 报告 `pdf_backend` / `page_count_source` / `page_count_available`，页数检查无法执行时记 `PDF_PAGE_COUNT_UNVERIFIED` 而非沉默。实测：模板 43 页、成品 81 页，`RENDER_PAGE_COUNT_MISMATCH` 可用（STYLE_GUIDE 下为 medium）。
- WPS 失败显式化：未登录/VIP 缺失返回 `WPS_VIP_REQUIRED`（exit 100/101），写入 `pdf_conversion_errors`，不静默降级。
- 实测（培养方案样例）：差异清单 37 条（29 字体、3 行数、2 表主导字号、1 加粗、1 单元格、1 新表），自动可修 2 条，其余进入 REVIEW/KEEP，均为可读的 current→reference 条目。
- 测试：新增 `tests/test_reformat_and_pdf.py` 7 项（WPS 转换/pdfinfo/VIP 错误/无后端、计划内容、修订写入、plan-only 不落盘），全量 126 项通过。

## v3.5.6

**主题：路由角色化、语义对齐 QA、严重级门禁、字体名归一与文件锁报告（P0 可信度修复）**

- 路由：`.docx` + `.xlsx` 不再无条件判 `MERGE`。生成意图下 `.docx` 为模板、`.xlsx` 记入 `data_sources` 并路由 `GENERATE`；修改意图（按模板修改格式/对齐/改格式）路由 `REFORMAT`；显式合并意图或无意图多源输入才保持 `MERGE`；双 `.docx` + “按模板修复格式”仍为 `REPAIR`。
- 语义对齐：新增 `engine/alignment.py`，段落按文本锚点 + 标题级别匹配，表格按表题 + 首行 + 列数 + 网格几何匹配。未匹配项标为 `NEW_CONTENT` / `NEW_TABLE`，不再拿模板的相邻段落/表格硬比。
- QA 配置：新增 `comparison_profile`（`REPLICA` / `STYLE_GUIDE`）。GENERATE 默认 `STYLE_GUIDE`，REPAIR/REVIEW 用 `REPLICA`；`run_qa.py --profile auto|replica|style-guide --task-mode ...` 会回显实际 profile。
- 误报修复：格式 QA 在 `STYLE_GUIDE` 下跳过全局字号白名单，改为与匹配段落/表格比较；表格单元格样式改为“非空文本样式集合”，空单元格→填内容不再报 `table_cell_font_or_size`；行数不同时跳过行级单元格/行高比较。
- 严重级门禁：只有 `high` 是硬失败；`medium`/`low` 进入 `warnings`，`PASSED` 可带警告；`coverage_gaps` 仍为 `UNVERIFIED`。本次样例的 2209 条 hard failure 降为 0 条硬失败（格式 6 条警告、版面 45 条警告）。
- 字体可用性：中文字体名与 Windows 英文注册名做归一映射（黑体↔SimHei、仿宋↔FangSong、宋体↔SimSun、Courier↔Courier New），修掉“已安装却报缺失”的误报。
- 文件锁：`DocumentTransaction` 捕获 `PermissionError` 返回 `OUTPUT_FILE_LOCKED` + `lock_info.editor_sdk_pids` + 处置提示；`cleanup_editor_sdk.py --kill-pid <pid> --confirm` 校验镜像名与启动时间后只终止该 PID，不做全局 `/IM`。
- 文档：修正 `render_document.py` 的 PDF 能力说明；明确 `RENDER_PDF_NOT_PRODUCED` 需要 LibreOffice；注明 OfficeCLI HTML 预览不处理分节、页数不可信。
- 测试：新增 8 项 P0 回归测试（路由、语义对齐、严重级、字体别名、文件锁），全量 119 项通过。

## v3.5.5

**主题：REVIEW 修订 ID 唯一性与修订感知版面 QA（全链路验证发现并修复）**

- 修订 ID 冲突：当同一段落既有格式修复又有文字修订时，拆分 Run 会把同一个 `w:rPrChange` 的 `w:id` 复制到 prefix / `w:del` / `w:ins` / suffix 副本中，导致 `audit_review_integrity()` 报 `duplicate revision ids`，REVIEW 事务被中止。现在只有第一个副本保留格式修订标记，其余副本剥离，保证每个 `w:id` 唯一。
- 版面 QA 误报：`run_qa.py --review --reference` 将修订拆分后的 Run 数量、批注故事段落计入版面指纹，导致合法 REVIEW 文档被判 `FAILED`。`fingerprint_docx()` 现在按“接受修订后”的视图计数（忽略 `w:del`/`w:moveFrom` 与批注引用），并合并格式相同的相邻 Run；批注故事不参与版面对比。
- 回归测试：新增 REVIEW 格式修订与文字修订同段落的 ID 唯一性测试，以及修订/批注感知的版面指纹测试。
- 功能验证：GENERATE（含负向中止）、REPAIR、REVIEW、PROOFREAD、EXCEL_GENERATE、输入路由、能力拦截、进程清理日志共 20 个端到端场景全部通过。
- 测试：111 项全部通过。

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
