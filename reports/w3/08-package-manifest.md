# W3 Skill 包清单（v4.0.0-dev-w3）

- 日期：2026-11-05
- 产物：`dist/officecli-template-filler-v4.0.0-dev-w3.zip`
- 来源：`git archive HEAD`（commit `4406083`，含 W3-8 文档同步与全量 Markdown 清理）
- 性质：**开发快照，不是正式发布**；无 tag、无 Release、未 push
- 版本关系：本包取代 `b74f059` 构建的旧包（旧 SHA-256 `8266d550…`）；旧包不再作为当前交付物
- 自引用处理：本清单文件不进入包内（`:(exclude)reports/w3/08-package-manifest.md`），否则清单记录自身哈希会形成循环依赖

## 校验值

| 项 | 值 |
|---|---|
| 大小 | 886,363 字节 |
| SHA-256 | `f12b90f4f6e8963803484b2682ec22219b00f5551b2e1aeb971a7fe7b1eb93f9` |
| 条目数 | 235 |
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

结果：**450 tests, OK，180.058s**；`AGENTS.md` 存在，包内无 `dist/`。

## 已知限制（与包一同声明）

- Alpha 未宣布：W3-9 真实语料待外部脱敏输入；P2-01/P2-04 待审计环境复跑。
- 不支持 SDT 内填充（`sdt_edit=false`）；SDT 仅作为 PROTECTED 位置发现并拒绝。
- 本机缺 PyMuPDF/matplotlib/OCR，相关检查如实 `UNVERIFIED`。
