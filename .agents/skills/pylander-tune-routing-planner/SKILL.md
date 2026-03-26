---
name: pylander-tune-routing-planner
description: Decide whether to run `pylander-tune-orchestrator` or go directly to `pylander-tune-loop-manager`, then emit an execution-ready handoff plan.
---

# Pylander Tune Routing Planner

Use this skill after strategy winner selection (or on-demand) when routing between parallel tuning and direct looping is unclear.

Script-backed status:
- executor: `.agents/skills/pylander-tune-routing-planner/scripts/route_tuning.py`
- output contract: `.agents/skills/contracts/route_decision.v1.json`

## Command

`uv run python .agents/skills/pylander-tune-routing-planner/scripts/route_tuning.py --input <input_json> --output <output_json>`

## Inputs

- `strategy_winner_ref`
- `focused_selectors`
- `baseline_ref` (default: `main`)
- `tuning_route`: `auto | arena | loop` (default: `auto`)
- optional `recent_metrics` object:
  - `candidate_directions` (int)
  - `viable_directions` (int)
  - `loop_plateau_iterations` (int)
  - `last_fuel_mean_primary_delta` (float)
  - `compute_avg_total_delta_ms` (float)
  - `compute_p99_total_delta_ms` (float)
  - `selector_success_rate_stddev` (float)
  - `selector_fuel_cv` (float)
  - `logic_coupled` (bool)
  - optional explicit overrides: `objective_conflict`, `selector_divergence`

## Routing behavior

Manual override:

- `tuning_route=arena` always selects `arena`
- `tuning_route=loop` always selects `loop`

Auto routing (`tuning_route=auto`) uses explicit thresholds:

Select `arena` if any one trigger is true:
- multiple plausible tuning directions exist (`candidate_directions >= 2`)
- recent direct loops plateaued (`loop_plateau_iterations >= 2` and `|last_fuel_mean_primary_delta| < 0.50`)
- objective conflict exists (fuel improved `last_fuel_mean_primary_delta < -0.25` while compute regressed `avg > 0.10ms` or `p99 > 0.20ms`)
- selector responses diverge materially (`selector_success_rate_stddev >= 0.05` or `selector_fuel_cv >= 0.15`)

Select `loop` when:
- tuning is narrow/local with clear gradient (`candidate_directions <= 1`)
- tuning is tightly coupled with active logic changes (`logic_coupled=true`)
- only one viable direction is currently known (`viable_directions <= 1`)

## Output contract

1. `recommended_route`: `arena | loop`
2. `route_rationale`: explicit trigger list and confidence
3. `execution_plan`: ordered next actions with commands
4. `handoff_payload`: ready-to-pass inputs for:
- `pylander-tune-orchestrator` when route is `arena`
- `pylander-tune-loop-manager` when route is `loop`

## Guardrails

- Be explicit about measured signals versus inferred conditions.
- If evidence quality is weak, still choose a route and mark confidence lower.
- Do not block execution waiting for perfect certainty.
