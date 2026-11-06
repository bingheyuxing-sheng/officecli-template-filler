# 发布包清单（v4.1.1）

- 包路径：`dist/officecli-template-filler-v4.1.1.zip`
- 大小：**993,950** 字节
- 条目数：**235**
- SHA-256：`f994ef64fdf347085dcab9376ec27bc267b27c355063c5371e8d84ed0ce1712c`
- 构建方式：Python `zipfile` 遍历仓库，排除 `.git/`、`dist/`、`__pycache__/`、`.ruff_cache/`、`*.pyc`、`*.pyo`、`*.zip`；按设计排除本清单、v4.1.0 manifest 与 `w4-9-exit-review.md`
- 构建日期：2026-11-06

## 内容核对

| 项 | 结果 |
|---|---|
| `engine.__version__` | `4.1.1` |
| 包含 `template_gate/` | 是 |
| 包含 `references/workflow-details.md` | 是 |
| 包含 `contracts/06-template-understanding-gate.md` | 是 |
| 包含 3 个 W4 Schema | 是 |
| 包含 `scripts/template_gate.py` | 是 |
| 包含 `config/template-gate-policy.json` | 是 |
| 包含 `.git/` 目录 | 否 |
| 包含 `dist/` 目录 | 否 |
| 包含 `__pycache__/` 或 `.pyc` | 否 |
| 包含真实语料/用户文档 | 否 |

## 验证

```powershell
py -3.15 -m unittest discover -s tests -p "test_*.py"
py -3.15 -m unittest discover -s tests/contracts -t tests -p "test_*.py"
py -3.15 -m ruff check . --output-format concise
```

结果：全量 **532 tests OK**；契约 **72 tests OK**；ruff **All checks passed**。
