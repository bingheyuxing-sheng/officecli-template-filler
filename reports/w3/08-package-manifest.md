# W3 Skill 包清单（v4.0.0-dev-w3）

- 日期：2026-11-05
- 产物：`dist/officecli-template-filler-v4.0.0-dev-w3.zip`
- 来源：`git archive HEAD`（commit `b74f059`，含 W3-8 文档同步）
- 性质：**开发快照，不是正式发布**；无 tag、无 Release、未 push
- 注意：本清单记录 commit `b74f059` 的包。之后的文档清理未重新打包，包内文档与当前工作树可能存在措辞差异；本任务明确不重建包。

## 校验值

| 项 | 值 |
|---|---|
| 大小 | 879,896 字节 |
| SHA-256 | `8266d5509eae5be38563fa2b5f3127a1a44945bd40a5f6755ba581424bbd643b` |
| 条目数 | 234 |
| 前缀 | `officecli-template-filler/` |

## 内容核对

- 包含：`SKILL.md`、`README.md`、`CHANGELOG.md`（v4.0.0-dev 条目）、`AGENTS.md`（4.2.0 权威副本）、`contracts/`（含 CP-W2-001/002）、`schemas/`、`config/`、`examples/`、`tests/`（含六类结构化 fixtures、契约测试、W3 回归）、`reports/w0–w3/`、`engine/`、`template_intelligence/`、`content_intelligence/`、`document_engine/`、`qa/`、`scripts/`、`references/`。
- 排除：`dist/`（历史归档与本次包自身）、`.git/`、缓存与临时文件。
- 未包含真实用户文档；`tests/fixtures` 均为合成/结构化样本，`tests/fixtures/legacy/` 为合成 ref/out。

## 验证

在解包副本中运行完整套件：

```powershell
py -3.15 -m unittest discover -s tests -p "test_*.py"
```

结果：**450 tests, OK，167.078s**；`AGENTS.md` 存在，包内无 `dist/`。

## 已知限制（与包一同声明）

- Alpha 未宣布：W3-9 真实语料待外部脱敏输入；P2-01/P2-04 待审计环境复跑。
- 不支持 SDT 内填充（`sdt_edit=false`）；SDT 仅作为 PROTECTED 位置发现并拒绝。
- 本机缺 PyMuPDF/matplotlib/OCR，相关检查如实 `UNVERIFIED`。
