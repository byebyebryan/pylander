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
2. `pylander-goal-doctor`
3. `pylander-strategy-arena` + `pylander-arena-worker`
4. `pylander-tune-router`
5. `pylander-tune-arena` + `pylander-arena-worker` -> `pylander-tune-loop`, or direct `pylander-tune-loop`
6. `pylander-regression-doctor`

Cross-cutting diagnostics usable at any stage:

- `pylander-benchmark`
- `pylander-benchmark-doctor`
- `pylander-plot`
- `pylander-plot-doctor`
- `pylander-telemetry-doctor`
- `pylander-telemetry-builder`

## Skill coverage matrix

| Skill | Workflow role | Execution status | Primary output |
|---|---|---|---|
| `pylander-goal-builder` | Build/adjust level goal surface and benchmark profile coverage | Playbook (`SKILL.md`) | Level + scenario updates and focused validation proof |
| `pylander-goal-doctor` | Failure diagnosis and ranked strategy proposal | Playbook (`SKILL.md`) | Doctor verdict, root causes, candidate strategy bundle |
| `pylander-strategy-arena` | Compare strategy branches and select winner/no-winner | Script-backed: `skills/pylander-strategy-arena/scripts/run_strategy_arena.py` | `arena_scoreboard.v1` |
| `pylander-arena-worker` | Execute one strategy/tune branch and emit normalized report | Script-backed: `skills/pylander-arena-worker/scripts/run_arena_branch.py` | `arena_branch_report.v1` |
| `pylander-tune-router` | Route between tune-arena and direct tune-loop | Script-backed: `skills/pylander-tune-router/scripts/route_tuning.py` | `route_decision.v1` |
| `pylander-tune-arena` | Compare tune branches and hand off winner/no-winner | Script-backed: `skills/pylander-tune-arena/scripts/run_tune_arena.py` | `arena_scoreboard.v1` |
| `pylander-tune-loop` | Bounded tuning loop (`light/standard/extensive`) | Script-backed: `skills/pylander-tune-loop/scripts/run_tune_loop.py` | `tune_loop_report.v1` |
| `pylander-regression-doctor` | Broad quick/full regression gate | Script-backed: `skills/pylander-regression-doctor/scripts/gate_regression.py` | `regression_gate_report.v1` |
| `pylander-benchmark` | Pack construction + cached benchmark execution/compare | Script-backed: `skills/pylander-benchmark/scripts/*` | Bench JSON/CSV and optional compare report |
| `pylander-benchmark-doctor` | Benchmark triage and root-cause ranking | Playbook (`SKILL.md`) | Doctor verdict, ranked findings, repro bundle |
| `pylander-plot` | Plot-pack case selection and plot command execution | Script-backed: `skills/pylander-plot/scripts/build_plot_pack.py` | Plot pack manifest |
| `pylander-plot-doctor` | Plot interpretation and anomaly diagnosis | Playbook (`SKILL.md`) | Doctor verdict, ranked visual findings, follow-ups |
| `pylander-telemetry-doctor` | Log/data crash+perf triage and reproducible repro bundle generation | Script-backed: `skills/pylander-telemetry-doctor/scripts/analyze_telemetry.py` | `telemetry_triage_report.v1` |
| `pylander-telemetry-builder` | Plan-first focused telemetry/probe design from triage gaps | Script-backed: `skills/pylander-telemetry-builder/scripts/plan_telemetry.py` | `telemetry_probe_plan.v1` |

## Contracts and artifacts

Script-backed orchestration contracts live under `skills/contracts/`:

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
- Use telemetry doctor first for crash/perf triage; only add probes via telemetry builder when the current signal set is insufficient.
