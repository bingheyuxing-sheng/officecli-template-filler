# W3-4B 变更清单与校验值 — CP-W2-002（契约集 4.2.0 候选）

- 日期：2026-11-05
- 状态：**4.2.0 候选，未冻结**；SHA-256 取自本实现工作区的最终文件内容，必须由 Agent 07
  实施后复审通过后方可作为冻结基线。
- 哈希算法：SHA-256；下表同时给出前 16 位（`first-16`）与完整值。

| 文件 | SHA-256 first-16 | SHA-256 (full) |
|---|---|---|
| `contracts/01-slot-id.md` | `a609237b4dbb4412` | `a609237b4dbb44124fdbf57def4c67d869679dedce980d76c74fe245d4cd44fa` |
| `contracts/02-document-spec.md` | `af81a8affb871fb0` | `af81a8affb871fb009638653c118ffef4f2896e926f445b1095ef2018423acdf` |
| `contracts/README.md` | `74becae612c04307` | `74becae612c04307b0eec9f0ee6573ab1c055acee7d4d0b5a6eae3a41915b661` |
| `engine/ooxml_utils.py` | `ff6319d7f68d63f7` | `ff6319d7f68d63f718551b14f54d46a01f192e59ca3f75b152631a72e42bf244` |
| `examples/slot-id/cases.json` | `f6396cce3294b7d3` | `f6396cce3294b7d34457ae53896822ca233a93e61f542e151106884cb084b14a` |
| `template_intelligence/spec_builder.py` | `948efe58e48a7197` | `948efe58e48a7197558bfac043638f3cd5aa07d94edc0c61dda3816a50b10492` |
| `tests/contracts/test_slot_id.py` | `55a83eebc6972f72` | `55a83eebc6972f727a0a2c1a821101a4589ddbd65fab569f51ff8838c96d3b50` |
| `tests/test_sdt_detection.py` | `bb70e50f2533db56` | `bb70e50f2533db56ccc19ead75178ce04b362be7026b88926f62aba89899f09a` |
| `tests/test_sdt_discovery.py` | `8107ee6f3317d546` | `8107ee6f3317d546d4360236501726351483a8a0200548e233d25ae8f702386b` |

## 未变更（任务边界）

- `schemas/`：无改动（location 正则 `[a-z_]+` 已接受 `sdt`，门禁事实核查 N1）。
- `document_engine/`、`qa/`、`config/`：无改动。
- `template_intelligence/slot_id.py`：无改动（`LOCATION_RE` 已接受 `sdt`）。
- `examples/document-spec/cases.json`：无改动（见实现报告 §6.6）。

## 验证摘要

| 套件 | 结果 |
|---|---|
| `test_sdt_discovery.py` | 15 tests, OK |
| `test_sdt_detection.py` | 7 tests, OK |
| `test_spec_builder.py` | 25 tests, OK |
| `tests/contracts` | 70 tests, OK |
| 全量 `tests/` | **447 tests, OK**（159.545s） |

工作区另有任务外既有改动（`tests/fixtures/class_05_nested_structure/...`），不属于 W3-4B
交付，未计入本清单。
