# OfficeCLI Template Filler

> 面向 Word / Excel 模板的文档智能引擎：把「填充模板」做成**可验证、可留痕、可回滚**的工程流程。

给它一个模板和资料，它交出一份格式不走样、内容可审计的文档；给它一份草稿，它交回一份**能用 Word/WPS 修订模式打开、逐条接受或拒绝**的审阅稿。

![Python](https://img.shields.io/badge/Python-3.9%2B-blue)
![Word](https://img.shields.io/badge/Word-.docx-2B579A)
![Excel](https://img.shields.io/badge/Excel-.xlsx%20%2F%20.xlsm-217346)
![License](https://img.shields.io/badge/License-MIT-green)

---

## 为什么需要它

模板填充的失败往往不是「没填上」，而是：

- 字号、字体悄悄偏离模板，肉眼才发现；
- 表格表头底色、垂直居中、列宽、行高丢了，文字检查完全查不出来；
- AI 把「项目总投资 100 万元」改在了错的段落，因为文中有两处相同文字；
- 交付了一个 Markdown 或 JSON 报告，用户却需要一份能逐条确认的 Word 修订稿；
- 明明「已修复」，打开文件却没有任何修改痕迹；
- QA 返回 `passed: true`，但其实根本没渲染、没计算出公式。

这个引擎针对的就是这些问题。核心原则只有一条：**报告为通过，必须是真的通过；无法验证，就明确标注。**

---

## 核心能力

| 能力 | 说明 |
|---|---|
| **8 种任务路由** | `GENERATE` / `POLISH` / `REPAIR` / `REVIEW` / `MERGE` / `REFORMAT` / `EXCEL_GENERATE` / `PROOFREAD`，按输入文件与意图自动分类；尚未实现的 `POLISH` / `MERGE` 返回 `CAPABILITY_NOT_AVAILABLE` |
| **内容真值 QA** | 正文↔表格数值冲突、表内合计闭合、名称拼写漂移、日期/单位写法混用；事实条目强制 `source` 溯源 |
| **图片完整性** | 栅格图 MIME 匹配替换、SVG 双嵌入清理、VML（`w:pict`）图片替换、裁剪框清除、矢量图显式报告未验证 |
| **模板兼容性分级** | `L1`–`L4`：从标准模板到 OLE / SmartArt / Chart / OMML 等只读保护区 |
| **非破坏式改写** | 保留未映射的样式、`<w:proofErr>`、书签、域代码、共享图片 `rId`，不重建整篇文档 |
| **Word 原生修订** | 文字改动写 `<w:ins>` / `<w:del>`，格式改动写 `w:*PrChange`，判断类问题写 `w:comment` |
| **修订生命周期** | `list_revisions()` / `accept_revision()` / `reject_revision()` / `restore_revision()` |
| **表格结构比对** | 列宽、`tblLayout`、边框、单元格边距、表头底纹、垂直对齐、行高、`tcW`、合并拓扑、单元格字体字号 |
| **Decimal SSOT** | 金额、占比、分项求和用 `Decimal` 精确校验，不使用浮点 |
| **诚实 QA** | 四态报告 + `issues` + `coverage_gaps` + `unverified_count` |
| **进程收尾** | 自己启动的 `editor_sdk.exe` 由入口脚本自动清理，不锁定文档，不全局杀进程 |

---

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

可选组件：

- **PyMuPDF**（`pip install pymupdf`）：用于 PDF 页面级差异比对（可选；缺失时页数改用 WPS `pdfinfo`）。
- **WPS Office**（Windows，可选）：`kwpsconvert.exe word2pdf` 提供 PDF 转换、`pdfinfo` 提供真实页数；需要登录 WPS 账号并有 VIP，否则报 `WPS_VIP_REQUIRED`。
- **LibreOffice**（可选，`soffice`）：WPS 缺失时的 PDF 转换后备，也用于 Excel 重算；缺失时相关检查标记为 `UNVERIFIED`。

### 2. 作为 Agent Skill 使用

把本目录放入 skills 目录（如 `~/.claude/skills/officecli-template-filler` 或 Trae 的 skills 路径），Agent 会依据 `SKILL.md` 自动路由任务。

### 3. 直接用 CLI

```bash
# 路由判断：先看输入该走哪个模式
python scripts/inspect_document.py --inputs template.docx --intent "按模板生成"

# 模板填充
python scripts/generate_document.py --template template.docx --data payload.json --out output.docx

# 按模板修复格式（双文档 REPAIR）
python scripts/repair_document.py --reference template.docx --broken broken.docx --out repaired.docx

# 按模板对齐格式（REFORMAT：先看差异清单，再应用为带修订的 .docx）
python scripts/reformat_document.py --reference template.docx --target draft.docx --plan-out plan.json --plan-only
python scripts/reformat_document.py --reference template.docx --target draft.docx --out formatted.docx

# 审阅：输出可在 Word/WPS 中以修订模式打开的 .docx
python scripts/review_document.py --reference template.docx --target draft.docx \
    --revisions revisions.json --out reviewed.docx

# Excel 模板填充（.xlsm 会保留 VBA 工程）
python scripts/generate_excel.py --template book.xlsx --data payload.json --out book_filled.xlsx

# 完整 QA（DOCX 包完整性 + 字体字号 + 表格 + 视觉 + 修订结构）
python scripts/run_qa.py output.docx --reference template.docx --profile style-guide --task-mode GENERATE
```

---

## 任务模式

| 模式 | 输入 | 输出 |
|---|---|---|
| `GENERATE` | 1 个 `.docx` 模板 + 主题/资料 | 填充后的 `.docx` |
| `EXCEL_GENERATE` | 1 个 `.xlsx` / `.xlsm` 模板 + 数据 | 填充后的工作簿（保留公式与宏） |
| `REPAIR` | 参考模板 + 待修复文档（2 个 `.docx`） | 格式对齐、内容不变的 `.docx` |
| `REVIEW` | 参考模板 + 待审文档 | **带修订与批注的 `.docx`**，供人工逐条确认 |
| `PROOFREAD` | 单个 `.docx` | **带修订与批注的 `.docx`**，校对错别字与数据问题 |
| `POLISH` | 单个草稿 | 措辞优化、版式保持（执行入口规划中） |
| `REFORMAT` | 参考模板 + 待调整文档（1–2 个 `.docx`）+ 排版意图 | **格式差异清单 + 带 `w:*PrChange` 修订的 `.docx`**，人工逐条接受/拒绝 |
| `MERGE` | 显式合并/汇总意图，或多个同格式来源 | 汇总文档 |

> `.docx` + `.xlsx` 不再自动判 `MERGE`：生成意图下 `.xlsx` 作为 `data_sources` 数据源，主模式为 `GENERATE`；只有显式合并意图或无意图多源输入才走 `MERGE`。

---

## QA 状态

`scripts/run_qa.py` 返回四种状态，绝不用「没问题」混淆「没检查」：

| 状态 | 含义 | 交付策略 |
|---|---|---|
| `PASSED` | 没有 `high` 级问题；`medium` / `low` 级问题列在 `warnings`，不阻断交付 | 可交付，需向用户说明警告项 |
| `PENDING_HUMAN_REVIEW` | 仅剩有意留给人工的占位项 | 可交付，需说明待确认项 |
| `UNVERIFIED` | 存在无法执行或覆盖不足的检查 | **不得声称通过**，须说明缺口 |
| `FAILED` | 存在 `high` 级问题 | 不可交付 |

报告同时包含：

- `issues`：结构化问题（`code` / `location` / `detail` / `severity`）
- `warnings` / `warning_count`：`medium` / `low` 级建议项
- `comparison_profile`：`STYLE_GUIDE`（生成，按语义锚点对齐）或 `REPLICA`（修复/审核，按模板顺序）
- `alignment`：匹配/新增/删除的段落与表格
- `coverage_gaps`：未能覆盖的检查项
- `unverified_count`：未验证数量

---

## 设计原则

1. **不猜位置**：修订目标优先用 `location_id` 精确定位；多处匹配且未指定 `occurrence` 时**拒绝自动修改**，转为批注请人工确认。
2. **不静默改格式**：`REVIEW` 中每一处格式恢复都会写入 Word 格式修订（`w:rPrChange` / `w:pPrChange` / `w:tblPrChange` / `w:tcPrChange`），人工可逐条接受或拒绝。
3. **不破坏结构**：替换只在连续纯文本 Run 内进行；超链接、内容控件、域代码容器绝不移动位置；含图片/域的 Run 拒绝拆分。
4. **不越界收尾**：只终止本任务记录为启动且身份可验证的进程；任务期间新出现但无法证明归属的进程计入 `unowned_pids`，保持运行，绝不强杀。
5. **不用断言做校验**：所有质量门禁抛出真实异常（`SSOTValidationError` / `QAValidationError`），`python -O` 下依然生效。

---

## 目录结构

```
officecli-template-filler/
├── README.md             # 项目介绍与使用说明
├── CHANGELOG.md          # 版本变更记录
├── SKILL.md              # Agent 使用规范与流程约束
├── engine/               # 核心引擎（OOXML / 表格 / 审阅 / QA / Excel / SSOT）
├── scripts/              # CLI 入口（路由、生成、修复、审阅、QA、渲染、清理）
├── schemas/              # JSON Schema（文档规格 / 修复计划 / QA 报告 / 审阅报告）
├── references/           # 引擎实现参考
├── dist/                 # 历史版本打包文件
└── tests/                # 回归测试
```

---

## 测试

```bash
python -m unittest discover -s tests -p "test_*.py"
```

当前基线：**138 项测试全部通过**（v3.5.8）。

---

## 历史版本

各版本的打包文件发布在 [Releases](https://github.com/bingheyuxing-sheng/officecli-template-filler/releases)，仓库 `dist/` 保留同一份归档；变更细节见 [CHANGELOG.md](CHANGELOG.md)。

| 版本 | 下载 | 要点 |
|---|---|---|
| v3.5.8 | [Release v3.5.8](https://github.com/bingheyuxing-sheng/officecli-template-filler/releases/tag/v3.5.8) | 内容真值 QA（数值冲突/合计闭合/名称漂移）、SVG 双嵌入修复、VML 图片替换、矢量图显式未验证、事实溯源校验 |
| v3.5.7 | [Release v3.5.7](https://github.com/bingheyuxing-sheng/officecli-template-filler/releases/tag/v3.5.7) | REFORMAT 差异清单与带修订应用、WPS/LibreOffice PDF 路径与真实页数测量 |
| v3.5.6 | 已并入 v3.5.7 | 路由角色化（docx+xlsx 数据源不再误判 MERGE）、语义对齐 QA、严重级门禁、字体名归一、文件锁报告 |
| v3.5.5 | [Release v3.5.5](https://github.com/bingheyuxing-sheng/officecli-template-filler/releases/tag/v3.5.5) | REVIEW 修订 ID 唯一性修复、修订/批注感知的版面 QA、全链路功能验证 |
| v3.5.4 | [Release v3.5.4](https://github.com/bingheyuxing-sheng/officecli-template-filler/releases/tag/v3.5.4) | 进程所有权收紧（无 spawn 证明不终止）、GENERATE/REPAIR 事务 QA 补齐、QA 状态诚实性修正 |
| v3.5.3 | [Release v3.5.3](https://github.com/bingheyuxing-sheng/officecli-template-filler/releases/tag/v3.5.3) | FAST/STANDARD/FULL、培养方案语义预检、分阶段检查点、渲染与目录降级（编排层） |
| v3.5.2 | [Release v3.5.2](https://github.com/bingheyuxing-sheng/officecli-template-filler/releases/tag/v3.5.2) | Excel Translator 与对象预检、版面指纹 QA、进程所有权、PROOFREAD、合并安全写入 |
| v3.5.0 | 已并入 v3.5.2 | 事务化交付、修订生命周期与快照、表格签名收紧、能力注册表 |
| v3.4.2 | [Release v3.4.2](https://github.com/bingheyuxing-sheng/officecli-template-filler/releases/tag/v3.4.2) | 修订 ID 真实一致、超链接结构保护、定位防误改、XLSM 保宏、QA 四态 |
| v3.4.1 | [Release v3.4.1-archive](https://github.com/bingheyuxing-sheng/officecli-template-filler/releases/tag/v3.4.1-archive) | 格式修复写入 Word 原生格式修订痕迹 |

---

## 已知限制

- `POLISH` / `MERGE` 目前没有独立执行入口，路由返回 `CAPABILITY_NOT_AVAILABLE`，不再让 Agent 自行挑选脚本。
- 图片内文字不做 OCR：`semantic_preflight` 只能依赖图片标题与周边正文判断占位图，无法识别图内的 `***`/`XXXX`。需要使用 OCR 时请自行抽取后作为文本输入。
- 图表/示意图重绘（`render_chart_image` 类工具）不在引擎内：`FULL` 档的"重绘占位图"是编排层要求，引擎只提供替换通道。
- SVG/EMF/WMF 等矢量图无法字节级校验，替换后只能报告 `VECTOR_IMAGE_UNVERIFIED`，渲染结果需人工或 PDF 比对确认。
- Excel 的 ActiveX、Power Query、透视表、切片器等复杂对象不会被 `openpyxl` 保留：`inspect_excel_objects()` 会预检，`generate_excel.py` 默认以 `OBJECT_LOSS_RISK` 拒绝执行，需显式加 `--allow-object-loss`。
- 版面 QA 使用 DOCX 版面指纹（字体、字号、对齐、缩进、表格列宽、图片比例），不承诺逐像素一致；像素级比对仍需本机 LibreOffice + PyMuPDF。
- 进程清理只终止能证明归属的实例；读取不到进程创建时间时记入 `unreleased_pids`，不做猜测性终止。
- 视觉 QA 依赖本机 PDF 后端：优先 WPS `kwpsconvert word2pdf` + `pdfinfo`，其次 LibreOffice；两者都没有时状态为 `UNVERIFIED`，不是通过。像素级页面比对仍需 PyMuPDF。
- 不承诺与 Word/WPS 逐像素一致；`L4` 对象只做只读保留并在 `coverage_gaps` 中列明。

---

## 路线图

v3.5 聚焦「让报告成功等于真的完成」：事务化交付（Preflight → Execute → Verify → Commit）、Excel 公式与对象可靠性、结构化版面 QA、Windows 进程所有权、单文档校对模式。

---

## License

本项目采用 [MIT License](LICENSE)，可自由使用、修改、分发与商用，需保留版权声明与许可声明。
