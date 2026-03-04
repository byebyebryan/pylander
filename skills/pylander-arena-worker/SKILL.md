---
name: pylander-arena-worker
description: Execute one arena branch (strategy or tuning), run focused validation, and emit a standardized report for arena ranking.
---

# Pylander Arena Worker

Use this skill for one branch in either `pylander-strategy-arena` or `pylander-tune-arena`.

## Inputs

- `arena_type`: `strategy | tune`
- `branch_id`: unique short token
- `hypothesis`: expected improvement and affected phase(s)
- `selectors`: focused selectors/seeds to validate
- `bot`: default `zem_zev`
- optional `baseline_ref`
- optional `bot_config_path`
- optional `loop_profile` for branch-local looping (default: `light`)

## Required artifacts

- `outputs/arena/<arena_id>/<branch_id>/notes.md`
- `outputs/arena/<arena_id>/<branch_id>/report.json`

## Workflow

1. Apply branch change (code and/or config override).
2. Run focused validation:
- `uv run python main.py sim <selector> --bot <bot> --freq 1`
- `uv run python main.py plot <selector> --bot <bot> --plot all --plot-output both`
- `uv run python skills/pylander-benchmark/scripts/run_cached_benchmark.py --mode focused --selectors <...> --seed-spec 0-4 --bot <bot> [--bot-config <path>]`
3. If branch stabilization is needed, run a short local loop via `pylander-tune-loop` using `profile=light` unless explicitly overridden.
4. If baseline is provided, run focused compare and include deltas.
5. Emit `report.json` with:
- summary metrics
- crash deltas
- compute deltas (avg/p90/p99)
- top selectors with repro commands
- decision: `promote | iterate | drop`

## Guardrails

- Keep branch scope narrow; avoid multi-goal refactors inside one branch.
- Record exact commands used.
- Do not commit artifacts under `outputs/`.
