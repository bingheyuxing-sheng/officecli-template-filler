# officecli-template-filler 版本事实清单

> 调查日期：2026-11-07（Asia/Shanghai）
> 调查对象：`bingheyuxing-sheng/officecli-template-filler`
> 调查范围：GitHub Releases、Git Tags、README、CHANGELOG、SKILL、AGENTS、`references/`、版本对应代码与测试
> 本阶段未修改 README.md、CHANGELOG.md、SKILL.md、AGENTS.md，也未修改任何线上 Release。

## 0. 调查方法与证据优先级

本次调查使用了以下证据，按优先级从高到低排列：

| 级别 | 证据 | 本次获取方式 |
|---|---|---|
| E1 | 对应版本的实际代码 | `git show <tag>:<path>`、`git ls-tree` |
| E2 | 对应版本的测试 | `git ls-tree <tag> tests`、在 tag 上运行测试记录 |
| E3 | Git 提交与 Tag | `git log`、`git for-each-ref`、`git ls-remote --tags origin` |
| E4 | GitHub Release 原始说明与资产 | GitHub API `repos/.../releases`、`gh release view` |
| E5 | CHANGELOG、README、SKILL、AGENTS | 仓库文件 |

本次在**当前工作区 HEAD**（`37ec46f`）实际运行了：

- 全量测试：`py -3.15 -m unittest discover -s tests -p "test_*.py"` → **Ran 653 tests in 223.452s — OK**
- 契约测试：`py -3.15 -m unittest discover -s tests/contracts -t tests -p "test_*.py"` → **Ran 72 tests in 1.333s — OK**
- 当前 `engine.__version__` → **4.2.0**

> 注意：当前工作区比 `origin/main` 多 4 个未发布提交（W5 后端骨架），并且有 2 个未提交的文件改动。上述 653 项是**本地未发布状态**的结果，不等于任何已发布版本的测试数。

---

## 1. 结论摘要

1. **公开可下载的最新稳定版是 v4.0.1**（GitHub `releases/latest` 返回 `v4.0.1`）。
2. **v4.1.2 已于 2026-11-07 以 Pre-release 发布**；v4.1.1 是更早的公开 Pre-release；**v4.1.0 仍是 Draft**（未公开）。
3. 阶段二曾发现 README 把 v4.1.2 当作“当前版本 / 稳定版候选”，但当时普通用户在 Releases 页面看不到 v4.1.2；该问题已在发布后更新 README/CHANGELOG。
4. README 历史表把 v4.1.0 写成“本地构建包”，实际线上存在一个 **Draft Release**（资产已上传但未发布）；v4.1.1 明明有公开 Pre-release，历史表却没有链接。
5. **v4.0.2 只有 CHANGELOG 条目和版本号提交**，没有 tag、没有 Release、没有构建包；README 写的“本地构建包”无法验证。
6. 当前工作区代码已把版本号改为 **4.2.0**（含 SKILL 标题和契约测试断言），但 CHANGELOG 的 Unreleased 仍写“软件版本保持 4.1.2”；这是一个未登记的版本号变化。
7. 四个 Release 说明中的“对应提交”在当前仓库历史中**不存在**（`8a4f7ab`、`b4b1625`、`92908c7`、`99ffbbe`、`c5fe9a8`），与当前 tag 指向不一致，疑似历史重写后未同步。
8. 测试基线在文档中出现 **479 / 532 / 535 / 648 / 653** 五个不同数字，需要统一口径。
9. “46 份真实 `.docx`”评测属于 **v4.0.0** 的证据；v4.1.1 Release 明确说明未在 W4 链路重跑真实语料；阶段二已在 README 中注明 v4.1.x 未重跑。
10. `v3.3.1`、`v3.4.0`、`v3.5.0`、`v3.5.6` **没有独立 Release**；其中 v3.5.0/v3.5.6 的内容可以在后续版本代码/说明中找到证据，v3.3.1/v3.4.0 只有 CHANGELOG 记录。`v3.5.1` 没有任何记录。

---

## 2. 三类版本号必须分开

项目同时存在三种“版本号”，发布说明中必须明确区分：

| 类型 | 当前值 / 历史 | 定义位置 | 说明 |
|---|---|---|---|
| **软件版本** | `4.1.2`（已发布基线）；工作区 `4.2.0`（未发布） | `engine/__init__.py::__version__`、Git tag、Release tag | 用户理解的“版本号” |
| **契约集版本** | `4.0.0` → `4.1.0` → `4.2.0` → `4.3.0` | `contracts/README.md` | 公共接口契约的集合版本，不是软件版本 |
| **产物 Schema 版本** | `schema_version: "4.0"`；W4 三个新 Schema 为 `1.0` | `schemas/*.schema.json` | 生成的 JSON 产物格式版本 |

补充事实：

- 契约集 `4.3.0` 由 W0 五份契约 + CP-W2-001（页眉/页脚位置语法，4.1.0）+ CP-W2-002（`sdt` 位置语法，4.2.0）+ Contract 06（Template Understanding Gate，4.3.0）组成，均为加法变更。
- `contracts/01-slot-id.md`、`02-document-spec.md` 等文件头仍写 `FROZEN (4.2.0)`，这是单份契约的最后修改版本；契约集 README 写 `4.3.0`。两者不矛盾，但容易误读。
- `references/compatibility-v3.5.9.md` 仍写 “Current contract set: 4.2.0”，是过时信息。

---

## 3. 版本总表

状态图例：

- **Latest**：GitHub 当前 Latest stable。
- **正式版**：Published，非 Pre-release、非 Draft。
- **预发布**：Published Pre-release。
- **Draft**：GitHub Draft，未公开。
- **未发布**：只有本地 tag / 本地包 / CHANGELOG，没有公开 Release。
- **未单独发布**：没有独立 tag/Release，内容并入后续版本。

| 版本 | `engine.__version__`（tag 上） | GitHub Release | 状态 | 发布时间（北京时间） | Tag → Commit | 下载资产 | 当时测试记录 |
|---|---|---|---|---|---|---|---|
| v4.1.2 | 4.1.2 | 有 | **预发布** | 2026-11-07 10:25 | `v4.1.2`（轻量）→ `bd9a2d6` | zip 997,540 字节 | 535 |
| v4.1.1 | 4.1.1 | 有 | **预发布** | 2026-11-06 14:43 | `v4.1.1`（附注）→ `c508a4c` | zip 993,950 字节 | 532 |
| v4.1.0 | 4.1.0 | 有 | **Draft** | 未发布；Draft 创建于 2026-11-06 13:18 | `v4.1.0`（附注）→ `1f2685c` | zip 992,825 字节 | 532 |
| v4.0.2 | 4.0.2（提交） | 无 | **未发布** | 无 | 无 tag；版本提交 `e4439d4` | 无 | 479 |
| v4.0.1 | 4.0.1 | 有 | **Latest 正式版** | 2026-11-05 22:06 | `v4.0.1`（附注）→ `2b5d41a` | zip 939,039 字节 + `.sha256` | 479 |
| v4.0.0 | 4.0.0 | 有 | **正式版** | 2026-11-05 21:21 | `v4.0.0`（附注）→ `c3cf9f2` | zip 923,924 字节 + `.sha256` | 479 |
| v4.0.0-dev.1 | 3.5.9 | 有 | **预发布** | 2026-11-05 20:06 | `v4.0.0-dev.1`（附注）→ `293ebcf` | zip 886,351 字节 + `.sha256` | 450 |
| v3.5.9 | 3.5.9 | 有 | **正式版** | 2026-11-04 18:44 | `v3.5.9`（轻量）→ `fed6f6b` | zip 305,704 字节 | 186 |
| v3.5.8 | 3.5.8 | 有 | **正式版** | 2026-11-04 14:47 | `v3.5.8`（轻量）→ `e39dd7c` | zip 264,510 字节 | 138 |
| v3.5.7 | 3.5.7 | 有 | **正式版** | 2026-11-03 20:49 | `v3.5.7`（轻量）→ `097156b` | zip 245,673 字节 | 126 |
| v3.5.6 | — | 无 | **未单独发布**（并入 v3.5.7） | 无 | 无独立 tag | 无 | 119 |
| v3.5.5 | 3.5.5 | 有 | **正式版** | 2026-11-02 21:16 | `v3.5.5`（附注）→ `e8053b5` | zip 212,606 字节 | 111 |
| v3.5.4 | 3.5.4 | 有 | **正式版** | 2026-11-02 20:26 | `v3.5.4`（附注）→ `63bf9c3` | zip 210,860 字节 | 109 |
| v3.5.3 | 3.5.3 | 有 | **正式版** | 2026-11-02 09:28 | `v3.5.3`（附注）→ `17d68f4` | zip 784,410 字节 | 106 |
| v3.5.2 | 3.5.2 | 有 | **正式版** | 2026-11-02 08:56 | `v3.5.2`（附注）→ `b1358ea` | zip 199,309 字节 | 101 |
| v3.5.1 | — | 无 | **无任何记录** | 无 | 无 | 无 | 无 |
| v3.5.0 | — | 无 | **未单独发布**（并入 v3.5.2） | 无 | 无独立 tag | 无 | 83 |
| v3.4.2 | 3.4.2 | 有 | **正式版** | 2026-11-01 23:56 | `v3.4.2`（附注）→ `69f0c86` | zip 196,345 字节 | 50 |
| v3.4.1 | 3.4.2（归档 tag 上） | 有 | **正式版（归档包）** | 2026-11-01 23:56 | `v3.4.1-archive`（轻量）→ `69f0c86` | zip 190,582 字节 | 无独立记录 |
| v3.4.0 | — | 无 | **未单独发布**（内容在 v3.4.2） | 无 | 无独立 tag | 无 | 无 |
| v3.3.1 | — | 无 | **未单独发布**（内容在 v3.4.2） | 无 | 无独立 tag | 无 | 无 |

> 总表口径：`engine.__version__` 取自 `git show <tag>:engine/__init__.py`。`v3.4.1` 没有源码 tag，只有一个归档 tag，因此该行显示的是归档 tag 指向提交里的版本号 `3.4.2`。

---

## 4. 逐版本事实记录

### 4.1 v4.1.2（预发布，稳定版候选补丁）

| 项目 | 内容 |
|---|---|
| 版本号 | 软件 4.1.2；契约集 4.3.0；产物 `schema_version` 4.0 |
| 发布时间 | 2026-11-07 10:25（GitHub `publishedAt`） |
| 发布状态 | **Pre-release（已发布）**：`isDraft=false`、`isPrerelease=true`、`isLatest=false` |
| 主要目标 | 为 REVIEW 增加“外部证据批注”路径，让 Excel/JSON 检查结果能直接写进目标 Word 文档 |
| 新增功能 | `review_document.py --findings`：把外部 findings 转为目标正文的内联批注；无法定位时返回 `COMMENT_LOCATION_UNRESOLVED`；`build_findings_review_plan()`；新增 `tests/test_review_findings.py` |
| 功能优化 | SKILL 与 `references/engine-internals.md` 明确：REVIEW 交付物必须是目标方案正文，不再交付独立的“核查报告” .docx |
| 问题修复 | 无独立修复项；以新增路径和交付物约束为主 |
| 已知限制 | W4 独立出口审查仍未完成；未在 W4 链路重跑真实语料；SDT 内填充仍不支持；本版本是 Pre-release，正式稳定版仍建议使用 v4.0.1 |
| 测试证据 | `reports/acceptance/w4-package-manifest-v4.1.2.md` 记录全量 **535 tests OK（191.921s）**、契约 72 tests OK、ruff 通过；本次未在 `v4.1.2` tag 上复跑 |
| 下载资产 | GitHub 资产 `officecli-template-filler-v4.1.2.zip`，997,540 字节，SHA-256 `c66c652ec177fcc57a3dade003fdd22d2603071405406d87ce39de5a84f23f53`；已下载复算，哈希一致 |
| 对应提交 | 轻量 tag `v4.1.2` → `bd9a2d6`（tag 已推送） |
| 证据来源 | E1 `engine/__init__.py`；E2 `tests/test_review_findings.py`（3 个测试方法）；E3 `git tag/rev-parse`、`git ls-remote`；E4 Release 与资产；E5 CHANGELOG v4.1.2 段 |

### 4.2 v4.1.1（公开 Pre-release，Skill 文档优化）

| 项目 | 内容 |
|---|---|
| 版本号 | 软件 4.1.1；契约集 4.3.0；`schema_version` 4.0 |
| 发布时间 | 2026-11-06 14:43（GitHub `publishedAt`） |
| 发布状态 | **Pre-release（公开）**，不是 Latest |
| 主要目标 | 精简 Skill 文档、把工作流细节下沉到 `references/`，不改变运行时行为 |
| 新增功能 | 新增 `references/workflow-details.md`，承接事务、checkpoint、渲染/TOC 降级、QAReport 语义与 content-truth 代码表 |
| 功能优化 | `SKILL.md` frontmatter description 从 900+ 字符压缩到 376 字符；顶部改为“四步启动检查 + Operating contract + Resource map”；补充 W4 模板闸门 CLI 表；目录树更新 |
| 问题修复 | 无运行时修复；只同步版本行与文档结构 |
| 已知限制 | 官方明确标注为 Pre-release / 稳定版候选；W4 出口评审仍是 `CONDITIONAL_PASS`，独立 Agent 07 复跑未完成；Release 说明写明已安装 Skill 副本 `.trae/skills/officecli-template-filler` 仍为 v4.0.0；未在 W4 链路重跑真实语料；SDT 内填充不支持 |
| 测试证据 | Release 记录全量 **532 tests（454.570s）OK**、契约 72 tests OK、ruff 通过；`w4-package-manifest-v4.1.1.md` 记录 532 |
| 下载资产 | `officecli-template-filler-v4.1.1.zip`，993,950 字节，SHA-256 `f994ef64fdf347085dcab9376ec27bc267b27c355063c5371e8d84ed0ce1712c` |
| 对应提交 | 附注 tag `v4.1.1` → `c508a4c` |
| 证据来源 | E1/E3 tag；E4 Release 与资产；E5 CHANGELOG v4.1.1 段 |

### 4.3 v4.1.0（Draft，Template Understanding Gate）

| 项目 | 内容 |
|---|---|
| 版本号 | 软件 4.1.0；契约集 4.3.0（新增 Contract 06）；`schema_version` 4.0 |
| 发布时间 | **未发布**；Draft 创建于 2026-11-06 13:18 |
| 发布状态 | **Draft**（`isDraft=true`、`publishedAt=null`），未公开 |
| 主要目标 | 交付 W4 Template Understanding Gate：在修改模板前先理解模板并让用户确认 |
| 新增功能 | Contract 06；`template_gate/` 十个模块；3 个新 Schema；`scripts/template_gate.py` 的 analyze/report/resolve/confirm/reject/status；7 个闸门错误码；执行入口强制校验；SKILL Step 1.5 |
| 功能优化 | `GENERATE / REPAIR / REFORMAT / REVIEW` 在无有效 `CONFIRMED` Gate Record 时停止；PROOFREAD / EXCEL_GENERATE / 等保持原行为 |
| 问题修复 | 无独立修复项；以闸门能力为主 |
| 已知限制 | W4 独立出口审查未完成；证据包由主智能体生成，不能称为 Agent 07 PASS；补充材料不复制入仓；闸门只覆盖 DOCX 模板相关模式 |
| 测试证据 | Release 与 CHANGELOG 记录全量 **532 项通过**、契约 70+ 项；`reports/acceptance/w4-9-exit-review.md` 记录 532 tests / 72 contract tests / ruff 通过；本次未在 tag 上复跑 |
| 下载资产 | Draft 资产 `officecli-template-filler-v4.1.0.zip`，992,825 字节，SHA-256 `6451954c14258fb78b17f7b6eb9938a5d1ac490cbb73ec5e88fb423068c7f71a`（未公开） |
| 对应提交 | 附注 tag `v4.1.0` → `1f2685c` |
| 证据来源 | E1 `template_gate/`；E2 `tests/` W4 用例；E3 tag；E4 Draft Release；E5 CHANGELOG v4.1.0、`reports/acceptance/w4-9-exit-review.md` |

### 4.4 v4.0.2（未发布，供应链清理）

| 项目 | 内容 |
|---|---|
| 版本号 | 软件 4.0.2；契约集 4.2.0；`schema_version` 4.0 |
| 发布时间 | **未发布** |
| 发布状态 | **未发布**。没有 tag、没有 Release、没有构建包 |
| 主要目标 | 移除两个会从第三方镜像下载并执行文件的安装脚本，清理 `dist/` 历史归档，并修复静态检查问题 |
| 新增功能 | 无用户新增功能 |
| 功能优化 | `SKILL.md` 架构细节下沉、正文精简；新增 `ruff.toml` 并清理 lint 问题；测试断言收窄 |
| 问题修复 | 删除 `scripts/ensure-officecli.ps1` / `.sh`（供应链风险）；清空 `dist/` 下 13 个历史归档 zip |
| 已知限制 | 没有公开版本、没有安装包；普通用户无法获取该版本 |
| 测试证据 | CHANGELOG 记录全量 **479 项通过**、0 失败、0 跳过；本次未复跑 |
| 下载资产 | 无 |
| 对应提交 | 版本提交 `e4439d4`（`release(v4.0.2): bump version for the supply-chain cleanup patch`），无 tag |
| 证据来源 | E1 `engine/__init__.py` at `e4439d4`；E3 commit；E5 CHANGELOG v4.0.2 段 |

### 4.5 v4.0.1（Latest 稳定版补丁）

| 项目 | 内容 |
|---|---|
| 版本号 | 软件 4.0.1；契约集 4.2.0；`schema_version` 4.0 |
| 发布时间 | 2026-11-05 22:06 |
| 发布状态 | **正式版**，GitHub 当前 **Latest** |
| 主要目标 | 关闭独立出口审查阻断项 B1，统一测试计数，补齐真实语料报告可复现信息 |
| 新增功能 | 无独立新功能；执行器 `data` 增加 `coverage_gaps` 证据字段 |
| 功能优化 | 文档测试计数统一为 479；真实语料报告记录运行命令、参数、环境与时间；JSON/报告补充 `coverage_gaps` 与 `missing_checks` |
| 问题修复 | 删除测试代码中残留的外部语料正文与来源措辞，改用合成文本；仓库与发布包不再包含语料路径、文件名或正文 |
| 已知限制 | 阻断项 B2 未完全关闭：Linux 环境未验证；v4.0.1 独立复核待执行；真实语料无人工标注基线；SDT 内填充不支持；浮动图片 QA 为 `UNVERIFIED`；本机缺 PyMuPDF / matplotlib / OCR |
| 测试证据 | Release 记录工作树 479 tests OK（173.0s）、发布包 479 tests OK（171.6s）、LibreOffice 定向 34 tests OK、全量 479 OK（182.1s）、真实语料复跑 46/46 解析、21/21 填充提交 |
| 下载资产 | zip 939,039 字节，SHA-256 `106a96fe7a6c4fa2953e7a2f11c9586d5c327bc976f33a0eec30cbc090706bb2`；另有 `.sha256` 文件 |
| 对应提交 | 附注 tag `v4.0.1` → `2b5d41a`；Release 说明写“源提交 `b4b1625`、tag 指向 `92908c7`”，这两个提交在当前仓库中不存在（见冲突 C-05） |
| 证据来源 | E1/E2 tag；E3 tag；E4 Release 与资产；E5 CHANGELOG v4.0.1 段、`reports/acceptance/w3-14-package-manifest-v4.0.1.md` |

### 4.6 v4.0.0（首个 v4 稳定版）

| 项目 | 内容 |
|---|---|
| 版本号 | 软件 4.0.0；契约集 4.2.0；`schema_version` 4.0 |
| 发布时间 | 2026-11-05 21:21 |
| 发布状态 | **正式版**（发布时曾为 Latest，现被 v4.0.1 取代） |
| 主要目标 | 发布 v4 文档主链：DocumentSpec 4.0 → ContentPlan/FillPlan → 事务执行 → QA/门禁 → 原子提交；用 46 份真实 `.docx` 做无损评测 |
| 新增功能 | v4 主链；真实语料评测工具（`--corpus` 运行时传入）；46 份真实模板验证；GENERATE 视觉检查使用 `STYLE_GUIDE` 档位 |
| 功能优化 | 授权文本填充原位替换、保留被清空的 run；`red_run_clue` / `internal_fact` 不再回退 strict-style；STANDARD 下 `UNVERIFIED` + 覆盖缺口可按契约提交；QA Pipeline 区分内容驱动警告与硬指标 |
| 问题修复 | 修复真实模板误报 `UNAUTHORIZED_TEMPLATE_CHANGE`；修复 `audit_format_and_text_qa(raise_on_failure=False)` 仍抛包完整性异常；Excel 大工作簿只读扫描、图表解析异常回退 |
| 已知限制 | 真实语料无脱敏/人工标注，不计算槽位 P/R/F1；SDT 内填充不支持；浮动图片、域更新、OLE、SmartArt、矢量图以 `UNSUPPORTED` / `UNVERIFIED` 披露；Linux/LibreOffice 未验证；独立 Agent 07 复查未执行；发布包 `SKILL.md` 目录树仍写 473 项（实际 479） |
| 测试证据 | Release 记录全量 **479 tests OK（175.8s）**、发布包解包 479 OK（173.4s）；真实语料 46/46 解析、21/21 填充提交、0 模板字节改动、12 PASSED / 9 UNVERIFIED |
| 下载资产 | zip 923,924 字节，SHA-256 `2c22cf4c20ebfb571516a9f2e11e7e0e725e3c7fbe983d78ea42497367207719`；另有 `.sha256` 文件 |
| 对应提交 | 附注 tag `v4.0.0` → `c3cf9f2`；Release 说明写“源提交 `8a4f7ab`”，该提交在当前仓库中不存在（见冲突 C-05） |
| 证据来源 | E1/E2 tag；E3 tag；E4 Release；E5 CHANGELOG v4.0.0 段、`reports/acceptance/w3-10-exit-review.md` |

### 4.7 v4.0.0-dev.1（预发布，W3 开发快照）

| 项目 | 内容 |
|---|---|
| 版本号 | tag 上 `engine.__version__` 仍为 **3.5.9**；Release 标题为 v4.0.0-dev.1；契约集 4.2.0 |
| 发布时间 | 2026-11-05 20:06 |
| 发布状态 | **Pre-release**，官方明确“不是稳定版，不是 Alpha” |
| 主要目标 | 发布 v4.0 执行链与 W3 加固的开发快照，供检查用 |
| 新增功能 | DocumentSpec 4.0、ContentPlan/FillPlan、事务执行器、QAReport 4.0、QA Gate、运行时环境能力探测；五份契约 + CP-W2-001/002；SDT fail-closed 披露、ZIP 配额、soffice 私有 profile |
| 功能优化 | GENERATE 主链切 v4 plan chain；`--data` 标注为 legacy；全量 Markdown 清理 |
| 问题修复 | W0 门禁的 COMMIT/UNVERIFIED 矛盾、QA 策略来源可伪造；W2 合并单元格列索引、嵌套表格、图片替换残留、授权缩放误报；W3 的 P1-01/P1-02/P2-01/P2-02/P2-03 |
| 已知限制 | 不是 Alpha、不是 W3 阶段完成；真实语料尚未获取/脱敏/标注；P2-01/P2-04 需审计方 Linux/LibreOffice 复跑；本机缺 PyMuPDF / matplotlib / OCR；SDT 内填充不支持 |
| 测试证据 | Release 记录 **450 tests OK**；发布包解包复跑 450 OK（171.776s） |
| 下载资产 | zip 886,351 字节，SHA-256 `91690799c13db8a1071a50b1888992179e4aac35244dfd95e0837b199490b451`；另有 `.sha256` 文件 |
| 对应提交 | 附注 tag `v4.0.0-dev.1` → `293ebcf`；Release 说明写“目标提交 `99ffbbe`”，该提交在当前仓库中不存在（见冲突 C-05） |
| 证据来源 | E1 `engine/__init__.py`（3.5.9）；E4 Release；E5 CHANGELOG v4.0.0-dev.1 段 |

### 4.8 v3.5.9（图片角色、可选 OCR、流程闭环）

| 项目 | 内容 |
|---|---|
| 版本号 | 软件 3.5.9；无 v4 契约集 |
| 发布时间 | 2026-11-04 18:44 |
| 发布状态 | **正式版** |
| 主要目标 | 补齐“文档写了但引擎没落地”的环节：内部事实槽位、REVIEW 自动文字修订、PROOFREAD 自动检查、SSOT 结构化错误、`w:proofErr` 完整性、文件锁证据，以及编排辅助 |
| 新增功能 | `find_images(role=...)` / `replace_image_by_role()`；可选 OCR；`render_chart_image()`；`engine/workflow.py`；`engine/logic_qa.py`；`engine/research.py`；`MUST_ASK_USER` 内部事实；REVIEW 自动文字 diff；PROOFREAD 自动检查 |
| 功能优化 | 合计检查支持表头行；文件锁错误增加 `cleanup_log`；图形重绘失败统一带 `needs_redraw`；包完整性新增 `w:proofErr` 配对检查 |
| 问题修复 | 修复 `find_images` 对页眉/页脚根节点漏检；修复 `w:proofErr` 不平衡未报告 |
| 已知限制 | `POLISH` / `MERGE` 无执行入口；逻辑检查是确定性启发式；research 模块不执行实际检索；视觉 QA 依赖本机 PDF 后端；SVG/EMF/WMF 只能报 `VECTOR_IMAGE_UNVERIFIED`；L4 对象只读保留；workflow 只提供 API，无 `--profile` CLI |
| 测试证据 | Release 记录全量 **186 项通过**；新增 `test_doc_gap_closure` 13、`test_workflow` 15、`test_research_logic` 9、`test_image_roles_ocr_render` 11；打包解压后复跑 186 项通过 |
| 下载资产 | zip 305,704 字节，SHA-256 `db8e3c880c1edc9adeef4c5de393f8eac819c547efcbd4d6bcae82cabc67764f` |
| 对应提交 | 轻量 tag `v3.5.9` → `fed6f6b`；Release 说明写“Commit `c5fe9a8`”，该提交在当前仓库中不存在（见冲突 C-05） |
| 证据来源 | E1/E2 tag；E3 tag；E4 Release；E5 CHANGELOG v3.5.9 段 |

### 4.9 v3.5.8（内容真值与图片真值）

| 项目 | 内容 |
|---|---|
| 版本号 | 软件 3.5.8 |
| 发布时间 | 2026-11-04 14:47 |
| 发布状态 | **正式版** |
| 主要目标 | 修复“假成功 / 假通过”，补齐图片真值和内容一致性两个盲区 |
| 新增功能 | `engine/consistency_qa.py`（内容真值 QA）；`audit_fact_sources()`；`find_numeric_occurrences()`；VML 图片替换；SVG 双嵌入清理；矢量图 `VECTOR_IMAGE_UNVERIFIED`；裁剪框/显示框处理；外部链接图片报告 |
| 功能优化 | `run_qa.py` 默认执行内容 QA；报告返回 `label_values`；引用计数同时统计 `a:blip` / `asvg:svgBlip` / `v:imagedata` |
| 问题修复 | SVG 双嵌入残留导致“换图后仍显示旧图却报告成功”；矢量图既不报错也不报缺口；VML 图片完全不支持；共享图误判独占；`r:link` 静默跳过 |
| 已知限制 | OCR 未集成（只做诚实降级）；图表/占位图重绘只是编排要求；按角色定位图片尚未实现（v3.5.9 才加入） |
| 测试证据 | Release 记录全量 **138 项通过**；新增 `test_content_and_image_truth.py` 12 项；实测 256 个 `label → value`、0 条误报 |
| 下载资产 | zip 264,510 字节，SHA-256 `f42d004a98964bcb06bb6725a94dcb768b565ee22af750d700aae2a364411b94` |
| 对应提交 | 轻量 tag `v3.5.8` → `e39dd7c` |
| 证据来源 | E1/E2 tag；E3 tag；E4 Release；E5 CHANGELOG v3.5.8 段 |

### 4.10 v3.5.7（REFORMAT 与 PDF 路径，含 v3.5.6）

| 项目 | 内容 |
|---|---|
| 版本号 | 软件 3.5.7 |
| 发布时间 | 2026-11-03 20:49 |
| 发布状态 | **正式版** |
| 主要目标 | 启用 REFORMAT 模式；增加 WPS/LibreOffice PDF 渲染与真实页数测量；一并发布 v3.5.6 的路由/QA 修复 |
| 新增功能 | `engine/reformat_engine.py`、`scripts/reformat_document.py`；结构化格式差异清单；带 `w:*PrChange` 的修订应用；`engine/pdf_backend.py`；WPS `pdfinfo` 页数测量 |
| 功能优化 | 差异分类 `AUTO_FIX` / `REVIEW` / `KEEP` / `UNSUPPORTED`；plan-only 不落盘；apply 走事务；能力注册表启用 REFORMAT |
| 问题修复 | 包含 v3.5.6 修复：`.docx + .xlsx` 不再误判 MERGE、语义对齐 QA、严重级门禁、字体名归一、文件锁报告；修复 WPS 未登录/VIP 缺失静默降级 |
| 已知限制 | REFORMAT 只自动应用 `AUTO_FIX`，其余需人工；PDF 依赖本机 WPS/LibreOffice；页数测量优先 PyMuPDF，缺失时用 `pdfinfo`；`POLISH` / `MERGE` 仍不可用 |
| 测试证据 | Release 记录 **126 项全部通过**（新增 `test_p0_semantic_qa.py` 8 项、`test_reformat_and_pdf.py` 7 项）；实测培养方案样例差异清单 37 条、自动可修 2 条 |
| 下载资产 | zip 245,673 字节，SHA-256 `181d58c35cff85916da539721bd7e397dba28fa035e24851947cae4f5ab4efea` |
| 对应提交 | 轻量 tag `v3.5.7` → `097156b` |
| 证据来源 | E1/E2 tag；E3 tag；E4 Release；E5 CHANGELOG v3.5.6/v3.5.7 段 |

### 4.11 v3.5.6（未单独发布，并入 v3.5.7）

| 项目 | 内容 |
|---|---|
| 版本号 | 软件版本记录为 3.5.6；无独立 tag |
| 发布时间 | 无 |
| 发布状态 | **未单独发布**；Release v3.5.7 明确写明“v3.5.6 一并包含” |
| 主要目标 | 路由角色化、语义对齐 QA、严重级门禁、字体名归一、文件锁报告（P0 可信度修复） |
| 新增功能 | `engine/alignment.py`；`comparison_profile`（`REPLICA` / `STYLE_GUIDE`）；文件锁 `OUTPUT_FILE_LOCKED` + `lock_info.editor_sdk_pids` |
| 功能优化 | `.docx + .xlsx` 生成意图下走 `GENERATE`；`medium`/`low` 进入 warnings，只有 `high` 硬失败；中英文字体名归一；`cleanup_editor_sdk.py --kill-pid` 只终止指定 PID |
| 问题修复 | 修复 2209 条 hard failure 误报（样例降为 0 条硬失败、6 条格式警告、45 条版面警告）；修复“已安装却报字体缺失” |
| 已知限制 | 无独立下载资产；用户只能通过 v3.5.7 获取 |
| 测试证据 | CHANGELOG 记录 **119 项通过**（新增 8 项 P0 回归） |
| 下载资产 | 无独立资产；包含在 v3.5.7 的 zip 中 |
| 对应提交 | 无独立 tag；内容随 `v3.5.7`（`097156b`）发布 |
| 证据来源 | E4 v3.5.7 Release 的“路由与 QA 可信度（v3.5.6 一并包含）”段；E5 CHANGELOG v3.5.6 段 |

### 4.12 v3.5.5（REVIEW 修订 ID 与版面 QA）

| 项目 | 内容 |
|---|---|
| 版本号 | 软件 3.5.5 |
| 发布时间 | 2026-11-02 21:16 |
| 发布状态 | **正式版** |
| 主要目标 | 修复全链路验证发现的 REVIEW 修订 ID 冲突与版面 QA 误报 |
| 新增功能 | 无独立新功能；以修复为主 |
| 功能优化 | 版面指纹改为“接受修订后”视图；合并同格式相邻 Run；排除批注故事；20 个端到端场景验证 |
| 问题修复 | 同一段落格式修订 + 文字修订时 `w:id` 被复制导致 `duplicate revision ids`、REVIEW 事务中止；修订拆分后的 Run 数与批注段落导致合法 REVIEW 文档被判 `FAILED` |
| 已知限制 | Release 说明没有单独列出限制；v3.5.4 的发布包不包含本次修复，应使用 v3.5.5 |
| 测试证据 | Release 记录 **111 项全部通过** |
| 下载资产 | zip 212,606 字节，SHA-256 `a0ac052025d462565419eed825beefc5e1023f8a507e461cd498c7b3a118e66d` |
| 对应提交 | 附注 tag `v3.5.5` → `e8053b5` |
| 证据来源 | E1/E2 tag；E3 tag；E4 Release；E5 CHANGELOG v3.5.5 段 |

### 4.13 v3.5.4（进程所有权与事务 QA）

| 项目 | 内容 |
|---|---|
| 版本号 | 软件 3.5.4 |
| 发布时间 | 2026-11-02 20:26 |
| 发布状态 | **正式版**（已被 v3.5.5 取代） |
| 主要目标 | 收紧进程所有权、补齐事务 QA、修正 QA 状态与文档 |
| 新增功能 | 无独立新功能 |
| 功能优化 | 只有 `note_spawned()` 记录的 PID 才会被终止；无法证明归属的进程记入 `unowned_pids` 并保留；`generate_document.py` 提交前同时跑包完整性 QA 与格式 QA；`repair_document.py` 新增对照参考模板的格式 QA |
| 问题修复 | 修复“只跑一半检查”仍报 `PASSED`；修复存在无法执行检查时 `PENDING_HUMAN_REVIEW` 掩盖覆盖缺口；修正不存在的函数名、错误的 `--target` 参数、导入示例、测试数量 |
| 已知限制 | 发布包不包含 v3.5.5 的修复，Release 明确建议优先使用 v3.5.5 |
| 测试证据 | Release 记录 **109 项全部通过** |
| 下载资产 | zip 210,860 字节，SHA-256 `d54ec22d160bfda99dd58599cd630609b09cb0a7574a1180d9680b81b056959b` |
| 对应提交 | 附注 tag `v3.5.4` → `63bf9c3` |
| 证据来源 | E1/E2 tag；E3 tag；E4 Release；E5 CHANGELOG v3.5.4 段 |

### 4.14 v3.5.3（执行档位、语义预检、检查点）

| 项目 | 内容 |
|---|---|
| 版本号 | 软件 3.5.3 |
| 发布时间 | 2026-11-02 09:28 |
| 发布状态 | **正式版**（Release 说明明确已被 v3.5.4 取代） |
| 主要目标 | 增加 FAST/STANDARD/FULL 执行档位、培养方案语义预检、分阶段检查点、渲染/目录降级 |
| 新增功能 | 三档执行模式；培养方案模板语义预检；`curriculum_ssot` 编排约束；正文/表格/图片/目录四阶段检查点；有界渲染与目录域降级；`PENDING_FIELD_UPDATE` / `ESTIMATED` 标记 |
| 功能优化 | 档位选择与缺失信息确认合并为一次交互；失败只重做失败阶段；REVIEW 格式修订契约修正 |
| 问题修复 | 移除清理示例中会被 `python -O` 移除的 `assert` |
| 已知限制 | **本版本是 Skill 编排规范更新**，复用现有底层引擎能力；尚无执行入口的编排项不代表已新增引擎实现；发布包早于一个 QA 修复，已被 v3.5.4 取代 |
| 测试证据 | Release 记录 **106 项全部通过** |
| 下载资产 | zip 784,410 字节，SHA-256 `c1ed3fb9f7b017a631fb16c4b9535fcbd097f881e629921992ea6518028df0b0` |
| 对应提交 | 附注 tag `v3.5.3` → `17d68f4` |
| 证据来源 | E1/E2 tag；E3 tag；E4 Release；E5 CHANGELOG v3.5.3 段 |

### 4.15 v3.5.2（Excel 可靠性、版面指纹、PROOFREAD）

| 项目 | 内容 |
|---|---|
| 版本号 | 软件 3.5.2 |
| 发布时间 | 2026-11-02 08:56 |
| 发布状态 | **正式版**（包含 v3.5.0 的事务层能力） |
| 主要目标 | 完成 v3.5 计划的 M4–M9：Excel 可靠性、版面指纹、进程所有权、PROOFREAD、合并安全写入 |
| 新增功能 | PROOFREAD 第 8 种模式与 `scripts/proofread_document.py`；`engine/layout_qa.py` 版面指纹；`engine/excel_objects.py` 对象预检；`formula_status`；`restore_table_style_from_reference()` 返回拓扑结果 |
| 功能优化 | 公式平移改用 openpyxl 官方 `Translator`；XLSM 对象丢失风险预检；进程身份改为 `(pid, image, creation_time)`；清理日志按任务拆分；段落格式优先采用 run 直接字号，修复 12pt 被写成 11pt |
| 问题修复 | 修复正则改坏公式字符串/跨表引用；修复共享图片对象误判；修复模板字号偏差；修复合并单元格写入破坏内容 |
| 已知限制 | 结构化引用、外部工作簿、`INDIRECT`/`OFFSET` 返回 `UNSUPPORTED_*`；内置评估器无法计算的公式计为未验证；复杂 Excel 对象（ActiveX、Power Query、透视表、切片器）无法保留 |
| 测试证据 | Release 记录 **101 项全部通过** |
| 下载资产 | zip 199,309 字节，SHA-256 `f0bb09b695bdc84cba774f0747544cd421c1bfe1e7082421f3787355a41ab71f` |
| 对应提交 | 附注 tag `v3.5.2` → `b1358ea` |
| 证据来源 | E1 `engine/transaction.py`、`engine/capabilities.py`；E2 tag；E3 tag；E4 Release；E5 CHANGELOG v3.5.0/v3.5.2 段 |

### 4.16 v3.5.1（无记录）

| 项目 | 内容 |
|---|---|
| 版本号 | 未发现 |
| 发布时间 | 无 |
| 发布状态 | **未发现任何 tag、Release、CHANGELOG 条目或版本号** |
| 主要目标 | 无法确认 |
| 新增功能 | 无法确认 |
| 功能优化 | 无法确认 |
| 问题修复 | 无法确认 |
| 已知限制 | 版本序列从 v3.5.0 直接到 v3.5.2；v3.5.1 是否存在、是否被跳过，需要维护者确认 |
| 测试证据 | 无 |
| 下载资产 | 无 |
| 对应提交 | 无 |
| 证据来源 | E3 `git tag`、E4 Releases、E5 CHANGELOG 均无记录 |

### 4.17 v3.5.0（未单独发布，并入 v3.5.2）

| 项目 | 内容 |
|---|---|
| 版本号 | 软件版本记录为 3.5.0；无独立 tag |
| 发布时间 | 无 |
| 发布状态 | **未单独发布**；README 写“已并入 v3.5.2” |
| 主要目标 | 可验证、可回滚、可解释（M1–M3） |
| 新增功能 | 事务化交付（Preflight → 暂存 → QA → 原子提交）；修订动作事务化；格式修订 `w:*PrChange`；修订快照；能力注册表；Excel 模板分析入口 |
| 功能优化 | 表格签名增加行数、行高、`tblLook`、band、`tblInd`、`tblCellSpacing`；比较新增行高/tblLook/band 漂移；未实现模式返回 `CAPABILITY_NOT_AVAILABLE` |
| 问题修复 | 修复旧属性快照被原地改写导致 reject 无效；修复缺少快照/定位失效时的静默猜测 |
| 已知限制 | 无独立下载资产；用户只能通过 v3.5.2 获取；`POLISH` / `MERGE` 仍不可用 |
| 测试证据 | CHANGELOG 记录 **83 项全部通过** |
| 下载资产 | 无独立资产；包含在 v3.5.2 的 zip 中 |
| 对应提交 | 无独立 tag；代码证据见 `v3.5.2` 的 `engine/transaction.py`、`engine/capabilities.py` |
| 证据来源 | E1 `git ls-tree v3.5.2`；E3 log；E5 CHANGELOG v3.5.0 段、README 历史表 |

### 4.18 v3.4.2（Review 安全性与 QA 诚实性）

| 项目 | 内容 |
|---|---|
| 版本号 | 软件 3.4.2 |
| 发布时间 | 2026-11-01 23:56 |
| 发布状态 | **正式版** |
| 主要目标 | 修复 REVIEW 修订 ID、结构安全、定位安全；Excel 宏/公式；QA 第四态 |
| 新增功能 | QA `UNVERIFIED` 第四态；`revision_ids` 真实记录；`location_id` + `occurrence` 定位；XLSM `keep_vba`；`SUBTOTAL` 功能码分派 |
| 功能优化 | 跟踪修订只在连续纯文本 Run 组内进行；超链接/内容控件/域容器不移动；含绘图/域代码/脚注引用的 Run 拒绝拆分并降级批注；Excel QA 对照原始模板 |
| 问题修复 | 修复多处匹配未指定位置时误改；修复合并差异静默；修复公式不可计算却报通过 |
| 已知限制 | 表格 `gridSpan` / `hMerge` / `vMerge` 不自动改写，必要时 `PARTIALLY_APPLIED`；本版本只有 1 个测试文件、50 项测试 |
| 测试证据 | Release 记录 **50 项全部通过** |
| 下载资产 | zip 196,345 字节，SHA-256 `b5104d441407c7a50231e6cdabe67362b02be69fe4fdcfecf5e032bb915ec07e` |
| 对应提交 | 附注 tag `v3.4.2` → `69f0c86`（归档提交；源码提交为 `c47be7a`，见冲突 C-10） |
| 证据来源 | E1/E2 tag；E3 tag；E4 Release；E5 CHANGELOG v3.4.2 段 |

### 4.19 v3.4.1（归档包，无源码 tag）

| 项目 | 内容 |
|---|---|
| 版本号 | 归档 tag 上 `engine.__version__` 为 **3.4.2**；Release 标题为 v3.4.1 |
| 发布时间 | 2026-11-01 23:56 |
| 发布状态 | **正式版（归档包）** |
| 主要目标 | 保留 v3.4.1 打包文件；格式修复写入 Word 原生格式修订 |
| 新增功能 | `w:rPrChange` / `w:pPrChange` / `w:tblPrChange` / `w:trPrChange` / `w:tcPrChange`；`list_format_revisions()`；`format_revision_count` |
| 功能优化 | 修订标记按 OOXML schema 顺序插入，避免 Word/WPS 修复提示；REPAIR 仍为直接修复，不写修订痕迹 |
| 问题修复 | 修复“已修复但打开文件没有任何修改痕迹” |
| 已知限制 | 仓库没有 v3.4.1 源码快照，因此没有 `v3.4.1` 源码 tag；只有归档 tag `v3.4.1-archive`；归档包内版本号实际为 3.4.2 |
| 测试证据 | Release 没有独立测试记录；v3.4.2 累计记录 50 项 |
| 下载资产 | zip 190,582 字节，SHA-256 `8702c8c9df4acf4c0f306752996788da483ae54abe171fc40643a3eeca1732a0` |
| 对应提交 | 轻量 tag `v3.4.1-archive` → `69f0c86`（与 v3.4.2 tag 指向同一提交） |
| 证据来源 | E1/E3 tag；E4 Release 说明；E5 CHANGELOG v3.4.1 段 |

### 4.20 v3.4.0（未单独发布，内容在 v3.4.2）

| 项目 | 内容 |
|---|---|
| 版本号 | 软件版本记录为 3.4.0；无独立 tag |
| 发布时间 | 无 |
| 发布状态 | **未单独发布**；README 历史表未列出该版本 |
| 主要目标 | 表格逐单元格一致性 + 修订生命周期 |
| 新增功能 | 逐单元格字体/字号指纹；`tcW` / `gridSpan` / `hMerge` / `vMerge` / `tcMar` 记录；`list_revisions()` / `accept_revision()` / `reject_revision()` / `restore_revision()`；表格样式档案；视觉与字体风险报告 |
| 功能优化 | 差异精确定位到“表格 / 行 / 列 / 属性”；恢复时复制模板段落标记与运行字体属性 |
| 问题修复 | 修复表格单元格字体字号不一致未被发现 |
| 已知限制 | 无独立 Release/资产；只能在 v3.4.2 中获取 |
| 测试证据 | CHANGELOG 没有单独测试数；v3.4.2 记录 50 项 |
| 下载资产 | 无独立资产；包含在 v3.4.2 的 zip 中 |
| 对应提交 | 无独立 tag；代码证据见 `v3.4.2` 的 `engine/review_engine.py::list_revisions` 等 |
| 证据来源 | E1 `git show v3.4.2:engine/review_engine.py`；E5 CHANGELOG v3.4.0 段 |

### 4.21 v3.3.1（未单独发布，内容在 v3.4.2）

| 项目 | 内容 |
|---|---|
| 版本号 | 软件版本记录为 3.3.1；无独立 tag |
| 发布时间 | 无 |
| 发布状态 | **未单独发布**；README 历史表未列出该版本 |
| 主要目标 | REVIEW 交付契约与结构化 QA |
| 新增功能 | REVIEW 交付物必须是可修订的 `.docx`；未定位修订转 Word 批注；QA 三态 `PASSED` / `FAILED` / `PENDING_HUMAN_REVIEW`；结构化 `issues` / `coverage_gaps` / `unverified_count` |
| 功能优化 | 移除业务校验中的 `assert`，改用 `SSOTValidationError` / `QAValidationError`，确保 `python -O` 下仍生效 |
| 问题修复 | 修复未定位修订被静默丢弃；修复 `python -O` 下校验失效 |
| 已知限制 | 无独立 Release/资产；只能在 v3.4.2 中获取 |
| 测试证据 | CHANGELOG 没有单独测试数；v3.4.2 记录 50 项 |
| 下载资产 | 无独立资产；包含在 v3.4.2 的 zip 中 |
| 对应提交 | 无独立 tag；代码证据见 `v3.4.2` |
| 证据来源 | E1 `git grep PENDING_HUMAN_REVIEW v3.4.2`；E5 CHANGELOG v3.3.1 段 |

### 4.22 未发布工作（W5，工作区 4.2.0）

| 项目 | 内容 |
|---|---|
| 版本号 | 工作区 `engine.__version__` = **4.2.0**；CHANGELOG Unreleased 写“保持 4.1.2” |
| 发布时间 | 未发布 |
| 发布状态 | **本地未发布**；`origin/main` 仍是 `bd9a2d6`（v4.1.2），本地领先 4 个提交 |
| 主要目标 | 新增可选 officecli 写入后端和 `document_backends/` 后端适配层，默认执行链不变 |
| 新增功能 | `engine/officecli_writer.py`；`document_engine/fill_executor.py` 的 `writer="officecli"`；`scripts/generate_document.py --writer`；`document_backends/` 骨架；`tests/w5/` 104 项 |
| 功能优化 | officecli 路径遇到不支持操作时整篇回退 python-docx 并记录 `data.writer_fallback` |
| 问题修复 | `template_gate/store.py` 密钥文件改为按原始字节读取，修复 HMAC 校验随机失败 |
| 已知限制 | officecli 仅覆盖 `.docx` 的 `replace_text` / `fill_paragraph` / `fill_cell`；页眉页脚、文本框、SDT、脚注、批注、图片、Excel 均回退 python-docx；officecli 是外部闭源二进制，不自动安装 |
| 测试证据 | CHANGELOG Unreleased 记录 **648 项**；本次在当前工作区实测 **653 项 OK**（223.452s），契约 72 项 OK |
| 下载资产 | 无（`dist/` 下只有 v4.1.0/v4.1.1/v4.1.2 本地包） |
| 对应提交 | 本地 `main`：`d342fe5`、`d4d3c19`、`be95e82`、`37ec46f`（未推送） |
| 证据来源 | E1 `engine/__init__.py`；E2 `tests/w5/`；E3 `git log origin/main..HEAD`；E5 CHANGELOG Unreleased 段 |

---

## 5. 版本信息冲突

> 以下冲突只记录事实，不做单方面修正；需要人工确认后再进入阶段二。

| 编号 | 冲突内容 | 证据 | 影响 | 处理建议 | 需人工确认 |
|---|---|---|---|---|---|
| C-01 | 阶段二发现 README 把 v4.1.2 写成“当前版本 / 稳定版候选”，当时 v4.1.2 没有 GitHub Release，远程也没有 tag | 阶段二 `gh release list` 无 v4.1.2；`git ls-remote --tags` 无 v4.1.2；本地 `dist/` 有包 | 当时用户按 README 去 Releases 找不到 v4.1.2 | 已于 2026-11-07 发布为 Pre-release，并更新 README/CHANGELOG | 否 |
| C-02 | README 历史表把 v4.1.0 写成“本地构建包”，实际存在一个 Draft Release | `gh release view v4.1.0` → `isDraft=true`、资产已上传 | 读者不知道 v4.1.0 tag 已推送、包在 Draft 里 | 历史表写“Draft Release（未公开）”；决定是否发布 | 是 |
| C-03 | README 历史表把 v4.1.1 写成“本地构建包”，实际是公开 Pre-release | Release `v4.1.1` 已 Published、`isPrerelease=true` | 用户不知道 v4.1.1 可以从 Releases 下载 | 历史表链接 v4.1.1 Release 并标注 Pre-release | 否（事实清楚） |
| C-04 | README 写 v4.0.2 有“本地构建包”，但 `dist/` 没有 v4.0.2 zip，也没有 tag/Release | `Get-ChildItem dist` 只有 4.1.0/4.1.1/4.1.2；`git tag -l '*4.0.2*'` 为空 | 无法验证该版本可获取 | 删除“本地构建包”表述，或补发 v4.0.2 | 是 |
| C-05 | 四个 Release 说明中的提交号在当前仓库不存在，且与 tag 指向不一致 | v3.5.9 写 `c5fe9a8`，tag → `fed6f6b`；v4.0.0-dev.1 写 `99ffbbe`，tag → `293ebcf`；v4.0.0 写 `8a4f7ab`，tag → `c3cf9f2`；v4.0.1 写 `b4b1625` / `92908c7`，tag → `2b5d41a`；`git cat-file -t` 全部失败 | 发布说明的“可追溯提交”失效 | 阶段三已按当前 tag 指向更正；线上说明已更新 | 否 |
| C-06 | 阶段一发现工作区 `engine.__version__ = 4.2.0`、SKILL 标题 v4.2.0、契约测试断言 4.2.0，但 CHANGELOG Unreleased 写“软件版本保持 4.1.2” | `py -3.15 -c "import engine; print(engine.__version__)"` → 4.2.0；`tests/contracts/test_legacy_compat.py` 断言 4.2.0；原 CHANGELOG 第 11 行 | 未发布代码的版本号与文档不一致 | 阶段二已登记为 4.2.0（未发布），CHANGELOG/README 已更新 | 否 |
| C-07 | 测试基线有 5 个数字：479 / 532 / 535 / 648 / 653 | AGENTS 479；SKILL 目录树 532；原 README 状态表 535、测试段 532；CHANGELOG Unreleased 648；本次实测 653 | 读者无法判断哪个是当前有效基线 | README/CHANGELOG 已统一为“v4.1.2 535；当前开发分支 653”；SKILL/AGENTS/references 见 C-17 | 否 |
| C-08 | README 的 v4.1.2 状态表把“46 份真实 `.docx`”作为当前版本验证；v4.1.1 Release 明确说未在 W4 链路重跑真实语料 | README 第 16 行；v4.1.1 Release “未在 W4 链路重跑真实语料” | 读者可能误以为 v4.1.2 也完成了 46 份真实语料验证 | 标注“v4.0.0 完成的真实语料验证，v4.1.x 未重跑” | 否（事实清楚） |
| C-09 | v4.0.0-dev.1 的 tag 上 `engine.__version__` 仍是 3.5.9 | `git show v4.0.0-dev.1:engine/__init__.py` → 3.5.9 | 版本号与 Release 标题不一致 | 在历史说明中注明“开发快照，engine 版本号尚未 bump” | 否 |
| C-10 | v3.4.2 tag 指向归档提交 `69f0c86`，不是源码提交 `c47be7a`；且与 `v3.4.1-archive` 指向同一提交 | `git for-each-ref`；`git rev-parse v3.4.2^{commit}` | tag 不能直接定位 v3.4.2 源码 | 不移动已发布 tag；在发布说明中注明源码提交与归档提交 | 是 |
| C-11 | README 写 v3.5.0 “已并入 v3.5.2”，但 v3.5.2 Release 说明没有明确写“包含 v3.5.0” | README 第 224 行；v3.5.2 Release；代码 `engine/transaction.py` + `capabilities.py` 存在 | 读者无法从 Release 确认合并关系 | 在 v3.5.2 说明中补一句“包含 v3.5.0 的事务层与能力注册表” | 否（代码可证） |
| C-12 | README 历史表列出 v3.5.0/v3.5.6，但没有列出 v3.3.1/v3.4.0 | README 第 214–226 行；CHANGELOG 有 v3.3.1/v3.4.0 段 | 版本历史不完整 | 历史表补两行“未单独发布，内容在 v3.4.2” | 否 |
| C-13 | `v3.5.1` 没有任何记录 | tag/Release/CHANGELOG 均无 | 版本序列有缺口 | 由维护者确认是跳过还是遗漏 | 是 |
| C-14 | v4.0.0 Release 自己披露：发布包 `SKILL.md` 目录树写 473 项，实际 479 项 | v4.0.0 Release “已知限制” | 已披露，不是未解决问题 | 保留披露即可 | 否 |
| C-15 | 契约 01/02 文件头写 `FROZEN (4.2.0)`，契约集 README 写 4.3.0；`references/compatibility-v3.5.9.md` 仍写 4.2.0 | 各文件头 | 容易把单份契约版本与契约集版本混淆 | 阶段二在 README/CHANGELOG 明确区分；是否修 references 由维护者决定 | 是 |
| C-16 | README 同一页出现 535 与 532 两个测试数 | README 第 15 行 vs 第 200 行 | 自相矛盾 | 阶段二已统一为“v4.1.2 本地包 535；当前开发分支 653” | 否 |
| C-17 | `SKILL.md`、`AGENTS.md` 和 `references/` 的版本行/测试数仍不一致：SKILL 标题写 v4.2.0、目录树写 532；`references/python-docx-engine.md` 标题写 “v4.2.0 stable”、测试写 479；AGENTS 写 479 | `SKILL.md` 第 6/87 行；`references/python-docx-engine.md` 第 1/17 行；`AGENTS.md` 第 60 行 | 内部文档与 README/CHANGELOG 口径不同；不直接影响普通用户，但会影响 Agent 读取 | 阶段二未修改这些文件；建议单独同步，避免把 Agent 规范与用户文档混在一起 | 是 |

---

## 6. 需要人工确认的事项

| 编号 | 问题 | 选项 / 建议 |
|---|---|---|
| Q-01 | v4.1.2 是否要正式发布？ | 已执行：2026-11-07 先以 **Pre-release** 发布；正式版待 W4 独立审查后决定 |
| Q-02 | v4.1.0 Draft 如何处理？ | A. 发布为正式版；B. 改为 Pre-release；C. 保持 Draft 并在文档中标注 |
| Q-03 | v4.0.2 是否补发？ | A. 补 tag/Release；B. 从 README 历史表移除“本地构建包”，只保留 CHANGELOG 记录 |
| Q-04 | Release 说明中的旧提交号是否更正？ | 已执行：以当前 tag 指向为准更正并更新线上说明 |
| Q-05 | 未发布的 4.2.0 是否正式登记？ | 已执行：登记为 4.2.0（未发布），CHANGELOG/README 已更新 |
| Q-06 | 测试基线统一口径 | 已执行：README/CHANGELOG 采用“v4.1.2 535；当前开发分支 653；v4.1.1 532；v4.0.1 479” |
| Q-07 | v3.3.1 / v3.4.0 / v3.5.0 / v3.5.6 的 CHANGELOG 章节是否保留 | 建议保留，但标注“未单独发布，内容并入 vX”；README 历史表补 v3.3.1/v3.4.0 |
| Q-08 | v3.5.1 是否存在 | 需要维护者确认；若不存在，在 CHANGELOG 说明“版本号跳过” |
| Q-09 | v3.4.2 tag 是否要重新指向源码提交 | 不建议移动已发布 tag；建议在 Release 说明中注明源码提交 `c47be7a` |
| Q-10 | 真实语料范围 | 建议在 README 明确“46 份真实 `.docx` 是 v4.0.0 的验证，v4.1.x 尚未重跑” |
| Q-11 | 是否同步 `SKILL.md` / `AGENTS.md` / `references/` 的版本行和测试数 | 建议单独任务处理；阶段二只改了 README/CHANGELOG，避免把 Agent 规范和用户文档混在一起 |

---

## 7. 当前仓库与线上状态（发布后更新）

| 项目 | 状态 |
|---|---|
| 默认分支 | `main` |
| `origin/main` | `bd9a2d6`（v4.1.2 提交） |
| 本地 `main` | `37ec46f`，领先 `origin/main` 4 个提交 |
| 未提交改动 | `document_backends/result.py`、`tests/w5/test_b1_result.py` |
| 未跟踪目录 | `dist/`、`reports/w5/`、`reports/current/` |
| 远程 tags | 15 个：v3.4.1-archive、v3.4.2、v3.5.2、v3.5.3、v3.5.4、v3.5.5、v3.5.7、v3.5.8、v3.5.9、v4.0.0、v4.0.0-dev.1、v4.0.1、v4.1.0、v4.1.1、v4.1.2 |
| GitHub Releases | 15 条：14 条已发布（其中 v4.1.1、v4.1.2 为 Pre-release）+ 1 条 Draft（v4.1.0） |
| v4.1.2 Release | https://github.com/bingheyuxing-sheng/officecli-template-filler/releases/tag/v4.1.2 |
| Latest | `v4.0.1` |
| 可选依赖（本机） | `python-docx` / `openpyxl` / `jsonschema` 可用；PyMuPDF、matplotlib、RapidOCR、PaddleOCR、pytesseract 不可用 |

---

## 8. 阶段一结论

阶段一已完成，事实清单如上。以下是阶段一当时最需要人工决策的问题，已在第 9 节记录决策：

1. **v4.1.2 / v4.1.0 / v4.1.1 三个版本在 README 中的真实状态**（已解决：v4.1.2 已发布 Pre-release，v4.1.0 仍为 Draft，v4.1.1 为 Pre-release）。
2. **未发布的 4.2.0 版本号如何处理**。
3. **四个 Release 说明中的旧提交号如何处理**。
4. **测试基线统一口径**。

在以上问题确认前，不建议直接重写 README、CHANGELOG 或 GitHub Releases，以免把“未发布”写成“已发布”，或把“Draft”写成“正式版”。

---

## 9. 人工决策记录（2026-11-07）

| 事项 | 决定 |
|---|---|
| v4.1.2 定位 | **已补发 v4.1.2**：2026-11-07 推送 tag，创建 Pre-release，上传并校验资产。 |
| 4.2.0 版本号 | **登记为 4.2.0（未发布）**：CHANGELOG/README 中明确写“开发中、未发布”，与代码和契约测试断言保持一致。 |
| Release 旧提交号 | **以当前 tag 为准更正**：阶段三草稿使用 tag 实际指向的 commit，不再保留已不存在的旧提交号。 |
| 阶段推进 | 阶段二（README/CHANGELOG）和阶段三（Release 草稿）已完成；经授权发布 v4.1.2，并更新 14 个已有 Release 说明。 |

执行结果：

- README.md、CHANGELOG.md 已按上述决定重写。
- `reports/acceptance/releases/` 已生成 15 份逐版本 Release 草稿。
- `v4.1.2` tag 已推送（`41e6633` → `bd9a2d6`）；Pre-release 已创建：https://github.com/bingheyuxing-sheng/officecli-template-filler/releases/tag/v4.1.2
- 发布资产 `officecli-template-filler-v4.1.2.zip` 已上传；下载复算 SHA-256 与本地一致：`c66c652ec177fcc57a3dade003fdd22d2603071405406d87ce39de5a84f23f53`。
- 14 个已有 Release 的说明已用草稿更新；状态未变：v4.1.0 仍为 Draft，v4.1.1/v4.1.2 为 Pre-release，v4.0.1 仍为 Latest。
- 没有修改或推送任何代码提交。
