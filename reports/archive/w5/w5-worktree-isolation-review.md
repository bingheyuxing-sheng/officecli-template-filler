# W5 工作区隔离审查报告

- 报告日期：2026-11-07
- 快照时间：2026-11-07 10:21:54 +08:00（Asia/Shanghai）
- 基线：`main` @ `37ec46f`；远程 `origin/main` @ `bd9a2d6`
- 审查性质：只读；未修改、删除、暂存或还原任何文件
- 结论：**R3 改动与外部并发改动可文本隔离，但工作区不处于稳定状态；外部改动归属为 REVIEW，不能混入 R3 提交**

---

## 1. 当前 Git 状态快照

```text
## main...origin/main [ahead 4]

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

- `HEAD` 仍为 `37ec46f78eefd75da065a911371c864bb01b7dff`。
- 远程 `main` 仍为 `bd9a2d6`。
- `contracts/`、`schemas/`、`config/` 工作区差异为空。
- 工作区在 10:09–10:17 期间持续变化；本快照只是时点记录，不保证后续不再变化。

---

## 2. Diff 摘要

| 文件 | 增/删 | 分类 | 是否 R3 |
|---|---:|---|---|
| `document_backends/result.py` | +17 / −6 | R3 生产代码 | **是** |
| `tests/w5/test_b1_result.py` | +98 / −0 | R3 测试 | **是** |
| `README.md` | +221 / −176 | 文档/版本事实 | 否 |
| `CHANGELOG.md` | +575 / −288 | 文档/版本事实 | 否 |
| `tests/test_e2e_v4.py` | +6 / −14 | 测试辅助重构 | 否 |
| `tests/test_fixture_matrix.py` | +4 / −11 | 测试辅助重构 | 否 |
| `tests/test_template_gate_e2e.py` | +2 / −5 | 测试辅助重构 | 否 |
| `tests/test_template_gate_enforcement.py` | +2 / −5 | 测试辅助重构 | 否 |
| `tests/test_transaction_gate.py` | +4 / −11 | 测试辅助重构 | 否 |
| `tests/test_w2_defects.py` | +6 / −13 | 测试辅助重构 | 否 |
| `tests/w5/test_b1_base.py` | +1 / −1 | 外部测试改动 | 否（**不在 R3 允许范围**） |
| `tests/support.py` | 新增 944 B | 测试辅助模块 | 否 |

---

## 3. 外部改动内容分析

### 3.1 README.md / CHANGELOG.md

- 内容性重写，不是仅换行。
- README 当前出现“v4.1.2 准备发布、4.2.0 开发中、653 项通过”等版本事实表。
- CHANGELOG 当前出现“阅读说明”“版本速览”“4.2.0（开发中，未发布）”等新章节。
- `reports/cleanup/cleanup-inventory.md` L33–L40 明确记录：README/CHANGELOG 由另一个并行会话的版本事实整理工作写入，该清理任务未读取后回写、未暂存、未还原。
- `reports/documentation/version-facts.md` 与 `reports/documentation/releases/*.md` 是版本事实调查与 Release 说明草稿。
- **归属判断**：关联候选为“并行文档/版本事实整理任务”；但本次任务没有看到该任务的授权记录，标记 **REVIEW**。

### 3.2 测试辅助重构

- `tests/support.py` 新增，提供 `sha256_file()` 与 `passing_qa()` 两个测试辅助函数。
- 抽查 `test_e2e_v4.py`、`test_fixture_matrix.py` 确认：6 个既有测试文件改为从 `support` 导入，删除各自重复的 `_sha256` 或 QA stub；其余文件模式一致。
- 这是典型的测试去重/重构，与 R3 输入边界修复无关。
- `tests/w5/test_b1_base.py` 的改动是：
  ```python
  _verified_record(verified_by=())
  →
  _verified_record(verified=False, verified_by=())
  ```
  该改动使测试更精确地命中“available without evidence”分支，但 **`test_b1_base.py` 不在 R3 允许修改的两个文件内**。
- **归属判断**：关联候选为“并行测试清理/辅助函数重构任务”；无授权记录，标记 **REVIEW**。

### 3.3 新增报告目录

| 路径 | 内容 | 关联候选 | 授权 |
|---|---|---|---|
| `reports/README.md` | reports/ 唯一索引；声明 w5/documentation 并行编写 | 并行清理任务 | **REVIEW** |
| `reports/cleanup/cleanup-inventory.md` | reports/ 全量清单与保护记录 | 并行清理任务 | **REVIEW** |
| `reports/cleanup/cleanup-plan.md` | 清理计划，声明“待人工批准、不执行操作” | 并行清理任务 | **REVIEW** |
| `reports/documentation/version-facts.md` | 版本事实调查 | 并行文档任务 | **REVIEW** |
| `reports/documentation/releases/*.md` | 1 个索引 + 15 份 Release 说明草稿 | 并行文档任务 | **REVIEW** |
| `reports/w5/w5-*.md` | 既有 W5 报告 + 本次新增报告 | 本任务/历史任务 | 报告类，未入库 |

---

## 4. 文件归属表

| 文件 | 修改状态 | 关联任务 | 是否属于 R3 | 是否获得授权 | 建议 |
|---|---|---|---|---|---|
| `document_backends/result.py` | M | W5-B1-R3 输入边界修复 | **是** | 是（R3 任务范围） | 仅此文件可进入 R3 提交准备 |
| `tests/w5/test_b1_result.py` | M | W5-B1-R3 输入边界修复 | **是** | 是（R3 任务范围） | 仅此文件可进入 R3 提交准备 |
| `README.md` | M | 并行文档/版本事实整理（关联候选） | 否 | **REVIEW** | 不进入 R3；等待归属确认 |
| `CHANGELOG.md` | M | 并行文档/版本事实整理（关联候选） | 否 | **REVIEW** | 不进入 R3；等待归属确认 |
| `tests/test_e2e_v4.py` | M | 并行测试辅助重构（关联候选） | 否 | **REVIEW** | 不进入 R3；等待归属确认 |
| `tests/test_fixture_matrix.py` | M | 并行测试辅助重构（关联候选） | 否 | **REVIEW** | 不进入 R3；等待归属确认 |
| `tests/test_template_gate_e2e.py` | M | 并行测试辅助重构（关联候选） | 否 | **REVIEW** | 不进入 R3；等待归属确认 |
| `tests/test_template_gate_enforcement.py` | M | 并行测试辅助重构（关联候选） | 否 | **REVIEW** | 不进入 R3；等待归属确认 |
| `tests/test_transaction_gate.py` | M | 并行测试辅助重构（关联候选） | 否 | **REVIEW** | 不进入 R3；等待归属确认 |
| `tests/test_w2_defects.py` | M | 并行测试辅助重构（关联候选） | 否 | **REVIEW** | 不进入 R3；等待归属确认 |
| `tests/w5/test_b1_base.py` | M | 并行测试改动（关联候选） | 否（不在 R3 允许范围） | **REVIEW** | 不进入 R3；不得自行还原 |
| `tests/support.py` | ?? | 并行测试辅助重构（关联候选） | 否 | **REVIEW** | 不进入 R3；不得删除 |
| `reports/README.md` | ?? | 并行清理任务（索引自述） | 否 | **REVIEW** | 不进入 R3；不得删除 |
| `reports/cleanup/cleanup-inventory.md` | ?? | 并行清理任务（自身声明） | 否 | **REVIEW** | 不进入 R3；不得删除 |
| `reports/cleanup/cleanup-plan.md` | ?? | 并行清理任务（自身声明“待批准”） | 否 | **REVIEW** | 不进入 R3；不得删除 |
| `reports/documentation/version-facts.md` | ?? | 并行文档任务（关联候选） | 否 | **REVIEW** | 不进入 R3；不得删除 |
| `reports/documentation/releases/*.md` | ?? | 并行文档任务（关联候选；1 索引 + 15 草稿） | 否 | **REVIEW** | 不进入 R3；不得删除 |
| `reports/w5/w5-*.md` | ?? | 本任务/历史 W5 审查 | 否 | 报告类，未入库 | 保持未跟踪，等待归档决策 |
| `dist/*.zip` | ?? | 本地构建产物 | 否 | 不允许提交 | 不进入任何提交；不得删除 |

> 归属判断基于文件内容、时间戳与并行报告的自述，不构成授权确认。所有外部文件保持 **REVIEW**，不得擅自认定属于某个任务，也不得覆盖或删除。

---

## 5. 隔离结论

1. **R3 改动在文本上可隔离**：只有 `document_backends/result.py` 与 `tests/w5/test_b1_result.py` 属于 R3；其 diff 与 `w5-b1-r3-fix-review.md` 一致。
2. **工作区不稳定**：10:09–10:21 期间持续出现 README、CHANGELOG、测试辅助重构、`tests/support.py`，并在 10:19:56 新增 `reports/README.md`；外部任务可能仍在写入。
3. **R3 提交只能通过精确选择两个文件来准备**：不得使用 `git add -A`、`git add .` 或任何目录级暂存。
4. **R3-only 全量证据已确认，但当前混合树全量不可归因**：653/653 通过发生在外部测试重构之前，可作为 R3-only 证据；10:18 的混合树全量运行因外部测试重构被中止，未计入。提交后仍需在隔离树复跑全量。
5. **不得删除、还原或暂存任何外部改动**：包括 README、CHANGELOG、6 个测试文件、`tests/support.py`、`reports/README.md`、`reports/cleanup/`、`reports/documentation/`。

---

## 6. 建议

1. 等待并行文档/测试/清理任务结束，并确认其授权与提交边界。
2. 在任何 R3 提交前，先确认 `git status` 只剩 R3 两文件（或其他文件已被各自任务提交/移出工作区）。
3. 若必须现在准备 R3 提交，只允许 `git add document_backends/result.py tests/w5/test_b1_result.py`；不得暂存其他文件（本任务不执行暂存）。
4. 在隔离后的树上重新执行 W5、契约、全量与 Ruff，再决定 R3 是否可提交。
5. 所有 REVIEW 文件等待人工确认归属；本任务不处理、不删除、不覆盖。
