# 当前架构审查结论

- 日期：2026-11-07
- 审查对象：v4.2.1 工作树
- 结论：**架构稳定，可继续演进；无阻断性架构缺陷**

## 1. 分层

```text
scripts/                     13 个 CLI 入口
        │
        ├── document_engine/  v4 执行器（fill_executor / pipeline / fill_ledger）
        ├── template_gate/    模板理解与确认闸门
        ├── template_intelligence/  DocumentSpec、槽位、指纹、语义校验
        ├── content_intelligence/   ContentPlan / FillPlan 校验
        ├── document_backends/      后端抽象（EXPERIMENTAL_NOT_WIRED）
        ├── qa/               环境能力、QA Pipeline、提交门禁
        └── engine/           v3 公共能力层（最大耦合点：__init__ 门面）
```

依赖方向为 `scripts → document_engine / qa / template_* → engine`，未发现循环依赖。

## 2. 主执行链

```text
generate_document.py
  → package_guard（ZIP 配额）
  → template_gate.require_confirmed_gate
  → document_engine.generate_document_v4
      → validate → 模板 SHA 预检 → 槽位前置条件 → 定位 → 写入 stage
      → qa.pipeline.run_full_qa（重新读取暂存文件）
      → DocumentTransaction.commit() / 回滚
```

事务边界、QA 独立性与提交门禁均符合契约 03/04/06 的设计意图。

## 3. 仍存在的结构性技术债

| 项 | 说明 | 影响 |
|---|---|---|
| `document_backends/` 未接线 | 后端抽象与 `engine.officecli_writer.py` 双轨；生产只用后者 | 读者易误判权威接口；B2–B5 需二次迁移 |
| QA 双链路 | `qa.pipeline.run_full_qa`（v4）与 `scripts/run_qa.py`（v3 风格汇总）并存 | 状态字段与退出码语义需要分别理解 |
| `engine/__init__.py` 门面 | 338 行、60+ 再导出 | 单点耦合，拆分需先补模块级测试 |
| 超长函数 | 47 个函数 ≥100 行，`execute_fill_plan` 622 行 | 可测试性与评审成本 |

上述均已在 `current/backlog.md` 登记为 P2，不阻断当前发布。

## 4. 结论

- 冻结契约（4.2.0 基线）未被本轮修改；Contract 06 仍为 DRAFT。
- 下一项架构决策是 W5-B2：把 `fill_executor` 的 officecli 路径迁入 `document_backends`，或将 `document_backends` 明确标记为实验并归档。二者必须择一，避免长期双轨。
- 在做该决策前，先完成 `current/backlog.md` 中与测试覆盖、超长函数相关的 P2，以降低迁移风险。
