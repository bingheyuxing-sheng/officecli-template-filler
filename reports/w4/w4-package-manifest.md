# W4 发布包清单（v4.1.0）

- 包路径：`dist/officecli-template-filler-v4.1.0.zip`
- 大小：**992,825** 字节
- 条目数：**234**
- SHA-256：`6451954c14258fb78b17f7b6eb9938a5d1ac490cbb73ec5e88fb423068c7f71a`
- 构建方式：Python `zipfile` 遍历仓库，排除 `.git/`、`dist/`、`__pycache__/`、`.ruff_cache/`、`*.pyc`、`*.pyo`、`*.zip`；按设计排除本清单与 `w4-9-exit-review.md`（出口证据留在仓库）
- 构建日期：2026-11-06

## 内容核对

| 项 | 结果 |
|---|---|
| 包含 `template_gate/` | 是 |
| 包含 `contracts/06-template-understanding-gate.md` | 是 |
| 包含 3 个 W4 Schema | 是 |
| 包含 `scripts/template_gate.py` | 是 |
| 包含 `config/template-gate-policy.json` | 是 |
| 包含 `reports/w4/w4-0-architecture-audit.md`、`w4-implementation-log.md` | 是 |
| 包含 `.git/` 目录 | 否 |
| 包含 `dist/` 目录 | 否 |
| 包含 `__pycache__/` 或 `.pyc` | 否 |
| 包含真实语料/用户文档 | 否 |
| 包含 7 个闸门错误码 | 是（`config/error-codes.json`） |

## 复现命令

```powershell
py -3.15 -m unittest discover -s tests -p "test_*.py"
py -3.15 -m unittest discover -s tests/contracts -t tests -p "test_*.py"
py -3.15 -m ruff check . --output-format concise
```

结果见 `reports/w4/w4-9-exit-review.md`。
