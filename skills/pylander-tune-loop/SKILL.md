---
name: pylander-tune-loop
description: Run a metric-gated tuning loop with profile-based depth (`light`, `standard`, `extensive`) before broad regression checks.
---

# Pylander Tune Loop

Use this skill for direct tuning, or for post-arena polish on a selected winner.

## Inputs

- `selector_scope` (focused)
- `bot` (default `zem_zev`)
- optional `bot_config_path`
- `profile`: `light | standard | extensive`
- optional overrides:
- `max_iterations`
- `seed_spec`
- `max_new_crashes`
- `min_success_rate`
- fuel target or relative delta target
- compute guardrail (avg/p99 ms/tick)

## Default profile budgets

- `light`: `max_iterations=2`, `seed_spec=0-2`
- `standard`: `max_iterations=4`, `seed_spec=0-4`
- `extensive`: `max_iterations=6`, `seed_spec=0-9`

Route-aware defaults:

- post `pylander-tune-arena` winner: default `profile=light`
- direct route from `pylander-tune-router`: default `profile=standard`

## Loop

For each iteration:

1. Apply one small tuning change.
2. Run focused compare:
- `uv run python skills/pylander-benchmark/scripts/run_cached_benchmark.py --mode focused --selectors <...> --seed-spec <seed_spec> --baseline-ref main --bot <bot> [--bot-config <path>]`
3. Inspect plots for top regressions:
- `uv run python main.py plot <selector> --bot <bot> --plot all --plot-output both`
4. Decide:
- `keep` (promote change)
- `adjust` (continue loop)
- `abort` (revert strategy)

## Exit criteria

- Improvement meets goal with no blocker regressions, or
- iteration budget exhausted, or
- hard blocker found (new crashes or severe compute spike).

## Guardrails

- Change one knob family at a time.
- Keep a short per-iteration change log and rationale.
- Do not broaden scope to full-pack tuning inside this skill.
