---
name: pylander-telemetry-builder
description: Build focused telemetry probe plans from triage findings to add the minimum instrumentation needed for confident diagnosis.
---

# Pylander Telemetry Builder

Use this skill when current logs/metrics are insufficient to confidently pinpoint root cause.

Default mode is plan-first (no code changes unless explicitly requested).

## Inputs

- `triage_report` (required, `telemetry_triage_report.v1`)
- optional `scope` list (files/subsystems)
- optional overhead budgets (`avg_ms`, `p99_ms`)

## Command

`uv run python .agents/skills/pylander-telemetry-builder/scripts/plan_telemetry.py --triage-report <path> [--scope <token> ...] [--overhead-budget-avg-ms <f>] [--overhead-budget-p99-ms <f>] [--output-plan <path>]`

## Output contract

- `telemetry_probe_plan.v1`
- includes:
  - `target_issue`
  - `probe_set` with exact file targets and insertion anchors
  - `validation_commands`
  - `rollout_and_cleanup`

## Probe design guardrails

- Add the smallest probe set that resolves ambiguity.
- Every probe must be env-gated.
- Every probe must include expected signal shape and expiry/cleanup criteria.
- Keep probe overhead bounded and documented.

## Handoff

After applying planned probes and collecting runs, re-run `pylander-telemetry-analyzer` to confirm the issue and close the loop.
