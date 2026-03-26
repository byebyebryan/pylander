# Skill workflow map

This document explains what the current skill set is built for and how skills fit
into the intended bot-development lifecycle.

## Target outcome

The workflow is built toward a reproducible, metric-gated optimization loop:

1. Define a concrete goal surface.
2. Diagnose failures with deterministic repro selectors.
3. Compare strategy candidates in a like-for-like arena.
4. Route tuning depth based on measured risk and uncertainty.
5. Tune in focused loops with bounded iteration budgets.
6. Run broad regression gates before merge.

## End-to-end path

Primary path:

1. `pylander-goal-builder`
2. `pylander-goal-analyzer`
3. `pylander-strategy-orchestrator` + `pylander-arena-branch-runner`
4. `pylander-tune-routing-planner`
5. `pylander-tune-orchestrator` + `pylander-arena-branch-runner` -> `pylander-tune-loop-manager`, or direct `pylander-tune-loop-manager`
6. `pylander-regression-analyzer`

Cross-cutting skills usable at any stage:

- `pylander-benchmark-runner`
- `pylander-benchmark-analyzer`
- `pylander-plot-runner`
- `pylander-plot-analyzer`
- `pylander-telemetry-analyzer`
- `pylander-telemetry-builder`
- `pylander-docs-sync-planner`
- `pylander-maintenance-planner`
- `pylander-refactor-planner`
- `pylander-commit-manager`

## Skill coverage matrix

| Skill | Workflow role | Execution status | Primary output |
|---|---|---|---|
| `pylander-goal-builder` | Build/adjust level goal surface and benchmark profile coverage | Playbook (`SKILL.md`) | Level + scenario updates and focused validation proof |
| `pylander-goal-analyzer` | Failure diagnosis and ranked strategy proposal | Playbook (`SKILL.md`) | Diagnostic verdict (`doctor_verdict`), root causes, candidate strategy bundle |
| `pylander-strategy-orchestrator` | Compare strategy branches and select winner/no-winner | Script-backed: `.agents/skills/pylander-strategy-orchestrator/scripts/run_strategy_arena.py` | `arena_scoreboard.v1` |
| `pylander-arena-branch-runner` | Execute one strategy/tune branch and emit normalized report | Script-backed: `.agents/skills/pylander-arena-branch-runner/scripts/run_arena_branch.py` | `arena_branch_report.v1` |
| `pylander-tune-routing-planner` | Route between tune-arena and direct tune-loop | Script-backed: `.agents/skills/pylander-tune-routing-planner/scripts/route_tuning.py` | `route_decision.v1` |
| `pylander-tune-orchestrator` | Compare tune branches and hand off winner/no-winner | Script-backed: `.agents/skills/pylander-tune-orchestrator/scripts/run_tune_arena.py` | `arena_scoreboard.v1` |
| `pylander-tune-loop-manager` | Bounded tuning loop (`light/standard/extensive`) | Script-backed: `.agents/skills/pylander-tune-loop-manager/scripts/run_tune_loop.py` | `tune_loop_report.v1` |
| `pylander-regression-analyzer` | Broad quick/full regression gate | Script-backed: `.agents/skills/pylander-regression-analyzer/scripts/gate_regression.py` | `regression_gate_report.v1` |
| `pylander-benchmark-runner` | Pack construction + cached benchmark execution/compare | Script-backed: `.agents/skills/pylander-benchmark-runner/scripts/*` | Bench JSON/CSV and optional compare report |
| `pylander-benchmark-analyzer` | Benchmark triage and root-cause ranking | Playbook (`SKILL.md`) | Diagnostic verdict (`doctor_verdict`), ranked findings, repro bundle |
| `pylander-plot-runner` | Plot-pack case selection and plot command execution | Script-backed: `.agents/skills/pylander-plot-runner/scripts/build_plot_pack.py` | Plot pack manifest |
| `pylander-plot-analyzer` | Plot interpretation and anomaly diagnosis | Playbook (`SKILL.md`) | Diagnostic verdict (`doctor_verdict`), ranked visual findings, follow-ups |
| `pylander-telemetry-analyzer` | Log/data crash+perf triage and reproducible repro bundle generation | Script-backed: `.agents/skills/pylander-telemetry-analyzer/scripts/analyze_telemetry.py` | `telemetry_triage_report.v1` |
| `pylander-telemetry-builder` | Plan-first focused telemetry/probe design from triage gaps | Script-backed: `.agents/skills/pylander-telemetry-builder/scripts/plan_telemetry.py` | `telemetry_probe_plan.v1` |
| `pylander-docs-sync-planner` | Docs drift analysis and patch planning | Playbook (`SKILL.md`) | Drift report and docs patch plan |
| `pylander-maintenance-planner` | Test/benchmark maintenance planning (`test|bench|both`) | Playbook (`SKILL.md`) | Prioritized maintenance plan and command bundle |
| `pylander-refactor-planner` | Incremental refactor planning with invariants and risk controls | Playbook (`SKILL.md`) | Phased refactor plan and optional patch-set spec |
| `pylander-commit-manager` | Task-scoped commit planning/execution and standardized commit messages | Playbook (`SKILL.md`) | Commit boundaries, staging plan, and message drafts |

## Contracts and artifacts

Script-backed orchestration contracts live under `.agents/skills/contracts/`:

- `route_decision.v1.json`
- `arena_branch_report.v1.json`
- `arena_scoreboard.v1.json`
- `tune_loop_report.v1.json`
- `regression_gate_report.v1.json`
- `telemetry_triage_report.v1.json`
- `telemetry_probe_plan.v1.json`

Common artifact locations:

- `outputs/arena/<arena_id>/<branch_id>/` branch notes and report artifacts
- `outputs/benchmarks/<commit-or-dirty-key>/` benchmark cache and compare reports
- `outputs/plots/` plot packs and generated plot bundles
- `outputs/diagnostics/` telemetry triage reports and probe plans

## Practical notes

- Cached baseline compares require a pre-seeded cache for non-current refs.
- Use explicit selectors/seeds whenever possible for reproducibility.
- Keep branch comparisons like-for-like: same selectors, seed spec, bot, and bot config.
- Use telemetry analyzer first for crash/perf triage; only add probes via telemetry builder when the current signal set is insufficient.
- Use docs-sync and maintenance/refactor planners as optional cross-cutting planning tools, not mandatory gates.
- Use commit-manager to keep commits goal-scoped (commit as PR scope) with consistent message structure.
