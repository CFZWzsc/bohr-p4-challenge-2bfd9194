# 版本与冲突规则 / Version and Conflict Rules

## 1. 标题干规范化

从文件名去掉扩展名后：

1. Unicode 统一为 `NFC`；
2. 把括号编号 `(1)`、`(2)` 识别为副本标记；
3. 按 `_`、`.`、`-`、空白切分 token；
4. 去掉显式修订标记 token；
5. 其余 token 转小写并用空格连接，得到 `stem_key`。

年份（如 `2019`）不会被当作修订标记删除，因此 `2019_Smith_Paper_v1` 与
`2019_Smith_Paper_v2` 会落在同一个 `stem_key`。

## 2. 修订标记

| 标记 | 秩 | 说明 |
|-|-|-|
| `draft` / `初稿` | -100 | 最早草稿 |
| `old` / `旧版` / `backup` / `备份` | -50 | 旧稿/备份 |
| 无标记 | 0 | 仅在带标记的组内作为候选 |
| `v1`、`v2`、`rev2`、`r3`、`version2`、`版本2` | 数字 | 数字越大越新 |
| `copy1`、`(1)`、`副本1` | 10 + 数字 | 副本，通常视为弱版本 |
| `new` / `新版` | 500 | 新稿 |
| `final` / `定稿` / `最终` | 1000 | 最终稿 |

排序键：`(mtime_ns, 标记秩, 路径)`。最后一个成员是 `current`。

## 3. 何时算版本链

必须同时满足：

- 同一 `stem_key` + 同一扩展名；
- 至少两个成员；
- 至少两个不同的 `sha256`；
- 至少一个成员带显式修订标记（例外：全部成员在同一目录、仅大小写/NFC 差异，视为版本）。

如果同 `stem_key`、不同目录、无标记、内容不同：记 `conflicts[type=stem_ambiguity]`，
目标路径按冲突规则各自消歧，不生成版本链。

如果同 `stem_key`、内容全部相同：只进入 `duplicates`，不进入 `versions`。

## 4. 重复

- 判据：`sha256` 相同且 `size > 0`；
- 每组给出 `canonical`（路径排序第一）、全部成员、可回收字节；
- `action=keep_all_no_delete`，本 Skill **不删除任何重复文件**；
- 重复文件仍各自落库，因此“重复”是事实报告，不是清理动作。

## 5. 目标路径冲突

规划按 `source` 路径升序进行，`used` 以大小写不敏感方式记录已占目标：

1. 第一次出现：使用模板目标；
2. 同名但来源不同：后者改为 `stem__<sha8>.ext`；仍冲突则 `__<sha8>_2`、`_3`；
3. 目标已存在且 hash 相同：`keep_existing`，不复制；
4. 目标已存在但内容不同：改为 `stem__<sha8>.ext`，记 `existing_target_differs`；
5. 目标位置是目录：改为 `stem__<sha8>.ext`，记 `existing_target_not_file`。

所有冲突记录包含：

```json
{
  "type": "target_collision",
  "proposed_target": "Project/documents/report.md",
  "resolved_target": "Project/documents/report__6774211a.md",
  "resolution": "sha256_suffix",
  "silent_overwrite": false
}
```

## 6. 示例（demo-case）

- `2019_Smith_AttentionIsAll_v1.md`、`_v2.md`、`_final.md`：同一目录、同一 stem、3 个不同 hash，
  带 `v1`/`v2`/`final` 标记 -> 一条 3 成员版本链；`final` 为当前版本，前两个进 `_archive/`。
- `measurements.csv` 与 `measurements_copy.csv`：字节完全相同 -> 一组重复，不生成版本链。
- `2019_Smith_AttentionIsAll_v1.md` 与 `paper_attention_copy1.md`：字节完全相同 -> 一组重复。
- `drafts/report.md` 与 `raw/report.md`：同 stem、不同目录、无修订标记、内容不同 ->
  `stem_ambiguity` + 目标冲突；一个保留 `report.md`，另一个 `report__<sha8>.md`。
