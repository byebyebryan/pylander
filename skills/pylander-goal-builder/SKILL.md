---
name: pylander-goal-builder
description: Design and implement a new evaluation level/scenario goal with strict benchmark-profile coverage and reproducible selectors.
---

# Pylander Goal Builder

Use this skill when the user asks to add or evolve a level to represent a new bot goal.

## Inputs

- `goal`: plain-language objective for the level
- `level_name`: new or existing level id
- `scenario_scope`: what scenarios are needed (`smoke`, `quick`, `full`)
- `success_criteria`: measurable pass/fail metrics
- `policy`: `normal | observe_only | excluded` (default: `normal`)

## Required outputs

1. Level/scenario implementation in `levels/`.
2. `benchmark_profile()` coverage:
- policy
- scenario sets for `smoke`, `quick`, `full`
3. Deterministic selector examples for `sim`, `plot`, and `bench`.
4. Minimal validation proof:
- one focused `sim`
- one focused `plot`
- one benchmark pack run

## Workflow

1. Define acceptance metrics before coding (success state, crash tolerance, fuel/time limits, or shape constraints).
2. Implement/modify level and scenarios.
3. Ensure scenario names are stable and meaningful.
4. Wire `benchmark_profile()` with explicit scenario lists for all pack modes.
5. Run:
- `uv run python main.py sim <level[:scenario[:seed]]> --bot zem_zev`
- `uv run python main.py plot <selector> --bot zem_zev --plot all --plot-output both`
- `uv run python skills/pylander-benchmark-runner/scripts/run_cached_benchmark.py --mode focused --selectors <selector> --seed-spec 0-4 --bot zem_zev`
6. Update docs (`README.md` and level-specific docs) when behavior/scope changed.

## Guardrails

- Do not leave benchmark profile incomplete.
- Fail fast on invalid scenario names and malformed selectors.
- Keep level mechanics decoupled from rendering.
- Prefer small, explicit scenario sets over ambiguous defaults.
