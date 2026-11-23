# Quickstart — demo-case

`demo-case/` 是一个完全合成的科研资料目录，用于验证入库 Skill，不包含真实研究数据。

## 1. 目录

```text
demo-case/
  case.json
  task.md
  materials/
    papers/
      2019_Smith_AttentionIsAll_v1.md      # 版本 1
      2019_Smith_AttentionIsAll_v2.md      # 版本 2
      2019_Smith_AttentionIsAll_final.md   # 当前版本
      paper_attention_copy1.md             # 与 v1 字节相同的副本
    data/
      measurements.csv
      measurements.csv.meta.json           # 完整元数据 sidecar
      measurements_copy.csv                # 与 measurements.csv 字节相同
    misc/
      研究笔记 2020 初稿 #2.md              # 中文 + 空格 + 特殊字符
    drafts/report.md
    raw/report.md                          # 同 stem、不同内容 -> 冲突
    raw/stub_unreadable.pdf/               # 空目录占位（不可作为普通文件读取）
    sidecars/broken.meta.json              # 非法 JSON，孤儿 sidecar
```

`case.json` 声明了一个缺失文件 `materials/raw/upload_interrupted.pdf`，用于验证“声明但缺失”的诚实记录。

## 2. 运行

在包根目录：

```bash
python scripts/run_skill.py \
  --input examples/demo-case \
  --work /tmp/sk-demo/work \
  --out /tmp/sk-demo/out
```

再看结果：

```bash
python -m json.tool /tmp/sk-demo/out/result.json | head -80
```

确认 `selfcheck` 无 `FAIL` 后执行：

```bash
python scripts/run_skill.py \
  --input examples/demo-case \
  --work /tmp/sk-demo/work \
  --out /tmp/sk-demo/out \
  --apply
```

## 3. 预期结果

| 指标 | 预期 |
|-|-|
| 扫描文件 | 11 个（不含 `case.json`、`task.md`） |
| 可读文件 | 11 个，全部带 64 位 sha256 |
| 重复组 | 2 组：`measurements*`、`AttentionIsAll_v1` + `copy1` |
| 版本链 | 1 条，3 个成员：`v1` -> `v2` -> `final` |
| 改名 | 1 个：`研究笔记 2020 初稿 #2.md` -> `研究笔记_2020_初稿_2.md` |
| 冲突 | 2 条：`report.md` 的 stem 歧义 + 目标同名，后者加 `__<sha8>` |
| 跳过 | 3–4 条：声明缺失、非法 sidecar、孤儿 sidecar；空目录占位若在打包后仍存在则多 1 条 |
| 状态 | `partial`（因跳过/冲突/元数据缺失），这是诚实的部分成功 |
| 输入 | 运行前后完全不变 |
| 库文件 | `--apply` 后 11 个，全部位于 `out/library/NeuroAttention/...` |

落库后的目录示例：

```text
out/library/NeuroAttention/
  documents/
    2019_Smith_AttentionIsAll_final.md
    paper_attention_copy1.md
    report.md
    report__<sha8>.md
    研究笔记_2020_初稿_2.md
  _archive/documents/
    2019_Smith_AttentionIsAll_v1.md
    2019_Smith_AttentionIsAll_v2.md
  data/
    measurements.csv
    measurements_copy.csv
  _metadata/
    broken.meta.json
    measurements.csv.meta.json
```

## 4. 验证清单

- `out/result.json` 存在且 `status` 为 `partial`；
- `inventory` 每项 `sha256` 为 64 位十六进制；
- `duplicates` 长度 2，`versions` 长度 1；
- `contract_fields` 里的 10 个字段都出现在结果顶层；
- `selfcheck` 全部 `ok=true`；
- `out/library` 中每个文件 hash 与 `manifest` 一致；
- `examples/demo-case` 下文件 hash 未变化；
- `run-review.md` 中的“Agent 复核备注”已由执行 Agent 补全。
