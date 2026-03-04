---
name: pylander-strategy-arena
description: Orchestrate parallel strategy experiments, compare standardized branch reports, and pick a winner for tuning.
---

# Pylander Strategy Arena

Use this skill when there are multiple plausible strategy directions and no clear winner yet.

Script-backed status:
- executor: `skills/pylander-strategy-arena/scripts/run_strategy_arena.py`
- output contract: `skills/contracts/arena_scoreboard.v1.json`

## Command

`uv run python skills/pylander-strategy-arena/scripts/run_strategy_arena.py --input <input_json> --output <output_json> --no-execute-workers`

Optional worker execution for branches that provide `worker_input` instead of `report_path`:

`uv run python skills/pylander-strategy-arena/scripts/run_strategy_arena.py --input <input_json> --output <output_json> --execute-workers`

## Inputs

- `arena_id`
- `branches` (each branch must provide one of: `report_path`, `inline_report`, or `worker_input` when worker execution is enabled)
- `focused_selectors`
- `bot` (default `zem_zev`)
- optional `baseline_ref`

## Workflow

1. Define arena scope:
- max strategies
- validation selectors and seed range
- stop conditions (crash/success/fuel/compute guardrails)
2. Resolve one branch report per strategy.
3. Apply hard gates:
- no new global crashes
- no global success-rate drop
- no notable global regression marker
4. Rank passing strategies by:
- correctness first (crashes/success)
- efficiency (fuel/time)
- compute cost (avg/p90/p99)
- robustness across selectors
5. Choose one outcome:
- `winner`: hand off to `pylander-tune-router`
- `no_winner`: stop and propose redesigned strategies

## Output contract

1. `arena_id`
2. `scoreboard` (one row per strategy)
3. `winner` or explicit `no_winner` rationale
4. `next_step_handoff` for `pylander-tune-router`

## Guardrails

- Keep experiments independent and comparable.
- Enforce same selector set and benchmark options for every strategy.
- Treat new global crashes as hard blockers.
