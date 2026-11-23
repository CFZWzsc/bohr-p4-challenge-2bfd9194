# 入库协议 / Ingest Protocol

本文件描述 `scripts/sk_entry.py` 的固定处理顺序。顺序是稳定契约的一部分：
同一个输入目录，在相同参数下必须得到同样的 `result.json`（哈希、清单、计划、冲突顺序一致）。

## 1. 顺序

1. 解析参数与 `assets/policy.json`，再用 `case.json.policy` 覆盖允许的项。
2. 读取 `case.json`；失败也继续扫描资料，`status=failed`。
3. 解析资料根目录（`materials` / `input_dir` / `data_dir` 等）；缺省用 `/input/materials`，再退回 `/input`。
4. 深度优先、目录内按名称升序扫描；不跟随符号链接，跳过策略排除目录。
5. 逐文件 `stat` + `sha256`；记录大小、mtime、深度、类别、可读性。
6. 解析 sidecar 与全局元数据表。
7. 推断每个文件的元数据。
8. 计算重复组与版本链。
9. 规划目标路径、解决冲突。
10. 可选 `--apply` 复制并复核 hash。
11. 自检、写 `result.json`、写 `run-review.md`、写 `work/plan/*`。

## 2. hash 与身份

- 算法：`sha256`，流式读取，块 1 MiB。
- 上限：`hash.max_hash_bytes`（默认 64 MiB）。超过时只读前缀，`hash_truncated=true`。
- 文件是否相同，只看 `sha256`；`mtime` 和 `size` 只用于排序与佐证。
- 空文件（0 字节）单独计数，不进入重复组，避免把多个空模板误判为重复。
- 不可读文件仍进入 `inventory`：`sha256=null`、`readable=false`，同时在 `skipped` 记原因。

## 3. 元数据来源与优先级

字段：`title`、`authors`、`year`、`journal`、`doi`、`project`、`instrument`。

优先级（从高到低）：

1. 同名 sidecar：`<文件名>.meta.json` 或 `<stem>.meta.json`（JSON 对象）；
2. 全局表：资料根目录的 `metadata.json`（`{"files": {"相对路径": {...}}}` 或直接映射）或 `metadata.csv`；
3. 文本首段（仅 `.md`、`.txt`、`.tex`、`.csv` 等文本扩展，最多 16 KiB）：
   - 标题取第一个 Markdown 标题或第一行；
   - `year` 与 `doi` 用正则从文件名或文本中提取；
4. 文件名（年份、DOI、标题干）；
5. `case.json` 顶层或 `metadata` 块：默认只继承 `project`、`instrument`；只有 `metadata.apply_to_all=true` 时才继承 `title`、`authors`、`year`、`journal`。

**不编造**：任何字段无法从上述来源得到时，值为 `null`、`source=null`、`confidence=0`。
缺失的必填字段进入 `unresolved_metadata`，不会用“Unknown”或空字符串填充。

## 4. 确定性规则

- 输出数组按路径排序；重复组按 hash 排序；版本链按规范化 stem 排序。
- 冲突解决按 `source` 路径排序决定谁保留原名。
- 不写当前时间、不用随机数、不依赖集合迭代顺序。
- `logs` 使用递增序号，不包含 wall-clock。
- `mtime` 只来自输入 `stat`，因此同一输入重复运行结果一致。

## 5. 产物

| 路径 | 内容 |
|-|-|
| `/app/output/result.json` | 契约结果，所有字段每次都会写出 |
| `/app/output/run-review.md` | 本次运行复核模板（Agent 必须核对后补全） |
| `/app/output/library/` | 仅 `--apply` 创建，按模板落库 |
| `/app/output/apply_manifest.json` | 仅 `--apply`，记录复制与校验 |
| `/app/output/rollback.json` | 仅 `--apply`，回滚清单 |
| `/app/work/plan/*.json` | inventory、manifest、actions、duplicates、versions、logs、rollback |

## 6. 上限

| 项 | 默认 | 超限行为 |
|-|-|-|
| 文件数 | 5000 | 记 `file_cap_reached`，不中断 |
| 目录深度 | 32 | 记 `depth_cap` |
| 单文件 hash | 64 MiB | 前缀 hash + `hash_truncated` |
| 文件名主干 | 120 字符 | 截断 + `length_capped` |
| 目标绝对路径 | 240 字符 | 截断 + sha256 前缀 |
