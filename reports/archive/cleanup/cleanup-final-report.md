# reports/ 与 tests/ 清理最终报告（Cleanup Final Report）

- 执行日期：2026-11-07（Asia/Shanghai）
- 仓库：`d:\docs\officecli-template-filler`
- Git 基线：`main` @ `37ec46f`（执行期间未 commit、未 push、未改 tag）
- 依据：[cleanup-inventory.md](cleanup-inventory.md)、[cleanup-plan.md](cleanup-plan.md)
- 执行范围：`reports/`、`tests/`；未修改业务代码、`contracts/`、`schemas/`、错误码

---

## 1. 清理结果

### 1.1 reports/

| 项 | 数量 |
|---|---:|
| 清理前（2026-11-07 10:11 快照） | 42 |
| 本任务删除 | 1（`w5/be95e82-review.patch`） |
| 本任务新增 | 4（`README.md`、`cleanup/` 三份） |
| 本任务迁移（移动，不改变总数） | 19 |
| 期间并行会话新增（非本任务） | 21（`documentation/` +16、`w5/` +5） |
| 清理后实测 | **66** |

> 数字关系：42 − 1 + 21（并行） + 4（本任务新增） = 66。
> 19 份迁移仅在目录间移动，数量不变。

### 1.2 tests/

| 项 | 数量 |
|---|---:|
| 清理前文件（不含 `.pyc`） | 94 |
| 本任务新增 | 1（`tests/support.py`） |
| 本任务删除源码文件 | 0 |
| 清理后文件（不含 `.pyc`） | **95** |
| 删除字节码缓存 | 3 个 `__pycache__` 目录 / 123 个 `.pyc` |

说明：`.pyc` 在随后执行测试时按 Python 设计**自动重建**（当前 65 个）。目录仍由 `.gitignore` 忽略，未进入版本控制。

### 1.3 操作汇总

| 操作 | reports | tests | 合计 |
|---|---:|---:|---:|
| KEEP | 40 | 87 | 127 |
| MERGE | 0 | 7 | 7 |
| ARCHIVE | 2 | 0 | 2 |
| DELETE | 1 | 0（源码）+ 123 `.pyc` | 1 + 缓存 |
| REVIEW | 1（`documentation/version-facts.md`） | 0 | 1 |
| 迁移（目录重组，非删除） | 19 | 0 | 19 |

---

## 2. reports 整理结果

### 2.1 目录结构（最终）

已完成物理角色归档，同时保留冻结引用锚点：

```text
reports/
├── README.md                       唯一索引（44 个路径引用全部可达）
├── development/    10             开发过程
├── acceptance/      7             最终验收
├── archive/         2             历史快照
├── w0/  4 ┐
├── w1/  1 │
├── w2/  1 ├ 14 个冻结引用锚点
├── w3/  7 │
├── w4/  1 ┘
├── w5/             12             W5 进行中（不归档）
├── documentation/  17             版本事实与 Release 说明（并行维护）
└── cleanup/         3             本次治理记录
```

**为什么保留 14 个锚点**：这些文件被冻结契约（6 个文件、10 处引用）、`AGENTS.md`（3 处）、`CHANGELOG.md`（2 处）或 `tests/real_corpus_eval.py`（2 个默认路径）引用。任务禁止修改契约，因此这 14 份保持原路径不动。

**可移动判定方法**：对 `w0/`–`w4/` 33 份报告逐一扫描 `reports/` 之外的引用来源；无外部引用的 19 份迁入角色目录，其余保留。逐文件映射见 `cleanup-plan.md` §6.1。

### 2.2 重要报告保留情况

- W0–W4 全部 33 份报告**内容保留**：19 份迁入角色目录（正文除路径引用外未改写），14 份保持原路径。
- 唯一负面独立裁决 `w3/12-independent-exit-review.md`（v4.0.0 FAIL）保持锚点位置不动。
- 契约冻结与版本清单全部保留：`development/w3-04b-manifest.md`、`acceptance/w3-11-package-manifest-v4.0.0.md`、`acceptance/w3-14-package-manifest-v4.0.1.md`、`acceptance/w4-package-manifest-v4.1.*.md`、锚点 `w0/05-contract-freeze-report.md`。
- W5 全部文档保留，并在索引中标注“进行中，不得归档”（G1.5 待人工批准，B2/B3 未启动）。
- 并行会话新增的 21 份文件（`documentation/` 16、`w5/` 5）全部保留并纳入索引。

### 2.3 历史报告归档情况

| 文件 | 原路径 | 归档理由 |
|---|---|---|
| `archive/w3-08-package-manifest-dev-snapshot.md` | `w3/08-package-manifest.md` | v4.0.0-dev-w3 开发快照，已被正式包清单取代；仍作为 W3-8⑤ 完成证据 |
| `archive/w3-real-corpus-candidates.md` | `w3/real-corpus-candidates.md` | 语料初筛记录，评测结果已由 `w3/real-corpus-eval.*` 交付 |

### 2.4 删除、迁移与失效引用修复

| 项 | 结果 |
|---|---|
| 删除 `w5/be95e82-review.patch` | 删除前已实测其与 `git diff be95e82^ be95e82` **逐字节一致**，可完整重建 |
| 因删除导致的失效引用 | 0（唯一引用方 `w5/w5-github-sync-plan.md` 保留说明性文字，不构成断链） |
| 迁移文件 | 19 份（10 development、7 acceptance、2 archive） |
| 因移动导致的失效引用 | 已扫描并修复 **42 处**，覆盖 21 个 Markdown 文件；复查 0 处残留（`cleanup/` 内的“执行前快照”表述除外） |
| 冻结契约引用 | 0 修改；10 处引用全部指向保留锚点，仍然有效 |
| 索引链接 | `reports/README.md` 44 个路径引用全部校验存在 |

---

## 3. tests 整理结果

### 3.1 目录结构

保持既有四层划分，不做重构：

```text
tests/
├── test_*.py            47 个（W0–W4 单元/集成/回归/端到端）
├── contracts/           10 个测试 + helpers.py + __init__.py（契约测试）
├── w5/                  3 个测试 + __init__.py（W5-B1，进行中）
├── fixtures/            6 类 fixture + legacy 资产 + 生成脚本
├── gate_helpers.py      既有共享辅助
└── support.py           新增共享辅助（本次合并目标）
```

不重构理由（实测）：30 个测试文件用 `Path(__file__).resolve().parents[1]` 定位仓库根，3 个用相对 `fixtures` 路径；下移一层需改动 ≥33 个文件的路径算术，且会扩大审查面而不增加覆盖。

### 3.2 重复测试处理情况

**发现 1 组方法体完全相同的用例**（AST 归一化比对，60 文件 / 653 方法）：

`tests/w5/test_b1_base.py::CapabilityRecordTests`

| 用例 | 原验证场景 | 处理后 |
|---|---|---|
| `test_verified_without_evidence_is_rejected` | `verified=True` + 无 `verified_by` → 拒绝（`base.py:191`） | **不变**，继续覆盖 `base.py:191` |
| `test_available_without_evidence_is_rejected` | 声称覆盖「未验证却 available」，实际因默认 `verified=True` 也在 `base.py:191` 抛出，`base.py:193` 无独立用例 | 输入改为 `_verified_record(verified=False, verified_by=())`，真正覆盖 `base.py:193` |

结果：用例数不变（653），两条不变量从「1 条被覆盖、1 条被伪装覆盖」变为「各自独立覆盖」，覆盖能力净增。

### 3.3 Fixture 整理情况

新增 `tests/support.py`，合并 2 个重复纯函数：

| 合并项 | 原位置 | 调用点 | 等价性 |
|---|---|---|---|
| `sha256_file` | `test_e2e_v4.py`、`test_fixture_matrix.py`、`test_w2_defects.py`、`test_transaction_gate.py` 各自的 `_sha256` | 16 处 | 逐字相同或仅分块大小不同（64 KB vs 1 MB），SHA-256 结果与分块无关 |
| `passing_qa` | `test_template_gate_e2e.py`、`test_template_gate_enforcement.py` 各自的 `_passing_qa` | 2 处 | 逐字相同 |

合并只改变定义位置，不改变返回值、调用时机或断言语义；`tests/support.py` 不以 `test_` 命名，不参与发现。

**未合并**（经核对为同名不同物或收益低于风险）：`_template`（5 处，内容不同）、`_standard_template`（2 处，内容不同）、`_source_docx`/`_staged_leftovers`（类方法与模块函数混用，需改 6 处调用点）。

### 3.4 回归测试与契约测试保留情况

| 类别 | 保留 |
|---|---|
| 契约测试 | `tests/contracts/` 10 个文件、72 用例，全部保留且通过 |
| 历史缺陷回归 | `test_w2_defects.py`（5）、`test_residual_inheritance.py`（4）、`test_fill_fidelity_inplace.py`（18）、`test_excel_spec_resilience.py`（4）、`test_pdf_hygiene.py`（6）、`test_excel_status_merge.py`（6），全部保留 |
| 安全相关 | `test_package_guard.py`（15）、`test_template_gate_store.py`（7）、`test_template_gate_enforcement.py`（6）、`test_process_ownership.py`（5），全部保留 |
| v3.5.9 兼容基线 | `test_v3_engine.py`（50）等，全部保留 |

未删除任何测试用例。

---

## 4. 测试验证结果

### 4.1 全量测试

```text
py -3.15 -m unittest discover -s tests -p "test_*.py"
→ Ran 653 tests in 219.676s — OK
```

清理后另行复跑一次：`Ran 653 tests in 225.079s — OK`。0 失败、0 错误、0 跳过。

### 4.2 契约与专项

```text
py -3.15 -m unittest discover -s tests/contracts -t tests -p "test_*.py"
→ Ran 72 tests in 1.356s — OK

py -3.15 -m unittest discover -s tests/w5 -t . -p "test_*.py"
→ Ran 109 tests in 0.007s — OK
```

### 4.3 Ruff

```text
py -3.15 -m ruff check .
→ All checks passed!
```

### 4.4 测试目录导入检查 / 发现覆盖

```text
discovered_modules=60  on_disk_test_modules=60
undiscovered=[]        discovered_not_on_disk=[]
discovered_cases=653   naming_outliers=[]
```

60 个测试模块全部被 `-s tests -p "test_*.py"` 加载，无漏收、无多余、无命名不符。

### 4.5 文档链接检查

对 `reports/README.md` 内全部反引号路径（44 个）逐一校验存在性：**全部可达**。
另对 19 份迁移文件涉及的 42 处引用做全仓库复查：除 `cleanup/` 中标注为“执行前快照/已移动”的历史表述外，0 处指向已不存在的路径。

### 4.6 CI 测试入口检查

仓库不存在 `.github/`、`pytest.ini`、`pyproject.toml`、`setup.cfg`；固定入口为 `unittest discover`（见 `requirements-dev.txt`、`README.md:197`、`CHANGELOG.md`）。本次未替换测试标准，未引入 pytest。

### 4.7 整理前后对比

| 指标 | 清理前 | 清理后 | 判定 |
|---|---:|---:|---|
| 测试文件（`test_*.py`） | 60 | 60 | 不变 |
| 测试用例 | 653 | 653 | 不变 |
| 通过 / 失败 / 跳过 | 653 / 0 / 0 | 653 / 0 / 0 | 不退化 |
| 契约用例 | 72 | 72 | 不变 |
| Ruff | pass | pass | 不变 |
| 覆盖率统计 | 项目无覆盖率配置 | 不适用 | 以用例数与场景矩阵代替 |
| 关键回归场景 | 全部保留 | 全部保留 | 不退化 |
| `base.py:193` 覆盖 | 无独立用例 | 有独立用例 | **净增** |

---

## 5. 风险与遗留问题

1. **`reports/documentation/` 与 `reports/w5/` 由并行会话持续写入**。执行期间新增 21 个文件，本任务未读取后回写、未移动、未删除；已全部登记入 `cleanup-inventory.md` §3.1A 与 `reports/README.md`。
2. **`reports/README.md` 的清单以整理时点为准**；`w5/` 与 `documentation/` 仍在演进，索引对这两处采用角色约定而非冻结清单。
3. **14 份报告保留在原 `wN/` 作为锚点**，未迁入角色目录：它们被冻结契约（10 处）、`AGENTS.md`（3 处）、`CHANGELOG.md`（2 处）或 `tests/real_corpus_eval.py`（2 处）引用。解除锚点须先取得引用方修改授权。
4. **`tests/w5/test_b1_base.py` 属 W5-B1 已提交测试证据**，本次改动仅修正重复用例输入。建议在 W5 的 G1.5 审查记录中同步说明（本次未修改任何 W5 报告）。
5. **`reports/documentation/version-facts.md` 归属未裁决**（原计划列为 REVIEW）。本任务保持原样，未移动、未合并。
6. **`README.md` / `SKILL.md` 中 `reports/` 目录注释仍写“W0–W3”/“W0–W4”**，已滞后于 W0–W5。因 `README.md`/`CHANGELOG.md` 正被并行会话重写，本任务未触碰；建议由该会话统一更新。
7. **`.pyc` 已按 Python 机制自动重建**（当前 65 个，gitignored），不属于残留问题。
8. **未创建 Commit、未 Push、未修改 Tag**，所有变更仍在工作区等待人工审核。

---

## 6. Git 状态与变更清单

### 6.1 `git status --short`

```text
 M CHANGELOG.md
 M README.md
 M document_backends/result.py
 M tests/test_e2e_v4.py
 M tests/test_fixture_matrix.py
 M tests/test_template_gate_e2e.py
 M tests/test_template_gate_enforcement.py
 M tests/test_transaction_gate.py
 M tests/test_w2_defects.py
 M tests/w5/test_b1_base.py
 M tests/w5/test_b1_result.py
?? dist/
?? reports/README.md
?? reports/cleanup/
?? reports/documentation/
?? reports/w5/
?? tests/support.py
```

### 6.2 本任务的文件变更清单

**删除**

```text
reports/w5/be95e82-review.patch          （与 git diff be95e82^ be95e82 逐字节一致）
tests/**/__pycache__/                     （3 个目录，123 个 .pyc；测试后自动重建）
```

**新增**

```text
reports/README.md                         唯一索引
reports/cleanup/cleanup-inventory.md      清理前清单
reports/cleanup/cleanup-plan.md           清理计划
reports/cleanup/cleanup-final-report.md   本报告
tests/support.py                          共享测试辅助（sha256_file / passing_qa）
```

**迁移（19 份，目录重组；内容除路径引用外未改写）**

```text
reports/w2/01-contract-change-manifest.md -> reports/development/w2-01-contract-change-manifest.md
reports/w2/issues.md                      -> reports/development/w2-issues.md
reports/w2/w2-acceptance.md               -> reports/acceptance/w2-acceptance.md
reports/w3/04b-implementation.md          -> reports/development/w3-04b-implementation.md
reports/w3/04b-manifest.md                -> reports/development/w3-04b-manifest.md
reports/w3/07-w3-6-review.md              -> reports/development/w3-07-w3-6-review.md
reports/w3/07-w3-8-review.md              -> reports/development/w3-07-w3-8-review.md
reports/w3/09-docs-cleanup-report.md      -> reports/development/w3-09-docs-cleanup-report.md
reports/w3/audit-triage.md                -> reports/development/w3-audit-triage.md
reports/w4/w4-0-architecture-audit.md     -> reports/development/w4-0-architecture-audit.md
reports/w4/w4-implementation-log.md       -> reports/development/w4-implementation-log.md
reports/w3/11-package-manifest.md         -> reports/acceptance/w3-11-package-manifest-v4.0.0.md
reports/w3/13-v4.0.1-exit-evidence.md     -> reports/acceptance/w3-13-v4.0.1-exit-evidence.md
reports/w3/14-package-manifest-v4.0.1.md  -> reports/acceptance/w3-14-package-manifest-v4.0.1.md
reports/w4/w4-package-manifest.md         -> reports/acceptance/w4-package-manifest-v4.1.0.md
reports/w4/w4-package-manifest-v4.1.1.md  -> reports/acceptance/w4-package-manifest-v4.1.1.md
reports/w4/w4-package-manifest-v4.1.2.md  -> reports/acceptance/w4-package-manifest-v4.1.2.md
reports/w3/08-package-manifest.md         -> reports/archive/w3-08-package-manifest-dev-snapshot.md
reports/w3/real-corpus-candidates.md      -> reports/archive/w3-real-corpus-candidates.md
```

**修改（仅测试文件）**

```text
tests/test_e2e_v4.py             移除本地 _sha256 与未使用的 hashlib 导入，改用 support.sha256_file
tests/test_fixture_matrix.py     移除本地 _sha256，改用 support.sha256_file
tests/test_w2_defects.py         移除本地 _sha256，改用 support.sha256_file
tests/test_transaction_gate.py   移除本地 _sha256，改用 support.sha256_file
tests/test_template_gate_e2e.py          移除本地 _passing_qa，改用 support.passing_qa
tests/test_template_gate_enforcement.py  移除本地 _passing_qa，改用 support.passing_qa
tests/w5/test_b1_base.py         修正重复用例输入（verified=False），补足 base.py:193 覆盖
```

**修改（仅路径引用，共 42 处 / 21 个 Markdown 文件）**

```text
reports/README.md                         按新结构重写
reports/cleanup/cleanup-inventory.md      增补快照后登记与执行后结构
reports/cleanup/cleanup-plan.md           追加执行结果与迁移映射
reports/cleanup/cleanup-final-report.md   本报告
其余 17 个报告                          仅将指向已迁移文件的路径替换为新路径
```

**未由本任务改动（仅存在）**

```text
CHANGELOG.md、README.md                并行会话改写
document_backends/result.py            W5-B1-R3 未提交修改（用户/前序任务）
tests/w5/test_b1_result.py             W5-B1-R3 未提交修改（用户/前序任务）
dist/、reports/w5/、reports/documentation/   并行/用户产物
```

---

## 7. 结论

- 清理未删除任何历史证据性报告，未删除任何测试用例。
- 删除项仅为 1 个可逐字节重建的 diff 补丁与 3 个字节码缓存目录。
- 测试用例数 653 → 653，契约 72 → 72，Ruff 保持通过；安全、契约、回归测试全部保留。
- `base.py:193` 的安全不变量由“无独立覆盖”变为“有独立覆盖”。
- `reports/` 已完成物理角色归档（development 10 / acceptance 7 / archive 2），14 个冻结引用锚点保持原位，42 处引用已同步更新，索引 44 个链接全部可达。
- 并行会话新增的 21 份文件已登记入清单与索引，未被移动或改写。
- W5 进行中状态已显式标注，未被误归档。
