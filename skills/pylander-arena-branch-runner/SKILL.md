---
name: pylander-arena-branch-runner
description: Execute one arena branch (strategy or tuning), run focused validation, and emit a standardized report for arena ranking.
---

# Pylander Arena Branch Runner

Use this skill for one branch in either `pylander-strategy-orchestrator` or `pylander-tune-orchestrator`.

Script-backed status:
- executor: `skills/pylander-arena-branch-runner/scripts/run_arena_branch.py`
- output contract: `skills/contracts/arena_branch_report.v1.json`

## Command

Dry-run using supplied metrics:

`uv run python skills/pylander-arena-branch-runner/scripts/run_arena_branch.py --input <input_json> --output <output_json> --no-execute-validation`

Execute focused benchmark validation:

`uv run python skills/pylander-arena-branch-runner/scripts/run_arena_branch.py --input <input_json> --output <output_json> --execute-validation`

## Inputs

- `arena_type`: `strategy | tune`
- `branch_id`: unique short token
- `hypothesis`: expected improvement and affected phase(s)
- `selectors`: focused selectors/seeds to validate
- `bot`: default `pdg`
- optional `baseline_ref`
- optional `bot_config_path`
- optional `loop_profile` for branch-local looping (default: `light`)
- optional `measured_metrics` for dry-run (when not executing commands)

## Required artifacts

- `outputs/arena/<arena_id>/<branch_id>/notes.md`
- `outputs/arena/<arena_id>/<branch_id>/report.json`

## Workflow

1. Apply branch change before running this skill (code and/or config override).
2. If `--execute-validation` is enabled, run focused validation:
- `uv run python main.py sim <selector> --bot <bot> --freq 1`
- `uv run python main.py plot <selector> --bot <bot> --plot all --plot-output both`
- `uv run python skills/pylander-benchmark-runner/scripts/run_cached_benchmark.py --mode focused --selectors <...> --seed-spec 0-4 --bot <bot> [--bot-config <path>]`
3. If `--no-execute-validation`, consume `measured_metrics` from input.
4. Emit `report.json` with:
- summary metrics
- crash deltas
- compute deltas (avg/p90/p99)
- top selectors with repro commands
- decision: `promote | iterate | drop`

## Guardrails

- Keep branch scope narrow; avoid multi-goal refactors inside one branch.
- Record exact commands used.
- Do not commit artifacts under `outputs/`.
