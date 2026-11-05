# 外部审计核查回复（Audit Triage）

- 对象：`officecli-template-filler-v4.0.0-technical-audit.md`（2026-11-05，Linux/Python 3.13/LibreOffice 环境）
- 回复方：主智能体（orchestrator），全部结论以本机源码复现/阅读为证据
- 日期：2026-11-05

## 逐项裁定

| 审计项 | 裁定 | 本机证据 |
|---|---|---|
| P1-01 body 级 SDT 静默漏检 | **成立，接受为 Alpha 阻断项** | 复现脚本（段落 `{{project_name}}` 移入 `w:sdtContent`）→ `build_document_spec_from_path`：`compatibility=L1, slots=0, unsupported=[], warnings=[], protected_regions=0`。此前 W2-I1 只在问题台账承认“不枚举”，但**产物本身零披露**且评级为 L1，审计升级正确；W2 验收“已明确 unsupported”措辞过强，予以更正 |
| P1-02 Skill 默认链仍是 v3 | **成立（已知，但未达到“已披露即可”的程度）** | `analyze_template.py --spec-version` 默认 3；SKILL.md GENERATE 主链仍为 `--payload`。打包说明中已声明，但作为产品入口确实是缺口 |
| P1-03 Fixtures 是合成而非真实模板 | **成立，措辞更正** | 六类模板全部由 `generate_fixtures.py` 用 `docx.Document()` 程序化构造。“Real-World Template Validation”应改称“结构化回归 Fixture”；真实语料验证归 W3-A |
| P2-01 Excel UNSUPPORTED 被覆盖为 FAILED | **成立（环境相关触发，逻辑缺陷真实）** | `excel_engine.py:390-394` 内置判 UNSUPPORTED；`:418-420` LibreOffice 分支对 `#NAME?` 无条件覆盖为 FAILED，`:431` unverified 不再计入。本机无 LibreOffice 故两测试通过——恰证明该缺陷只在装有 soffice 的机器暴露，属宿主机依赖型状态合并 bug |
| P2-02 PDF 转换残留源文件副本 | **成立** | `pdf_backend.py:148` `mkdtemp(prefix="pdf-src-", dir=out_dir)`，`:156-160` 两条 return 均无 finally 清理；WPS 与 LibreOffice 分支同样泄漏 |
| P2-03 无 ZIP 资源限额 | **成立（静态确认）** | 全项目无解压配额；TaskResourceGuard 只管子进程 |
| P2-04 全量套件在其环境停滞 | **部分成立，原因待定位** | 本机（Windows/WPS/py3.15）154-182s 完成 397 项。其环境有 LibreOffice，fixture-matrix 视觉 QA 每次转换裸调 soffice，共享默认用户配置目录，存在 profile 锁竞争嫌疑；需加 `-env:UserInstallation` 隔离与测试级超时后复测 |
| P3-01 包内无 AGENTS.md | **成立** | 规则文件在 `d:\docs\AGENTS.md`，未入库未入包；W2-I4 因此无法在包内核验 |
| P3-02 v4 文档缺口 | **成立（已知）** | README/SKILL/CHANGELOG 无 v4 章节 |

## 对审计的两点补充澄清

1. 审计称“不能宣称 397 全过”：本机与解包副本均有完整通过记录（154.8s / 169.1s，OK），该结论在 Windows/WPS 目标环境成立；其 Linux/LibreOffice 环境两项 Excel 失败为真实代码缺陷（P2-01），两者不矛盾，验收报告应补记“跨环境矩阵未验证”。
2. `record_gate` 二次门禁与 staged-hash 绑定被审计确认有效，维持 W2 结论。

## 总体裁定

接受审计的 W3 准入判断：**当前不宣布无范围 Alpha**。W0-W2 工程成果保留，进入 W3 修复波。

## W3 修复计划（按依赖排序）

| # | 项 | 内容 | Owner | 验收 |
|---|---|---|---|---|
| 1 | P2-02 | `convert_docx_to_pdf` 用 try/finally 清理 `pdf-src-*`；四条路径测试 | 05 | 成功/失败/超时/复制失败均无残留 |
| 2 | P2-01 | Excel 状态合并：builtin UNSUPPORTED + 外部 `#NAME?` → 保持 UNVERIFIED 语义，记录 builtin/external/final 三级溯源；mock 测试脱离宿主机 soffice 依赖 | 03+06 | 其环境两项失败测试转绿；无 soffice 环境不回退 |
| 3 | P1-01 短期 | body 子树结构预扫描：发现包裹段落/表格的 `w:sdt` 时，compatibility 至少降为 L3 并产出 `SDT_BODY_UNSUPPORTED` unsupported_feature + warning（阻断 L1 误报） | 01 | 审计复现脚本输出含披露；正反向测试 |
| 4 | CP-W2-002 | 定义 body-level SDT 的 location 语法（如 `body.sdt[i].p[j]`）、指纹边界、填充/拒绝策略；Agent 07 审查后实施枚举器扩展 | 05+07→01/03 | 契约冻结 + 端到端槽位可填或显式拒绝 |
| 5 | P2-04 | soffice 调用加 `-env:UserInstallation` 独立 profile；测试套件加模块级超时与残留 PID 报告 | 04+06 | Linux/LibreOffice 环境完整套件通过 |
| 6 | P1-02 | SKILL.md GENERATE 默认切 v4 链（spec4→plan→executor→gate），`--data` 标注 Legacy；新增按 SKILL 步骤执行的集成测试 | 05+02+03 | 默认指令不落回 schema 3 |
| 7 | P2-03 | ZIP 预检配额（entry 数/解压总量/压缩比/单 part 大小），超限结构化拒绝 | 05+06 | 恶意样本测试 |
| 8 | P3-01/02 | AGENTS.md 入库并入包；README/SKILL/CHANGELOG 补 v4.0-alpha 章节；W2 报告“real-template”措辞更正 | 05 | 文档与版本一致 |
| 9 | W3-A | 去标识化真实模板语料 + 人工标注基线 | 06 | 真实模板验证报告 |
