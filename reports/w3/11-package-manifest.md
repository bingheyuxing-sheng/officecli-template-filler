# v4.0.0 发布包清单

- 日期：2026-11-05
- 产物：`dist/officecli-template-filler-v4.0.0.zip`
- 来源：`git archive`，源提交 `e50f27c`（`release: v4.0.0 stable`）
- 发布级别：**稳定版**（GitHub Release 标记 Latest stable）
- 自引用处理：本清单不进入包内（`:(exclude)reports/w3/11-package-manifest.md`），`dist/` 整体排除
- 说明：本清单与 zip 作为发布提交的一部分提交；tag `v4.0.0` 指向包含它们的提交，而 zip 内容对应其上一条源提交 `e50f27c`，两者差异仅为清单与 zip 自身

## 校验值

| 项 | 值 |
|---|---|
| 文件名 | `officecli-template-filler-v4.0.0.zip` |
| 大小 | 923,924 字节 |
| SHA-256 | `2c22cf4c20ebfb571516a9f2e11e7e0e725e3c7fbe983d78ea42497367207719` |
| 条目数 | 243 |
| 前缀 | `officecli-template-filler/` |

## 内容核对

- 包含：`SKILL.md`、`README.md`、`CHANGELOG.md`（v4.0.0 稳定版条目）、`AGENTS.md`（契约 4.2.0 权威副本）、`contracts/`（含 CP-W2-001/002）、`schemas/`、`config/`、`examples/`、`tests/`（六类结构化 fixtures、契约测试、W3 回归、真实语料评测脚本）、`reports/w0–w3/`（含 `10-exit-review.md` 与匿名化真实语料报告）、`engine/`、`template_intelligence/`、`content_intelligence/`、`document_engine/`、`qa/`、`scripts/`、`references/`。
- 排除：`dist/`（历史归档与本次包自身）、`.git/`、缓存与临时文件。
- 二进制文档仅 8 个合成/结构化 fixture（六类模板 + legacy ref/out）；无真实用户文档、无语料路径或文件名。

## 验证

在解包副本中运行完整套件：

```powershell
python -m unittest discover -s tests -p "test_*.py"
```

结果：**479 tests, OK，173.457s**（Windows，Python 3.15）。

## 已知限制（与包一同声明）

- 真实语料无人工标注基线，不计算、不声称槽位准确率。
- 不支持 SDT 内填充（`sdt_edit=false`）；SDT 仅作为 PROTECTED 位置发现并拒绝。
- 本机缺 PyMuPDF/matplotlib/OCR，相关检查如实 `UNVERIFIED`。
- 仅在 Windows + WPS 后端完成全量验证；Linux/LibreOffice 未验证。
- 独立 Agent 07 复查缺口见 `reports/w3/10-exit-review.md` §6。
