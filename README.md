# Runtime contract

Bohrium Playground Period 4 submission — challenge `challenge-2bfd9194` (track: `research-library`).

This repository holds the complete skill package for the challenge: the skill
definition, its executable entry point and all supporting scripts. No precomputed
answers, private data or credentials are included.

## Skill

- Name: `research-archive-steward`
- Summary: Use when a research-library case supplies scattered documents, uploads, or backups and asks for inventory, directory organization, content-hash deduplication, version-chain reconstruction, or a handover manifest; run scripts/run_skill.py to produce a deterministic contract-preserving result.json.

## Contents

| File |
|------|
| `SKILL.md` |
| `scripts/run_skill.py` |
| `README.md` |

## How to run

```bash
python scripts/run_skill.py --case /input/case.json --output /app/output/result.json
```

The entry point is `SKILL.md`; input/output contracts, error handling and a minimal
usage example are documented there.

## Notes

- Pure Python standard library; no network access required.
- The result JSON keeps the input case id, the main results, per-item evidence,
  a run status and an uncertainty section.
