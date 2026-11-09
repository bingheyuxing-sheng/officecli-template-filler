# OfficeCLI-first 架构

本文记录 v4.3.x 的底座重构：OfficeCLI 从“可选的 FillPlan 写入后端”升级为
**唯一的文档变更执行通道**。目标不是把 OfficeCLI 包成子进程，而是让 skill 的
契约（模板门禁、DocumentSpec、FillPlan、事务、四态 QA）全部建立在 OfficeCLI
的 DOM、批次和校验能力之上。

## 1. 分层

```
scripts/*.py                  CLI 入口：路由、参数、退出码
        │
engine/*                     工作流引擎：分析、规划、执行、QA
        │  只允许通过
engine/officecli_runtime.py  OfficeCLI 运行时：进程、信封、路径、生命周期
        │
officecli.exe >= 1.0.130     实际执行者（已在 1.0.160 验证）
```

硬性规则：

1. **写入只走 OfficeCLI**。任何修改暂存文档的行为必须是 `officecli batch` 中的
   一个 `set` / `add` / `remove` / `move` / `swap` / `raw-set` 项。
2. **不静默回退**。OfficeCLI 表达不了的 plan 以 `WRITER_UNSUPPORTED` 阻断；
   `--allow-writer-fallback` 才允许整篇切换到 `python-docx`，并写入
   `data.writer_fallback`。
3. **读取可以使用 Python OOXML**。模板分析、指纹、字体/图片测量、QA 需要
   ZIP/XML 级证据，`python-docx` / `lxml` / `openpyxl` 作为只读探针保留；
   它们不再承担写入。
4. **事务边界不变**。先写暂存文件，再 QA，最后两次 `os.replace` 原子发布。
   OfficeCLI 的批次失败本身会整批回滚，失败不会留下半成品。

## 2. 运行时契约

`engine/officecli_runtime.py` 负责：

- 二进制发现：`OFFICECLI_BINARY` → `PATH` → `%LOCALAPPDATA%\OfficeCLI` /
  `/usr/local/bin` / `~/.local/bin`。
- 版本门槛：`MIN_VERSION = 1.0.130`，验证基线 `1.0.160`。
- JSON 信封：`{"success": bool, "data": ...}`；退出码 `2` 且 `success=true`
  视为“带警告成功”，`success=false` 一律抛 `OfficecliError`。
- 进程边界：统一超时、UTF-8 解码、Windows 无窗口启动、`OFFICECLI_RESIDENT_FLUSH=each`
  保证写盘对下一个进程可见。
- 读命令：`query` / `get` / `dump` / `raw`。
- 写命令：`batch` / `set` / `add` / `remove` / `raw-set`。
- 生命周期：`open` / `save` / `close`；每次读或写结束后必须 `close`，否则下一步
  QA 或提交会撞上驻留进程的文件锁。

`engine/officecli_writer.py` 现在只是兼容层：保留旧的函数名，内部委托给运行时。

## 3. 路径模型

DocumentSpec 的 location 是 0-based、按 story 分段；OfficeCLI 是 1-based 的
DOM 路径。`location_to_path()` 的映射：

| DocumentSpec | OfficeCLI |
|---|---|
| `body.p[0]` | `/body/p[1]` |
| `body.tbl[1].r[2].c[3].p[0]` | `/body/tbl[2]/tr[3]/tc[4]/p[1]` |
| `sec[0].header.p[0]` | `/header[1]/p[1]` |
| `sec[0].first_page_footer.p[0]` | `/footer[2]/p[1]` |
| `footnotes.footnote[0].p[0]` | `/footnotes/footnote[1]/p[1]` |
| `endnotes.endnote[2].p[0]` | `/endnotes/endnote[3]/p[1]` |
| `comments.comment[0]` | `/comments/comment[1]` |

节到页眉/页脚的映射不是猜的：`get /section[N]` 返回
`headerRef.default` / `headerRef.first` / `headerRef.even` 与 footer 对应项，
`build_story_map()` 用它建立 `sec[i].<story> -> /header[k]` 的交叉表。链接到
上一节的 story 没有独立 part，会明确报 `WRITER_LOCATION_UNSUPPORTED`。

仍不可寻址的 story：文本框内部段落、SDT 内部段落、脚注中的任意第 N 段
（只支持 `footnotes.footnote[i]` 的整条注文），以及嵌套 comment 节点。

## 4. 写入与归一化

FillPlan 的每个操作先解析到**唯一的直接 run**：

- token 必须唯一；
- token 不能跨 run；
- token 不能位于嵌套 run；
- `fill_cell` 的单元格只能有一个段落。

满足条件时生成 `set <run-path> --prop find=... --prop replace=...`，整篇作为
一个原子 batch。任一操作失败，OfficeCLI 回滚整批，执行器返回
`OFFICECLI_WRITE_FAILED`，暂存文件保持不变。

写入后有两步归一化：

1. `restore_paragraph_identity()` 撤销 OfficeCLI 保存时写入的
   `w14:paraId` / `w14:textId`，否则模板指纹会把它们当作未授权的结构变更；
2. `restore_table_look()` 还原 `w:tblLook`。

这两步目前仍用只读解析 + 重写 OOXML 完成；它们的输入是 OfficeCLI 的输出，
不是业务写路径。后续可以改为 `raw-set` 的逐节点操作，使写入面完全收敛。

## 5. QA

`run_qa.py` 与 `qa/pipeline.py` 的 `PACKAGE` 检查现在包含
`officecli validate`：

- `PASSED`：OpenXML schema 校验通过；
- `FAILED`：输出 `PACKAGE_SCHEMA_INVALID`（high），阻断提交；
- `UNVERIFIED`：OfficeCLI 不可用或 validate 无法运行，写入
  `coverage_gaps`，绝不当作通过。

其余检查（格式、内容、视觉、修订完整性）仍以 Python 只读探针为主。

## 6. 迁移矩阵

| 能力 | 现状 | 说明 |
|---|---|---|
| `GENERATE` FillPlan 写入 | **OfficeCLI** | 正文、表格、页眉、页脚；原子 batch + 回读 + 指纹归一化 |
| `GENERATE` 旧 `--data` token | **OfficeCLI** | 平铺 token 映射翻译为单批 `set`；不可寻址 story 回退或阻断 |
| `POLISH` | **OfficeCLI** | run/段落级 `set`，跨格式 run 直接拒绝 |
| `MERGE` | **OfficeCLI** | 第一个输入为基准包，后续 `dump`/`batch` 回放 |
| `PACKAGE` QA | **OfficeCLI** | `validate` 作为必需证据 |
| `REPAIR` | **OfficeCLI** | 段落/表格/节属性恢复走 batch；卫生清理仍为 Python OOXML |
| `REFORMAT` | **OfficeCLI** | `revision.author` 触发原生 `w:*PrChange`，含表格 `tblPrExChange` |
| `REVIEW` / `PROOFREAD` | **OfficeCLI** | 文本修订、批注、接受/拒绝、快照恢复全部走 batch / `raw-set` |
| `EXCEL_GENERATE` | **OfficeCLI** | `xlsx` 由 `/Sheet1/A1` 写入；宏工作簿 `xlsm` 需显式回退 |
| 模板分析 / Spec | `python-docx` 只读 | `build_document_spec_from_path` |
| 指纹 / 格式 QA | `python-docx` / `lxml` 只读 | 需要 ZIP 与样式继承证据 |

### REVIEW 命令映射

| 动作 | OfficeCLI 命令 |
|---|---|
| 修订文本 | `set <run-path> --prop find=... --prop replace=... --prop revision.author=...` |
| 添加批注 | `add <path> --type comment --prop author=... --prop text=...` |
| 接受/拒绝 | `set /revision[@id=N] --prop revision.action=accept\|reject` |
| 恢复快照 | `raw-set /document --xpath ... --action insertbefore --xml ...` |
| 开启修订 | `set /settings --prop trackChanges=true`（写入 `w:trackRevisions`） |

OfficeCLI 的修订时间戳可能是 `Z`，也可能带 `+08:00` 一类本地偏移；完整性审计
按 XML Schema `dateTime` 允许可选小数秒和时区偏移。

### 已知限制

- `w:pPrChange` 的旧值快照在部分 OfficeCLI 版本中可能为空；执行器依赖
  `query revision` 的 `nativePath` 做补偿，审计按“可识别但可能不完整”处理。
- 表格格式修订会同时产生 `w:tblPrChange` 与行级 `w:tblPrExChange`；
  `_FORMAT_CHANGE_TAGS` 与审计均已纳入后者。
- 启用宏的 `.xlsm` 不走 OfficeCLI `xlsx` 路径；未显式传入
  `--allow-writer-fallback` 时以 `WRITER_UNSUPPORTED` 阻断。
- 旧 `--data` token 映射默认走 OfficeCLI。文本框、SDT、脚注/尾注的单段没有稳定
  DOM 路径，会以 `WRITER_LOCATION_UNSUPPORTED` 阻断；调用方可显式传
  `--writer python-docx` 或 `--allow-writer-fallback`。
- 模板分析、Spec 构建、指纹和多数 QA 仍是 Python 只读探针，不参与写入。
- `restore_paragraph_identity()` / `restore_table_look()` 仍是 OOXML 归一化，
  输入是 OfficeCLI 的输出，不是业务写路径。

## 7. 失败码

| 代码 | 含义 |
|---|---|
| `OFFICECLI_UNAVAILABLE` | 二进制缺失、无法启动或 `OFFICECLI_BINARY` 无效 |
| `OFFICECLI_VERSION_UNSUPPORTED` | 版本低于能力门槛 |
| `WRITER_UNSUPPORTED` | plan 无法忠实表达，且未允许回退 |
| `WRITER_LOCATION_UNSUPPORTED` | 目标 story/节点没有 OfficeCLI 路径 |
| `OFFICECLI_WRITE_FAILED` | batch 被拒，整批已回滚 |
| `OFFICECLI_READBACK_FAILED` | 写入后回读不到预期文本 |
| `OFFICECLI_NORMALIZE_FAILED` | 指纹归一化失败 |
| `PACKAGE_SCHEMA_INVALID` | `officecli validate` 判定 OpenXML 不合法 |

## 8. 验证

```powershell
# 单元测试（无 OfficeCLI 时集成用例自动 skip）
python -m pytest -q

# 真实运行时往返（需要可执行的 officecli）
$env:OFFICECLI_BINARY="$env:LOCALAPPDATA\OfficeCLI\officecli.exe"
python -m pytest tests/test_officecli_runtime.py -q

# 完整生成链路：模板门禁 -> ContentPlan/FillPlan -> batch -> QA
python -m pytest tests/test_officecli_pipeline.py -q

# 工作流级实时校验：REVIEW / REFORMAT / REPAIR / EXCEL
python -m pytest tests/test_officecli_review.py tests/test_officecli_reformat_repair.py tests/test_officecli_excel.py -q

# 旧 --data token 映射：OfficeCLI 默认路径与显式 python-docx 对照
python -m pytest tests/test_officecli_legacy_data.py -q
```
