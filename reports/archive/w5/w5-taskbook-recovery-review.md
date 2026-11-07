# W5 任务书恢复审查报告

- 报告日期：2026-11-07
- 审查基线：`main` @ `37ec46f`
- 审查性质：只读资料检索；未修改任何文件
- 最终状态：**BLOCKED**（原始 §八 未能恢复）

---

## 1. 检索范围与方法

| 检索对象 | 方法 | 结果 |
|---|---|---|
| 工作区文件 | `**/*w5*`、`**/*task*book*`、`reports/**` 全量清单 | 仅找到 `reports/w3/w3-task-book.md`（W3），无 W5 任务书 |
| 工作区文本 | 检索 `W5 任务书`、`任务书 §八`、`## 八`、`E1–E9`、`W5-B1-R3`、`输入边界修复` | 仅命中 W5 报告对任务书的引用与 R3 修复报告，无原始正文 |
| Git 历史 | `git log --all --name-only` 检索 `w5.*task|task.*w5`；`git log --all -- reports/w5/*task*` | 无匹配；W5 任务书从未进入任何分支或提交 |
| `.trae/documents` | 列出并检索 W5 相关计划文件 | 仅有 `W5-github-sync-preflight-plan.md`（同步预检计划），不是 W5 任务书 |
| 项目记忆 | `project_memory.md`、`topics.md`、session memory 摘要 | 有 W5 阶段约束与 R3 范围约束，但没有任务书 §八 原文 |
| 并行清理报告 | `reports/cleanup/cleanup-inventory.md` | 明确记录 `reports/` 中只有 `w3-task-book.md`，不存在 W5 任务书 |
| 附件目录 | 环境给出的附件路径 | 路径不存在，无法检索 |

### 1.1 找到的相关引用

| 位置 | 内容 | 性质 |
|---|---|---|
| `reports/w5/w5-target-architecture.md` L7 | “约束来源：W5 任务书 §八 E1–E6” | 引用，不是原文 |
| `reports/w5/w5-architecture-audit.md` L10 | “对照任务书 W5 强制工程约束 E1–E6 逐项核对现状” | 引用，不是原文 |
| `reports/w5/w5-migration-plan.md` §6/§9 | 引用任务书 §六/§九 的验收与交付要求 | 引用，不是原文 |
| `reports/w5/w5-b1-r3-fix-review.md` §8 | “任务书在 §八 处截断” | R3 任务书恢复记录 |
| `reports/cleanup/cleanup-inventory.md` | 全量报告清单，只有 W3 任务书 | 独立旁证 |

### 1.2 结论

- **原始 W5 任务书 §八 未能恢复。**
- **不得根据上下文自行补写。**
- R3 任务书在 `## 八` 处截断，未收到 §八 文本。
- 因此，“原始 §八 与当前验收报告逐项对照”无法逐字完成；只能使用已记录的 E1–E9 派生约束做补充核对，并明确标注其不是原文。

---

## 2. 可用的派生约束（E1–E9）

来源：`reports/w5/w5-target-architecture.md` §5（L264–L278）。该表是 W5-A 设计记录，不是任务书原文。

| 约束 | 派生内容 | 当前 B1 证据 | 状态 |
|---|---|---|---|
| E1 契约保护 | 契约零修改；错误码只增 | `contracts/`、`schemas/` 与 `bd9a2d6` 零差异；error-codes 34→56，0 删除/0 既有修改 | **PASS（B1 范围）** |
| E2 向后兼容 | `--writer` 默认不变；旧输出面保留；Legacy `--data` 冻结 | 默认 `python-docx`；`engine.__all__` 无移除；契约 72 项通过 | **PASS（B1 范围）** |
| E3 质量不倒退 | KEEP_PY 不迁移；CANDIDATE 先过 T01–T10 | B1 未迁移任何能力；`document_backends` 仅骨架、无后端实现 | **PASS（B1 范围；完整 E3 证据属 B7）** |
| E4 单写入者 | 串行阶段、组内单后端、统一事务 | B1 仅登记责任边界；无 Router/Transaction 实现 | **NOT APPLICABLE（B1）；边界已登记** |
| E5 可追溯性 | op→backend→Ledger→QA→交付全链 | B1 有 `OpOutcome` 前后 SHA 与 `to_dict`；尚无 Ledger 接入 | **PARTIAL（基础已具备；全链属 B5/B6）** |
| E6 无虚假成功 | reason_code 全枚举；validate 缺失=UNAVAILABLE；无静默降级 | 四态 `ValidationResult`、15 个 reason code、失败/回退分离；测试通过 | **PASS（B1 范围）** |
| E7 路由可解释 | 每个能力组记录六字段 RoutingDecision | B1 无 Router | **NOT APPLICABLE（B5）** |
| E8 阶段间检查 | close + normalize + stage_check | B1 无多阶段执行 | **NOT APPLICABLE（B5/B6）** |
| E9 事务级回滚 | 失败注入矩阵、交付件不变 | B1 无后端实现 | **NOT APPLICABLE（B5/B7）** |

> 该表只能作为“派生约束核对”，不能替代原始 §八 的逐字验收。

---

## 3. 已满足与缺少证据的条件

### 3.1 已有明确证据

- E1 契约保护：`contracts/`、`schemas/` 零差异；错误码只增。
- E2 向后兼容：默认 writer、旧公共 API、Legacy 行为均有测试/差异证据。
- E6 无虚假成功：`ValidationResult` 四态、UNVERIFIED 白名单、reason code 与 envelope 映射均有测试。
- B1 技术验收：R1–R5、B1-R2、R3 修复均有代码与测试证据。

### 3.2 缺少证据或不可核对

- **原始 §八 文本**：缺失，无法逐字核对（BLOCKED）。
- **E5 全链可追溯性**：B1 只有结果模型基础，Ledger/Router 尚未实现（属 B5/B6）。
- **E7/E8/E9**：B1 不实现路由、阶段检查、事务级回滚（属 B5/B6/B7）。
- **E3 完整质量对照**：T01–T10 属 B7，B1 只能证明“未迁移、未倒退”。

---

## 4. 结论与建议

**BLOCKED**：原始 W5 任务书 §八 无法恢复，不能把派生 E1–E9 当作原文逐字验收。

建议：

1. 由人工提供 W5 原始任务书（至少 §八 原文），或明确书面接受 `w5-target-architecture.md` §5 的 E1–E9 映射作为等价验收依据。
2. 在接受替代依据前，G1.5 不能因“任务书完整性”判 PASS。
3. 本报告不补写、不猜测、不重构任务书原文。
