# 发布包清单（v4.1.2）

- 包路径：`dist/officecli-template-filler-v4.1.2.zip`
- 大小：**997,540** 字节
- 条目数：**236**
- SHA-256：`c66c652ec177fcc57a3dade003fdd22d2603071405406d87ce39de5a84f23f53`
- 构建方式：Python `zipfile` 遍历仓库，排除 `.git/`、`dist/`、`__pycache__/`、`.ruff_cache/`、`*.pyc`、`*.pyo`、`*.zip`；按设计排除本清单、v4.1.0/v4.1.1 manifest 与 `w4-9-exit-review.md`
- 构建日期：2026-11-06

## 内容核对

| 项 | 结果 |
|---|---|
| `engine.__version__` | `4.1.2` |
| 包含 `template_gate/` | 是 |
| 包含 `references/workflow-details.md` | 是 |
| 包含 `tests/test_review_findings.py` | 是 |
| 包含 `review_document.py --findings` | 是 |
| 包含 `.git/` 目录 | 否；仅 `.gitignore` / `.gitattributes` |
| 包含 `dist/` 目录 | 否 |
| 包含 `__pycache__/` 或 `.pyc` | 否 |
| 包含真实语料/用户文档 | 否 |

## 验证

```powershell
py -3.15 -m unittest discover -s tests -p "test_*.py"
py -3.15 -m unittest discover -s tests/contracts -t tests -p "test_*.py"
py -3.15 -m ruff check . --output-format concise
```

结果：全量 **535 tests OK（191.921s）**；契约 **72 tests OK（1.298s）**；ruff **All checks passed**。
