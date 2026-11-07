# 变更记录

本文件用普通用户能理解的方式，记录 officecli-template-filler 每个版本**解决了什么问题、带来了什么变化、还有什么限制**。

发布包统一由 [GitHub Releases](https://github.com/bingheyuxing-sheng/officecli-template-filler/releases) 提供，仓库内不再保留 `dist/` 归档副本。

## 阅读说明

- **版本状态**：正式版、预发布、Draft（未公开）、未发布、未单独发布。
- **测试数字**：指该版本发布时记录的全量测试数，不代表当前开发分支的测试数。
- **契约集版本**：公共接口契约的版本，和软件版本不是一回事；产物里的 `schema_version` 又是另一个版本号。
- 当前开发分支与最新发布均为 **v4.2.1**，2026-11-07 实测 **692 项通过**（含契约 76 项）；v4.1.2 本地构建包记录为 **535 项通过**。

### 名词说明

| 名词 | 简单解释 |
|---|---|
| 修订 | Word 里的“修改记录”，可以看到谁改了什么，并逐条接受或拒绝 |
| Run | Word 里一段连续、格式相同的文字 |
| OOXML | Word / Excel 文件内部的 XML 结构 |
| SDT | Word 的内容控件，例如可填写的小表单 |
| SSOT | 单一事实来源：同一个指标只保留一个值，避免前后不一致 |
| 契约集 | 项目内部约定的接口规则集合，不是软件版本号 |

## 版本速览

| 版本 | 日期 | 状态 | 一句话说明 |
|---|---|---|---|
| v4.2.1 | 2026-11-07 | 正式版 | CI 跨平台修复：UTF-8、短路径、Python 3.12 时间/摘要 |
| v4.2.0 | 2026-11-07 | 正式版 | 安全与 QA 收口；新增可选 officecli 写入后端 |
| v4.1.2 | 2026-11-07 | 预发布 | 审阅时可以把外部检查结果直接写成 Word 批注 |
| v4.1.1 | 2026-11-06 | 预发布 | 只精简 Skill 文档，不改运行时行为 |
| v4.1.0 | 2026-11-06 | Draft | 新增模板理解与确认闸门 |
| v4.0.2 | 2026-11-05 | 未发布 | 删除有供应链风险的安装脚本，清理历史归档 |
| v4.0.1 | 2026-11-05 | 正式版（Latest） | v4.0.0 合规补丁，关闭独立审查阻断项 B1 |
| v4.0.0 | 2026-11-05 | 正式版 | 首个 v4 稳定版，46 份真实文档无损验证 |
| v4.0.0-dev.1 | 2026-11-05 | 预发布 | v4 文档主链和 W3 加固的开发快照 |
| v3.5.9 | 2026-11-04 | 正式版 | 图片角色、可选 OCR、流程闭环与编排辅助 |
| v3.5.8 | 2026-11-04 | 正式版 | 内容真值、图片真值与事实来源检查 |
| v3.5.7 | 2026-11-03 | 正式版 | REFORMAT 差异清单、带修订应用、PDF 渲染 |
| v3.5.6 | 2026-11-03 | 未单独发布 | 路由、语义对齐、严重级门禁、字体名、文件锁；随 v3.5.7 发布 |
| v3.5.5 | 2026-11-02 | 正式版 | 修复审阅修订 ID 冲突与版面检查误报 |
| v3.5.4 | 2026-11-02 | 正式版 | 收紧进程权限，补齐事务检查，修正检查状态 |
| v3.5.3 | 2026-11-02 | 正式版 | 执行档位、语义预检、分阶段检查点 |
| v3.5.2 | 2026-11-02 | 正式版 | Excel 可靠性、版面指纹、PROOFREAD、合并安全写入 |
| v3.5.0 | 2026-11-02 | 未单独发布 | 事务化交付、修订生命周期、能力注册表；随 v3.5.2 发布 |
| v3.4.2 | 2026-11-01 | 正式版 | 审阅安全性、QA 四态、XLSM 保宏 |
| v3.4.1 | 2026-11-01 | 正式版（归档） | 格式修复写入 Word 原生格式修订 |
| v3.4.0 | — | 未单独发布 | 表格逐单元格一致性、修订生命周期；内容在 v3.4.2 |
| v3.3.1 | — | 未单独发布 | 审阅交付契约、结构化 QA；内容在 v3.4.2 |

> v3.5.1 没有 tag、Release 或 CHANGELOG 记录，版本序列从 v3.5.0 直接到 v3.5.2。

---

## v4.2.1（2026-11-07，正式版）

> 状态：正式版。软件版本 4.2.1；契约集 4.3.0；产物 `schema_version` 4.0。
> 本版本只修复 v4.2.0 首次 CI 运行暴露的跨平台问题，不改变 CLI 参数、契约字段或默认行为。

### 问题修复

- **Windows CI 的 UTF-8 输出**：子进程默认使用 cp1252，输出中文时抛 `UnicodeEncodeError`，导致 analyze / generate / QA 等 8 个 CLI 测试失败。`scripts/run_tests.py` 现在为自身和所有子进程设置 `PYTHONIOENCODING=utf-8` / `PYTHONUTF8=1`，CI 工作流也显式设置同一环境变量。
- **Windows 8.3 短路径**：GitHub Runner 的 `TEMP` 是 `RUNNER~1` 短路径，而测试期望 `resolve()` 后的长路径。两处路径断言改为双侧 `resolve()`。
- **Python 3.12 拒绝 `24:00:00`**：`datetime.fromisoformat` 在不同解释器上对 ISO-8601 的 end-of-day 形式接受度不一致。`_validate_verified_at` 在解析前把 `T24:00:00` 归一化为 `T00:00:00`，使 3.10–3.14 的判定一致；保存的仍是调用方原始字符串。
- **Windows 时钟精度导致摘要测试偶发失败**：连续两次 `datetime.now()` 可能落在同一微秒。测试改为断言真正的不变量——`report_digest` 忽略 `generated_at`，并显式篡改时间戳验证摘要不变。
- **Ubuntu 字体假设**：两个视觉 QA 测试要求本机安装宋体、Times New Roman 等字体。断言改为宿主无关的不变量：`missing` 必须是 `requested` 的子集，且不存在的字体必须被报告。

### 测试

- 全量：**692 项通过，0 失败 / 0 错误**（243s，Windows 11 / Python 3.14.10）。
- GitHub Actions：**6/6 job 通过**（Ubuntu + Windows × Python 3.10 + 3.12 的 fast profile，以及两个 external job）。
- 契约测试：76 项通过；Ruff 0.17.4：`All checks passed`。

### 破坏性变更

- 无。CLI 参数、默认行为、契约字段与 `schema_version` 均未变化。

### 已知限制

- 与 v4.2.0 相同：officecli 仅覆盖 `.docx` 三类文字操作；`document_backends/` 仍为 `EXPERIMENTAL_NOT_WIRED`；POLISH / MERGE 无入口；SDT 内填充不开放；视觉检查依赖 WPS/LibreOffice；Linux/macOS 仅通过 CI fast profile 验证，未做真实文档发布验证。

### 发布资产

- `officecli-template-filler-v4.2.1.zip`
- SHA-256 与大小见 Release 页面及 `reports/acceptance/w5-package-manifest-v4.2.1.md`。

---

## v4.2.0（2026-11-07，正式版）

> 状态：正式版。软件版本 4.2.0；契约集 4.3.0（4.2.0 冻结基线 + Contract 06 DRAFT）；产物 `schema_version` 4.0。
> 发布资产：`officecli-template-filler-v4.2.0.zip`，SHA-256 见 GitHub Release。

### 本次修复（P0/P1）

**P0 — 兼容性**

- README、badge 与开发说明统一为 **Python 3.10+**。旧文档声明 3.9，但生产代码使用 `zip(..., strict=)`，3.9 会在执行中段抛 `TypeError`。新增一致性测试，锁定 README、badge 与 `ruff.toml` 的版本口径。

**P1 — 安全**

- 7 个解析入口（review / proofread / repair / reformat / run_qa / render / template-gate analyze）接入 ZIP 资源配额。此前只有生成与模板分析链路有配额，构造包可以直接进入 python-docx/openpyxl。现在统一返回 `PACKAGE_LIMIT_EXCEEDED` 并以退出码 2 拒绝。
- Excel 公式求值移除 `eval()`，改为 AST 白名单（仅数字字面量、`Decimal(<literal>)` 与 `+ - * /`）。字符白名单保留为第二道防线。

**P1 — QA 语义**

- `run_qa.py` 在 `UNVERIFIED` 时改为退出码 1；需要放行时显式加 `--allow-unverified`，报告新增 `exit_ok` 字段。此前 `UNVERIFIED` 返回 0，CI 会把“没检查完”当成成功。
- FillPlan 执行器只在 `qa` 包确实缺失时降级为 PACKAGE+FORMAT 报告；`qa.pipeline` 内部错误（缺依赖、语法错误、循环导入）现在会以 `QA_EVIDENCE_MISSING` 失败，不再伪装成环境限制。

**P1 — 进程与测试**

- PDF 转换改用 `TaskResourceGuard.run_owned_command(kill_tree=True)`：子进程在独立进程组中启动，超时终止整棵进程树，避免 `kwpsconvert.exe` 派生的 `wps.exe` 残留。
- 测试拆分为 `fast` / `external` / `all` 三种 profile（`scripts/run_tests.py`），`fast` 不依赖 WPS/LibreOffice 或 officecli；新增 GitHub Actions，在 Ubuntu/Windows + Python 3.10/3.12 上执行 ruff 与 fast profile。

**P1 — 治理与披露**

- `document_backends/` 明确标记为 `EXPERIMENTAL_NOT_WIRED`：它是 W5 的后端抽象骨架，尚未接入执行链；README、CHANGELOG 与模块 docstring 同步披露。
- 契约集版本统一为 4.3.0（4.2.0 冻结基线 + Contract 06 DRAFT），AGENTS.md 同步；新增契约测试交叉校验索引、AGENTS.md、各契约冻结版本与 `engine.__version__`/CHANGELOG。
- 4.2.0 正式发布后，`engine.__version__`、Git tag 与 CHANGELOG 三者一致，关闭“版本号早于发布状态”的问题。

### 新增功能

- 可选的 officecli 写入后端：`generate_document.py --writer {python-docx,officecli}`，默认仍为 `python-docx`。遇到不支持的位置或操作时回退并在 `data.writer_fallback` 记录原因。
- `scripts/run_tests.py`：按 profile 运行测试，打印被跳过的外部依赖模块及原因。
- `.github/workflows/ci.yml`：lint + fast profile 必跑，external profile 为允许失败的信息性 job。

### 技术记录

- 新增 `engine/officecli_writer.py`、`document_backends/` 后端接口与结果类型，`tests/w5/` 104 项单元测试。
- 新增 15 个 reason code 和 3 个通用 `BACKEND_*` 错误码；错误码配置只增不改。
- 后端能力记录在构造时强制要求证据，未验证的能力不能标记为“支持”。
- 模板确认记录的密钥文件按原始字节读取，避免裁掉首尾空白字节导致签名校验失败。

### 测试

- 全量：**692 项通过，0 失败 / 0 错误**（243.154s，Windows 11，Python 3.14.10）。
- `fast` profile：**670 项通过**（92.893s，`OFFICECLI_PDF_BACKEND=none`，证明不依赖 PDF 后端）。
- `external` profile：**15 项通过**（76.586s，本机 WPS）。
- 契约测试：**76 项通过**（含新增 4 项版本一致性）。
- Ruff 0.17.4：`All checks passed`。

### 破坏性变更与迁移

- **Python 最低版本从 3.9 提升到 3.10**。3.9 用户需先升级解释器；这是修正既有声明与实现的偏差，不是 API 变化。
- **`run_qa.py` 的 `UNVERIFIED` 退出码从 0 改为 1**。依赖旧退出码的 CI 需加 `--allow-unverified`，或改为消费报告里的 `status` / `exit_ok`。
- 其余 CLI 参数与默认行为不变；`--writer` 默认仍是 `python-docx`。

### 已知限制

- officecli 只覆盖 `.docx` 的三类文字操作；其他位置和 Excel 全部回退 python-docx。
- officecli 是外部闭源二进制，升级后需要重新跑一致性测试。
- `document_backends/`（W5-B1 后端抽象）尚未接入执行链，`PACKAGE_STATUS = EXPERIMENTAL_NOT_WIRED`；当前写入仍走 `engine/officecli_writer.py`。
- `POLISH` / `MERGE` 仍无执行入口；SDT 内填充仍不开放（`sdt_edit=false`）。
- 视觉检查依赖本机 WPS 或 LibreOffice；缺失时相关检查为 `UNVERIFIED`，不是通过。
- Linux / macOS 未纳入本版本的发布验证范围。

### 发布资产

- `officecli-template-filler-v4.2.0.zip`
- SHA-256 与文件大小见 Release 页面及 `reports/acceptance/w5-package-manifest-v4.2.0.md`。
- 回滚：重新安装上一版本（v4.1.2 或 v4.0.1）并替换 Skill 目录即可；本版本未修改冻结契约的字段语义。

---

## v4.1.2（2026-11-07，预发布）

> 状态：已于 2026-11-07 推送 tag `v4.1.2` 并以 Pre-release 发布；发布资产已上传并校验。软件版本 4.1.2；契约集 4.3.0；产物 `schema_version` 4.0。
> Release：https://github.com/bingheyuxing-sheng/officecli-template-filler/releases/tag/v4.1.2

### 这个版本解决了什么

审阅文档时，检查结果可能来自 Excel 或 JSON。以前的审阅报告是一份单独的文档，用户需要在两份文件之间来回看。这个版本把外部检查结果直接写成目标 Word 文档里的批注，打开一份文档就能逐条看。

### 用户能感受到的变化

- `review_document.py --findings findings.json`：把外部 findings 转成目标正文或表格里的批注。
- 输出仍然是带修订标记的目标方案正文，不是一份独立的“核查报告”。
- 无法定位的 finding 会返回 `COMMENT_LOCATION_UNRESOLVED`，不会悄悄丢掉。
- 可以同时附带文本修订和外部批注。

### 技术记录

- 新增 `engine/review_engine.py::build_findings_review_plan()`，校验 `body.p[n]` / `body.tbl[t].r[r].c[c]` 位置。
- 新增 `tests/test_review_findings.py`，覆盖正文批注、表格批注、无法定位拒绝、批注与文本修订并行。
- `review_report.json` 仍作为旁路审计文件保留，不作为最终交付物。
- 不修改冻结契约、Schema 或错误码语义。

### 测试

- 发布包记录 **535 项通过**；契约测试 **72 项通过**；ruff 通过。

### 已知限制

- W4 独立出口审查仍未完成；不能称为正式稳定版 PASS。
- 未在 W4 链路重跑 46 份真实语料。
- 不支持 SDT 内填充。
- 本版本是 Pre-release；正式稳定版发布前，普通用户仍建议使用 v4.0.1。

### 发布包

- 文件名：`officecli-template-filler-v4.1.2.zip`
- 大小：997,540 字节
- SHA-256：`c66c652ec177fcc57a3dade003fdd22d2603071405406d87ce39de5a84f23f53`

---

## v4.1.1（2026-11-06，预发布）

> 状态：GitHub Pre-release，已公开。软件版本 4.1.1；契约集 4.3.0；产物 `schema_version` 4.0。

### 这个版本解决了什么

Skill 文档越来越长，Agent 每次加载都要读很多内容。这个版本把工作流细节移到 `references/`，主文件只保留启动检查、操作约定和资源地图，运行时行为不变。

### 用户能感受到的变化

- `SKILL.md` 的说明从 900 多字符压缩到 376 字符，更容易被正确触发。
- 新增 `references/workflow-details.md`，专门放事务、检查点、渲染/目录降级、QA 报告语义和内容检查代码表。
- 目录树和命令表补充了模板理解闸门。

### 测试

- 全量 **532 项通过**（454.570s）；契约 **72 项通过**；ruff 通过。

### 已知限制

- 官方标注为 Pre-release，不是稳定版，也不会被标记为 Latest。
- W4 出口评审仍是 `CONDITIONAL_PASS`，独立 Agent 07 复跑未完成。
- 已安装的 Skill 副本可能仍是 v4.0.0，需要手动替换。
- 未在 W4 链路重跑真实语料；SDT 内填充仍不支持。

### 发布包

- 文件名：`officecli-template-filler-v4.1.1.zip`
- 大小：993,950 字节
- SHA-256：`f994ef64fdf347085dcab9376ec27bc267b27c355063c5371e8d84ed0ce1712c`

---

## v4.1.0（2026-11-06，Draft）

> 状态：GitHub Draft，未公开。软件版本 4.1.0；契约集 4.3.0（新增 Contract 06）；产物 `schema_version` 4.0。

### 这个版本解决了什么

以前的流程可能在还没有真正看懂模板的情况下就开始改文档。这个版本增加“模板理解与确认闸门”：先生成模板分析报告，把证据分成已确认、待确认、有歧义、有冲突四类；只有拿到有效的确认记录，才允许生成、修复、重排或审阅。

### 用户能感受到的变化

- 生成、修复、重排、审阅四类任务开始前，会先做模板分析。
- 关键内容无法确定时，会要求用户确认，而不是猜测。
- 没有确认记录就执行，会返回 `TEMPLATE_GATE_REQUIRED` 等错误并停止。
- 模板被修改过、任务类型变了，之前的确认记录会失效，返回 `TEMPLATE_GATE_STALE`。

### 技术记录

- 新增 `template_gate/`：证据、分析、报告、状态机、确认记录存储、校验器、补充材料。
- 新增 3 个 Schema：`template_evidence-1.0`、`template_gate_record-1.0`、`template_analysis_report-1.0`。
- 新增 `scripts/template_gate.py` 的 analyze / report / resolve / confirm / reject / status 子命令。
- 新增 7 个闸门错误码；`GENERATE / REPAIR / REFORMAT / REVIEW` 执行入口强制校验。

### 测试

- 全量 **532 项通过**；契约测试 70+ 项通过；`reports/acceptance/w4-9-exit-review.md` 记录 72 项契约测试通过。
- 覆盖无记录阻断、模板修改后失效、任务类型变化、记录被篡改、证据冲突等场景。

### 已知限制

- W4 独立出口审查未完成；证据包由主智能体生成，不能称为 Agent 07 PASS。
- 闸门只覆盖 DOCX 模板相关模式；Excel、校对、渲染保持原行为。
- 带补充材料确认的记录通过证据摘要回放校验，补充文件本身不复制入仓。

### 发布包

- 文件名：`officecli-template-filler-v4.1.0.zip`
- 大小：992,825 字节
- SHA-256：`6451954c14258fb78b17f7b6eb9938a5d1ac490cbb73ec5e88fb423068c7f71a`

---

## v4.0.2（2026-11-05，未发布）

> 状态：未发布。没有 tag、没有 Release、没有构建包；只有 CHANGELOG 和版本号提交。

### 这个版本解决了什么

仓库里曾有两个安装脚本，会从多个第三方镜像下载可执行文件、在校验前直接运行、写入用户全局 PATH，并回退到 `npm install -g`。这构成供应链风险。这个版本删除了这两个脚本和 `dist/` 下的历史归档副本，并清理了静态检查问题。

### 用户能感受到的变化

- 不再提供 `scripts/ensure-officecli.ps1` / `.sh`。
- 历史归档统一从 Releases 下载，仓库内不再保留副本。
- `SKILL.md` 精简，架构细节移到 `references/`。
- 新增 `ruff.toml`，修复缺失导入、异常链、死变量、重复导入等问题。

### 测试

- 全量 **479 项通过**，0 失败、0 跳过。

### 已知限制

- 没有公开发布，普通用户无法下载这个版本。
- 该版本的清理内容已经包含在后续版本中。

---

## v4.0.1（2026-11-05，正式版，Latest）

> 状态：正式版，GitHub 当前 Latest。软件版本 4.0.1；契约集 4.2.0；产物 `schema_version` 4.0。

### 这个版本解决了什么

v4.0.0 的独立出口审查发现一个阻断项：测试代码里残留了外部语料正文和来源归属措辞。这个补丁删除了这些内容，改用完全合成的通用文本，并统一了文档里的测试计数。

### 用户能感受到的变化

- 仓库和发布包不再包含外部语料路径、文件名或正文。
- 真实语料报告记录运行命令、参数、环境与时间，9 份 `UNVERIFIED` 的原因可以直接复核。
- 文档里的测试计数统一为 479。

### 技术记录

- `engine.__version__` 从 4.0.0 改为 4.0.1。
- 执行器 `data` 增加 `coverage_gaps` 自由字段，用于证据复核；ToolEnvelope 的 `data` 本来就是自由对象，不构成契约变更。
- 新增独立出口审查记录 `reports/acceptance/w3-12-independent-exit-review.md`：v4.0.0 时裁定 FAIL，B1 由本补丁关闭。

### 测试

- 工作树全量 **479 项通过**（173.0s）。
- 发布包解压后全量 **479 项通过**（171.6s）。
- LibreOffice 复验：定向 34 项通过，全量 479 项通过（182.1s）。
- 真实语料复跑：46/46 解析、21/21 填充提交、0 模板字节改动、12 PASSED / 9 UNVERIFIED。

### 已知限制

- B2 只部分关闭：LibreOffice 已在 Windows 主机复验，Linux 环境仍未验证。
- v4.0.1 的独立复核待执行。
- 真实语料无人工标注基线，不计算、不声称槽位准确率。
- SDT 内填充不支持；浮动图片检查为 `UNVERIFIED`。
- 本机缺 PyMuPDF / matplotlib / OCR，相关检查如实 `UNVERIFIED`。

### 发布包

- 文件名：`officecli-template-filler-v4.0.1.zip`
- 大小：939,039 字节
- SHA-256：`106a96fe7a6c4fa2953e7a2f11c9586d5c327bc976f33a0eec30cbc090706bb2`
- 另有 `.sha256` 校验文件。

---

## v4.0.0（2026-11-05，正式版）

> 状态：正式版（发布时曾是 Latest，现被 v4.0.1 取代）。软件版本 4.0.0；契约集 4.2.0；产物 `schema_version` 4.0。

### 这个版本解决了什么

这是 v4 架构的第一个稳定版。它把文档处理拆成一条可检查的链路：

```text
DocumentSpec 4.0 → ContentPlan / FillPlan → 事务执行 → QA 报告 → 提交门禁 → 原子提交
```

同时用 46 份外部真实 `.docx` 做了一次无损验证。

### 用户能感受到的变化

- 生成文档走 v4 计划链，不再默认走旧的 token 模式。
- 授权填充不再误报“模板被擅自修改”。
- 红字提示段落、内部事实段落填充后，字体和字号保持不变。
- STANDARD 模式下，如果只是有覆盖缺口、没有缺失检查，报告可以按契约提交。
- Excel 大工作簿或图表解析异常时，不再崩溃或长时间卡住。

### 兼容性

- 软件版本从 3.5.9 跨到 4.0.0，用于标识 v4 文档主链；公共 API、v3.5.9 公共导出和 legacy 3.0 输出没有破坏。
- CLI `analyze_template.py --spec-version` 的默认值仍是 3；使用 v4 主链需要显式传 `--spec-version 4`。
- `UNVERIFIED` 报告的提交资格按契约 04 §7 处理：STANDARD + 显式允许即可提交，但缺失检查和覆盖缺口必须披露。

### 真实文档验证

- 解析 46/46 成功，0 字节改动，0 个 Spec 校验失败。
- 21 份可填模板全部完成填充并提交：12 份 `PASSED`，9 份因浮动图片覆盖缺口标为 `UNVERIFIED`。
- 模板字节 0 改动。
- 真实语料未经脱敏和人工标注，因此不计算、不声称槽位准确率。

### 测试

- 全量 **479 项通过**（175.8s）；发布包解包复跑 479 项通过（173.4s）。

### 已知限制

- SDT 内填充不支持，SDT 只作为受保护位置被发现并拒绝。
- 浮动图片、域更新、OLE、SmartArt、矢量图以 `UNSUPPORTED` 或 `UNVERIFIED` 披露。
- Linux / LibreOffice 未验证。
- 独立 Agent 07 复查未在当前环境执行。
- 发布包里的 `SKILL.md` 目录树仍写 473 项测试，实际是 479 项；仓库后续已更正，tag 和资产未变。

### 发布包

- 文件名：`officecli-template-filler-v4.0.0.zip`
- 大小：923,924 字节
- SHA-256：`2c22cf4c20ebfb571516a9f2e11e7e0e725e3c7fbe983d78ea42497367207719`
- 另有 `.sha256` 校验文件。

---

## v4.0.0-dev.1（2026-11-05，预发布）

> 状态：预发布，开发快照；官方明确“不是稳定版，不是 Alpha”。契约集 4.2.0；tag 上的 `engine.__version__` 仍是 3.5.9。

### 这个版本解决了什么

这是 v4.0 执行链和 W3 加固的检查用快照，用来在正式稳定版之前验证：

- DocumentSpec 4.0、ContentPlan / FillPlan、事务执行器、QA 报告、QA 门禁。
- 页眉页脚位置语法、SDT 位置语法与 PROTECTED 发现。
- SDT fail-closed 披露、ZIP 输入配额、soffice 私有 profile、PDF 临时副本清理。

### 测试

- **450 项通过**；发布包解包复跑 450 项通过（171.776s）。

### 已知限制

- 不是 Alpha，也不是 W3 阶段完成。
- 真实语料尚未获取、脱敏、标注；六类 Fixtures 是程序化构造的，不是真实业务模板验证。
- P2-01 / P2-04 需要审计方 Linux/LibreOffice 完整套件复跑。
- 本机缺 PyMuPDF / matplotlib / OCR；SDT 内填充不支持。

### 发布包

- 文件名：`officecli-template-filler-v4.0.0-dev-w3.zip`
- 大小：886,351 字节
- SHA-256：`91690799c13db8a1071a50b1888992179e4aac35244dfd95e0837b199490b451`
- 另有 `.sha256` 校验文件。

---

## v3.5.9（2026-11-04，正式版）

### 这个版本解决了什么

补齐流程文档里“写了但引擎里没有落地”的环节：内部事实字段没人确认、审阅没有自动文字修订、校对没有自动检查、SSOT 错误不够结构化、文件锁没有证据，以及确认门、执行档位、检查点、目录判定、多轮视觉检查、逻辑检查和研究计划缺少可执行接口。

### 用户能感受到的变化

- **确认门有数据源了**：空白内部事实字段（负责人、联系电话、编号等）会被识别为“必须问用户”，不再让 Agent 猜。
- **审阅能自动生成文字修订**：模板和草稿的措辞差异直接写成 Word 的插入/删除，同时避开占位符、红字和受保护容器。
- **校对能自动检查**：内容冲突、错别字、重复标题、空章节、编号跳号、日期倒挂都会写成批注，能定位到表格单元格。
- **图片能按角色找**：`logo` / `stamp` / `qr` / `illustration` / `photo`，每个结果都给出判定依据；匹配到多个时拒绝替换。
- **OCR 可选**：装了 RapidOCR / PaddleOCR / Tesseract 就能读图内文字；没装就明确报 `OCR_UNAVAILABLE`。
- **图表能重绘**：表格、柱状图、饼图可以渲染成 PNG，再走普通图片替换流程。
- **编排规则可执行**：确认门、档位、检查点、目录降级和多轮视觉检查有了确定性 API。

### 技术记录

- 新增 `engine/workflow.py`、`engine/logic_qa.py`、`engine/research.py`、`engine/ocr_engine.py`、`engine/chart_render.py`。
- `SSOTValidationError` 增加 `code / metric / locations / values` 和 `as_dict()`。
- 包完整性新增 `w:proofErr` 配对检查 `PACKAGE_PROOFERR_UNBALANCED`。
- 文件锁错误增加 `cleanup_log`，指向当前任务的清理日志。
- 合计检查支持表头行；图形重绘失败统一带 `needs_redraw`。

### 测试

- 全量 **186 项通过**；新增 `test_doc_gap_closure` 13 项、`test_workflow` 15 项、`test_research_logic` 9 项、`test_image_roles_ocr_render` 11 项。

### 已知限制

- `POLISH` / `MERGE` 仍无执行入口。
- 逻辑检查是确定性启发式，不能判断论证是否成立。
- `research` 模块只负责策略、查询计划和来源校验，实际联网检索由 Agent 完成。
- 视觉检查依赖本机 PDF 后端；缺失时状态为 `UNVERIFIED`。
- SVG / EMF / WMF 只能报 `VECTOR_IMAGE_UNVERIFIED`。
- `L4` 对象只读保留；`workflow` 只提供 API，不新增 `--profile` 等 CLI 参数。

### 发布包

- 文件名：`officecli-template-filler-v3.5.9-review-docx.zip`
- 大小：305,704 字节
- SHA-256：`db8e3c880c1edc9adeef4c5de393f8eac819c547efcbd4d6bcae82cabc67764f`

---

## v3.5.8（2026-11-04，正式版）

### 这个版本解决了什么

修复两个“假成功”：

1. 替换 SVG 图标时，只换了栅格兜底图，真正的 SVG 引用还在，Word 仍显示旧图，但程序报告成功。
2. 矢量图（SVG / EMF / WMF）既不报错也不报缺口，等于静默跳过检查。

同时补上内容真值检查，解决“正文写 100 万、表格写 105 万”这类问题。

### 用户能感受到的变化

- 替换图片时会清理 SVG 双嵌入，避免“换了但看起来没换”。
- 矢量图无法校验时会明确标为 `VECTOR_IMAGE_UNVERIFIED`，不再沉默。
- 支持 WPS 页眉 logo、公章、老模板常用的 VML 图片替换。
- 替换图片时清除旧裁剪框；可以按新图比例重算显示框。
- 外部链接图片会列出所属部件和目标，提示分发可能丢图。
- 新增内容一致性检查：正文/表格数值冲突、合计不等于分项之和、名称两种写法、日期和金额单位混用。
- 事实条目缺少 `source` 会报 `FACT_SOURCE_MISSING`。

### 测试

- 全量 **138 项通过**；新增 `test_content_and_image_truth.py` 12 项。
- 实测 256 个 `label → value`，0 条误报；构造的合计错误和正文/表格冲突都被高严重度捕获。

### 已知限制

- OCR 未集成，只做诚实降级。
- 图表/占位图重绘仍只是编排要求。
- 按角色定位图片尚未实现（v3.5.9 才加入）。

### 发布包

- 文件名：`officecli-template-filler-v3.5.8-review-docx.zip`
- 大小：264,510 字节
- SHA-256：`f42d004a98964bcb06bb6725a94dcb768b565ee22af750d700aae2a364411b94`

---

## v3.5.7（2026-11-03，正式版）

### 这个版本解决了什么

以前 `REFORMAT` 只有声明，没有执行入口；用户想“按模板统一格式”，只能得到 `CAPABILITY_NOT_AVAILABLE`。这个版本正式启用 REFORMAT，并补上 WPS / LibreOffice 的 PDF 渲染路径。

### 用户能感受到的变化

- `reformat_document.py` 可以先生成格式差异清单，再应用为带 Word 格式修订的 `.docx`。
- 差异分成四类：`AUTO_FIX`（能安全自动修）、`REVIEW`（需要人看）、`KEEP`（新增内容，不和模板硬比）、`UNSUPPORTED`（列数不一致等）。
- plan-only 模式不写任何输出；apply 模式走事务，包检查通过但仍有待审项时状态为 `PENDING_HUMAN_REVIEW`。
- 自动检测 WPS `kwpsconvert` 和 LibreOffice `soffice`，转换在临时副本上进行，避免源文件被锁。
- 页数优先用 PyMuPDF 读取；没有时用 WPS `pdfinfo` 读取真实页数。
- WPS 未登录或无 VIP 时明确报 `WPS_VIP_REQUIRED`，不静默降级。

### 同时包含 v3.5.6 的修复

- `.docx` + `.xlsx` 不再无条件判为 `MERGE`。
- 语义对齐检查：GENERATE 用 `STYLE_GUIDE`，REPAIR / REVIEW 用 `REPLICA`。
- 只有 `high` 是硬失败，`medium` / `low` 进入警告。
- 中英文字体名归一，修掉“已安装却报缺失”。
- 文件锁报告占用 PID；清理脚本只终止指定 PID，不做全局强杀。

### 测试

- 全量 **126 项通过**；新增 `test_p0_semantic_qa.py` 8 项、`test_reformat_and_pdf.py` 7 项。
- 实测培养方案样例：差异清单 37 条，自动可修 2 条，其余进入 REVIEW / KEEP。

### 已知限制

- REFORMAT 只自动应用 `AUTO_FIX`，其余需要人工确认。
- PDF 渲染依赖本机 WPS / LibreOffice。
- `POLISH` / `MERGE` 仍不可用。

### 发布包

- 文件名：`officecli-template-filler-v3.5.7-review-docx.zip`
- 大小：245,673 字节
- SHA-256：`181d58c35cff85916da539721bd7e397dba28fa035e24851947cae4f5ab4efea`

---

## v3.5.6（2026-11-03，未单独发布）

> 状态：没有独立 tag 和 Release，内容随 v3.5.7 一起发布。

### 这个版本解决了什么

- 路由：`.docx` + `.xlsx` 不再无条件判为 `MERGE`；生成意图下 `.xlsx` 是数据源，主模式是 `GENERATE`。
- 语义对齐：段落按文本锚点和标题级别匹配，表格按表题、首行、列数、网格几何匹配；新增内容标为 `NEW_CONTENT` / `NEW_TABLE`，不再拿相邻段落硬比。
- 严重级门禁：只有 `high` 是硬失败，`medium` / `low` 进入警告；样例从 2209 条硬失败降为 0 条硬失败。
- 字体名归一：黑体↔SimHei、仿宋↔FangSong、宋体↔SimSun、Courier↔Courier New。
- 文件锁：返回 `OUTPUT_FILE_LOCKED` 和占用 PID；清理脚本只终止指定 PID。

### 测试

- **119 项通过**（新增 8 项 P0 回归测试）。

---

## v3.5.5（2026-11-02，正式版）

### 这个版本解决了什么

全链路验证发现两个问题：

1. 同一段落里既有格式修复又有文字修订时，拆分 Run 会把同一个格式修订 ID 复制到多个副本，导致审阅完整性检查报“重复修订 ID”，审阅事务被中止。
2. 版面检查把修订拆分后的 Run 数量和批注段落也算进去，导致合法的审阅文档被判 `FAILED`。

### 用户能感受到的变化

- 每个修订 ID 保持唯一，审阅文档可以正常提交。
- 版面检查改为“接受修订后”的视图，忽略被删除内容和批注引用，合并同格式相邻 Run。
- 20 个端到端场景全部通过：生成（含负向中止）、修复、审阅、校对、Excel、输入路由、能力拦截、进程清理日志。

### 测试

- **111 项全部通过**。

### 已知限制

- v3.5.4 的发布包不包含本次修复，请使用 v3.5.5。

### 发布包

- 文件名：`officecli-template-filler-v3.5.5-review-docx.zip`
- 大小：212,606 字节
- SHA-256：`a0ac052025d462565419eed825beefc5e1023f8a507e461cd498c7b3a118e66d`

---

## v3.5.4（2026-11-02，正式版）

### 这个版本解决了什么

- 移除“基线差集即所有权”的进程清理回退逻辑。只有明确记录为本次任务启动的 PID 才会被终止；无法证明归属的进程保留。
- 生成文档提交前同时运行包完整性检查和格式检查；修复文档新增对照参考模板的格式检查。
- 存在无法执行的检查时返回 `UNVERIFIED`，不再让 `PENDING_HUMAN_REVIEW` 掩盖覆盖缺口。
- 修正不存在的函数名、错误的 `--target` 参数、导入示例和测试数量。

### 测试

- **109 项全部通过**。

### 已知限制

- 发布包不包含 v3.5.5 的修复，请优先使用 v3.5.5。

### 发布包

- 文件名：`officecli-template-filler-v3.5.4-review-docx.zip`
- 大小：210,860 字节
- SHA-256：`d54ec22d160bfda99dd58599cd630609b09cb0a7574a1180d9680b81b056959b`

---

## v3.5.3（2026-11-02，正式版）

### 这个版本解决了什么

增加执行档位、培养方案语义预检、分阶段检查点，以及渲染和目录降级规则。

### 用户能感受到的变化

- 写入前统一选择 `FAST` / `STANDARD` / `FULL` 档位，档位只改变处理范围，不降低安全检查要求。
- 培养方案任务会预检培养层次、目录与正文标题、跨表课程名称/代码、学分学时、学期数、占位图、过期目录页码。
- 课程数据以单一 `curriculum_ssot` 派生，跨表校验统一使用精确小数。
- 正文、表格、图片、目录分阶段保存检查点，失败时从最近的有效检查点恢复。
- 每阶段只允许一次有界渲染；失败后降级到包/OOXML/版面检查。
- 无法刷新目录域时标记 `PENDING_FIELD_UPDATE`；估算页码标记 `ESTIMATED`。

### 测试

- **106 项全部通过**。

### 已知限制

- 本版本新增的是 Skill 编排规范，复用已有底层引擎能力；尚无执行入口的编排项不代表已新增引擎实现。
- 发布包早于一个 QA 修复，已被 v3.5.4 取代。

### 发布包

- 文件名：`officecli-template-filler-v3.5.3-review-docx.zip`
- 大小：784,410 字节
- SHA-256：`c1ed3fb9f7b017a631fb16c4b9535fcbd097f881e629921992ea6518028df0b0`

---

## v3.5.2（2026-11-02，正式版）

### 这个版本解决了什么

完成 v3.5 计划的 M4–M9：Excel 可靠性、版面指纹、进程所有权、PROOFREAD 和合并单元格安全写入。同时包含 v3.5.0 的事务层与能力注册表。

### 用户能感受到的变化

- Excel 公式平移改用 openpyxl 官方解析器，字符串常量和跨表引用不再被正则误改。
- 每个公式单元格有 `formula_status`：`VERIFIED` / `FAILED` / `UNSUPPORTED` / `NOT_RECALCULATED`；后两类计入未验证。
- 新增 Excel 对象预检：扫描 VBA、ActiveX、Power Query、透视表、切片器、外部连接、图表；可能丢失时以 `OBJECT_LOSS_RISK` 拒绝生成。
- 新增版面指纹检查：字号/字体漂移、对齐/缩进漂移、表格列宽比例差超过 5%。
- 进程身份改为 `(pid, image, creation_time)`；只终止能证明由本任务启动的进程。
- 新增 PROOFREAD 模式，用于单文档校对，输出带修订的 `.docx` 和快照。
- 合并单元格只在拓扑一致、合并区域至多一个非空文本、且不含修订/批注锚点时写入，否则降级为 `manual_required`。
- 修复“模板 12pt 被写成 11pt”的长期偏差。

### 测试

- **101 项全部通过**。

### 已知限制

- 结构化引用、外部工作簿、`INDIRECT` / `OFFSET` 返回 `UNSUPPORTED_*`。
- 内置评估器无法计算的公式计为未验证。
- 复杂 Excel 对象无法保留。

### 发布包

- 文件名：`officecli-template-filler-v3.5.2-review-docx.zip`
- 大小：199,309 字节
- SHA-256：`f0bb09b695bdc84cba774f0747544cd421c1bfe1e7082421f3787355a41ab71f`

---

## v3.5.0（2026-11-02，未单独发布）

> 状态：没有独立 tag 和 Release，内容随 v3.5.2 发布（v3.5.2 代码中包含 `engine/transaction.py` 和 `engine/capabilities.py`）。

### 这个版本解决了什么

主题是“可验证、可回滚、可解释”：

- 生成、Excel、修复、审阅、渲染统一改为 `Preflight → 暂存 → QA → 原子提交`。
- 修订动作（接受/拒绝/恢复）走同一事务；未发生改动时不产出文件。
- 格式修订使用 `w:rPrChange` / `w:pPrChange` / `w:tblPrChange` / `w:trPrChange` / `w:tcPrChange`，可程序化接受或拒绝。
- 审阅同时产出修订快照；缺少快照返回 `SNAPSHOT_MISSING`，定位失效返回 `LOCATION_LOST`。
- 表格签名增加行数、行高、`tblLook`、band、`tblInd`、`tblCellSpacing`。
- 新增能力注册表；未实现模式返回 `CAPABILITY_NOT_AVAILABLE`，不支持的输入返回 `UNSUPPORTED_INPUT`。
- 新增 Excel 模板分析入口 `analyze_excel_template.py`。

### 测试

- **83 项全部通过**。

---

## v3.4.2（2026-11-01，正式版）

### 这个版本解决了什么

- 修订 ID 直接记录真实分配值，和 DOCX 里的 `w:id` 严格一致。
- 跟踪修订只在连续纯文本 Run 组内进行；超链接、内容控件、域容器位置不变；含绘图、域代码、脚注引用的 Run 拒绝拆分，降级为批注。
- 支持 `location_id` 精确寻址和 `occurrence` 指定第几处；多处匹配但未指定位置时拒绝自动修改，写入批注。
- `.xlsm` 使用 `keep_vba=True`、`keep_links=True` 加载，强制输出 `.xlsm`；Excel 检查对照原始模板。
- 内置评估器无法计算的公式计入未验证；`SUBTOTAL` 按功能码分派。
- 新增 QA 第四态 `UNVERIFIED`。

### 测试

- **50 项全部通过**。

### 已知限制

- 表格合并属性不自动改写；恢复后仍有差异时状态为 `PARTIALLY_APPLIED`。

### 发布包

- 文件名：`officecli-template-filler-v3.4.2-review-docx.zip`
- 大小：196,345 字节
- SHA-256：`b5104d441407c7a50231e6cdabe67362b02be69fe4fdcfecf5e032bb915ec07e`

---

## v3.4.1（2026-11-01，正式版，归档包）

### 这个版本解决了什么

以前审阅时恢复格式，文档里没有任何修改痕迹。这个版本把格式恢复写成 Word 原生格式修订：

- `w:rPrChange`、`w:pPrChange`、`w:tblPrChange`、`w:trPrChange`、`w:tcPrChange`
- 修订标记里保存修改前的属性，人工可以在修订窗格逐条接受或拒绝
- 新增 `list_format_revisions()`
- 修订标记按 OOXML schema 顺序插入，避免 Word/WPS 打开时弹修复提示

### 说明

- 仓库没有 v3.4.1 的源码快照，因此没有 `v3.4.1` 源码 tag，只有归档 tag `v3.4.1-archive`。
- 归档包里的 `engine.__version__` 实际为 3.4.2。
- REPAIR 仍然是直接修复，不写修订痕迹。

### 发布包

- 文件名：`officecli-template-filler-v3.4.1-review-docx.zip`
- 大小：190,582 字节
- SHA-256：`8702c8c9df4acf4c0f306752996788da483ae54abe171fc40643a3eeca1732a0`

---

## v3.4.0（未单独发布）

> 状态：没有独立 tag 和 Release，内容包含在 v3.4.2 中（v3.4.2 代码里已有 `list_revisions()` 等接口）。

### 这个版本解决了什么

- 表格逐单元格字体/字号一致性：新增 `table_cell_font_or_size` 差异，恢复时复制模板的段落标记和运行字体属性。
- 逐单元格结构：记录 `tcW` / `gridSpan` / `hMerge` / `vMerge` / `tcMar`，差异定位到表格 / 行 / 列 / 属性。
- 修订生命周期：`list_revisions()`、`accept_revision()`、`reject_revision()`、`restore_revision()`。
- 表格样式档案：`save_table_style_profile()` / `load_table_style_profile()`。
- 视觉与字体风险：报告 `FONT_NOT_INSTALLED`、`RENDER_PAGE_COUNT_MISMATCH`、`RENDER_PAGE_PIXEL_DIFF`；无法验证时记入 `coverage_gaps`。

---

## v3.3.1（未单独发布）

> 状态：没有独立 tag 和 Release，内容包含在 v3.4.2 中。

### 这个版本解决了什么

- 明确 REVIEW 的最终交付物必须是可在 Word / WPS 中以修订模式打开的 `.docx`；Markdown / JSON 只能作为内部中间产物。
- 未定位的文本修订不再静默丢弃，转为 Word 原生批注。
- QA 支持三态 `PASSED` / `FAILED` / `PENDING_HUMAN_REVIEW`，并输出结构化 `issues`、`coverage_gaps`、`unverified_count`。
- 移除业务校验中的 `assert`，改用 `SSOTValidationError` / `QAValidationError`，确保 `python -O` 下校验仍然生效。
