# 发布包清单（v4.2.0）

- 包路径：`dist/officecli-template-filler-v4.2.0.zip`
- 大小：**1,187,653** 字节
- 条目数：**271**
- SHA-256：`22a9fb5d9933fe4902bc7cc6b053d4f41fe19c1261804a773f27978ba84a494d`
- 构建方式：逐文件读取 `git show v4.2.0:<path>` 的 blob 内容并用 Python `zipfile` 打包（固定 ZIP 时间戳），因此不受工作区 CRLF/未跟踪文件影响；排除 `.github/`、`dist/`、`__pycache__/`、`.ruff_cache/`、`*.pyc`、`*.pyo`、`*.zip`，以及历史 package manifest 与 `reports/acceptance/w4-9-exit-review.md`。已逐条比对 271 个条目与 tag blob 的 SHA-256，**0 mismatch**。
- 构建日期：2026-11-07

## 内容核对

| 项 | 结果 |
|---|---|
| `engine.__version__` | `4.2.0` |
| 包含 `document_backends/`（EXPERIMENTAL_NOT_WIRED） | 是 |
| 包含 `scripts/run_tests.py` | 是 |
| 包含 `tests/test_entrypoint_package_guard.py` | 是 |
| 包含 `contracts/` 与 `schemas/` | 是 |
| 包含 `.git/` 或 `dist/` | 否 |
| 包含 `__pycache__/` 或 `.pyc` | 否 |
| 包含 `.github/`（仅仓库 CI） | 否 |
| 包含真实语料 / 用户文档 | 否 |

## 验证

```powershell
python scripts/run_tests.py --profile all
python scripts/run_tests.py --profile fast        # 无 PDF 后端环境
python scripts/run_tests.py --profile external    # 有 WPS/LibreOffice 环境
python -m unittest discover -s tests/contracts -t tests
python -m ruff check . --output-format concise
```

结果：

| 检查 | 结果 |
|---|---|
| 全量 `all` | **692 tests OK**（243.154s，Windows 11 / Python 3.14.10） |
| `fast`（`OFFICECLI_PDF_BACKEND=none`） | **670 tests OK**（92.893s），跳过 2 个外部依赖模块 |
| `external` | **15 tests OK**（76.586s，本机 WPS） |
| 契约测试 | **76 tests OK** |
| Ruff 0.17.4 | `All checks passed` |

## 本版本包含的 P0/P1 修复

| ID | 修复 |
|---|---|
| COMPAT-01 | Python 最低版本统一为 3.10 |
| SEC-01 | 7 个解析入口接入 ZIP 配额 |
| SEC-02 | Excel 公式求值移除 `eval` |
| QA-01 | `run_qa.py` 的 `UNVERIFIED` 退出码改为 1，新增 `--allow-unverified` |
| QA-02 | 仅在 `qa` 包缺失时降级，内部错误显式失败 |
| PROC-01 | PDF 转换接入进程所有权管理并终止进程树 |
| TEST-01 | 测试拆分为 fast / external / all |
| CI-01 | 新增 GitHub Actions（ruff + fast profile） |
| ARCH-01 | `document_backends` 标记为 EXPERIMENTAL_NOT_WIRED |
| VER-01 | 契约集版本统一为 4.3.0 并加一致性测试 |
| VER-02 | 4.2.0 正式发布，版本号 / tag / CHANGELOG 一致 |

## 未验证能力

- Linux / macOS 运行时未在本机验证；CI 工作流已配置 Ubuntu / Windows 矩阵，但本次发布前未在远端执行。
- officecli 后端仅在 officecli 1.0.160 上验证；其他版本需重跑 `tests/test_officecli_writer.py`。
- PyMuPDF、matplotlib、OCR 仍未安装，对应检查按 `UNVERIFIED` 披露。
