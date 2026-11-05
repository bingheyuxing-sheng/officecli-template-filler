# Agent 07 实施后复审（修订）：CP-W2-002 rev 2

- 对象：commit `5417f8a` 实现 + 三项文本修正（工作区 `contracts/02-document-spec.md`、`contracts/changes/CP-W2-002-sdt-location.md`）
- 环境：Windows / PowerShell 7 / `py -3.15` / unittest
- 结论：**PASS**

## 三项阻断关闭证据

1. **Contract 02 §7.2.1（行 135-142）**：改为“Every paragraph **with non-whitespace text**”；并明确空/纯空白 SDT 段落只留在 `structure.paragraphs`、不产生 slot。与实现一致（`spec_builder.py:499-523` 仅在 `end > start` 时生成候选；空 wrapper `body.sdt[0].p[0]` 实测只在 structure）。
2. **Contract 02 §8.1.3（行 171-176）**：新增 textbox 例外——`txbx_p[i]` 非容器前缀扩展，由 §7.2.2 的 PROTECTED 状态保护，改址会破坏既有 `slot_id`。与实测一致（`body.txbx_p[0]` 的 `slot_key` 不变、PROTECTED；`fill_executor.py:370-409` 按槽位状态拒绝）。
3. **CP-W2-002 §4（行 67）**：改为 `slot_id.py` / `tests/contracts/helpers.py` **no code edit required**。核实两文件 `LOCATION_RE` 仍为 `[a-z_]+`（`slot_id.py:24-28`、`helpers.py:33-37`），本次 diff 仅上述两份 Markdown，无代码/schema/test 改动。

## 回归

- `py -3.15 -m unittest discover -s tests/contracts -t tests` → **70 tests, OK（1.525s）**
- `py -3.15 -m unittest discover -s tests -p "test_sdt_discovery.py"` → **15 tests, OK（5.969s）**
- 前次全量：447 tests, OK（167.357s）。

## 冻结决定

**契约集 4.2.0 可由 Agent 05 于 2026-11-05 正式冻结。** 冻结时须：更新 Contract 01/02 状态行、README 头部 `4.1.0 → 4.2.0` 且 4.2.0 行改为 “frozen”、重算并复核 `reports/w3/04b-manifest.md` 的 SHA-256（02/CP 文本已变）、在 CP §7 记录本复审。

非阻断：`LOCATION_RE` 仍接受任意 `[a-z_]+`；单个 header/footer 异常 `continue`；空/仅嵌套容器 `SDT_BODY_EMPTY` 措辞；class_05 fixture 仅 stat 变化。
