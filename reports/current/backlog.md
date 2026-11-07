# 当前待办与阻塞项

- 日期：2026-11-07
- 状态：**P0：0，P1：0，P2：20**
- 阻塞项：**无**。下列 P2 不阻断 v4.2.1；POLISH / MERGE / SDT 内填充属于产品范围决策，不是缺陷。

## 1. 已关闭

| 级别 | ID | 关闭版本 |
|---|---|---|
| P0 | COMPAT-01 Python 版本声明 | v4.2.0 |
| P1 | SEC-01 ZIP 配额覆盖 7 个入口 | v4.2.0 |
| P1 | SEC-02 移除公式 `eval` | v4.2.0 |
| P1 | QA-01 `UNVERIFIED` 退出码 | v4.2.0 |
| P1 | QA-02 QA 主链降级收口 | v4.2.0 |
| P1 | ARCH-01 后端双轨披露 | v4.2.0 |
| P1 | PROC-01 PDF 进程树回收 | v4.2.0 |
| P1 | TEST-01 测试 profile 分层 | v4.2.0 |
| P1 | CI-01 GitHub Actions | v4.2.0 / v4.2.1 绿 |
| P1 | VER-01 契约版本一致性 | v4.2.0 |
| P1 | VER-02 版本号与发布一致 | v4.2.0 / v4.2.1 |

## 2. P2 待办

| ID | 模块 | 事项 | 建议方向 |
|---|---|---|---|
| SEC-03 | `template_gate/store.py` | HMAC 密钥创建存在并发竞态；Windows `chmod` 不设 ACL | `os.open(O_CREAT|O_EXCL)`；Windows 显式 ACL |
| SEC-04 | `engine/package_guard.py` | 未校验 ZIP 条目名路径穿越 | 增加条目名规范化与拒绝规则 |
| PERF-01 | `qa/pipeline.py` | 一次 QA 重复解析 staged 4 次、模板 3 次 | 单次运行内缓存 Document |
| PERF-02 | `engine/package_guard.py` | 图片像素统计对每个条目重开 ZIP | 复用 ZipFile 句柄 |
| PERF-03 | `engine/pdf_backend.py` | 每次能力探测全盘 glob | 进程级缓存探测结果 |
| BUG-01 | `engine/pdf_backend.py` | 版本排序键混用 int/str，可能 `TypeError` | 稳定元组键 |
| QA-03 | `document_engine/fill_executor.py` | 错误码注册表加载失败静默置空 | 显式阻断或写入 coverage_gaps |
| TEST-02 | 8 个核心模块 | 无直接单元测试 | 补表格/SSOT/样式/一致性/图片/修复/重排/plan_validator 单测 |
| TEST-03 | 多个测试 | `TemporaryDirectory` 未显式释放 | `addCleanup(cleanup)` 或 `tmp_path` |
| TEST-04 | `CHANGELOG.md` | 测试数字多口径 | 统一为版本 × 环境 × 日期表 |
| MAINT-01 | 全仓 | 47 个函数 ≥100 行，最长 622 行 | 先补测试再按阶段拆分 |
| MAINT-02 | `scripts/` | 无 `pyproject.toml`，13 处 `sys.path.insert` | 增加打包元数据与入口点 |
| MAINT-03 | 全仓 | 80 处 `except Exception:` 无统一日志 | 统一 `soft_fail` 记录 |
| MAINT-04 | `engine` / `template_intelligence` | 两个 `normalize_text` 同名不同语义 | 重命名区分 |
| MAINT-05 | `engine/*`、各包 `__init__` | 8 个模块缺编码头，5 个缺 `__future__` | 统一头部并用 CI 约束 |
| TREE-01 | 仓库根 | `dist/` 与 `.gitignore` 策略冲突 | 决定跟踪或忽略，并清理工作树 |
| DOC-01 | `fill_executor.py` | docstring 称 “silently falls back”，实际记录原因 | 修正措辞 |
| DOC-02 | `README.md` | WPS/LibreOffice 列为“可选”但配置为 required | 明确“缺失时只能 UNVERIFIED” |
| DOC-03 | `AGENTS.md` | 已更新至 v4.2.1，但测试基线仍需随发布维护 | 发布流程自动核对 |
| UNFIN-01 | `engine/capabilities.py` | POLISH / MERGE 无入口；SDT 内填充不开放 | 单独立项，不顺手扩展 |

## 3. 下一阶段入口条件

1. 完成 MAINT-01 / TEST-02 中与 `fill_executor`、`table_engine`、`ssot_engine` 相关的部分。
2. 对 W5-B2 做 ADR：`document_backends` 接入或归档。
3. 任何冻结契约变更必须先走 `contracts/README.md` §2 的提案流程。
