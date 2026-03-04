---
name: pylander-tune-loop-lite
description: Run a bounded, metric-gated tuning loop on one chosen strategy before broad regression checks.
---

# Pylander Tune Loop Lite

Use this skill after a strategy winner is selected and needs focused tuning.

## Inputs

- `selector_scope` (focused)
- `bot` (default `zem_zev`)
- optional `bot_config_path`
- target guardrails:
- `max_new_crashes`
- `min_success_rate`
- fuel target or relative delta target
- compute guardrail (avg/p99 ms/tick)
- `max_iterations` (default: 3)

## Loop

For each iteration:

1. Apply one small tuning change.
2. Run focused compare:
- `uv run python skills/pylander-benchmark/scripts/run_cached_benchmark.py --mode focused --selectors <...> --seed-spec 0-4 --baseline-ref main --bot <bot> [--bot-config <path>]`
3. Inspect plots for top regressions:
- `uv run python main.py plot <selector> --bot <bot> --plot all --plot-output both`
4. Decide:
- `keep` (promote change)
- `adjust` (continue loop)
- `abort` (revert strategy)

## Exit criteria

- Improvement meets goal with no blocker regressions, or
- iteration budget exhausted, or
- hard blocker found (new crashes / severe compute spike).

## Guardrails

- Change one knob family at a time.
- Keep a short per-iteration change log and rationale.
- Do not broaden scope to full-pack tuning inside this skill.

