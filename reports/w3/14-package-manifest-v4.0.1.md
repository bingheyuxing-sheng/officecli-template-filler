# v4.0.1 发布包清单

- 日期：2026-11-05
- 产物：`dist/officecli-template-filler-v4.0.1.zip`
- 来源：`git archive`，源提交 `b4b1625`（`docs(release): record v4.0.1 B1 closure evidence`）
- 发布级别：**稳定版补丁**（GitHub Release Latest stable）
- 自引用处理：本清单不进入包内（`:(exclude)reports/w3/14-package-manifest-v4.0.1.md`），`dist/` 整体排除
- 说明：tag `v4.0.1` 指向包含本清单与 zip 的提交；zip 内容对应该提交之前的源提交 `b4b1625`，差异仅为清单与 zip 自身

## 校验值

| 项 | 值 |
|---|---|
| 文件名 | `officecli-template-filler-v4.0.1.zip` |
| 大小 | 939,039 字节 |
| SHA-256 | `106a96fe7a6c4fa2953e7a2f11c9586d5c327bc976f33a0eec30cbc090706bb2` |
| 条目数 | 246 |
| 前缀 | `officecli-template-filler/` |

## 内容核对

- 包含：`SKILL.md`、`README.md`、`CHANGELOG.md`（v4.0.1 合规补丁条目）、`AGENTS.md`、`contracts/`（4.2.0）、`schemas/`、`config/`、`examples/`、`tests/`（六类结构化 fixtures、契约测试、W3 回归、匿名化真实语料评测脚本）、`reports/w0–w3/`（含 `12-independent-exit-review.md`、`13-v4.0.1-exit-evidence.md`）、`engine/`、`template_intelligence/`、`content_intelligence/`、`document_engine/`、`qa/`、`scripts/`、`references/`。
- 排除：`dist/`（历史归档与本次包自身）、`.git/`、缓存、临时文件与本清单。
- 二进制文档仅合成/结构化 fixtures；无真实用户文档、无语料路径/文件名/正文。

## 验证

在解包副本中运行完整套件：

```powershell
python -m unittest discover -s tests -p "test_*.py"
```

结果：**479 tests, OK，171.615s**（Windows，Python 3.15；0 failure / 0 error / 0 skip）。

## 已知限制（与包一同声明）

- Linux/LibreOffice 审计环境复验未完成（B2）；P2-01/P2-04 关闭条件不变。
- v4.0.1 的独立复核尚未执行；条件 8 不声称已通过。
- 真实语料无人工标注基线，不计算、不声称槽位准确率。
- 不支持 SDT 内填充（`sdt_edit=false`）；浮动图片 QA 为 `UNVERIFIED`。
- 本机缺 PyMuPDF/matplotlib/OCR，相关检查如实 `UNVERIFIED`。
