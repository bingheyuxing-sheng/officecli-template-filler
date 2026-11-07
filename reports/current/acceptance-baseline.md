# 当前验收基线

- 日期：2026-11-07
- 基线版本：**v4.2.1**
- 分支 / Tag：`main` / `v4.2.1`
- 契约集：4.3.0（4.2.0 冻结基线 + Contract 06 DRAFT）
- 产物 `schema_version`：4.0

## 1. 测试结果

| 检查 | 命令 | 结果 |
|---|---|---|
| 全量 | `python scripts/run_tests.py --profile all` | **692 tests OK**（269.120s） |
| 宿主无关 | `python scripts/run_tests.py --profile fast` | **677 tests OK**（`OFFICECLI_PDF_BACKEND=none` 下 87.569s） |
| 外部依赖 | `python scripts/run_tests.py --profile external` | **15 tests OK**（76.586s，本机 WPS） |
| 契约 | `python -m unittest discover -s tests/contracts -t tests` | **76 tests OK** |
| 静态检查 | `python -m ruff check .` | **All checks passed**（0.17.4） |
| GitHub Actions | `.github/workflows/ci.yml` | **6/6 job 通过**（Ubuntu / Windows × Python 3.10 / 3.12） |

环境：Windows 11、Python 3.14.10、python-docx 1.2.0、WPS PDF 后端可用；CI 覆盖 Python 3.10 / 3.12。

## 2. 发布证据

- Release：[v4.2.1](https://github.com/bingheyuxing-sheng/officecli-template-filler/releases/tag/v4.2.1)（Latest）
- 资产：`officecli-template-filler-v4.2.1.zip`
  - 大小：1,189,228 字节
  - 条目：271
  - SHA-256：`33ee1f3bf722b81f0d4efb3af4deeda65ceb68131f09dea43a6201e91c3e5a9f`
- 包清单：`reports/acceptance/w5-package-manifest-v4.2.1.md`
- 资产由 tag 的暂存区 blob 构建，271 个条目逐条比对，0 mismatch。

## 3. 契约与版本一致性

- `engine.__version__` = `4.2.1`；CHANGELOG 存在 `## v4.2.1` 段；tag 指向 `d7aed75`。
- 契约索引、AGENTS.md、各契约头部的版本由 `tests/contracts/test_version_consistency.py` 交叉校验。
- 冻结契约字段与 `schema_version` 未变。

## 4. 未验证能力

- Linux / macOS 仅通过 CI fast profile 验证，未做真实文档发布验证。
- officecli 后端仅在 1.0.160 上验证。
- PyMuPDF、matplotlib、OCR 未安装，对应检查按 `UNVERIFIED` 披露。

## 5. 复现命令

```bash
python -m pip install -r requirements.txt -r requirements-dev.txt ruff
python -m ruff check .
python scripts/run_tests.py --profile fast
python scripts/run_tests.py --profile external   # 需 WPS/LibreOffice 或 officecli
python scripts/run_tests.py --profile all
```
