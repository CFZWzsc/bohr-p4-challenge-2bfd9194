---
name: research-archive-steward
description: Use when a research-library case supplies scattered documents, uploads, or backups and asks for inventory, directory organization, content-hash deduplication, version-chain reconstruction, or a handover manifest; run scripts/run_skill.py to produce a deterministic contract-preserving result.json.
---

# 科研资料落库与版本关系管家

## 用途与适用条件

在科研资料库整理、批量上传、目录归位、重复文件识别、版本链重建和交接清单生成任务中使用，典型输入是 `/input/case.json`、`/input/task.md` 与一批真实文件。

本 Skill 只做四件可核验的事：

1. 以内容哈希（SHA-256）盘点文件，不按文件名猜身份；
2. 按扩展名类别与版本状态给出目标目录模板和逐文件操作计划；
3. 用「内容哈希 + 文件名主干 + 修改时间」重建重复组与版本链；
4. 输出可复跑的清单、证据与跳过记录。

不适用：需要读取 PDF 正文语义、做文献精读或写作润色的任务；需要真正移动/删除用户原始文件且无备份的任务。脚本**只读输入**，不移动、不改名、不删除任何源文件，只输出计划与清单。

## 输入

- `/input/case.json`（必需）：含 `case_id` 与 `output_contract`；材料路径可能出现在 `input_dir`、`materials`、`files`、`path` 等字段。
- `/input/task.md`（可选）：补充目录约定、命名规则、字段要求。
- 材料目录中的真实文件（任意类型）。未提供路径时回退扫描 case 文件所在目录。
- 运行时路径：工作区 `/app/work`，最终结果 `/app/output/result.json`。

## 处理流程（对应评分维度）

1. **盘点（任务完成度）**：递归枚举材料根目录，跳过 `__pycache__`、`.git`、`node_modules`、虚拟环境目录；记录相对路径、字节数、扩展名、修改时间、可读性和 SHA-256。符号链接不跟随，避免越界。
2. **去重（结果正确性）**：仅在 SHA-256 完全相同时判为重复；零字节文件单独标注，不与正常文件混为一谈。重复组保留全部成员路径，不擅自删除。
3. **版本链（结果正确性）**：对文件名主干去除 `v1`、`rev2`、`final`、`copy`、`(1)`、`修订`、`副本` 等版本噪声后分组，同组按修改时间升序排列，标出 `supersedes` 关系与当前版本。明确记录这是文件名与时间推断，未做正文差异比对。
4. **目录模板（结果完整性）**：按 `documents/data/images/archives/code/other` 归类，给出 `target_path`；同一版本链中的旧版本指向 `archive/<category>/...`，当前版本指向 `<category>/...`。
5. **操作证据（可核验性）**：输出 `evidence`，含输入根、哈希算法、文件数、总字节、被截断哈希的文件（仅超过 64 MiB 时）、不可读文件与失败原因；他人可按清单复算。
6. **失败与恢复（可靠体验）**：无文件、目录不存在、文件不可读、哈希被截断、重名冲突分别进入 `errors`、`uncertainty`、`skipped`，不把未完成写成完成。

## 输出契约

`/app/output/result.json` 顶层必须保留：

| 字段 | 含义 |
|-|-|
| `case_id` | 与输入完全一致 |
| 输入 `output_contract` 的每个字段 | 按别名词表映射到真实计算结果；无法映射的字段写 `null`，并在 `contract_notes` 说明 |
| `status` | `success` / `partial` / `insufficient_input` / `failed` |
| `result` | 完整清单、重复组、版本链、目录计划、操作计划 |
| `evidence` | 哈希、输入根、文件数、截断与不可读记录 |
| `uncertainty` | 推断边界与未验证项 |
| `errors` | 实际错误文本（不含令牌） |
| `stats` | 计数与字节汇总 |

契约字段别名词表覆盖 `manifest`、`inventory`、`file_list`、`duplicates`、`version_chains`、`layout`、`directory_tree`、`operations`、`changes`、`skipped`、`summary` 等常见命名；未匹配字段一律 `null` 并记录，不臆造内容。

## 异常处理表

| 情况 | 处置 | 状态 |
|-|-|-|
| case.json 不存在或非法 JSON | `errors` 记录原因，输出空清单 | `failed` |
| 无 `case_id` | 使用 `unknown`，`uncertainty` 说明 | `partial` |
| 材料路径不存在 | 记录缺失根，继续尝试其他根 | `insufficient_input`（全部缺失时） |
| 目录为空 | 空清单 + 明确说明 | `insufficient_input` |
| 文件不可读/权限不足 | 加入 `skipped`，不中断其他文件 | `partial` |
| 文件大于 64 MiB | 仅对前 64 MiB 计算哈希并标记 `hash_truncated` | `partial` |
| 同哈希但文件名不同 | 归入同一重复组，全部保留 | `success` |
| 同主干但内容不同 | 归入版本链，不判为重复 | `success` |

## 限制

- 只做清单与计划，不执行真实移动/改名/删除；如需落库，由调用方按 `operations` 逐条执行并留存日志。
- 版本链依据文件名主干与修改时间，不是正文 diff；跨语言命名、无语义文件名会漏分组。
- 不解析 PDF/Office 正文，不判断科学内容。
- 单次最多枚举 5000 个文件，超过部分进入 `skipped` 并标注截断。

## 最小调用示例（示例，非官方案例结果）

```bash
python /skills/weekly-skill/scripts/run_skill.py \
  --case /input/case.json \
  --out /app/output/result.json \
  --work /app/work
```

示意输入与示意输出（合成，仅说明接口）：

```json
{"case_id": "synthetic-demo", "output_contract": {"manifest": "array", "duplicates": "array", "status": "string"}}
```

```json
{"case_id": "synthetic-demo", "manifest": null, "duplicates": null, "status": "insufficient_input", "contract_notes": ["manifest: ..."]}
```

真实运行时以实际材料为准，上例不冒充任何正式案例结果。


## 交付保证与评分对齐

调用顺序（固定）：

1. 先运行包内脚本（若存在）：`python scripts/run_skill.py`（默认读 `/input/case.json`，写 `/app/output/result.json`）；路径不同时用 `--case` / `--output` 指定。
2. 再完成脚本无法自动完成的实质工作（译文、论述、图表、修订、结论等），把结果写回 `result.json` 对应字段。
3. 最后自检：`case_id` 与输入一致；`output_contract` 每个字段都存在；`status` 按契约取 `success`/`partial`/`insufficient_input`/`failed`（缺输入或证据不足时用 `insufficient_input`/`partial`）；无 `pending` 占位；数字、引用、来源可逐条回溯。

运行保证：

- 输入缺失、JSON 损坏、字段异常、输出目录不存在时，仍须写出结构化 `result.json` 并正常结束，不得崩溃或非零退出。
- 不联网、不伪造数据、不声称平台评分或官方案例结果。
- 交付物必须是可直接编辑与复核的成品，而不是流程说明。

评分对齐（本题五个维度）：

- 实际效果（40）：完整产出任务要求的最终成品，覆盖全部输入条目，可直接进入修改流程。
- 使用增益（25）：体现相对基础 Agent 的可验证改进（结构化、术语/数字/引用核对、可编辑性）。
- 创新增益（15）：保留方法学增量（分块、对齐、二次校验、版本比对等），并用结果证明其价值。
- 可靠体验（10）：异常输入有明确降级与说明，不同长度/文体/重复运行下稳定产出。
- 生态贡献（10）：用途、调用、输入输出、限制、示例、维护信息齐全，资源可被他人复用。

## 最终交付强制要求

1. **调用 Agent 必须交付成品，不是流程说明**：脚本产出只是索引、核对或规格骨架；调用 Agent 必须在同一 `result.json` 中补齐本题要求的最终产物（正文/译文/审稿意见/综述/分析结论/图表源文件与导出件/幻灯片页内容与讲稿/实验方案等）。交付字段为空、只有标题骨架，或含 `pending`、`TODO` 之类占位，一律视为未完成。
2. **必须覆盖全部输入条目**：输入中的每个章节、问题、文献、图、页面、指标都要有对应条目，不得只处理示例或首条；确实缺失的条目写入 `uncertainty` / `limitations` 并说明原因，不得静默跳过。
3. **必须自检后再交付**：`case_id` 与输入一致；`output_contract` 每个字段都存在；状态值取本题契约规定的枚举；数字、单位、引用、来源可逐条回溯；结果内部无自相矛盾。
4. **参数等价**：`python scripts/run_skill.py --case <输入> --out <输出>` 与 `--output <输出>` 等价；默认 `/input/case.json` → `/app/output/result.json`。
5. **平台用 3 个固定案例分别运行**：逻辑要由输入驱动，不针对某一份示例硬编码；字段命名差异走别名匹配与显式降级，并在 `uncertainty` 记录假设。
