# officecli-template-filler

> 给 Word / Excel 模板自动填内容，尽量不改变原有格式；改完能检查、能留痕、能回滚。

![Python](https://img.shields.io/badge/Python-3.10%2B-blue)
![Word](https://img.shields.io/badge/Word-.docx-2B579A)
![Excel](https://img.shields.io/badge/Excel-.xlsx%20%2F%20.xlsm-217346)
![License](https://img.shields.io/badge/License-MIT-green)

## 项目简介

officecli-template-filler 是一个面向 Word 和 Excel 的文档处理工具，适合“有固定模板、需要反复填内容”的场景。

它和普通的“查找替换”脚本不同：处理之前会先分析模板结构，遇到不确定的地方会要求确认；修改时尽量保留原来的字体、字号、表格、图片、页眉页脚和公式；修改完成后会做一轮检查，检查不了的项会明确写“未验证”，不会把“没检查”说成“没问题”。

一句话概括：**模板不被擅自改变，事实不被编造，失败不被隐藏，检查不可绕过。**

## 这个项目能做什么？

- 根据 Word 模板生成文档：把主题、资料或数据填进模板，输出一份格式基本不变的 `.docx`。
- 按模板修复格式：拿一份格式走样的文档，对照模板把字体、字号、表格样式恢复回来。
- 按模板统一格式：先列出“哪里和模板不一样”，再把能安全修复的地方写成 Word 修订，供你逐条接受或拒绝。
- 审阅并留下修改痕迹：把修改写成 Word 的“修订”和“批注”，在 Word / WPS 里可以逐条确认。
- 校对文档：检查错别字、重复标题、空章节、编号跳号、日期前后矛盾等问题。
- 填 Excel 模板：填充 `.xlsx` / `.xlsm`，尽量保留公式；对可能丢失的宏、透视表、切片器等对象会提前警告。
- 检查文档质量：检查文件结构、字体字号、表格、图片、内容数字和版面，并给出可读的检查报告。
- 处理图片：替换图片时尽量保持引用关系；可以按“logo / 公章 / 二维码 / 插图”等角色查找图片；可选 OCR 读取图片里的文字。
- 生成图表图片：把表格、柱状图、饼图渲染成 PNG，再按普通图片替换流程放进文档。

## 核心功能

| 能力 | 用普通话说 |
|---|---|
| **先理解模板，再动手** | 处理前先分析模板结构，标出需要填写的位置；如果关键内容无法确定，会先要求确认，避免“没看懂就改”。 |
| **识别 8 种任务** | 根据输入文件和你的描述，自动判断是生成、修复、审阅、校对、重排还是 Excel 填充；其中 6 种已有执行入口。 |
| **Word 原生修订** | 文字修改写成 Word 的“插入 / 删除”，格式修改写成 Word 的“格式修订”，判断类问题写成批注，能在 Word / WPS 里逐条接受或拒绝。 |
| **尽量保留原格式** | 不重建整篇文档；未涉及到的样式、书签、域代码、页眉页脚、共享图片关系尽量不动。 |
| **内容一致性检查** | 检查正文和表格的数字是否冲突、分项合计是否等于总数、同一名称是否有两种写法、日期和金额单位是否混用。 |
| **表格结构比对** | 对比列宽、边框、表头底纹、垂直对齐、行高、合并单元格、单元格字体字号。 |
| **金额精确计算** | 金额、占比、分项求和用精确小数计算，减少“差一分钱”的问题。 |
| **Excel 可靠性处理** | 公式平移使用官方解析器；无法计算的公式标为“未验证”；`.xlsm` 尽量保留 VBA 宏；可能丢失对象时默认拒绝执行。 |
| **事务式交付** | 先写临时文件，检查通过后再替换正式文件；失败不会留下半成品。 |
| **诚实的检查报告** | 检查结果分四种状态；没执行、缺依赖或覆盖不足的检查会明确标出来。 |
| **进程收尾** | 只清理本次任务自己启动的进程，不会全局强杀；无法证明归属的进程保持运行。 |

## 适用场景

- 学校、培训机构的培养方案、教学计划、课程表等固定模板文档。
- 企业合同、项目报告、申请表、通知书等需要反复填写的 Word 模板。
- 需要把修改交给别人逐条确认的审阅场景。
- 需要保留公式和宏的 Excel 台账、报价单、统计表。
- 已经有一份“格式正确”的模板，想把另一份草稿的格式对齐过来的场景。

## 使用流程

```text
准备模板和资料
      ↓
识别任务类型（生成 / 修复 / 审阅 / 校对 / 重排 / Excel）
      ↓
分析模板并确认（不确定的地方先问你）
      ↓
生成或修改文档（写入临时文件）
      ↓
自动检查（结构 / 格式 / 内容 / 图片 / 版面）
      ↓
交付 .docx 或 .xlsx（需要时带 Word 修订和批注）
```

几个关键点：

1. **先确认，再修改**：生成、修复、重排、审阅这四类任务，会先检查模板是否已经理解并确认；没有确认记录就不会继续。
2. **修改留痕**：审阅和重排默认输出带修订的文档，不是一份“看不出改了什么”的成品。
3. **检查结果分状态**：通过就是通过，没检查就是没检查，不会混在一起。

## 安装方法

### 环境要求

- Python 3.10 或更高版本（代码使用 `zip(..., strict=)` 等 3.10 语法）。
- Windows 是主要验证平台；Linux / macOS 未在发布验证范围内。PDF 渲染和部分视觉检查依赖本机 WPS / LibreOffice。

### 安装依赖

```bash
python -m pip install -r requirements.txt
```

必需依赖：`python-docx`、`openpyxl`、`lxml`、`Pillow`、`jsonschema`。

### 可选组件

| 组件 | 用途 | 不安装时 |
|---|---|---|
| PyMuPDF | PDF 页面级差异比对 | 页数改用 WPS `pdfinfo`；像素级比对不可用 |
| WPS Office | Word 转 PDF、读取真实页数 | 相关检查标为“未验证” |
| LibreOffice | PDF 转换后备、Excel 重算 | 相关检查标为“未验证” |
| RapidOCR / PaddleOCR / Tesseract | 读取图片里的文字 | OCR 检查标为 `OCR_UNAVAILABLE` |
| matplotlib + 中文字体 | 把表格/柱状图/饼图渲染成图片 | 图表重绘不可用，不会输出乱码图 |

### 作为 Agent Skill 使用

把整个目录放进 Agent 的 skills 目录，例如：

```text
~/.claude/skills/officecli-template-filler
```

或 Trae 对应的 skills 路径。Agent 会根据 `SKILL.md` 自动判断任务类型和操作流程。

## 快速开始

### 1. 先判断该走哪个模式

```bash
python scripts/inspect_document.py --inputs template.docx --intent "按模板生成"
```

### 2. 生成 Word 文档（v4 主链）

```bash
# 分析模板，输出 DocumentSpec
python scripts/analyze_template.py --input template.docx --spec-version 4 --out spec.json

# 由 Agent 或调用方生成 ContentPlan / FillPlan，并先校验
python scripts/generate_document.py --template template.docx --spec spec.json \
  --content-plan content_plan.json --plan fill_plan.json --out output.docx \
  --mode STANDARD --allow-unverified
```

> 旧的 `--data payload.json` 仍然可用，但它是兼容路径，不是 v4 主链。

### 3. 审阅文档并留下修订

```bash
python scripts/review_document.py --reference template.docx --target draft.docx \
  --revisions revisions.json --out reviewed.docx
```

如果检查结果来自 Excel 或 JSON，可以直接转成目标文档里的批注：

```bash
python scripts/review_document.py --target draft.docx --findings findings.json --out reviewed.docx
```

### 4. 修复格式或按模板重排

```bash
# 双文档修复：保留内容，对齐模板格式
python scripts/repair_document.py --reference template.docx --broken broken.docx --out repaired.docx

# 重排：先看差异清单，再写成带修订的文档
python scripts/reformat_document.py --reference template.docx --target draft.docx --plan-out plan.json --plan-only
python scripts/reformat_document.py --reference template.docx --target draft.docx --out formatted.docx
```

### 5. 填充 Excel

```bash
python scripts/generate_excel.py --template book.xlsx --data payload.json --out book_filled.xlsx
```

`.xlsm` 会尽量保留 VBA 工程；如果模板里有 ActiveX、Power Query、透视表、切片器等 `openpyxl` 无法保留的对象，默认会拒绝执行，需要显式加 `--allow-object-loss`。

### 6. 运行完整检查

```bash
python scripts/run_qa.py output.docx --reference template.docx --profile style-guide --task-mode GENERATE
```

## 支持的文档处理任务

| 任务 | 输入 | 输出 | 当前状态 |
|---|---|---|---|
| `GENERATE` | 1 个 `.docx` 模板 + 主题/资料/数据 | 填充后的 `.docx` | 可用 |
| `EXCEL_GENERATE` | 1 个 `.xlsx` / `.xlsm` 模板 + 数据 | 填充后的工作簿 | 可用 |
| `REPAIR` | 参考模板 + 待修复文档 | 格式对齐、内容不变的 `.docx` | 可用 |
| `REVIEW` | 参考模板 + 待审文档，或外部 findings | 带修订和批注的 `.docx` | 可用 |
| `PROOFREAD` | 单个 `.docx` | 带修订和批注的校对稿 | 可用 |
| `REFORMAT` | 参考模板 + 待调整文档 | 格式差异清单 + 带格式修订的 `.docx` | 可用 |
| `POLISH` | 单个草稿 | 措辞优化、版式保持 | 暂未开放 |
| `MERGE` | 多个同格式来源或明确合并意图 | 汇总文档 | 暂未开放 |

补充说明：

- `.docx` + `.xlsx` 不会自动当成“合并”。如果是生成意图，`.docx` 是模板，`.xlsx` 是数据源，主模式仍是 `GENERATE`。
- 双 `.docx` + “按模板修复格式”走 `REPAIR`；单个 `.docx` + “统一字体 / 重新排版”走 `REFORMAT`。
- `POLISH` / `MERGE` 目前没有执行入口，会返回 `CAPABILITY_NOT_AVAILABLE`，不会被悄悄当成别的模式处理。

## 文档检查与质量保障

`scripts/run_qa.py` 的检查结果分四种状态：

| 状态 | 含义 | 能不能交付 |
|---|---|---|
| `PASSED` | 没有高严重度问题；中低严重度问题列在警告里 | 可以交付，但要说明警告项 |
| `PENDING_HUMAN_REVIEW` | 只剩有意留给人工确认的占位项 | 可以交付，但要说明待确认项 |
| `UNVERIFIED` | 有检查没执行，或覆盖不足 | 不能声称“通过”，必须说明缺口 |
| `FAILED` | 存在高严重度问题 | 不能交付 |

检查内容大致包括：

- DOCX 包结构是否完整，图片引用、关系、内容类型是否正常。
- 字体、字号、段落、对齐、缩进、行高、列宽是否偏离模板。
- 表格结构、合并单元格、表头底纹、单元格字体是否一致。
- 正文和表格的数字是否冲突，分项合计是否等于总数。
- 名称、日期、金额单位的写法是否一致。
- 图片是否是共享引用，SVG / VML / 外部链接图片是否处理正确。
- Excel 公式是否能重新计算，宏和复杂对象是否可能丢失。
- 页面数量、字体是否安装、PDF 渲染是否成功（依赖本机后端）。

检查报告会同时给出：

- `issues`：具体问题和位置。
- `warnings`：中低严重度建议。
- `coverage_gaps`：没有覆盖到的检查项。
- `unverified_count`：未验证数量。

## 当前版本

截至 2026-11-07：

| 类型 | 版本 | 状态 | 说明 |
|---|---|---|---|
| 公开稳定版 | **[v4.0.1](https://github.com/bingheyuxing-sheng/officecli-template-filler/releases/tag/v4.0.1)** | GitHub Latest | 普通用户建议优先使用这个版本 |
| 最新预发布 | **[v4.1.2](https://github.com/bingheyuxing-sheng/officecli-template-filler/releases/tag/v4.1.2)** | Pre-release（已发布） | 审阅结果可直接写成 Word 批注；稳定版仍建议 v4.0.1 |
| 公开预发布 | **[v4.1.1](https://github.com/bingheyuxing-sheng/officecli-template-filler/releases/tag/v4.1.1)** | Pre-release | 只改了 Skill 文档，运行时行为与 v4.1.0 相同 |
| Draft | **v4.1.0** | 未公开 | 模板理解闸门；Release 仍在 Draft |
| 开发中 | **4.2.0** | 未发布 | 新增可选 officecli 写入后端，默认行为不变 |

测试情况：

- v4.1.2 本地构建包：**535 项通过**，契约测试 72 项通过。
- 当前开发分支（4.2.0，未发布）：**653 项通过**，契约测试 72 项通过（2026-11-07 实测）。
- v4.1.1：532 项通过；v4.0.1：479 项通过。

### 版本号说明

项目里同时有三个容易混淆的编号：

| 编号 | 当前值 | 含义 |
|---|---|---|
| 软件版本 | v4.1.2（Pre-release）；4.2.0（开发中） | 用户通常说的“版本号”，对应 Git tag 和 Release |
| 契约集版本 | 4.3.0 | 公共接口契约的集合版本，由多份契约和变更提案组成 |
| 产物 `schema_version` | 4.0 | 生成的 JSON 产物使用的 Schema 版本 |

三者不是同一个编号体系。看到 `4.3.0` 时，它通常指契约集，不是软件版本。

真实文档验证：

- v4.0.0 曾用 46 份外部真实 `.docx` 做无损验证：解析 46/46、模板字节 0 改动、0 个 Spec 校验失败；21 份可填模板全部完成填充并提交（12 份 `PASSED`，9 份因浮动图片覆盖缺口如实标为 `UNVERIFIED`）。
- v4.1.x 尚未在模板闸门链路重跑这批真实语料，因此不能把上述结果直接当作 v4.1.2 的验证结论。

## 已知限制

- `POLISH` / `MERGE` 还没有独立执行入口，会返回 `CAPABILITY_NOT_AVAILABLE`。
- 不支持在 Word 内容控件（SDT）内部填充；SDT 只作为“受保护位置”被发现并拒绝修改。
- 图片里的文字需要额外安装 OCR 后端；没安装时 `run_qa.py --ocr` 会报 `OCR_UNAVAILABLE`，默认不执行这项检查。
- 图表重绘需要 matplotlib；中文标签还需要本机安装中文字体，否则返回明确状态，不会输出乱码图。
- SVG / EMF / WMF 等矢量图无法做字节级校验，替换后只能报告 `VECTOR_IMAGE_UNVERIFIED`，需要人工或 PDF 比对确认。
- Excel 的 ActiveX、Power Query、透视表、切片器等复杂对象不会被 `openpyxl` 保留；默认会以 `OBJECT_LOSS_RISK` 拒绝执行，需要显式允许对象丢失。
- 版面检查使用 DOCX 版面指纹（字体、字号、对齐、缩进、列宽、图片比例），不承诺逐像素一致；像素级比对需要本机 LibreOffice + PyMuPDF。
- 视觉检查依赖本机 PDF 后端（WPS 或 LibreOffice）；两者都没有时状态是 `UNVERIFIED`，不是通过。
- 进程清理只终止能证明由本次任务启动的实例；无法证明归属的进程会保留，不做猜测性终止。
- 不承诺与 Word / WPS 逐像素一致；Chart、SmartArt、OLE 等复杂对象只做只读保留，并在 `coverage_gaps` 中列明。

## 历史版本

各版本的发布包和说明见 [Releases](https://github.com/bingheyuxing-sheng/officecli-template-filler/releases)，完整变更见 [CHANGELOG.md](CHANGELOG.md)。

| 版本 | 状态 | 主要变化 |
|---|---|---|
| 4.2.0 | 开发中，未发布 | 新增可选 officecli 写入后端和后端适配层；默认仍走 python-docx，行为不变 |
| v4.1.2 | 预发布 | 审阅时可以把 Excel/JSON 检查结果直接写成目标 Word 的批注，不再单独交付一份“核查报告” |
| v4.1.1 | 预发布 | 精简 Skill 文档，把工作流细节移到 `references/`；不改运行时行为 |
| v4.1.0 | Draft | 新增模板理解与确认闸门：先理解模板，再允许生成、修复、重排、审阅 |
| v4.0.2 | 未发布 | 删除两个有供应链风险的第三方下载脚本，清理历史归档，修复静态检查问题 |
| v4.0.1 | 正式版（Latest） | v4.0.0 合规补丁：移除测试中残留的外部语料，统一测试计数，补齐真实语料报告信息 |
| v4.0.0 | 正式版 | 首个 v4 稳定版：DocumentSpec → 计划 → 事务执行 → 检查 → 提交；46 份真实文档无损验证 |
| v4.0.0-dev.1 | 预发布 | v4 文档主链和 W3 加固的开发快照，不是 Alpha |
| v3.5.9 | 正式版 | 按角色定位图片、可选 OCR、图表重绘、内部事实确认、审阅自动文字修订、校对自动检查、工作流编排辅助 |
| v3.5.8 | 正式版 | 内容真值检查、SVG/VML 图片修复、矢量图显式标为未验证、事实来源检查 |
| v3.5.7 | 正式版 | REFORMAT 差异清单与带修订应用、WPS/LibreOffice PDF 渲染与真实页数测量（含 v3.5.6 修复） |
| v3.5.6 | 未单独发布 | 路由不再把 `.docx + .xlsx` 误判为合并；语义对齐、严重级门禁、字体名归一、文件锁报告；内容随 v3.5.7 发布 |
| v3.5.5 | 正式版 | 修复审阅修订 ID 冲突和版面检查误报；20 个端到端场景验证 |
| v3.5.4 | 正式版 | 收紧进程清理权限；补齐生成和修复的事务检查；修正检查状态 |
| v3.5.3 | 正式版 | 增加 FAST / STANDARD / FULL 执行档位、培养方案语义预检、分阶段检查点、渲染和目录降级 |
| v3.5.2 | 正式版 | Excel 公式与对象预检、版面指纹、进程身份、PROOFREAD 模式、合并单元格安全写入（含 v3.5.0 事务层） |
| v3.5.0 | 未单独发布 | 事务化交付、修订生命周期与快照、表格签名、能力注册表；内容随 v3.5.2 发布 |
| v3.4.2 | 正式版 | 审阅修订 ID 真实一致、超链接结构保护、定位防误改、XLSM 保宏、检查四态 |
| v3.4.1 | 归档版 | 恢复格式时写入 Word 原生格式修订，可在修订窗格逐条接受或拒绝 |
| v3.4.0 | 未单独发布 | 表格逐单元格字体字号一致性、单元格结构记录、修订生命周期；内容在 v3.4.2 中 |
| v3.3.1 | 未单独发布 | 明确审阅交付物必须是可修订的 `.docx`；未定位修改转批注；结构化检查报告；内容在 v3.4.2 中 |

## License

本项目采用 [MIT License](LICENSE)，可自由使用、修改、分发与商用，需保留版权声明与许可声明。
