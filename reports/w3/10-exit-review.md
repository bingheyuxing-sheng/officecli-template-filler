# W3 出口证据与发布门禁记录（v4.0.0 稳定版）

- 日期：2026-11-05
- 发布级别：**稳定版（stable）**，取代预发布 `v4.0.0-dev.1`
- 软件版本：`engine.__version__ = 4.0.0`
- 契约集：**4.2.0**（4.0.0 冻结基线 + CP-W2-001 + CP-W2-002；本次发布未修改任何契约、Schema、枚举或错误码）
- 代码基线：`a5d5911`（最后一个代码修复提交，`fix(v4.0-w3-9): never-slot template tokens must not block an authorized fill`）；`v4.0.0` tag 指向包含本报告与版本声明的提交
- 记录性质：本文件是主智能体的发布门禁证据包。受当前环境限制，未由独立 Agent 07 进程复跑；独立性缺口在 §6 显式披露，不冒充独立审查。

---

## 1. 范围

本次发布包含：

1. v4 文档主链（DocumentSpec 4.0 → ContentPlan/FillPlan → 事务执行器 → QA Pipeline → 二次门禁 → 原子提交）。
2. W3-1 … W3-9 修复与加固（PDF 临时副本清理、Excel 三级状态、SDT fail-closed、CP-W2-002、soffice 私有 profile、GENERATE 主链切 v4、ZIP 配额、文档一致性、真实语料无损评测）。
3. 真实语料暴露的填充/QA 缺陷修复：
   - 授权文本填充原位替换，不再重写 `rPr`，结构指纹零漂移；
   - STANDARD/UNVERIFIED 仅覆盖缺口的报告按契约 04 §7 允许提交；
   - 模板既有 `xml:space` 缺省、未被 FillPlan 触达的空位与既有红字按基线披露，不阻断；
   - `STYLE_GUIDE` 档位传入视觉检查，内容驱动的分页/字体漂移降级为警告，版式几何仍阻断；
   - Excel 大文件/图表异常回退 `read_only` 并结构化披露。

非范围：SDT 内填充（W4）、POLISH/MERGE 独立入口、Linux/LibreOffice 环境验证。

---

## 2. 自动化测试证据

| 项 | 值 |
|---|---|
| 命令 | `python -m unittest discover -s tests -p "test_*.py"`（cwd=`tests/`，`PYTHONPATH=<repo>`） |
| 环境 | Windows，Python 3.15，python-docx 1.2.0 |
| 结果 | **479 tests, OK**（0 failure / 0 error / 0 skip） |
| 耗时 | 175.8s |
| 覆盖 | v3.5.9 兼容基线、W0 契约、W1–W3 回归、真实语料稳定性回归、端到端与故障注入 |
| 既有测试 | 未删除、未跳过、未降低断言 |

新增/加强的回归测试：

- `tests/test_fill_fidelity_inplace.py`：红字段落/跨 run 填充保留 run 结构与 `rPr`；结构哈希不变；针对槽位残留仍阻断。
- `tests/test_package_guard.py`：模板继承的 `xml:space` 缺省降级为披露；超出基线的仍阻断；`raise_on_failure=False` 不抛异常。
- `tests/test_excel_spec_resilience.py`：大工作簿只读扫描、全量解析异常回退、双重失败结构化错误。

---

## 3. 真实语料证据（W3-9）

来源：`reports/w3/real-corpus-eval.md`（仅匿名序号与聚合指标；运行时不写入仓库路径、文件名或正文）。

| 指标 | 结果 |
|---|---|
| `.docx` 解析 | 46 / 46 成功，0 exception，0 无效 Spec |
| 解析阶段模板字节改动 | 0 |
| 含可填槽位模板的完整填充（全部可填文本槽位） | 21 / 21 结构化成功，0 崩溃、0 拒绝 |
| 填充后模板字节改动 | 0 |
| 冒烟 QA 状态 | 12 PASSED / 9 UNVERIFIED（9 份均因 `FLOATING_IMAGE_LAYOUT_UNSUPPORTED` 覆盖缺口如实披露） |
| 总耗时 | 212.1s |

限制：语料未经人工标注，按 E3 不计算、不声称槽位 P/R/F1 或漏检率；真实与合成指标分列。

---

## 4. 环境能力矩阵（2026-11-05 运行时实测）

| 能力 | 必需 | 状态 | 证据 |
|---|---|---|---|
| `docx_parse` | 是 | AVAILABLE | python-docx 1.2.0 |
| `docx_write` | 是 | AVAILABLE | 临时目录可写 |
| `wps_pdf_render` | 是 | AVAILABLE | `kwpsconvert.exe`（WPS 12.1.0.29690） |
| `pdf_page_analysis` | 是 | AVAILABLE | WPS `pdfinfo` |
| `pixel_visual_diff` | 否 | UNAVAILABLE | PyMuPDF 缺失 |
| `ocr` | 否 | UNAVAILABLE | 无 RapidOCR/PaddleOCR/Tesseract |
| `chart_render` | 否 | UNAVAILABLE | matplotlib 缺失 |

必需能力全部可用；可选能力缺失只影响对应检查，相关结果如实 `UNVERIFIED`，不记为通过。

---

## 5. 发布包与一致性

- 发布包：`dist/officecli-template-filler-v4.0.0.zip`（`git archive` 构建，排除 `dist/`、`.git/`、缓存与本清单自身）。
- 校验值、条目数与内容核对见 `reports/acceptance/w3-11-package-manifest-v4.0.0.md`。
- 包内不含真实用户文档；`tests/fixtures` 均为合成/结构化样本。
- 版本一致性：`engine.__version__`、`CHANGELOG.md`、`README.md`、`SKILL.md`、`references/python-docx-engine.md`、发布 tag 均为 `4.0.0`；契约集保持 `4.2.0`，产物 `schema_version` 保持 `4.0`。

---

## 6. 已知限制与独立性缺口

1. **独立审查缺口**：本次门禁证据由主智能体编排生成，未由独立 Agent 07 进程复跑。依据项目规则，这不等同于 Agent 07 的正式 `PASS`；发布说明与交付报告必须如实标注这一点。
2. **平台范围**：仅在 Windows + WPS PDF 后端上完成全量验证；Linux/LibreOffice 组合未验证（P2-04 的 Linux 复跑条件仍未关闭）。这不影响 Windows/WPS 支持声明，但不得表述为跨平台已验证。
3. **真实语料精度**：无人工标注基线，不声称槽位准确率；仅报告结构鲁棒性、无损性与披露完整性。
4. **不支持项**：SDT 内填充（`sdt_edit=false`）、域更新、OLE/SmartArt 编辑、矢量图字节校验；均以 `UNSUPPORTED` 或 PROTECTED 披露。
5. **浮动图片**：含浮动图片的模板 QA 为 `UNVERIFIED`（可提交但需人工复核版式），不是 PASSED。

---

## 7. 门禁结论

在 Windows/WPS 支持范围内，本文档列出的测试、真实语料、环境与版本一致性证据满足发布条件，结论为 **PASS（scope-limited）**。该结论不覆盖 Linux/LibreOffice，也不替代独立 Agent 07 审查；两者均在发布说明中披露。
