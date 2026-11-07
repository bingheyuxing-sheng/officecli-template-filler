# 发布包清单（v4.2.1）

- 包路径：`dist/officecli-template-filler-v4.2.1.zip`
- 大小：**1,189,228** 字节
- 条目数：**271**
- SHA-256：`33ee1f3bf722b81f0d4efb3af4deeda65ceb68131f09dea43a6201e91c3e5a9f`
- 构建方式：先 `git add` 全部 v4.2.1 变更，再逐文件读取暂存区 blob（`git show :<path>`）用 Python `zipfile` 打包（固定 ZIP 时间戳），因此不受工作区 CRLF、未跟踪文件或构建顺序影响；排除 `.github/`、`dist/`、`__pycache__/`、`.ruff_cache/`、`*.pyc`、`*.pyo`、`*.zip`，以及历史 package manifest 与 `reports/acceptance/w4-9-exit-review.md`。本清单本身也被排除，所以更新哈希不会改变发布包。
- 构建日期：2026-11-07

## 内容核对

| 项 | 结果 |
|---|---|
| `engine.__version__` | `4.2.1` |
| 包含 `scripts/run_tests.py` | 是 |
| 包含 `.github/`（仅仓库 CI） | 否 |
| 包含 `tests/test_entrypoint_package_guard.py` | 是 |
| 包含 `contracts/` 与 `schemas/` | 是 |
| 包含 `.git/` 或 `dist/` | 否 |
| 包含 `__pycache__/` 或 `.pyc` | 否 |
| 包含真实语料 / 用户文档 | 否 |

## 验证

```powershell
python scripts/run_tests.py --profile all
python scripts/run_tests.py --profile fast        # 无 PDF 后端环境
python scripts/run_tests.py --profile external    # 有 WPS/LibreOffice 环境
python -m unittest discover -s tests/contracts -t tests
python -m ruff check . --output-format concise
```

| 检查 | 结果 |
|---|---|
| 全量 `all` | **692 tests OK**（Windows 11 / Python 3.14.10） |
| `fast`（`OFFICECLI_PDF_BACKEND=none`） | **677 tests OK** |
| `external` | **15 tests OK** |
| 契约测试 | **76 tests OK** |
| Ruff 0.17.4 | `All checks passed` |
| GitHub Actions | **6/6 job 通过**（Ubuntu + Windows × Python 3.10/3.12） |

## 本版本修复

| 问题 | 修复 |
|---|---|
| Windows cp1252 无法输出中文 | `run_tests.py` 与 CI 设置 `PYTHONIOENCODING=utf-8` / `PYTHONUTF8=1` |
| Windows 8.3 短路径 vs 长路径 | 两处路径断言双侧 `resolve()` |
| Python 3.12 拒绝 `24:00:00` | 解析前归一化 ISO end-of-day |
| Windows 时钟精度导致摘要测试偶发失败 | 改为断言摘要忽略 `generated_at` |
| Ubuntu 缺少宋体等字体 | 断言改为 `missing ⊆ requested` 且不存在的字体必须被报告 |

## 未验证能力

- Linux / macOS 仅通过 CI fast profile 验证，未做真实文档发布验证。
- officecli 后端仅在 1.0.160 上验证。
- PyMuPDF、matplotlib、OCR 未安装，对应检查按 `UNVERIFIED` 披露。
