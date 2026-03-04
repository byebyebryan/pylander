---
name: pylander-tune-router
description: Decide whether to run `tune-arena` or go directly to `tune-loop`, then emit an execution-ready handoff plan.
---

# Pylander Tune Router

Use this skill after strategy winner selection (or on-demand) when routing between parallel tuning and direct looping is unclear.

## Inputs

- `strategy_winner_ref`
- `focused_selectors`
- `baseline_ref` (default: `main`)
- `tuning_route`: `auto | arena | loop` (default: `auto`)
- optional `recent_results_refs` (benchmark/plot/doctor outputs)

## Routing behavior

Manual override:

- `tuning_route=arena` always selects `arena`
- `tuning_route=loop` always selects `loop`

Auto routing (`tuning_route=auto`):

Select `arena` if any one trigger is true:
- multiple plausible tuning directions exist
- recent direct loops plateaued
- objective conflict exists (fuel gains versus compute regressions)
- selector responses diverge materially across scenarios

Select `loop` when:
- tuning is narrow/local with clear gradient
- tuning is tightly coupled with active logic changes
- only one viable direction is currently known

## Output contract

1. `recommended_route`: `arena | loop`
2. `route_rationale`: explicit trigger list and confidence
3. `execution_plan`: ordered next actions with commands
4. `handoff_payload`: ready-to-pass inputs for:
- `pylander-tune-arena` when route is `arena`
- `pylander-tune-loop` when route is `loop`

## Guardrails

- Be explicit about measured signals versus inferred conditions.
- If evidence quality is weak, still choose a route and mark confidence lower.
- Do not block execution waiting for perfect certainty.
