# W3 独立出口审查报告（v4.0.0 稳定版）

- 审查角色：Agent 07（独立审查，不参与本次实现）
- 审查日期：2026-11-05
- 审查对象：仓库 `officecli-template-filler`，annotated tag `v4.0.0` → commit `8a4f7ab3503d599455f4036fd0bd5fdf359dad96`
- 发布资产：`dist/officecli-template-filler-v4.0.0.zip`（923,924 字节；SHA-256 `2c22cf4c20ebfb571516a9f2e11e7e0e725e3c7fbe983d78ea42497367207719`）
- 审查方式：以发布 zip 解压副本为准，未在当前工作区运行测试；未修改任何代码、测试、契约或配置
- 报告约束：不记录外部语料目录路径、文件名或正文；外部语料只以匿名序号引用

---

## 1. 审查环境与工作区状态

| 项 | 实测 |
|---|---|
| OS | Windows NT 10.0.26300.0 |
| Python | 3.15.0 |
| python-docx | 1.2.0 |
| openpyxl | 3.1.5 |
| PyMuPDF / matplotlib | 均缺失 |
| LibreOffice `soffice` | 未检测到 |
| 解压目录 | `%TEMP%\officecli_w3_review\officecli-template-filler` |

工作区状态（仅记录，不计入发布内容）：

- `HEAD = 1dfb0b7`，比 tag 多两个纯文档提交（`7f6cfed`、`1dfb0b7`）；tag 内容才是本次发布审查对象。
- 最终复查时工作区为 **19 个已修改文件，+23/-40**（初始检查为 18 个、+20/-34，审查期间发生变化）。
- 这些改动**不是纯 import 清理**：实际 diff 还包含 `zip(..., strict=True)`、异常链 `from exc`、删除 `reference_body_font` 计算、删除测试中的 `shutil.which` mock 等语义或测试隔离变化。它们不在 tag 中，本次审查不计入发布，也不应作为“未使用 import 清理”直接提交。
- tag 与 HEAD 的差异仅在 `SKILL.md`、`references/python-docx-engine.md` 两个文档文件，不涉及代码。

---

## 2. 执行命令与真实结果

### 2.1 发布 zip 完整性

```powershell
Get-FileHash -Algorithm SHA256 d:\docs\officecli-template-filler\dist\officecli-template-filler-v4.0.0.zip
Get-Item d:\docs\officecli-template-filler\dist\officecli-template-filler-v4.0.0.zip | Select-Object Length
```

结果：

- SHA-256 = `2C22CF4C20EBFB571516A9F2E11E7E0E725E3C7FBE983D78EA42497367207719`（与要求值一致）
- 大小 = `923924` 字节（与 manifest、Release 资产元数据一致）
- zip 条目数 = 243；`HAS_DIST=False`（不含 `dist`/`.git`）

### 2.2 全量测试（解压包内）

```powershell
$env:PYTHONPATH="%TEMP%\officecli_w3_review\officecli-template-filler"
Push-Location "%TEMP%\officecli_w3_review\officecli-template-filler\tests"
py -3.15 -m unittest discover -s . -p "test_*.py"
```

真实结果：

- `Ran 479 tests in 167.233s`
- `OK`
- 退出码 `0`
- **0 failure / 0 error / 0 skip**
- 仅有 `ResourceWarning`（临时目录回收）和一次 `Duplicate name: '[Content_Types].xml'` 的 `UserWarning`，均为测试构造警告，不是失败或跳过。

### 2.3 W3 关键条件定向测试

```powershell
py -3.15 -m unittest test_pdf_hygiene test_excel_status_merge test_sdt_detection `
  test_sdt_discovery test_soffice_profile_isolation test_package_guard `
  test_skill_workflow_v4 test_transaction_gate
```

结果：`Ran 65 tests in 16.368s`，`OK`，退出码 `0`。

### 2.4 发布内容来源比对

将 `git archive --format=zip e50f27c` 与发布 zip 解压副本逐文件哈希比对：

- 归档文件 214 个；发布包文件均匹配（`DIFF` 0 条）。
- 仅 11 个 `dist\*.zip` 历史归档被发布包按设计排除。
- `reports/w3/11-package-manifest.md` 按设计自排除。
- 结论：发布包内容对应 `e50f27c`，tag `8a4f7ab` 包含该包与清单提交。

---

## 3. 逐项核验证据

### 3.1 版本一致性

| 对象 | 证据 | 结论 |
|---|---|---|
| `engine.__version__` | `engine/__init__.py:187` → `"4.0.0"` | 一致 |
| `CHANGELOG.md` | 第 9、11 行：v4.0.0 稳定版；契约集 4.2.0；`schema_version` 4.0 | 一致 |
| `README.md` | 第 11、174、207 行：v4.0.0 / 契约集 4.2.0 | 一致 |
| `SKILL.md` | 第 6、80 行：v4.0.0 stable / contract set 4.2.0 | 一致 |
| `references/python-docx-engine.md` | 第 1 行：v4.0.0 stable / 4.2.0 | 一致 |
| tag | `v4.0.0` 为 annotated tag，指向 `8a4f7ab` | 一致 |

契约与受控文件：

- `contracts/README.md:3`：Contract set version **4.2.0**（4.0.0 freeze + CP-W2-001 + CP-W2-002）。
- `contracts/02-document-spec.md:20,32`：产物 MUST emit `schema_version: "4.0"`，const `"4.0"`。
- Schema：`document_spec-4.0.schema.json:23`、`content_plan-4.0.schema.json:10` 等仍为 `"const": "4.0"`。
- `git diff --name-status 99ffbbe..8a4f7ab -- contracts schemas config` → **空**。
- `git diff 99ffbbe..8a4f7ab -- engine/__init__.py` → 仅 `__version__` 由 `3.5.9` 改为 `4.0.0`。

结论：**版本一致，本次发布未修改任何受控契约/Schema/配置**。

### 3.2 外部语料隔离（仓库与发布包）

已在解压包内执行以下检查：

```powershell
# 使用目录名关键词、绝对路径与用户目录模式扫描；
# 为避免二次扩散，本报告不复述具体语料关键词。
Select-String -Path <package> -Pattern "<目录名关键词>|<绝对路径模式>"

# 8 个二进制 fixture 内部 XML 扫描
py -3.15 -c "<zipfile 扫描 word/*.xml、xl/*.xml>"
```

结果：

- 未发现外部语料目录路径或真实文件名进入包内文本文件；但**文本文件层面发现 B1 所述的语料正文片段**（见 §5.1）。
- 唯一命中的“用户目录模式”字符串为 `engine/pdf_backend.py:30-31` 的 WPS 转换器运行时探测路径，属于合法能力探测，不是语料路径。
- 包内 8 个 `.docx` 二进制 fixture 为合成/结构化样本；内部 XML 扫描命中 0。
- `tests/real_corpus_eval.py:400` 将 `--corpus` 设为 **required**，语料目录只在运行时传入；报告写入不保存该路径。
- `reports/w3/real-corpus-eval.json` 的记录编号为 `D001`–`D046`，无路径/文件名/正文。

**但发现阻断缺陷 B1**：包内测试代码仍内嵌了外部语料正文片段，见 §5。

### 3.3 真实语料报告自洽性

从 `reports/w3/real-corpus-eval.json` 重新计算结果：

| 指标 | Markdown 报告 | JSON 重算 | 结论 |
|---|---|---|---|
| 解析总数 | 46/46 OK | `records=46`, `{"OK":46}` | 一致 |
| Spec 校验失败 | 0 | `spec_invalid=0` | 一致 |
| 解析阶段字节改动 | 0 | `template_bytes_changed=0` | 一致 |
| 填充冒烟 | 21/21 OK | `smoke_records=21`, `{"OK":21}` | 一致 |
| 冒烟后字节改动 | 0 | `fill_smoke.template_bytes_changed=0` | 一致 |
| 冒烟 QA | 12 PASSED / 9 UNVERIFIED | `{"PASSED":12,"UNVERIFIED":9}` | 一致 |
| 总耗时 | 212.1s | `elapsed_s=212.1` | 一致 |

- Markdown 第 6–8 行明确写明“无人工标注基线（E3）”“不计算也不声称 P/R/F1/漏检率”“真实与合成指标分列”。
- 21 条 smoke 记录均 `committed=true`；`UNVERIFIED` 与 `PASSED` 未混写为通过。
- 非阻断观察：JSON 含逐条 `size_bytes`/`sha256`/槽位统计，严格说不是“仅聚合指标”，但无路径/文件名/正文；见 N3。
- 非阻断观察：报告未记录生成命令与参数；脚本默认 `--fill-sample 6`，而实际报告为 21 条，无法仅凭默认参数复现；见 N4。
- 非阻断观察：smoke 记录未保存 `coverage_gaps`，因此“9 份均因浮动图片缺口”只能在 10-exit-review 中看到，JSON 不能直接复核；见 N6。

### 3.4 关键修复是否真实落地

| 修复项 | 代码证据 | 测试证据 | 结论 |
|---|---|---|---|
| 授权填充原位替换、保留 run/rPr | `document_engine/fill_executor.py:462-481`（`_replace_span_in_place`，`preserve_empty_runs=True`、`strip_red_color=True`）；`:510-524`、`:526-541` 不再对非空段落走 strict-style 重建；`engine/ooxml_utils.py:241-312` 仅原位切片替换并保留 `w:t` 属性 | `tests/test_fill_fidelity_inplace.py:120-149` 断言 2 个 run 保留、bold 保留、红色被剥离、structural/style/layout 哈希不变 | 已落地 |
| `red_run_clue` 段落不回退 v3 strict-style | `fill_executor.py:526-539`：非空段落一律 `_replace_span_in_place`；仅空段落用 strict-style 创建 run | `tests/test_fill_fidelity_inplace.py:196-220` 断言红字段落原位替换、run 数保持 1、bold 保留、结构哈希不变 | 已落地 |
| UNVERIFIED 仅 coverage gaps 时 STANDARD 可提交，且 final 一致 | `qa/gate.py:67-90` 按契约 04 §7 计算；`qa/report_builder.py:168-228` 生成 `coverage_gaps` 与 `final.eligible_for_commit`；`document_engine/fill_executor.py:1281-1285` 要求 STANDARD + `allow_unverified`；`engine/transaction.py:298-391` 二次门禁复核报告与暂存 SHA | `tests/test_fill_fidelity_inplace.py:429-460`：gap-only + STANDARD + allowance → `UNVERIFIED` 且 committed；无 allowance → `FAILED`/`QA_NOT_ELIGIBLE` | 已落地 |
| 模板继承 `xml:space`/未触达空位/既有红字仅警告，新问题仍阻断 | `qa/pipeline.py:292-354` 区分“被 FillPlan 触达且是注册槽位 token”与继承内容；`engine/qa_engine.py:301-312,805-812` 继承缺省降为 medium | `tests/test_package_guard.py:144-187`（继承不阻断、超出基线仍阻断、`raise_on_failure=False` 不抛）；`tests/test_residual_inheritance.py:73-129`（未注册空位降级、目标内注册槽位仍阻断）；`tests/test_fill_fidelity_inplace.py:325-354`（目标内红字仍阻断、模板外新红字仍阻断） | 已落地 |
| GENERATE 视觉检查使用 STYLE_GUIDE 档位 | `qa/pipeline.py:439` 对 GENERATE 设 `STYLE_GUIDE`，`:483` FORMAT、`:685` `run_visual_layout_qa` 均传入；`engine/qa_engine.py:1235-1241` 分页数漂移在非 REPLICA 下降为 medium；`engine/layout_qa.py:208-231` 字体漂移在 STYLE_GUIDE 下降为 medium，表格列数/宽度仍 high | `tests/test_p0_semantic_qa.py:112-150`；`tests/test_package_guard.py:175-187` | 已落地 |
| Excel >2MB 只读扫描与异常回退 | `engine/excel_spec.py:23` `2 * 1024 * 1024`；`:110-135` 大文件 `read_only_large`，全量解析异常 `read_only_fallback`，双失败结构化错误 | `tests/test_excel_spec_resilience.py:52-96` 四项测试 | 已落地 |
| 未放宽必需检查/未删除断言 | `contracts`/`schemas`/`config` 在发布范围无 diff；`git diff 99ffbbe..8a4f7ab -- tests` 仅 `test_legacy_compat.py` 的版本断言 `3.5.9 → 4.0.0`，无测试文件删除 | 全量 479 OK；定向 65 OK | 未发现放宽或删除 |

补充：

- 二次门禁真实存在：`engine/transaction.py:298-391` 绑定 `staged_sha256`、`qa_report_sha256`、`task_id`，提交前重算暂存 SHA；不一致中止 `QA_REPORT_STALE`。
- W3-2 Excel 状态合并测试覆盖 `UNSUPPORTED` 保留、`VERIFIED_EXTERNAL`、`NOT_RECALCULATED`、`unverified_count` 等组合，见 `tests/test_excel_status_merge.py:68-128`。
- W3-1/W3-3/W3-4/W3-5/W3-7 对应测试文件均存在且在全量/定向运行中通过：`test_pdf_hygiene.py`、`test_sdt_detection.py`、`test_sdt_discovery.py`、`test_soffice_profile_isolation.py`、`test_package_guard.py`。

### 3.5 发布资产

本地：

| 项 | 值 |
|---|---|
| 文件名 | `officecli-template-filler-v4.0.0.zip` |
| 大小 | 923,924 字节 |
| SHA-256 | `2c22cf4c20ebfb571516a9f2e11e7e0e725e3c7fbe983d78ea42497367207719` |
| 条目数 | 243 |
| 前缀 | `officecli-template-filler/` |
| manifest | `reports/w3/11-package-manifest.md:14-17` 与上述完全一致 |
| 包内顶层 | `AGENTS.md`、`LICENSE`、`README.md`、`SKILL.md`、`requirements*.txt` 等 |
| 包内排除 | `dist/`、`.git/`、缓存、清单自身 |

在线（`gh release view v4.0.0 --repo bingheyuxing-sheng/officecli-template-filler --json tagName,isDraft,isPrerelease,assets`）：

```json
{
  "tagName": "v4.0.0",
  "isDraft": false,
  "isPrerelease": false,
  "asset": {
    "name": "officecli-template-filler-v4.0.0.zip",
    "size": 923924,
    "digest": "sha256:2c22cf4c20ebfb571516a9f2e11e7e0e725e3c7fbe983d78ea42497367207719"
  }
}
```

- 在线资产大小与digest均与本地 zip、manifest一致。
- 再次重试 `gh release view` 及下载 `.sha256` 资产时网络返回 `EOF`；已记录为**部分在线复核**：首次 Release 元数据查询成功，`.sha256` 资产的**文件内容**未能在本次会话下载验证。服务端对该资产返回的 digest 为 `sha256:cf8987369ceaed5b116f80cf8fc4df9dcef8274b9558fc3999626bb4104bb8ca`。

---

## 4. W3 出口条件 1–8 逐条判定

| # | 条件 | 判定 | 证据与说明 |
|---|---|---|---|
| 1 | W3-1/2/3/5/7 修复完成且测试绿（含 mock 矩阵） | **满足** | 全量 479 OK；定向 65 OK；对应测试文件齐全；E2 宿主无关 mock 路径存在 |
| 2 | W3-4 契约 4.2.0 冻结（07 两次 PASS）且实施合入，SDT 闭环 | **满足（按任务书 W3-4 的解释）** | `contracts/README.md:3,92` 4.2.0 FROZEN；`07-cp-w2-002-gate-review.md` 提案阶段 CONDITIONAL_PASS，`07-cp-w2-002-post-review.md` 实施后 PASS；B1–B4 已折入 rev 2。严格按 §3 字面“两次 PASS”看，第一次为 CONDITIONAL_PASS，属条件措辞与任务书 W3-4 行的偏差，非阻断。`test_sdt_detection`/`test_sdt_discovery`/`test_e2e_v4` 覆盖发现→定位→`PROTECTED_SLOT_VIOLATION` 拒绝 |
| 3 | W3-6 GENERATE 走 v4 链，集成测试证明不落回 schema 3 | **满足** | `07-w3-6-review.md` PASS；`tests/test_skill_workflow_v4.py` 3 项；定向运行通过；CLI 默认仍为 3（兼容边界未被翻转） |
| 4 | 审计方 Linux/LibreOffice 环境复验 Excel 两测试转绿、完整套件跑完 | **不满足** | 当前为 Windows + WPS，未检测到 `soffice`；`reports/w3/10-exit-review.md:92-96` 自认 Linux/LibreOffice 未验证；`audit-triage.md` 明确 P2-01/P2-04 关闭条件为该环境复跑。本次审查无法替代 |
| 5 | W3-9 真实语料报告存在，指标分列合成/真实 | **满足（主条件）** | 报告与 JSON 存在；46/46、21/21、0 字节、12 PASSED/9 UNVERIFIED 自洽；明确无标注、不声称准确率。附带 N3/N4/N6 非阻断偏差 |
| 6 | AGENTS/README/SKILL/CHANGELOG 版本一致，重打包 zip 含清单与 SHA-256 | **满足（版本面）** | 五处版本均为 4.0.0 / 契约 4.2.0；zip 大小/SHA/条目数与 manifest 一致；Release 提供 `.sha256` 资产。测试计数文档仍有 473 vs 479 不一致（N1，非阻断） |
| 7 | 全量回归 ≥ 基线，0 项既有测试被删除/弱化 | **满足** | 479 > 473；发布范围测试 diff 仅版本断言更新，无测试删除；全量 0 失败/0 跳过 |
| 8 | Agent 07 出口评审 PASS（CONDITIONAL_PASS 不得冒充） | **不满足** | 本次独立审查结论为 **FAIL**（B1/B2）；且发布时 `10-exit-review.md:92` 自认“未由独立 Agent 07 进程复跑”，本次为发布后审查，不能追溯冒充发布时门禁 |

**独立性边界（条件 8 必读）：**

- 本次审查者未参与实现，审查基于发布包、静态代码、契约与测试证据，属于独立作者视角。
- 但审查运行在与实现相同的 Windows/WPS 主机和账号，未使用独立 Linux/LibreOffice 环境，未复跑外部语料（仅重算已提交 JSON）。
- 因此本次审查可以成为一份独立审查记录，但不能关闭条件 4；也不能把“发布后 FAIL 审查”包装成“发布时 PASS 门禁”。
- 若项目要求条件 8 必须在发布前由独立进程完成，则 v4.0.0 发布时该条件本身即未满足，本次审查不改变这一事实。

---

## 5. 缺陷清单

### 5.1 阻断缺陷

#### B1（阻断）发布包内测试代码含外部语料正文片段

- 位置：
  - `tests/test_residual_inheritance.py:4`：以 “An exam-corpus paragraph” 引出并内嵌一段外部语料的模板行正文。
  - `tests/test_fill_fidelity_inplace.py:284,294,307`：以 “exam template” 引出并内嵌一段外部语料的红字正文短语。
- 证据命令：

```powershell
Select-String -Path tests/test_residual_inheritance.py -Pattern "exam-corpus"
Select-String -Path tests/test_fill_fidelity_inplace.py -Pattern "exam template"
```

- 影响：
  - 直接违反用户硬约束“语料路径/文件名/正文绝不能写入仓库代码”。
  - 与发布说明/CHANGELOG 中“仓库内不保存路径、文件名或文档内容”“报告只含匿名序号与聚合指标”的表述冲突，构成发布说明不准确。
  - 虽然是短片段且已去标识化，但仍是外部语料正文；作为公开稳定版资产不可接受。
- 最小修复建议（不修改本报告范围外代码）：
  1. 将上述 docstring 与常量改为**完全合成、与语料无关**的通用文本；删除 “exam-corpus”“exam template” 等来源归属措辞，保留同样的回归语义（跨 run 红色 token、标签 + 下划线空白）。
  2. 重新运行全量测试，重建发布包与清单，发布补丁版（例如 v4.0.1）；不要移动/覆盖已发布的 `v4.0.0` tag 或资产。
  3. 在 Release Notes 中明确“包内无任何语料正文；测试文本均为合成”。
- 复现路径：解压发布 zip → 打开上述两个测试文件对应行；或对包内执行上述 `Select-String`。

#### B2（阻断，门禁条件）审计方 Linux/LibreOffice 复验未完成

- 证据：
  - 当前环境 `soffice` 不存在；OS 为 Windows。
  - `reports/w3/10-exit-review.md:92-96` 明确 Linux/LibreOffice 未验证。
  - `reports/w3/audit-triage.md` 将 P2-01/P2-04 的关闭条件定义为审计环境复跑。
- 影响：W3 出口条件 4 不满足；无法宣称 P2-01/P2-04 已关闭。
- 最小修复建议：在 Linux/LibreOffice 审计环境运行完整套件及 `test_excel_reliability.py` 两项宿主机相关测试，保存命令、环境、总数、耗时、日志；完成后由 Agent 07 复核。代码本身不需要为此改动。

### 5.2 非阻断缺陷

| # | 级别 | 发现 | 建议 |
|---|---|---|---|
| N1 | P3 文档精度 | 包内 `AGENTS.md:60`、`CHANGELOG.md:41`、`README.md:14,197`、`SKILL.md:135` 仍写 473 项；实际 479。HEAD 仅把 `SKILL.md` 改为 479，README/AGENTS/CHANGELOG 仍未改；Release Notes 只披露 SKILL 一处 | 统一改为 479 或“≥473”；补丁版更新文档 |
| N2 | P3 溯源措辞 | Release Notes 称“发布包的源提交为 8a4f7ab”，但 `11-package-manifest.md` 与哈希比对表明包内容构建自 `e50f27c`；tag 提交仅额外包含清单与 zip | 明确写“tag 提交 8a4f7ab；包内容构建自 e50f27c，差异仅清单与 zip 自身” |
| N3 | P3 报告措辞 | `real-corpus-eval.json` 含逐条 `size_bytes`/`sha256`/槽位统计，不是严格意义的“仅聚合指标”；但无路径/文件名/正文 | 二选一：JSON 只保留 totals；或把说明改为“匿名序号 + 技术元数据 + 聚合指标” |
| N4 | P3 可复现性 | `real-corpus-eval.md` 未记录运行命令/参数；脚本默认 `--fill-sample 6` 不会产生 21 条 smoke | 在报告中记录完整命令、参数、运行时间与环境 |
| N5 | P3 工作区卫生 | 工作区 19 文件 +23/-40 且审查期间仍在变化；包含 `zip(strict=True)`、异常链、删除变量、删测试 mock 等非 import 改动 | 不要作为“import 清理”提交；另开任务审查；确保不进入任何发布 commit |
| N6 | P3 证据完整性 | 10-exit-review 称 9 份 UNVERIFIED 均因浮动图片缺口，但 JSON smoke 记录未保存 `coverage_gaps` | 在 smoke 记录中保存 `coverage_gaps`/`final.reasons`，或弱化该因果表述 |

---

## 6. 发布说明与出口报告诚实性检查

已确认如实披露的内容：

- Windows + WPS 为已验证平台；Linux/LibreOffice 未验证（Release Notes 与 `10-exit-review.md:92-96`）。
- 真实语料无人工标注基线，不计算/不声称槽位准确率（报告第 6 行、Release Notes）。
- SDT 内填充不支持，`sdt_edit=false`，仅发现并拒绝（Release Notes、README、10-exit-review）。
- 浮动图片相关 QA 为 `UNVERIFIED`，不等于通过（Release Notes、10-exit-review）。
- 独立 Agent 07 在发布时未复跑（10-exit-review §6 自认）。
- 未发现把 `UNVERIFIED` 写成 `PASSED`、把失败写成成功、或删除/跳过测试的证据。

不成立的表述：

- “仓库内不保存……文档内容”与“包内不含真实用户文档/语料正文”被 B1 推翻。
- “报告只含匿名序号与聚合指标”与 N3 存在措辞偏差（虽无正文）。
- Release Notes 对 473/479 的披露只覆盖 SKILL，未覆盖 README/AGENTS/CHANGELOG（N1）。

---

## 7. 已知限制

1. 本次审查以发布 zip 解压副本为准，未在当前脏工作区运行测试；工作区改动不计入发布。
2. 未在 Linux/LibreOffice 环境复验，无法关闭条件 4。
3. 未复跑外部语料评测；基于已提交 JSON 重算指标，未接触语料路径/文件名/正文。
4. `.sha256` 资产文件内容因网络 `EOF` 未下载验证；已验证 Release 元数据中的 size/digest 与本地 zip 一致。
5. 本次审查是发布后独立审查，不能追溯替代发布时的独立门禁；也不能修改已发布 tag/资产。
6. 静态代码审查 + 测试运行不等于对所有 DOCX/XLSX 结构的普遍支持证明。

---

## 8. 最终裁定

**FAIL**

裁定理由：

1. **B1 阻断**：发布包内测试代码含外部语料正文片段，直接违反用户硬约束，并与发布说明“仓库不保存文档内容”冲突。该问题不需要复杂复现，解压发布包即可确认。
2. **B2 阻断**：W3 出口条件 4（Linux/LibreOffice 审计环境复验）未完成，P2-01/P2-04 关闭条件未满足。
3. **条件 8 不满足**：本次独立审查结论为 FAIL；发布时亦无独立 Agent 07 进程复跑，不能以发布后审查冒充发布时 PASS。

技术面需要同时记录的正面证据：

- 全量 479 项测试在发布包内通过，0 失败、0 跳过，耗时 167.233s。
- 版本/契约/Schema 一致：软件 4.0.0、契约集 4.2.0、产物 schema_version 4.0；发布范围未修改受控文件。
- 发布 zip SHA-256、大小、条目数、Release 在线元数据与 manifest 一致；包内无 `dist/`、`.git/`。
- 关键修复（原位填充、red_run_clue、UNVERIFIED 提交门、继承降级、STYLE_GUIDE、Excel 只读回退）均能在代码与测试中找到真实落点，未发现为通过测试而放宽必需检查或删除断言。
- 真实语料报告的核心数字（46/46、21/21、0 字节、12 PASSED/9 UNVERIFIED）与 JSON 完全自洽，且明确不声称准确率。

结论边界：若仅按“Windows/WPS 范围内发布资产技术完整性”评价，上述正面证据很强；但按 `w3-task-book.md` §3 的**全部出口条件**，B1 与条件 4 使本次不能判 PASS，也不能用 CONDITIONAL_PASS 掩盖。建议先完成 B1 修复与 Linux/LibreOffice 复验，再发布补丁版并重新执行 Agent 07 出口评审。

---

## 9. 关键文件索引

- 版本：`engine/__init__.py:187`；`contracts/README.md:3`；`contracts/02-document-spec.md:20,32`
- 原位填充：`document_engine/fill_executor.py:462-481,510-541`；`engine/ooxml_utils.py:241-312`
- QA 资格：`qa/gate.py:67-90`；`qa/report_builder.py:168-228`
- 二次门禁：`engine/transaction.py:298-391`
- 继承降级：`qa/pipeline.py:292-354`；`engine/qa_engine.py:301-312,805-812`
- 视觉档位：`qa/pipeline.py:439,483,685`；`engine/qa_engine.py:1235-1241`；`engine/layout_qa.py:208-231`
- Excel：`engine/excel_spec.py:23,110-135`
- 发布清单：`reports/w3/11-package-manifest.md:10-18`
- 出口自评：`reports/w3/10-exit-review.md:92-102`
- B1 位置：`tests/test_residual_inheritance.py:4`；`tests/test_fill_fidelity_inplace.py:284,294,307`
</content>
