---
name: pylander-telemetry-analyzer
description: Diagnose crash and performance regressions from benchmark artifacts and sim/debug logs, then emit ranked findings with reproducible commands.
---

# Pylander Telemetry Analyzer

Use this skill when you need data/log-driven diagnosis instead of visual-only inspection.

This skill is read-only by default.

## Inputs

- `benchmark_json` (optional)
- `compare_json` (optional)
- `sim_log` (optional, repeatable)
- `bot` (default `zem_zev`)
- `max_findings` (default `8`)

At least one source input is required.

## Command

`uv run python skills/pylander-telemetry-analyzer/scripts/analyze_telemetry.py [--benchmark-json <path>] [--compare-json <path>] [--sim-log <path> ...] [--bot <bot>] [--max-findings <n>] [--output-report <path>]`

## Sources and signals

- Compare report JSON from benchmark tooling (preferred for regression truth)
- Benchmark records JSON for phase/perf outliers
- Sim log text (`--freq 1`) for per-tick state, profiler lines, and sectioned final-result blocks
- Optional setup debug traces (`PYLANDER_ZEM_DEBUG_SETUP=1`)

Current signal conventions:

- generic setup metrics: `setup_gate_*`, `setup_goal_*`
- bot-owned diagnostics: `bot_<botname>_*` (for example `bot_zem_zev_*`)
- profiler fields: `bot_profile_*` covering passive/update/total timing

## Output contract

- `telemetry_triage_report.v1`
- fields include:
  - `doctor_verdict`
  - `top_findings`
  - `repro_bundle`
  - `probe_request`
  - `next_actions`

## Triage policy

1. Prioritize crash findings.
2. Then perf regressions and hotspots.
3. Then phase-control quality hints.
4. Always separate measured evidence from inferred likely cause.

## Handoff

If `probe_request.needed` is true, hand off to `pylander-telemetry-builder` with the emitted report.
