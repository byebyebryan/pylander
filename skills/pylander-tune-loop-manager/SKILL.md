---
name: pylander-tune-loop-manager
description: Run a metric-gated tuning loop with profile-based depth (`light`, `standard`, `extensive`) before broad regression checks.
---

# Pylander Tune Loop Manager

Use this skill for direct tuning, or for post-arena polish on a selected winner.

Script-backed status:
- executor: `skills/pylander-tune-loop-manager/scripts/run_tune_loop.py`
- output contract: `skills/contracts/tune_loop_report.v1.json`

## Command

`uv run python skills/pylander-tune-loop-manager/scripts/run_tune_loop.py --input <input_json> --output <output_json>`

## Inputs

- `selector_scope` (focused; string or list)
- `bot` (default `zem_zev`)
- optional `bot_config_path`
- `profile`: `light | standard | extensive`
- optional overrides:
- `max_iterations`
- `seed_spec`
- `max_new_crashes`
- `min_success_rate`
- `fuel_target_delta` (negative is improvement target)
- compute guardrail (avg/p99 ms/tick)
- optional `iterations` list with measured metrics per iteration

## Default profile budgets

- `light`: `max_iterations=2`, `seed_spec=0-2`
- `standard`: `max_iterations=4`, `seed_spec=0-4`
- `extensive`: `max_iterations=6`, `seed_spec=0-9`

Route-aware defaults:

- post `pylander-tune-orchestrator` winner: default `profile=light`
- direct route from `pylander-tune-routing-planner`: default `profile=standard`

## Loop

For each provided iteration entry:

1. Evaluate blocker gates (crash/success/compute).
2. Evaluate fuel target progress.
3. Decide:
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
