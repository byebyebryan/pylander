---
name: pylander-strategy-arena
description: Orchestrate parallel strategy experiments, compare standardized worker reports, and pick a winner for deeper tuning.
---

# Pylander Strategy Arena

Use this skill when there are multiple plausible strategies and no clear winner yet.

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
2. Launch one `pylander-strategy-worker` per strategy (parallel).
3. Collect reports under `outputs/arena/<arena_id>/`.
4. Rank strategies by:
- correctness first (crashes/success)
- efficiency (fuel/time)
- compute cost (avg/p90/p99)
- robustness across selectors
5. Choose one outcome:
- `winner`: advance to tune loop
- `no_winner`: stop and propose redesigned strategies

## Output contract

1. `arena_id`
2. `scoreboard` (one row per strategy)
3. `winner` or explicit `no_winner` rationale
4. command bundle to reproduce winner and top failure

## Guardrails

- Keep experiments independent and comparable.
- Enforce same selector set and benchmark options for every strategy.
- Treat new global crashes as hard blockers.

