---
name: research-library-ingest-steward
description: Use when a research-library case supplies case.json plus scattered materials and needs deterministic inventory, sha256 hashes, metadata inference, duplicate and version detection, conflict-safe target planning, default copy into /app/output/library (--dry-run for a plan only), and /app/output/result.json plus run-review.md. Triggers include 科研资料入库, 文件整理, 入库清单, 重复文件, 版本链, manifest, dry-run.
---

# 科研资料入库 / Research Library Ingest Steward

## 1. 用途

把一个没有整理过的科研资料目录，变成**可复核、可回滚、可重复运行**的资料库入库结果：

- 逐文件计算 `sha256`，给出清单（inventory）与字节数；
- 从 `case.json`、sidecar、文件名和文本首段推断元数据，缺失就留空；
- 检测**完全重复**（同 hash）与**版本链**（同标题干 + 修订标记）；
- 生成 `source -> target` 的入库清单、冲突处理方案；
- 默认把文件**复制**到 `/app/output/library`，复制后复核 hash；`--dry-run` 只输出计划；
- 输出 `/app/output/result.json`（契约字段齐全）与 `/app/output/run-review.md`（人工复核）。

## 2. 适用条件

适用于同时满足以下条件的情况：

- 输入是一个目录，通常包含 `case.json` 与 `materials/`（或 `case.json` 中用 `materials`、`data_dir`、`input_dir` 等键指定资料根目录）；
- 需要按项目/类别/文件名建立目录结构，或至少需要一份带 hash 的入库清单；
- 需要区分“重复文件”和“同一文献的多个版本”；
- 需要可预览、可验证、失败可回滚的落库；
- 允许只读输入，输出写在 `/app/output` 与 `/app/work`。

## 3. 不适用场景

- 需要联网检索、补全真实作者/期刊/DOI：本 Skill 不联网，缺失元数据不会编造；
- 需要 OCR、PDF 正文抽取、图像识别：本 Skill 只做字节级 hash 与文本首段探测；
- 需要真正删除、去重删除、覆盖原文件：本 Skill 明确禁止；
- 需要数据库、对象存储、MongoDB 等外部系统写入；
- 需要处理有版权的资料再分发：本 Skill 只做本地整理，不改变授权。

## 4. 输入形态

典型输入：

```text
/input/
  case.json
  task.md                  # 可选，人类任务说明
  materials/
    papers/...
    data/...
    *.csv.meta.json        # 可选 sidecar
    metadata.json          # 可选全局元数据
    metadata.csv           # 可选全局元数据表
```

`case.json` 常用字段：

- `case_id`、`title`、`project`、`instrument`、`metadata`；
- `materials` / `input_dir` / `data_dir` / `files` 等资料根路径；
- `required_metadata`（默认 `title`、`authors`、`year`）；
- `declared_files`（声明但可能缺失的文件）；
- `policy`（`target_template`、`archive_template`、`allow_move` 等）；
- `output_contract`（运行时期望的输出字段，dict/list/string 均可）。

支持 sidecar：`<文件名>.meta.json`、`<stem>.meta.json`、根目录 `metadata.json`、`metadata.csv`。
`case.json` 缺失或损坏时仍会扫描资料并写出 `result.json`，状态为 `failed`。

## 5. 调用方式（必须使用精确命令）

在评测容器内，Skill 安装在 `/skills/weekly-skill`：

```bash
python /skills/weekly-skill/scripts/run_skill.py \
  --input /input \
  --work /app/work \
  --out /app/output
```

以上命令**默认执行落库**（复制到 `library/`，不修改输入）。只看计划时加 `--dry-run`：

```bash
python /skills/weekly-skill/scripts/run_skill.py \
  --input /input \
  --work /app/work \
  --out /app/output \
  --dry-run
```

`--apply` 仍可传入，等价于默认行为。

参数：

| 参数 | 默认值 | 说明 |
|-|-|-|
| `--input` | `/input` | 输入目录 |
| `--work` | `/app/work` | 计划、日志等中间产物 |
| `--out` | `/app/output` | `result.json`、`run-review.md`、`library/` |
| `--dry-run` | 关闭 | 只输出计划，不创建 `library/` |
| `--apply` | 开启 | 兼容参数；不传也已执行落库 |
| `--policy` | 内置 `assets/policy.json` | 可选策略覆盖 |

在仓库内可直接用示例验证：

```bash
python scripts/run_skill.py --input examples/demo-case --work /tmp/work --out /tmp/out
python scripts/run_skill.py --input examples/demo-case --work /tmp/work --out /tmp/out --dry-run
```

## 6. 输出字段

`/app/output/result.json` 固定包含：

| 字段 | 说明 |
|-|-|
| `case_id` | 案例编号；缺失时为 `unknown` |
| `status` | `success` / `partial` / `failed` / `insufficient_input` |
| `mode` | `apply`（默认）或 `dry_run` |
| `inventory` | 每个文件的路径、字节、sha256、mtime、类别、是否可读 |
| `manifest` | `source -> target`，含 sha256、action、status、版本链 |
| `duplicates` | 同 sha256 的重复组，`keep_all_no_delete` |
| `versions` | 版本链及成员、当前版本、被替代关系 |
| `renamed` | 因 NFC/空格/非法字符/保留名而改名的记录 |
| `skipped` | 不可读、空目录、声明缺失、无效 sidecar 等，附原因 |
| `conflicts` | 同名目标、已有不同内容、同 stem 歧义及解决方式 |
| `unresolved_metadata` | 缺失的必填元数据字段，不猜测 |
| `plan_actions` | 逐条复制/归档/保留动作，`overwrite=false` |
| `applied` | 本次是否执行了落库（默认 `true`） |
| `applied_records` | 每条落库记录：`source_rel`、`target`、`action`、`source_sha256`、`target_sha256` |
| `state` | 落库后目录树：`path`（以 `library/` 开头）、`target_sha256`、`kind`、`source_path` |
| `rollback_plan` | 已创建文件/目录与撤销操作；输入永远只读 |
| `logs` / `run_log` | 事件序列与阶段计数（不含 wall-clock，保证可复现） |
| `uncertainty` | 版本推断、截断 hash、跳过等限制说明 |
| `stats` / `metadata` / `layout` / `hashes` / `selfcheck` | 统计、元数据索引、目标目录树、hash 表、自检结果 |
| `contract_fields` / `contract_extras` / `contract_unmapped` | 契约字段与映射说明 |

契约字段自动映射（大小写与下划线不敏感）：

- `files` / `items` / `records` -> `inventory`
- `state` / `states` -> 落库后目录树（`library/` 前缀）
- `moves` / `renames` / `operations` / `manifest` -> `manifest`
- `dupes` / `duplicates` -> `duplicates`
- `versions` / `revision_chain` -> `versions`
- `conflicts` -> `conflicts`；`skips` / `skipped` -> `skipped`
- `report` / `summary` -> 一段短字符串
- `evidence` -> 证据块（`manifest` + `input_fingerprint`/`policy_sha256`/`tool_version`/`source_mutation`）；`sources` -> `logs`
- 未知字段先做同义/子串启发式，仍无法映射则保留 `null` 并记入 `contract_extras`

## 7. 入库规则

### 7.1 hash、size、mtime

- 算法固定 `sha256`，流式读取，块大小 1 MiB；
- 单文件最多 hash 64 MiB（`assets/policy.json` 可调），超出部分不读，记录 `hash_truncated=true` 并写入 `uncertainty`；
- `bytes` 取 `stat` 实际大小；`mtime` 只用于版本排序与证据，**不用于判断文件相同**；
- 文件相同必须 `sha256` 相同；空文件单独统计，不进入重复组；
- 不可读文件仍进入 `inventory`，`sha256=null`、`readable=false`，并写 `skipped`。

### 7.2 重复 vs 版本

- **重复**：`sha256` 相同且大小 > 0。报告全部成员，`action=keep_all_no_delete`，绝不删除；
- **版本链**：同一规范化标题干（去掉修订标记后）且扩展名相同，且至少一个成员带显式修订标记（或全部成员在同一目录、仅大小写/NFC 差异）；
  - 标记示例：`v1`、`v2`、`rev2`、`r3`、`version2`、`draft`、`final`、`new`、`old`、`backup`、`(1)`、`copy1`、`修订`、`副本`、`备份`、`定稿`、`最终`、`版本2`；
  - 同 hash 的“副本”只算重复，不算版本；
  - 不同目录、没有修订标记、内容又不同：记 `stem_ambiguity` 冲突，不强行合并；
  - 成员按 `mtime_ns -> 标记秩 -> 路径` 排序，最后一个为当前版本；
  - 旧版本进 `_archive/`，当前版本进正常目录；不做正文 diff，只报告 hash/大小/时间证据。

### 7.3 命名策略

- Unicode 统一 `NFC`；
- 非法字符 `<>:"/\|?*#%` 与控制字符替换为 `_`；
- 连续空白折叠为 `_`；
- Windows 保留名（`CON`、`NUL`、`COM1` 等）前加 `_`；
- 扩展名小写；主干最长 120 字符；目标绝对路径超过 240 字符时截断并追加 sha256 前缀；
- 默认目标模板：`{project}/{category}/{filename}`；
- 旧版本：`{project}/_archive/{category}/{filename}`；
- sidecar：`{project}/_metadata/{filename}`；
- 类别按扩展名映射到 `documents` / `data` / `images` / `archives` / `code` / `other`；
- `project` 缺失时使用 `_unassigned`；所有改名都写入 `renamed`。

### 7.4 冲突解决

- 两个源文件映射到同一目标：按路径排序，先到者保留原名，后者追加 `__<sha8>`；仍冲突则 `__<sha8>_2`；
- 目标已存在且 hash 相同：`keep_existing` / `already_present`，不复制；
- 目标已存在但 hash 不同：追加 `__<sha8>`，记 `existing_target_differs`，绝不覆盖；
- 目标位置是目录：追加 `__<sha8>`，记 `existing_target_not_file`；
- 所有冲突都写 `conflicts`，包含 `resolution` 与 `silent_overwrite=false`。

### 7.5 move vs copy

- 默认 `mode=copy`，**只复制**，输入保留；
- `safety.allow_move` 即使被 case 打开，本实现也不删除源文件，仍以复制落库，并在 `uncertainty` 说明；
- 复制使用 `O_CREAT|O_EXCL` 独占创建，复制后复核目标 `sha256`；失败则删除本次新建的目标文件并记 `failed`，不影响源文件。

## 8. 安全约束

1. **永不删除输入**：只读扫描；默认只创建 `/app/output/library` 下的新文件。
2. **永不静默覆盖**：目标存在一律走 `keep_existing` 或加后缀；`overwrite` 固定 `false`。
3. **默认落库、可预览**：不带参数即复制落库；`--dry-run` 只写计划与结果，不创建库文件。
4. **不跟随符号链接**：遇到 symlink 记 `skipped`，不读取链接目标。
5. **有上限**：默认最多 5000 个文件、深度 32、单文件 hash 64 MiB，超出均记录，不崩溃。
6. **不联网**：不使用 requests、curl、外部 API；仅标准库。
7. **确定性**：不使用当前时间、随机数、集合迭代顺序；输出按路径排序，重复运行结果一致。
8. **输出可回滚**：`rollback_plan` 列出本次创建的文件与目录，输入侧无需恢复。

## 9. 回滚与日志

- `logs`：编号事件（`scan_start`、`plan`、`apply`、`selfcheck` 等），只有计数与路径，无 wall-clock；
- `run_log`：阶段级 `ok/count`，便于判断在哪一步失败；
- `work/plan/*.json`：`inventory`、`manifest`、`plan_actions`、`duplicates`、`versions`、`logs`、`rollback_plan`；
- 落库时额外写 `out/apply_manifest.json` 与 `out/rollback.json`；
- 回滚方式：按 `rollback_plan.undo_operations` 删除**本次创建**的文件，再按需删除空目录；输入文件从未改动。

## 10. 异常处理

| 场景 | 行为 |
|-|-|
| 无权限 / 文件被占用 | 记 `skipped(unreadable)`，`readable=false`，`status=partial`，仍写 `result.json`，进程退出 0 |
| 超大文件 | 只 hash 前 64 MiB，`hash_truncated=true`，在 `uncertainty` 说明 |
| 深层目录 | 超过 `max_depth` 记 `depth_cap`，不静默忽略 |
| 空目录 | 记 `skipped(empty_directory)` |
| 中文/空格/特殊字符 | NFC + 替换 + 折叠空白，写 `renamed`，不改源文件 |
| 损坏 sidecar / 非法 JSON | 记 `skipped(invalid_sidecar_json / orphan_sidecar)`，继续处理其他文件 |
| 损坏的二进制/正文 | 仍按字节计算 sha256 并入库；不解析正文，无法识别格式级损坏，写入 `uncertainty` |
| 声明的文件缺失 | 记 `skipped(declared_but_missing)` |
| `case.json` 损坏 | `status=failed`，`errors` 说明，仍扫描资料并写 `result.json` |
| 目标同名/已存在 | 加 sha256 后缀，记 `conflicts`，不覆盖 |
| 输出目录不可写 | 尝试写到 `/app/work/result.json`，仍返回 0 |
| 参数错误 | 写最小失败结果，仍返回 0 |

## 11. 自检清单

运行后必须逐项确认：

- [ ] `result.json` 存在，`case_id` 与 `status` 非空；
- [ ] `inventory` 中每个可读文件都有 64 位 `sha256`；
- [ ] `manifest` 条数与 `inventory` 条数一致，`source` 均存在于 `inventory`；
- [ ] `manifest` 的 `target` 非空且互不重复（大小写不敏感）；
- [ ] 契约字段全部存在（`contract_fields` 中无缺失）；
- [ ] `duplicates`、`versions` 与人工抽查一致；
- [ ] `skipped`、`conflicts`、`unresolved_metadata` 均有原因；
- [ ] `selfcheck` 无 `FAIL`；
- [ ] 运行前后输入文件的 size/mtime/sha256 未变化；
- [ ] 默认运行后 `out/library` 中每个文件的 hash 与 `manifest` 一致；
- [ ] `run-review.md` 已按第 12 节写完。

## 12. 执行 Agent 必做步骤

1. **默认运行落库**（第 5 节第一条命令）；需要只读预览时加 `--dry-run`。
2. 读取 `/app/output/result.json`：
   - `status`、`stats`、`selfcheck`、`skipped`、`conflicts`、`unresolved_metadata`、`plan_actions`；
   - 若 `selfcheck` 有 `FAIL`，停止后续操作，在复核报告中说明失败项。
3. **独立核对 manifest 与文件系统**：
   - 遍历 `/input` 的资料根目录，统计普通文件数（排除 `case.json`、`task.md`）；
   - 与 `len(inventory) + 未进入 inventory 的 skipped 文件数` 比较；
   - 抽查至少 3 个文件（含中文名）用 `sha256sum` 或 Python `hashlib` 复算，与 `manifest` 对比。
4. 若自检通过（允许 `partial` 来自已解释的 skipped/unresolved；冲突均为命名冲突），核对落库结果。
5. 落库后核对：
   - `/app/output/library` 的文件数等于 `manifest` 中 `target` 非空条数；
   - 库内文件 hash 与 `manifest` 一致；
   - `/input` 下文件 hash 未变化。
6. **写入 `/app/output/run-review.md`**（脚本已生成模板，必须核对并补全，不能只留“待填写”）：
   - 运行命令、模式、`status`；
   - 文件数、重复组、版本链、冲突、跳过、未解析元数据数量；
   - 自检结果逐项 PASS/FAIL；
   - manifest 与文件系统的独立比对结果；
   - 已知限制与不确定项；
   - 回滚方式（删除哪些新文件/目录，输入未改）。
7. 最终答复必须诚实：`status=partial` 时明确列出 partial 原因，不得声称全部成功；`status=failed` 时说明未能完成的部分与已产出的证据。

## 13. 参考

- `references/ingest-protocol.md`：扫描顺序、hash、元数据来源、确定性；
- `references/version-and-conflict-rules.md`：版本标记、重复、命名冲突；
- `references/safety-and-rollback.md`：只读、独占复制、回滚；
- `assets/policy.json`：命名、hash、上限、allow-move 等策略；
- `examples/demo-case/` 与 `examples/quickstart.md`：可直接运行的合成样例。
