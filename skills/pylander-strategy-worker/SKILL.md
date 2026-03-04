---
name: pylander-strategy-worker
description: Execute one candidate strategy experiment (code/config + focused validation) and emit a standardized result report.
---

# Pylander Strategy Worker

Use this skill for one strategy branch in a larger arena experiment.

## Inputs

- `strategy_id`: unique short token
- `hypothesis`: expected improvement and affected phase(s)
- `selectors`: focused selectors/seeds to validate
- `bot`: default `zem_zev`
- optional `baseline_ref`

## Required artifacts

- `outputs/arena/<arena_id>/<strategy_id>/notes.md`
- `outputs/arena/<arena_id>/<strategy_id>/report.json`

## Workflow

1. Apply the strategy change (code and/or bot config override).
2. Run focused validation:
- `uv run python main.py sim <selector> --bot <bot> --freq 1`
- `uv run python main.py plot <selector> --bot <bot> --plot all --plot-output both`
- `uv run python skills/pylander-benchmark/scripts/run_cached_benchmark.py --mode focused --selectors <...> --seed-spec 0-4 --bot <bot>`
3. If baseline is provided, run focused compare and include deltas.
4. Capture outcome and stop if:
- crashes increase materially
- success drops
- fuel/compute regress sharply
5. Emit `report.json` with:
- summary metrics
- crash deltas
- compute deltas
- top selectors with repro commands
- decision: `promote | iterate | drop`

## Guardrails

- Keep strategy scope narrow; avoid multi-goal refactors.
- Record exact commands used.
- Do not commit artifacts under `outputs/`.

