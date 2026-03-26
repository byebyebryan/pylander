---
name: pylander-regression-analyzer
description: Diagnose broad benchmark regression state (quick/full) after tuning and recommend keep/investigate/revert.
---

# Pylander Regression Analyzer

Use this skill as the final broad gate after `pylander-tune-loop-manager` (whether reached directly or via `pylander-tune-orchestrator`).

Script-backed status:
- executor: `.agents/skills/pylander-regression-analyzer/scripts/gate_regression.py`
- output contract: `.agents/skills/contracts/regression_gate_report.v1.json`

## Command

Use an existing compare report:

`uv run python .agents/skills/pylander-regression-analyzer/scripts/gate_regression.py --input <input_json> --output <output_json> --no-execute`

Run compare first, then gate:

`uv run python .agents/skills/pylander-regression-analyzer/scripts/gate_regression.py --input <input_json> --output <output_json> --execute`

## Inputs

- `mode`: usually `quick`, optionally `full`
- `baseline_ref`: usually `main`
- `bot`: default `pdg`
- optional `bot_config_path`
- optional `compare_report_path` (required when `--no-execute`)
- optional level policy overrides:
- `exclude_levels`
- `observe_only_levels`

## Workflow

1. If `compare_report_path` is missing and `--execute` is enabled, execute cached compare:
- `uv run python .agents/skills/pylander-benchmark-runner/scripts/run_cached_benchmark.py --mode <mode> --baseline-ref <baseline_ref> --bot <bot> [--bot-config <path>]`
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
