---
name: pylander-tune-arena
description: Orchestrate parallel tuning branches for a selected strategy winner, then pick a tuning winner for final loop polish.
---

# Pylander Tune Arena

Use this skill when `pylander-tune-router` recommends parallel tuning exploration.

## Inputs

- `strategy_winner_ref`
- `focused_selectors`
- optional `branch_plan`
- `baseline_ref` (default: `main`)
- `bot` (default `zem_zev`)

## Default branch plan

If no `branch_plan` is provided:
- 4 branches total
- 3 knob/config branches
- 1 small code branch

## Workflow

1. Define arena scope:
- selectors and seed range
- branch hypotheses
- stop conditions (crash/success/fuel/compute)
2. Launch one `pylander-arena-worker` per branch in parallel.
3. Collect reports under `outputs/arena/<arena_id>/`.
4. Apply hard gates:
- no new global crashes
- no global success-rate drop versus baseline
5. Rank passing branches:
- fuel delta (primary)
- compute delta (avg total then p99 total ms/tick)
- observation-only regressions (tie-break)
6. Select outcome:
- `winner`: hand off to `pylander-tune-loop` (default `profile=light`)
- `no_winner`: recommend redesign and stop

## Output contract

1. `arena_id`
2. `scoreboard`
3. `winner | no_winner`
4. `next_step_handoff` for `pylander-tune-loop`

## Guardrails

- Keep branch comparisons like-for-like (same selectors/options).
- Treat hard-gate failures as non-promotable.
- Do not mix broad regression gating into this skill.
