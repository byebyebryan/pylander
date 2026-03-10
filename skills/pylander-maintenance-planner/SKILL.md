---
name: pylander-maintenance-planner
description: Plan test and benchmark maintenance work using explicit modes (test, bench, both), with prioritized tasks, reproducible commands, and acceptance gates.
---

# Pylander Maintenance Planner

Use this skill for recurring maintenance work that should be planned before execution.

Default is planning only.

## Inputs

- `mode`: `test | bench | both` (default `both`)
- optional `baseline_ref`: default `main`
- optional `bot`: default `pdg`
- optional `bot_config_path`
- optional `selectors`
- optional `seed_spec`
- optional `scope_notes`: constraints or priorities

## Required outputs

1. `maintenance_findings`
- current state snapshot
- drift/debt areas
- impact and confidence

2. `prioritized_plan`
- ordered tasks with:
  - objective
  - scope
  - risk
  - expected impact
  - stop condition

3. `command_bundle`
- exact reproducible commands for each task

4. `acceptance_gates`
- pass/fail checks required to close the maintenance pass

## Mode behavior

### `test`

Focus on:
- stale tests due to behavior changes
- brittle/flaky patterns
- missing coverage for recent logic shifts

Core commands:
- `uv run pytest`
- `uv run ruff check .`

### `bench`

Focus on:
- benchmark selector/profile drift
- regression signal quality gaps
- reproducibility consistency (selectors/seeds/bot-config)

Core commands:
- `uv run python skills/pylander-benchmark-runner/scripts/run_cached_benchmark.py --mode quick --baseline-ref <baseline_ref> --bot <bot>`
- focused follow-up compares with explicit selectors/seeds when needed

### `both`

Merge `test` and `bench` findings into one ranked plan.

## Workflow

1. Gather current evidence from tests, benchmark scripts/profiles, and recent changes.
2. Separate global risks from observation-only/non-gating concerns.
3. Build a bounded plan that avoids mixed unrelated cleanup.
4. Provide executable command bundles for each planned step.
5. Define closure gates before any execution.

## Guardrails

- Keep plans bounded; avoid broad rewrites in maintenance passes.
- Use explicit selectors/seeds for reproducibility.
- Keep benchmark comparisons like-for-like (`bot`, config, selectors, seed spec).
- Call out tradeoffs when maintenance work defers fixes.
