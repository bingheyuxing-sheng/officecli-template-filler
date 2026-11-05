# W3-9 真实语料评测报告（real-corpus-eval）

- 评测时间：2026-11-05T21:02:55+08:00
- 语料来源：运行时通过 `--corpus` 提供的外部目录（路径不入库、不写入代码）
- 语料构成：46 份 `.docx`（递归发现）
- 标注基线：无（E3）——因此**不计算也不声称**槽位 P/R/F1、漏检率等需要人工标注的指标
- 指标性质：本报告全部为**真实语料的鲁棒性/披露性指标**，与合成 Fixture 指标分列，未合并
- 内容安全：报告仅含匿名序号与聚合元数据，不含路径、文件名或文档正文

## 总体结果

| 指标 | 值 |
|---|---|
| 解析分类 | {"OK": 46} |
| 兼容级别分布（解析成功件） | {"L1": 17, "L4": 26, "L3": 2, "L2": 1} |
| 模板字节被改动（分析阶段，目标 0） | 0 |
| Spec 校验失败 | 0 |
| 填充冒烟：尝试 / 分类 | 21 / {"OK": 21} |
| 冒烟后模板字节被改动（目标 0） | 0 |
| 冒烟 QA 状态 | {"UNVERIFIED": 9, "PASSED": 12} |
| 总耗时 | 212.1s |

## 警告码直方图

| 警告码 | 次数 |
|---|---|
| `READ_ONLY_STRUCTURES_PRESENT` | 26 |
| `SDT_BODY_PROTECTED_ONLY` | 5 |

## UNSUPPORTED 码直方图

| 码 | 次数 |
|---|---|
| `FIELD_UPDATE_UNSUPPORTED` | 380 |
| `FLOATING_ANCHOR_LAYOUT_UNSUPPORTED` | 59 |
| `OLE_EDIT_UNSUPPORTED` | 30 |
| `VECTOR_IMAGE_UNVERIFIED` | 9 |
| `SDT_BODY_UNSUPPORTED` | 5 |
| `SMARTART_EDIT_UNSUPPORTED` | 5 |

## 逐文件异常清单（仅异常项）

（无：全部分析成功、字节不变）

## 填充冒烟异常清单

（无）

## 已知限制

- 语料未经脱敏与人工标注，按 E3 不得用于准确率统计，也不得进入仓库 fixtures。
- 本机缺失 PyMuPDF/OCR/matplotlib，视觉类 QA 在冒烟中如实 `UNVERIFIED`。
- SDT 内填充为 W4 能力项（`sdt_edit=false`）；本语料如含 SDT，填充会被显式拒绝，属预期保护行为。
- 冒烟填充全部可填文本槽位：只填一部分会触发 `TEMPLATE_TEXT_RESIDUAL`，那是 QA 门禁对未完成填充的预期 fail-closed 行为，不代表填充链缺陷。
- 语料含大量【】括号样式文本（如教材式菜单标注），槽位发现按括号约定枚举为候选槽位；无标注基线（E3）时不声称其精确率，生成内容由内容层负责任何槽位的取舍。
