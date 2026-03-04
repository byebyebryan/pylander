---
name: pylander-strategy-arena
description: Orchestrate parallel strategy experiments, compare standardized branch reports, and pick a winner for tuning.
---

# Pylander Strategy Arena

Use this skill when there are multiple plausible strategy directions and no clear winner yet.

## Inputs

- `goal`
- `strategy_candidates` (2-4 preferred)
- `focused_selectors`
- `bot` (default `zem_zev`)
- optional `baseline_ref`

## Workflow

1. Define arena scope:
- max strategies
- validation selectors and seed range
- stop conditions (crash/success/fuel/compute guardrails)
2. Launch one `pylander-arena-worker` per strategy (parallel).
3. Collect reports under `outputs/arena/<arena_id>/`.
4. Rank strategies by:
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
