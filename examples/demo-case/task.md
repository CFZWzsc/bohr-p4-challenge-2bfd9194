# 任务（示例）

请把 `materials/` 下的科研资料按项目目录入库：

1. 逐文件计算 sha256，检测完全重复文件与版本链。
2. 从 `case.json`、同名 `.meta.json`、文件名和文本首段推断元数据；缺失就留空，不要编造。
3. 目标路径使用 `{project}/{category}/{filename}`，旧版本放到 `_archive/`。
4. 同名目标冲突时追加 sha256 前缀，绝不覆盖。
5. 先 dry-run，再 `--apply`；输入只读。
6. 最终写入 `/app/output/result.json` 与 `/app/output/run-review.md`。

本示例包含：2 组重复文件、1 条 3 成员版本链、1 个中文/空格/特殊字符文件名、1 个空目录占位、1 个损坏 sidecar、1 个声明但缺失的文件。
