# Agent 07 独立复核 — W3-6（P1-02：GENERATE 默认链切 v4）

- 复核对象：未提交工作树（`README.md`、`SKILL.md`、新增 `tests/test_skill_workflow_v4.py`）
- 复核日期：2026-11-05
- **裁定：PASS**（无阻断项；2 项非阻断建议）

## 命令与结果

```
py -3.15 -m unittest tests.test_skill_workflow_v4 -v
→ Ran 3 tests in 7.362s, OK

git status --porcelain
→ M README.md / M SKILL.md / ?? tests/test_skill_workflow_v4.py
git diff --stat → 2 files, +22/-9（代码、契约、schema 均未改动）
```

## 逐项证据

| # | 结论 | 证据 |
|---|---|---|
| 1 可执行性 | 通过（非捷径） | `tests/test_skill_workflow_v4.py:70-133` 以子进程逐步复现 SKILL 链：analyze `--spec-version 4`(72-79)、`validate_document_spec`(80)、`build_content_plan/build_fill_plan`(92-101)、generate `--spec/--content-plan/--plan --mode STANDARD --allow-unverified`(111-120)。`--plan` 与 `--data` 互斥（`scripts/generate_document.py:143-145`），必然进入 `_run_plan_path`(165-169)。断言 schema 4.0、`transaction.committed`、`qa_status`、无 `replaced_occurrences`(126-129)、输出含「示例项目」「120000」(131-133)。SKILL 用 `--output`、测试用 `--out`，两者均为合法别名（`generate_document.py:146`、`analyze_template.py:38`），不构成偏离 |
| 2 兼容边界 | 通过 | `analyze_template.py:44` 仍 `default=3` 且该文件不在 diff；SKILL.md:176/181 显式要求 4 并说明「默认 3 = legacy CLI summary」；README.md:74-82 标注 Legacy token mode。与 `reports/w3/w3-task-book.md:82` 决策及 AGENTS §12.2/§12.3 一致，公共 CLI 默认未被翻转 |
| 3 无隐藏绕过 | 通过 | SKILL.md 全文仅 181/296 提及 `--data`（均标 legacy）与 313（Excel 模式，合法）；无 3.0 spec 指令，`ssot_payload` 路径已移除；GENERATE 行(44)/Step 2(176-181)/Step 4(285-296) 一致 |
| 4 QA/门禁语义 | 通过 | 文档与代码相符：STRICT 仅 PASSED（`qa/gate.py:82-83`、`fill_executor.py:1242-1247`）；STANDARD 的 UNVERIFIED 需 `allow_unverified` 且有 missing_checks（`1244-1245`）；二次门禁 `1272-1308`；staging 保存 `1172`；ledger `770,797`；变更前拒绝 `948-999,370-409`；overflow 仅 REJECT `439-449` |
| 5 测试质量 | 通过（可加强） | 内容与 `committed` 断言可排除「静默回落 legacy」：若走 legacy 则输出不含填入值且 `--plan` 互斥无法成立。未断言 envelope `schema_version`/`plan_validation`/`ledger`；文档反向断言为单一精确字符串（`test:152-156`） |
| 6 文档/契约一致 | 通过 | SKILL:181「body-level w:sdt → PROTECTED、`sdt_edit` false」与 `contracts/README.md:92`（4.2.0）一致；实测 v4 spec 含 `slots/protected_regions/unsupported_features/warnings`，`template.compatibility="L1"` 与 SKILL:181 描述一致 |
| 7 范围 | 通过 | 仅 3 个文件；无无关改动；无 W3 完成声明 |

## 非阻断发现

- **F-1（文档精度）**：SKILL.md:271 泛化声明提交门允许 `PENDING_HUMAN_REVIEW`，而 v4 执行器对 PENDING 判不合格（`fill_executor.py:1246-1247`）。294 行已收紧，建议在 GENERATE 段明示该状态会被拒绝。
- **F-2（测试强度）**：可补断言 envelope `schema_version="4.0"`、`data.plan_validation.passed`、`ledger` 非空，并将 SKILL 反向断言扩展为「GENERATE 段不含 `--payload`」。

## 明确结论

**W3-6 可以接受。** 验收条件「默认 GENERATE 文档链走 v4 且不落回 schema 3」已由测试与默认值未改动共同证明；F-1/F-2 不影响本次合入资格，建议后续文档轮次处理。
