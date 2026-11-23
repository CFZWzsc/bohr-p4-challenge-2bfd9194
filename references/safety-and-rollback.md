# 安全与回滚 / Safety and Rollback

## 1. 不变量

1. 输入目录只读：`/input` 下任何文件都不会被写入、改名、移动或删除。
2. 不覆盖：目标已存在时，要么 `keep_existing`（hash 相同），要么追加 sha256 后缀。
3. 不删除：包括重复文件、旧版本、无效 sidecar，一律保留并报告。
4. 不跟随符号链接。
5. 不联网，不使用第三方包。

## 2. dry-run 与 apply

- 默认 dry-run：只扫描、hash、推断、规划，写 `result.json`、`run-review.md`、`work/plan/*`。
- `--apply`：在 dry-run 结果基础上，把 `plan_actions` 中 `copy` / `archive_copy` 的文件复制到
  `/app/output/library/`。
- `keep_existing`、`skipped_unreadable` 不复制。
- `applied=true` 只表示执行了 apply 模式，不保证每个文件都已落库；看 `manifest[].status`。

## 3. 独占复制

```text
os.open(target, O_WRONLY | O_CREAT | O_EXCL)
```

- `O_EXCL` 保证不会覆盖已有文件；若并发出现同名文件，抛 `FileExistsError`，记冲突并保留原文件。
- 复制完成后按策略 `shutil.copystat` 保留时间戳（失败不影响内容）。
- 若 `apply.verify_sha256_after_copy=true`，复制后重新计算目标 hash：
  - 与源 hash 一致 -> `status=applied`；
  - 不一致 -> 删除**本次新建的目标文件**，记 `failed`，源文件不受影响。

## 4. 失败处理

| 失败 | 处理 |
|-|-|
| 源文件在扫描后被删除 | 复制抛错，记 `copy_failed`，继续其他文件 |
| 目标目录不可创建 | 记 `copy_failed`，`status=partial` |
| 目标已存在（并发） | 记 `apply_target_exists`，不改原文件 |
| 校验失败 | 删除新目标，记 `failed`，继续 |
| 输出目录不可写 | 尝试 `/app/work/result.json`，进程仍退出 0 |

## 5. 回滚清单

`result.json.rollback_plan`：

```json
{
  "mode": "apply",
  "inputs_modified": false,
  "created_files": ["/app/output/library/Project/documents/a.md"],
  "created_dirs": ["/app/output/library/Project", "/app/output/library/Project/documents"],
  "undo_operations": [
    {"op": "remove_file", "path": "/app/output/library/Project/documents/a.md"},
    {"op": "remove_dir_if_empty", "path": "/app/output/library/Project/documents"}
  ],
  "restore_source": "inputs are read-only; no restore needed",
  "note": "delete created files (inputs untouched); created dirs may be removed only when empty"
}
```

回滚步骤：

1. 按 `created_files` 删除本次新建文件；
2. 按 `created_dirs` 逆序删除空目录；
3. 不要删除 `/input` 下任何内容；
4. 如只跑了 dry-run，`created_files` 与 `created_dirs` 为空，无需回滚。

同时写出：

- `/app/output/rollback.json`（apply 模式）；
- `/app/output/apply_manifest.json`（复制记录与校验结果）；
- `/app/work/plan/rollback_plan.json`（两种模式都写）。

## 6. 日志

- `logs`：编号事件，如 `start`、`scan_start`、`plan`、`apply`、`result_written`；
- `run_log`：阶段级记录，含 `phase`、`ok`、计数；
- 不记录 wall-clock，保证同一输入重复运行结果稳定；
- 错误信息截断到 300 字符，不包含凭证或环境变量。
