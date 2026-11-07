# W3-4B 实现报告 — CP-W2-002 SDT location 语法与保护发现

- 任务：W3-4B（Agent 01 + Agent 03 角色实施）
- 提案：`contracts/changes/CP-W2-002-sdt-location.md`（rev 2，已折入 Agent 07 门禁修正 B1–B4）
- 契约集版本：4.2.0（实施时为候选；07 实施后复审 PASS 后正式冻结）
- 冻结状态：**已冻结**（`reports/w3/07-cp-w2-002-post-review.md`、`reports/development/w3-04b-manifest.md`）。本报告是实施记录，本身不构成冻结证据。
- 日期：2026-11-05
- 环境：Windows / PowerShell 7 / `py -3.15`（Python 3.15.0）/ python-docx 1.2.0 / `unittest`

## 1. 目标与非目标

已实现：

1. `location_id` 元素集加入 `sdt`，覆盖 body、header/footer story、表格单元格与嵌套 SDT。
2. SDT 容器内容被枚举为 **可命名但受保护的槽位**（`control_or_field` / `PROTECTED` /
   `PROTECTED_DO_NOT_TOUCH`），并产生 blocking `kind: "sdt"` 保护区域。
3. 保留 W3-3 fail-closed 行为：L3 封顶；发现成功路径改为 medium
   `SDT_BODY_PROTECTED_ONLY`；扫描失败路径仍为 high `SDT_BODY_ENUMERATION_GAP` +
   `SDT_BODY_SCAN_INCOMPLETE`（B1）。
4. 语法、文档与测试更新；FillPlan/执行器对 SDT 槽位零写入拒绝（已验证，未改执行器）。

明确非目标（未做）：

- 不实现 SDT 内容填充；`sdt_edit` 保持 `false`。
- 不修改 `schemas/`、`document_engine/`、`qa/`、`config/`。
- 不改变既有非 SDT 内容的 `location_id`/`slot_id`。
- 不改变 `--spec-version 3` 输出形状。

## 2. 文件变更清单

| 文件 | 变更 |
|---|---|
| `engine/ooxml_utils.py` | 两个迭代器新增 SDT 遍历（body / 六个 header-footer 名 / cell / 嵌套），只取 `w:sdtContent` 直接子级，不下探 `w:txbxContent`（B3）；表迭代器暴露 SDT 内表格及其嵌套表 |
| `template_intelligence/spec_builder.py` | SDT 内候选强制 `control_or_field`/`PROTECTED`；`_scan_body_sdt` 扩展到 body + header/footer 根 + 单元格；容器 `kind:"sdt"` blocking 区域；B1 警告拆分；`SDT_BODY_UNSUPPORTED` 详情与 `location_id` 精确到容器 |
| `contracts/01-slot-id.md` | §3 元素集加入 `sdt`，新增 §3.1 容器/直接子级规则；B4 迭代器一致性措辞改为 v4 超集；版本 1.2.0 + 变更记录 |
| `contracts/02-document-spec.md` | §7.2 SDT 发现规则；§8.1 `kind:"sdt"` 区域语义；版本 1.2.0 + 变更记录 |
| `contracts/README.md` | 4.2.0 变更行：日期 2026-11-05，标注 "frozen pending 07 post-implementation review" |
| `examples/slot-id/cases.json` | 新增 4 个语法/ID 向量（body、nested、cell、裸容器） |
| `tests/contracts/test_slot_id.py` | 扩充正/反语法向量，旧向量保留 |
| `tests/test_sdt_detection.py` | W3-3 预期更新：发现为 PROTECTED 槽位 + `kind: sdt` 区域 + L3 + medium 警告；scan_error 仍 high |
| `tests/test_sdt_discovery.py` | 新增 15 项发现/稳定性/拒绝测试 |

未修改：`schemas/`、`document_engine/`、`qa/`、`config/`、`template_intelligence/slot_id.py`。
`template_intelligence/slot_id.py` 的 `LOCATION_RE` 现有 `[a-z_]+` 已接受 `sdt`，CP §4 所述“显式加入 sdt”无需改动（与门禁事实核查 N1 一致）。

工作区中 `tests/fixtures/class_05_nested_structure/{fill_plan.json,expected/expected.json}` 的改动属于任务外既有本地修改，本次未触碰。

## 3. 实现细节

### 3.1 迭代器（`engine/ooxml_utils.py`）

- `_walk_sdt_container(sdt_el, sdt_location, parent_obj)`：
  - 只枚举 `w:sdtContent` 的 **直接** `w:p`、`w:tbl`、`w:sdt` 子级；
  - 表格经 `_walk_tables` 复用既有单元格/合并单元格去重逻辑；
  - 嵌套 SDT 以 `sdt[i]` 相对地址递归；
  - **不下探** `w:txbxContent`：正文/页眉页脚的全局 textbox 遍历先执行，`id()` 去重不会抢占
    textbox 段落，`txbx_p[i]` 与既有 slot id 保持不变（B3）。
- 遍历顺序：非 SDT 内容先、SDT 内容后（body textbox 之后 / 每个 header-footer textbox 之后 /
  单元格既有段落与嵌套表之后），保证既有位置编号不变。
- `iter_all_document_tables_with_context` 新增 `_walk_sdt_tables`，产出
  `body.sdt[i].tbl[j]`、`sec[n].<hf>.sdt[i].tbl[j]`、`body.tbl[r].c[c].sdt[i].tbl[j]`，
  并复用 `_walk` 暴露这些表内的嵌套表。
- `_infer_scope` 未改：`body.sdt…` → `body`，`sec[…]` → `header_footer`，含 `tbl[` → `table`。

### 3.2 发现语义（`spec_builder.py`）

- `_collect_candidates`：候选位置含 `.sdt[`，或段落的 XML 祖先含 `w:sdt`（覆盖
  `txbx_p[i]` 这类地址无法显露容器的情况）时，整段作为 `control_or_field` /
  `PROTECTED` / `PROTECTED_DO_NOT_TOUCH`；SDT 内不产生任何 FILLABLE token。
- `_scan_body_sdt` 保留名称（测试通过 mock 该名称）。返回
  `{"containers": [{"location", "paragraph_count", "table_count", "has_content"}], "scan_error"}`；
  覆盖 body、六个 header/footer root、单元格、嵌套 SDT、SDT 内容中的表格。
- 任一有内容容器或 scan_error → compatibility 至少 L3（保留 `sdt_body_prescan` L3 feature）。
- 每个有内容容器一条 `SDT_BODY_UNSUPPORTED`（`detail` 与 `location_id` 均为容器地址）；
  scan_error 追加 `SDT_BODY_SCAN_INCOMPLETE`。
- 保护区：每个有内容容器一条 `kind:"sdt"`、`severity:"blocking"`、`location_id` 为容器地址，
  `evidence` 含直接段落/表格计数；既有区域 ID 顺序不变（容器区域追加在末尾）。
- 警告：有内容容器 → `SDT_BODY_PROTECTED_ONLY`（medium）；scan_error →
  `SDT_BODY_ENUMERATION_GAP`（high，未改名/未降级）；空容器 → `SDT_BODY_EMPTY`（low）。
- `sdt_edit` 仍为 `false`；`fill_executor` 未改。

### 3.3 保护闭合（未改执行器的验证）

- 槽位 `PROTECTED` → `validate_fill_plan` 与 `_evaluate_preconditions("not_protected")`
  均返回 `PROTECTED_SLOT_VIOLATION`；
- 容器 blocking 区域通过 `region + "."` 前缀匹配覆盖容器内所有深路径；
- 实测执行器返回 `BLOCKED`、零 artifact、无输出文件、模板 SHA-256 前后一致。

## 4. 实际产出的 location 示例（真实探测输出）

段落（`iter_all_document_paragraphs_with_Wait_context`）：

```
body.p[0]                                              scope=body
body.tbl[0].r[0].c[0].sdt[0].p[0]                      scope=table
body.sdt[0].p[0]                                       scope=body
body.sdt[0].p[1]                                       scope=body
body.sdt[1].tbl[0].r[0].c[0].p[0]                      scope=table
body.sdt[2].sdt[0].p[0]                                scope=body
body.tbl[0].r[0].c[0].sdt[0].tbl[0].r[0].c[0].p[0]    scope=table
body.sdt[0].tbl[0].r[0].c[0].tbl[0].r[0].c[0].p[0]    scope=table
sec[0].header.sdt[0].p[0]                              scope=header_footer
```

表格（`iter_all_document_tables_with_context`）：

```
body.tbl[0]                                   scope=body          depth=0
body.tbl[0].r[0].c[0].sdt[0].tbl[0]           scope=nested_table  depth=1
body.sdt[0].tbl[0]                            scope=body          depth=0
body.sdt[0].tbl[0].r[0].c[0].tbl[0]           scope=nested_table  depth=1
```

## 5. 测试命令与真实结果

| # | 命令 | 结果 |
|---|---|---|
| 1 | `py -3.15 -m unittest discover -s tests -p "test_sdt_discovery.py"` | **Ran 15 tests, OK**（4.185s） |
| 2 | `py -3.15 -m unittest discover -s tests -p "test_sdt_detection.py"` | **Ran 7 tests, OK**（1.999s） |
| 3 | `py -3.15 -m unittest discover -s tests -p "test_spec_builder.py"` | **Ran 25 tests, OK**（8.118s） |
| 4 | `py -3.15 -m unittest discover -s tests/contracts -t tests` | **Ran 70 tests, OK**（1.254s） |
| 5 | `py -3.15 -m unittest discover -s tests -p "test_*.py"` | **Ran 447 tests, OK**（实施时；159.545s；0 fail / 0 error / 0 skip） |

`test_sdt_discovery.py` 覆盖：body/多段、header、even_page_footer、cell、嵌套、SDT 内表格、
locked+plain、内联 SDT 非容器、非 SDT 地址回归不变、textbox 地址与 slot id 不变、两轮一致、
结构哈希跨授权文本填充不变、FillPlan/执行器拒绝且模板字节不变。

## 6. 与 CP-W2-002 / 任务书的偏差与解释

1. **textbox 保护判定增加祖先检查。** CP §3.2.1 要求“SDT 内每个槽位必须 PROTECTED”，但 B3
   要求 textbox 段落保留 `body.txbx_p[i]` 地址，该地址不含 `.sdt[`。因此发现阶段同时检查
   `p_el` 的 `ancestor::w:sdt`；textbox 槽位保持原地址与 slot id，但被标为 PROTECTED。
   这是实现细节，未新增契约字段，且与 CP 意图一致。
2. **`_scan_body_sdt` 返回结构变更。** 旧 `body_child_index` 替换为 `location`（CP §3.2.4
   要求容器地址）；直接子级计数与发现口径统一（门禁 N4）。
3. **`SDT_BODY_UNSUPPORTED` 增加 `location_id`。** Schema 的可选字段，用于精确追溯。
4. **02 § 编号。** `§7.1` 容量语义保持原位，SDT 发现规则作为 `§7.2` 追加，避免重编号破坏
   既有引用（既有表格中 `capacity → §7.1` 不变）。CP 未指定子节号。
5. **空容器定义。** “有内容”仅按直接 `w:p`/`w:tbl` 计数；仅包裹嵌套 SDT 的外层容器不计为
   有内容（嵌套容器自身单独登记保护区）。这与 N4 的直接子级口径一致。
6. **未修改 `examples/document-spec/cases.json`。** 任务允许“仅在校验保持绿色时添加”；本次
   SDT 语法已由 `examples/slot-id/cases.json` 覆盖，DocumentSpec 示例保持不变以避免示例/语义
   校验漂移；`tests/contracts` 70 项保持绿色。
7. **未修改 `template_intelligence/slot_id.py`。** `LOCATION_RE` 已用 `[a-z_]+`，`sdt` 天然
   被接受（CP §4 的“显式扩展”与门禁事实核查确认的 schema 现状一致，无需代码改动）。

## 7. 已知限制与风险

1. 4.2.0 已冻结（07 实施后复审 PASS）；实施当时处于未冻结候选状态。
2. 不提供 SDT 填充能力；`sdt_edit=false`。锁定、`w:dataBinding`、sdtContent 内多 run 等
   填充问题仍在 W4 提案范围。
3. textbox 段落的容器级 `kind:"sdt"` 区域不会以 `body.sdt[…]` 前缀覆盖 `body.txbx_p[i]`；
   该位置的安全性由 PROTECTED 槽位状态保证（执行器 `not_protected` 前置条件覆盖）。
4. header/footer 扫描跳过 `is_linked_to_previous` 的继承节（内容在拥有该定义的节地址上已
   扫描）；这与迭代器地址语义一致，但若未来需要“继承链逐节地址”，属新变更。
5. 既有 header/footer 代理的惰性实例化是 python-docx 的既有行为；扫描本身不创建 header
   定义（先判断 linked）。
6. 全量 447 项（实施时）通过只说明现有 Fixtures 覆盖范围；当前全量为 450 项，仍不对任意 DOCX SDT 结构作普适性声明。
