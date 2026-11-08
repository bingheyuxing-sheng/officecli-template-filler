# Office Template Filler

[English](README.md) | 简体中文

面向 AI Agent 的模板驱动 Word / Excel 文档引擎：先路由请求，确认模板，规划内容，以事务方式执行填充，再以四态报告 QA 结果。

> **当前状态：没有自动化测试，也没有 CI。**
> 本仓库只保留实现各工作流所需的文件。没有 `tests/`、没有 `.github/`、没有回归门禁，因此对引擎的任何改动都只能在真实模板上手工跑完整链路来验证。除发布 manifest 中记录的打包校验外，每个版本都应视为未经验证。

## 这是什么

本仓库是 `officecli-template-filler` 这个 skill 背后的运行时。全部是 Python，直接从 `scripts/` 运行，不安装为包，也不需要编译。

它以两种方式编辑文档：

- **生成型内容**在触碰任何 OOXML 之前就已确定。`DocumentSpec` 描述模板，`ContentPlan` 说明写什么，`FillPlan` 说明写在哪里、怎么写。只有执行器会写文件。
- **审阅型内容**写成原生 Word 修订（`w:ins`、`w:del`）或原生格式修订（`w:rPrChange`、`w:pPrChange`），绝不做无痕迹的覆盖写入。

### 与 OfficeCLI 的关系

[OfficeCLI](https://github.com/iOfficeAI/OfficeCLI) 是**可选的写入后端**，不是依赖。默认后端是 `python-docx`；传入 `--writer officecli` 才会改走 OfficeCLI CLI 填充。

- 当 OfficeCLI 无法表达某个位置（页眉、页脚、内容控件、文本框）时，引擎会放弃整篇文档的 OfficeCLI 路径，回退到 `python-docx`，并把原因记录在 `writer_fallback` 中。
- 默认后端不会被自动翻转。两者之间没有共享代码、没有内置二进制、也没有版本握手；OfficeCLI 的查找顺序是 `OFFICECLI_BINARY` 环境变量、`PATH`、默认安装路径。

## 运行要求

**Python 3.10 或更高版本。** 这是硬性要求，且本仓库其它地方都没有声明：代码在六处使用 `zip(..., strict=True)` 比较可迭代对象，在 Python 3.9 上会抛出 `TypeError`。

| 组件 | 要求 |
|---|---|
| Python | >= 3.10（使用 `zip(strict=)`；见 `engine/table_engine.py`、`engine/review_engine.py`、`engine/ssot_engine.py`、`engine/consistency_qa.py`、`template_intelligence/spec_builder.py`） |
| `python-docx` | >= 1.1.0 — DOCX 读写、修订写入 |
| `openpyxl` | >= 3.1.2 — XLSX 读写、公式保留 |
| `lxml` | >= 5.0.0 — OOXML 命名空间处理 |
| `Pillow` | >= 10.0.0 — 图片检查 |
| `jsonschema` | >= 4.20 — 版本化 JSON 产物的校验 |
| `PyMuPDF` | 可选（`>= 1.24`）— 页面渲染与页级视觉比对；缺少时页数统计回退到 WPS `pdfinfo` 或 poppler |
| WPS Office 或 LibreOffice | 可选 — 为视觉 QA 做 PDF 转换；缺少时返回 `RENDER_PDF_NOT_PRODUCED` |
| OfficeCLI | `POLISH` / `MERGE` 必需；FillPlan 路径的 `--writer officecli` 可选 |

```powershell
python -m pip install -r requirements.txt
```

## 工作流与入口

| 模式 | 入口脚本 | 用途 | 模板闸门 |
|---|---|---|---|
| `GENERATE` | `scripts/generate_document.py` | 按 ContentPlan/FillPlan 填充 `.docx` 模板，或用 `--data` 走旧的 token 映射 | **必须 CONFIRMED** |
| `REPAIR` | `scripts/repair_document.py` | 按参考模板重建损坏的 `.docx`，保留其原有内容 | **必须 CONFIRMED** |
| `REFORMAT` | `scripts/reformat_document.py` | 按参考模板统一排版，写成 `w:*PrChange` | **必须 CONFIRMED** |
| `REVIEW` | `scripts/review_document.py` | 按参考模板审阅单个文档，或用 `--findings` 把外部发现挂成批注 | **必须 CONFIRMED** |
| `PROOFREAD` | `scripts/proofread_document.py` | 对单个文档施加带痕迹的文字更正 | 不需要 |
| `POLISH` | `scripts/polish_document.py` | 通过 OfficeCLI 的 run/段落级替换润色措辞，保持版式 | 不需要 |
| `MERGE` | `scripts/merge_documents.py` | 通过 OfficeCLI dump/replay 合并 2+ 个 DOCX 或 XLSX | 不需要 |

Excel 模板是另一条独立路由：`EXCEL_GENERATE` → `scripts/generate_excel.py`（`--template`、`--data`、`--out`），负责填单元格并保留既有公式。

`POLISH` 与 `MERGE` 基于 OfficeCLI 后端。`POLISH` 遇到跨不同格式 run 的替换会直接拒绝，而不是让 OfficeCLI 重建段落；`MERGE` 以第一个输入为基准包，把后续输入作为 OfficeCLI batch 回放，未合并的故事/对象会记入 `limitations`。若后续文档的样式 id 与基准包重名，保留基准包的定义，只导入缺失样式。

## 最短可用路径

路由和模板闸门必须先行。闸门会写入一条签名记录；任何变更类入口在没有 `CONFIRMED` 记录时都会拒绝执行。

```powershell
# 1. 路由请求
python scripts/inspect_document.py --inputs template.docx --intent "generate a project proposal" --out routing.json

# 2. 分析模板并查看证据
python scripts/template_gate.py analyze --template template.docx --task-type GENERATE --out gate-analysis.json
python scripts/template_gate.py report --analysis gate-analysis.json

# 3. 用 report 打印的 token 确认，确认后持久化 Gate Record
python scripts/template_gate.py confirm --analysis gate-analysis.json --review-token <token> --user-statement "confirmed" --out-record gate.json
```

闸门确认后，最短的端到端填充走旧的 token 映射：

```powershell
python scripts/generate_document.py --template template.docx --data values.json --out out.docx
python scripts/run_qa.py out.docx --reference template.docx --task-mode GENERATE --out qa.json
```

版本化的计划链路用同一个入口，但显式传入各产物：

```powershell
python scripts/analyze_template.py template.docx --spec-version 4 --out spec.json
python scripts/generate_document.py --template template.docx --spec spec.json `
    --content-plan content.json --plan fill.json --out out.docx --mode STANDARD
```

没有任何 CLI 负责生成 `content.json` / `fill.json`：需要用 `content_intelligence` 的 API（`build_content_plan`、`build_fill_plan`）构建，并在执行前完成校验。

单文档的三种审阅形态与其余入口：

```powershell
python scripts/review_document.py    --reference template.docx --target draft.docx --revisions revisions.json --out reviewed.docx
python scripts/proofread_document.py --target draft.docx --revisions revisions.json --out proofread.docx
python scripts/reformat_document.py  --reference template.docx --target draft.docx --out reformatted.docx
python scripts/repair_document.py    --reference template.docx --broken broken.docx --out repaired.docx
python scripts/generate_excel.py     --template budget.xlsx --data values.json --out budget-filled.xlsx
python scripts/polish_document.py    --target draft.docx --edits edits.json --out polished.docx
python scripts/merge_documents.py    --inputs part1.docx part2.docx --out merged.docx
```

以上脚本都接受 `--output` 作为 `--out` 的别名；`generate_document.py` 与 `generate_excel.py` 还接受 `--payload` 作为 `--data` 的别名。有一处不对称要记住：在 `run_qa.py` 上，`--output` 是**输入文档**的别名，JSON 报告路径是 `--out` / `--report`。

## 闸门与 QA 规则

这些是不变量，不是约定。

- **没有确认的闸门，就没有执行。** `GENERATE`、`REPAIR`、`REFORMAT`、`REVIEW` 都需要一份 `CONFIRMED` 的 Gate Record，并绑定模板的哈希、spec 和指纹。改动模板会使其失效（`TEMPLATE_GATE_STALE`）。
- **QA 只有四种状态。** `PASSED`、`FAILED`、`PENDING_HUMAN_REVIEW`、`UNVERIFIED`。没有执行过的检查会变成 `UNVERIFIED` 并列入 `coverage_gaps`，绝不会被报告为通过。
- **`UNVERIFIED` 不等于通过。** 只有在 `STANDARD` 模式下配合 `--allow-unverified` 才允许提交，且交付说明必须披露。
- **`committed: false` 表示没有最终文件。** 事务记录（见 `engine/transaction.py`）会给出 `committed`；为 false 时暂存文件已被丢弃，输出路径没有被写入。
- **退出码。**

  | 退出码 | `generate_document.py` | `run_qa.py` |
  |---|---|---|
  | `0` | 文档已提交 | `PASSED`、`PENDING_HUMAN_REVIEW`，或带 `--allow-unverified` 的 `UNVERIFIED` |
  | `1` | 未提交（QA 失败，或 `UNVERIFIED` 未加开关） | `FAILED`，或未加开关的 `UNVERIFIED` |
  | `2` | 写入前被拒绝（闸门、包配额、缺 spec、计划被阻断） | 用法错误或包配额拒绝 |

  `review_document.py` 与 `proofread_document.py` 在事务未提交时返回 `1`，闸门或预检拒绝时返回 `2`。在 `committed` 为 true 之前，不要把一个已生成的文件当作已交付。

## 目录结构

```
officecli-template-filler/
├── SKILL.md                  # 面向 Agent 的工作流契约（权威）
├── config/                   # 包配额、QA 策略、错误码、闸门策略、环境探测
├── schemas/                  # DocumentSpec、ContentPlan、FillPlan、QAReport 的 JSON Schema（schema 4.0）
├── template_gate/            # 证据分析、状态机、Gate Record 存取与校验
├── template_intelligence/    # DocumentSpec 生成：槽位、指纹、不支持特性
├── content_intelligence/     # ContentPlan 与 FillPlan 的构建与校验
├── document_engine/          # FillPlan 执行器、填充账本、事务式流水线
├── qa/                       # QAReport 汇总、必需检查矩阵、提交资格判定
├── engine/                   # 共享引擎：OOXML、样式、表格、图片、Excel、PDF、事务、修订
└── scripts/                  # CLI 入口（Agent 实际调用的接口面）
```

| 模块 | 职责 | 从哪里读起 |
|---|---|---|
| `scripts/` | 参数解析、文件级预条件、退出码 | `scripts/generate_document.py` |
| `document_engine/` | 校验计划、暂存文件、执行填充、跑 QA、提交或中止 | `document_engine/fill_executor.py` |
| `template_gate/` | 分析证据、强制确认、持久化 HMAC 签名记录 | `template_gate/validator.py` |
| `template_intelligence/` | 把模板转成带稳定槽位 id 的 `DocumentSpec` | `template_intelligence/spec_builder.py` |
| `content_intelligence/` | 把内容转成 `ContentPlan` / `FillPlan` 并校验 | `content_intelligence/plan_builder.py` |
| `qa/` | 把各项检查折叠成单一状态并判定提交资格 | `qa/pipeline.py` |
| `engine/` | 全部 OOXML 与文件格式机制，以及事务和修订写入 | `engine/transaction.py`、`engine/review_engine.py` |
| `config/`、`schemas/` | 策略取值与机器可读契约 | `config/qa-policy.json` |

写入始终是事务式的：`preflight` → 暂存副本 → 执行 → QA → 原子替换。`w:proofErr` 标记、未映射的样式、复杂表格单元格、共享图片关系与 Excel 公式都按设计保留；检查失败会中止事务，而不是降低输出质量。

## 版本与发布

当前版本：**4.3.0**（`engine/__init__.py`、`SKILL.md`）。

- `dist/` 已被 git 忽略。它是发布流程产生的构建产物，从不入库。
- 一次发布由 `officecli-template-filler-<version>.zip` 与同名的
  `officecli-template-filler-<version>.manifest.json` 组成。
- manifest 记录来源提交、构建时间、归档 SHA-256、条目数，以及归档内每个文件的路径、
  字节数与 SHA-256。使用前请按 manifest 校验 zip。

## 已知限制

- **没有自动化测试，没有 CI。** 这是本仓库最大的风险，见文首提示。改动引擎后必须在有代表性的模板上手工跑完整链路。
- `POLISH` / `MERGE` 依赖 OfficeCLI；缺少二进制时以 `OFFICECLI_UNAVAILABLE` 退出（exit 2）。
- `POLISH` 无法在同一个 run 内只替换多个匹配中的一个，也无法替换跨不同格式 run 的文本；它会返回规划错误，而不是改变 run 格式。
- `MERGE` 只把各文档正文合并进第一个输入的包。后续文档的页眉页脚、脚注、尾注、批注与各自的末节页面设置不会带入；XLSX 的命名区域、图表、透视表与宏不会合并。这些都会在合并报告的 `limitations` 中列出。
- OfficeCLI 写入后端只覆盖正文段落与表格，目标位于其它位置时整篇回退；其行为不会随每个 OfficeCLI 版本重新验证。
- 视觉 QA 需要 WPS/LibreOffice 做 PDF 转换、PyMuPDF 做页面渲染；缺少任一依赖时，相应检查保持 `UNVERIFIED`，不会被当作通过。
- XLSX 处理无法保证保留 `openpyxl` 不能往返的形状、图表等对象；这类对象会被报告出来，而不是静默丢弃。
