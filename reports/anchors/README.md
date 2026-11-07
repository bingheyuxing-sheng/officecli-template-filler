# 锚点登记（特殊保护）

> 本目录只登记**被仓库内不可修改的引用指向**的历史文件。锚点文件本身**不在本目录物理迁移**，因为冻结契约仍以 `reports/w0/…`、`reports/w1/…`、`reports/w2/…`、`reports/w3/…` 的原路径引用它们；移动会直接断链。

## 1. 不可移动清单

| 锚点（原路径） | 引用来源 | 冻结状态 |
|---|---|---|
| `reports/w0/05-contract-freeze-report.md` | `contracts/changes/CP-W2-001-location-story.md` | 冻结契约证据 |
| `reports/w0/07-gate-review.md` | `contracts/README.md`、`contracts/compatibility-v3.5.9.md` | 冻结契约证据 |
| `reports/w0/issues.md` | `contracts/README.md` | 冻结契约证据 |
| `reports/w0/w0-acceptance.md` | `contracts/compatibility-v3.5.9.md` 的 `reports/w0/**` 通配 | 冻结契约证据 |
| `reports/w1/w1-acceptance.md` | `contracts/02-document-spec.md` | **FROZEN 契约正文引用** |
| `reports/w2/07-n1-gate-review.md` | `contracts/changes/CP-W2-001-location-story.md` | 冻结契约证据 |
| `reports/w3/07-cp-w2-002-gate-review.md` | `contracts/changes/CP-W2-002-sdt-location.md` | 冻结契约证据 |
| `reports/w3/07-cp-w2-002-post-review.md` | `contracts/README.md`、`contracts/changes/CP-W2-002-sdt-location.md` | **FROZEN 契约证据** |

## 2. 规则

1. 上述文件只能原位保留；`reports/README.md` 与 `current/` 只做指引，不做复制。
2. 解除锚点前必须先修改引用方；若引用方是 `contracts/` 下的冻结契约，必须走契约变更提案（`contracts/README.md` §2）并升级契约版本。
3. 新增报告不得再写入 `w0/`–`w3/`；新报告一律进入 `current/`、`development/`、`acceptance/` 或 `archive/`。
4. 每次移动报告后，必须复查本清单与 `git grep "reports/w[0-9]/"` 的结果。

## 3. 当前锚点目录状态

- `reports/w0/`：4 个锚点文件（无其他文件）
- `reports/w1/`：1 个锚点文件
- `reports/w2/`：1 个锚点文件
- `reports/w3/`：2 个锚点文件（`07-cp-w2-002-*`）
- `reports/w4/`、`reports/w5/`、`reports/cleanup/`、`reports/documentation/`：已清空并移除

除上述 8 个文件外，其余报告均已迁入 `current/`、`development/`、`acceptance/` 或 `archive/`。
