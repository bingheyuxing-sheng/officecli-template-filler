# W3-8 抽查复审：文档措辞更正（Agent 07）

**结论：PASS（本次措辞抽查通过，无阻断项）。**
**可接受性**：W3-8 的文档/措辞部分可接受；但 task book W3-8 ⑤「重新打包 zip 并核对包内清单」（`reports/w3/w3-task-book.md:103,105`）当时尚未完成，故 W3-8 整行与 W3 出口条件 6（同书 `:137`）不能凭本次审查宣称完成。

> 后续状态：`reports/w3/08-package-manifest.md` 已记录 `v4.0.0-dev-w3` 包（commit `b74f059`，450 tests OK，含 AGENTS.md 且无 `dist/`）。W3-8 ⑤ 的完成以该清单为准。

## 逐项证据

1. **无过度宣称** — `README.md:7,15` 标注"未发布"、Alpha 未宣布、真实语料待外部输入；`CHANGELOG.md:9,11,37` 明确无 tag/Release/push、W3-9 未获取；`AGENTS.md:5,145` 一致。未见"已发布 / alpha-ready / 真实模板已验证"。
2. **数字一致** — 4.2.0：`AGENTS.md:5,57,65`、`README.md:11`、`CHANGELOG.md:11,19`、`contracts/README.md:3,92`；450 项：`AGENTS.md:59`、`README.md:14`、`CHANGELOG.md:44`，实测 `Ran 450 tests ... OK`（168.9s）；`sdt_edit=false`（`README.md:17`、`contracts/02-document-spec.md:146`）；CLI `--spec-version` 默认 3（`scripts/analyze_template.py:44`）。
3. **AGENTS 保真** — 与 `d:\docs\AGENTS.md` diff 仅 4 处：头部基线、§3.1、§3.2 首句、§5；§1/§6/§7/§11 安全规则零改动。
4. **CHANGELOG 诚实** — `:11` 区分契约 4.2.0 与引擎 3.5.9、声明非发布；`:37-40` 限制项与 P2-01/P2-04、W3-9 现状一致；无隐藏 PASS。
5. **W2 更正忠实** — `reports/w2/w2-acceptance.md:115-120` 四条与 `reports/w3/audit-triage.md:11,13,14,17,23`（P1-01/P1-03/P2-01/P2-04）一致，无软化；历史正文 `:109-111` 未改，diff 仅追加 9 行。
6. **台账** — `reports/w2/issues.md:10,13` 关闭均有上述证据；`:11,12,14` 仍 OPEN，正确。
7. **打包就绪** — `AGENTS.md` 已位于仓库根；新增文本无本机路径、凭据或个人信息。

## 非阻断问题

- `dist/officecli-template-filler-v4.0.0-dev.zip` 当时仍为 `aa6e44d` 的 W0–W2 旧包（397 项、无 AGENTS.md、无 CP-W2-002）；后续已由 `v4.0.0-dev-w3.zip` 补充，旧包保留为历史归档。
- `d:\docs\AGENTS.md` 工作区副本仍写 `4.0.0`/W2；建议同步或声明仓内副本为权威，否则 W2-I4 的关闭依据需注明为"仓内副本"。
