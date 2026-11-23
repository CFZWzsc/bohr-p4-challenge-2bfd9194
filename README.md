# Runtime contract

Bohrium Playground Period 4 submission — challenge `challenge-2bfd9194` (track: `research-library`).

This repository holds the complete skill package for the challenge: the skill
definition, its executable pipeline and all supporting documents. No precomputed
answers, private data or credentials are included.

## Skill

- Name: `research-library-ingest-steward`
- Summary: Use when a research-library case supplies case.json plus scattered materials and needs deterministic inventory, sha256 hashes, metadata inference, duplicate and version detection, conflict-safe target planning, dry-run then apply into /app/output/library, and /app/output/result.json plus run-review.md. Triggers include 科研资料入库, 文件整理, 入库清单, 重复文件, 版本链, manifest, dry-run.

## Contents

| File |
|------|
| `SKILL.md` |
| `assets/policy.json` |
| `examples/demo-case/case.json` |
| `examples/demo-case/materials/data/measurements.csv` |
| `examples/demo-case/materials/data/measurements.csv.meta.json` |
| `examples/demo-case/materials/data/measurements_copy.csv` |
| `examples/demo-case/materials/drafts/report.md` |
| `examples/demo-case/materials/misc/研究笔记 2020 初稿 #2.md` |
| `examples/demo-case/materials/papers/2019_Smith_AttentionIsAll_final.md` |
| `examples/demo-case/materials/papers/2019_Smith_AttentionIsAll_v1.md` |
| `examples/demo-case/materials/papers/2019_Smith_AttentionIsAll_v2.md` |
| `examples/demo-case/materials/papers/paper_attention_copy1.md` |
| `examples/demo-case/materials/raw/report.md` |
| `examples/demo-case/materials/sidecars/broken.meta.json` |
| `examples/demo-case/task.md` |
| `examples/quickstart.md` |
| `references/ingest-protocol.md` |
| `references/safety-and-rollback.md` |
| `references/version-and-conflict-rules.md` |
| `scripts/run_skill.py` |
| `scripts/sk_entry.py` |
| `README.md` |

## How to run

```bash
python scripts/sk_entry.py --input /input --work /app/work --out /app/output
```

Two passes are intended: the first writes `/app/work/agent_tasks.json` (evidence
skeleton) and `/app/output/result.json`; after the agent writes
`/app/work/agent_judgement.json`, the second pass merges and validates the result.
See `SKILL.md` and `references/two-phase-workflow.md`.

## Notes

- Pure Python standard library; no network access required.
- Every claim is anchored to paragraph-level evidence; unknown items are reported
  in `uncertainty` instead of being fabricated.
