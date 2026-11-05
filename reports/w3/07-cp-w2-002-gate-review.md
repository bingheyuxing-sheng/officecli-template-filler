# Agent 07 门禁审查：CP-W2-002（SDT location 语法与保护发现）

- 审查对象：`contracts/changes/CP-W2-002-sdt-location.md`（commit 143cb74，仅新增该文件，无代码改动）
- 结论：**CONDITIONAL_PASS** —— 设计成立、安全闭合，但 B1–B4 必须先在提案文本内修正（均为编辑性修正，不改变方案结构）后方可实施。

## 逐项核查

1. **契约缺口而非映射错误：成立。** Contract 01 §3 语法枚举 `p|tbl|r|c|txbx_p`，且规定语法"MUST match v3.5.9 iterator"；迭代器 `engine/ooxml_utils.py:465/459/491` 仅取直接子级（python-docx `paragraphs` 语义），body/cell 级 SDT 内容无任何既有路径可命名。W3-3 披露（`spec_builder.py:982-1093`）只给计数与 body 子级序号，FillPlan/QA 无法绑定位置，audit-triage P1-01 行亦要求精确拒绝。选项 A 为最小增广，与 CP-W2-001 先例一致。
2. **语法健全性：成立，有一处需收紧。** `sdt[i]` 按容器内同类直接子级编号，与既有约定一致；`body.p[i]`、`c….p[i]` 索引不变（直接子级语义证实）。风险点：迭代器 `_yield_p` 按 `id()` 去重（`ooxml_utils.py:435-440`），而 textbox 枚举用 `.//` 后代 xpath（:472）——若 SDT 遍历误用后代搜索，SDT 内 textbox 段落会被抢占改址、破坏既有 slot_id。见 B3。
3. **sdt_edit=false 安全性：闭合。** 三层防线均证实：plan_validator 无条件拒绝 PROTECTED 槽位（`content_intelligence/plan_validator.py:455`）、区域前缀匹配（:460,607-611）、`not_protected` 为强制前置条件（:36,469）；执行器 `fill_executor.py:370-403` 双重复核，`_region_matches`（:285-288）要求 `region+"."` 前缀，无 `sdt[0]/sdt[01]` 类碰撞。容器区域 `body.sdt[i]` blocking 覆盖全部内部路径；cell 外兄弟段落不被误拦。未发现绕过路径。
4. **兼容性主张：大体成立，§4 有误。** 旧 slot_id 不变（canonical 串未改格式）；但两个 Schema 的 location 正则已是通用 `[a-z_]+`（`document_spec-4.0.schema.json:117`、`fill_plan-4.0.schema.json:101`），"pattern adds sdt" 为空改动，真实变更仅在 Contract 01 §3 文字与契约测试向量（N1）。"迭代器只增上下文"在 B3 约束下为真。
5. **与内联 SDT 处理：一致，无双计。** 段内联 `w:sdt` → control_or_field（`spec_builder.py:499-504`）作用于段落自身后代；sdtContent 直接子级段落的 sdt 是祖先，新规则与既有规则节点集不相交；区域构建（:764）同理不重复。
6. **W3-3 衔接：基本一致，一处措辞危险。** L3 封顶保留（:1016-1024）。但 `SDT_BODY_ENUMERATION_GAP` 有两个发射点：内容命中（:1152）与 scan_error fail-closed（:1161，测试 `test_sdt_detection.py:160-171` 断言 high）。改名只允许作用于前者（B1）。QA 提交门禁不消费 spec warning 严重度（`qa_policy.py:14` 仅作用于 QA issues），故降为 medium 不构成隐藏阻断——阻断性由 SDT_BODY_UNSUPPORTED + blocking 区域 + PROTECTED 槽位继续承担。
7. **测试要求：不足，见 N3。** 缺：header/footer story SDT（现为 fail-open：`_scan_body_sdt` 仅扫 body，`hf.paragraphs` 仅直接子级——B2）、空 sdtContent、内联 sdt 不得产生 `sdt[i]`、SDT 内 textbox 的 txbx_p 地址稳定性、合并单元格×cell-SDT。
8. **提交路径：无放宽。** 4.2.0 后拒绝面严格多于 W3-3（新增 PROTECTED 槽位与 blocking 区域两层），不存在 W3-3 阻断而新方案可提交的文档。

## 必须修正（阻断）

- **B1**：§3.2.5 明确改名仅限发现成功路径；scan_error 路径保留 `SDT_BODY_ENUMERATION_GAP`/high。
- **B2**：§3.4 增补 header/footer story SDT 处置——扩入发现/预扫描，或显式记录残余缺口并要求披露（Contract 02 §12"沉默不是支持的证据"）。
- **B3**：§3.2.1 增加规范性约束：SDT 遍历只取 sdtContent 直接子级，MUST NOT 下探 txbxContent；SDT 内 textbox 段落保持 `body.txbx_p[k]`；表迭代器对 `body.sdt[i].tbl[j]` 同步暴露或删除语法中的 tbl 示例。
- **B4**：Contract 01 §3"MUST match v3.5.9 iterator"句需 4.2.0 修订措辞。

## 非阻断

N1 §4 更正 Schema 影响为"无需改动，勿收紧"；N2 任务书 W3-4A 写 CONDITIONAL/SDT_EDIT_UNSUPPORTED，提案改为 PROTECTED/PROTECTED_SLOT_VIOLATION——提案与冻结契约更一致（02 §7.2、schema allOf:239-246），由主智能体回改任务书；N3 补上述测试向量；N4 `_scan_body_sdt` 后代计数与直接子级发现口径统一。

## W3-4B 实施授权

**暂不放行。** B1–B4 折入提案文本（或主智能体在本记录等同确认）并更新 README 4.2.0 变更行后，W3-4B 可开始；实施完成仍需 07 二次复审（任务书 W3-4 行）。
