---
name: pylander-goal-doctor
description: Diagnose why the current bot fails a target level goal, then produce ranked strategy options with measurable success signals.
---

# Pylander Goal Doctor

Use this skill when the user wants failure analysis and strategy selection for a specific level/goal.

## Inputs

- `selector_scope`: `level[:scenario[:seed]]` or a focused set
- `bot`: default `zem_zev`
- `goal`: what must improve
- optional `baseline_ref`: compare against baseline behavior

## Workflow

1. Reproduce failures:
- `uv run python main.py sim <selector> --bot <bot> --freq 1`
- `uv run python main.py plot <selector> --bot <bot> --plot all --plot-output both`
2. If regression context exists, run compare:
- `uv run python skills/pylander-benchmark/scripts/run_cached_benchmark.py --mode focused --selectors <selector_scope...> --seed-spec 0-4 --baseline-ref <baseline_ref> --bot <bot>`
3. Summarize measured signals:
- crashes/success rate
- fuel/time deltas
- setup/coast/terminal projected-dx signals
- trajectory-shape clues from plots
- compute hot spots (avg/p90/p99 ms/tick)
4. Produce 1-3 ranked strategy candidates with explicit tradeoffs and expected impact.
5. Hand off to `pylander-strategy-arena` with candidate bundle.

## Output contract

1. `doctor_verdict`: `healthy | watch | investigate | critical`
2. `root_causes`: measured evidence first, inferences second
3. `strategy_candidates`: ranked with effort/risk/expected gain
4. `next_step_handoff`: ready input payload for `pylander-strategy-arena`

## Guardrails

- Distinguish measured facts from hypotheses.
- Avoid broad retuning before reproducing on focused selectors.
- Include at least one deterministic repro selector in findings.
