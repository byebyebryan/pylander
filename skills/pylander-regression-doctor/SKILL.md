---
name: pylander-regression-doctor
description: Diagnose broad benchmark regression state (quick/full) after focused tuning and recommend keep/investigate/revert.
---

# Pylander Regression Doctor

Use this skill to make the merge decision after strategy tuning.

## Inputs

- `mode`: usually `quick`, optionally `full`
- `baseline_ref`: usually `main`
- `bot`: default `zem_zev`
- optional `bot_config_path`
- optional level policy overrides:
- `exclude_levels`
- `observe_only_levels`

## Workflow

1. Execute cached compare:
- `uv run python skills/pylander-benchmark/scripts/run_cached_benchmark.py --mode <mode> --baseline-ref <baseline_ref> --bot <bot> [--bot-config <path>]`
2. Read compare report:
- global (gating) crash/success/fuel deltas
- observation-only deltas
- compute avg/p90/p99 deltas
- worst scenarios and repro commands
3. Decide:
- `keep`: no notable global regression and goals met
- `investigate`: mixed signal or ambiguous cost tradeoff
- `revert`: notable global regression or instability

## Output contract

1. `gate_verdict`: `keep | investigate | revert`
2. `evidence`: concrete metrics and selectors
3. `follow_ups`: top repro commands for any blockers

## Guardrails

- Treat new global crashes as high severity.
- Observation-only regressions are reported but non-gating.
- Call out when crash filtering affects aggregate fuel interpretation.
