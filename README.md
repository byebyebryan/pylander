# Pylander

A retro-modern Lunar Lander-inspired game with deterministic simulation, procedural terrain, and bot-driven play.

## Docs

- Start here: [`docs/README.md`](docs/README.md)
- Bot framework + API: [`docs/overview.md`](docs/overview.md)
- Bot docs: [`docs/plunge.md`](docs/plunge.md), [`docs/pdg.md`](docs/pdg.md)
- Scenario docs: [`docs/terminal_normal.md`](docs/terminal_normal.md), [`docs/terminal_error.md`](docs/terminal_error.md), [`docs/boost_downhill.md`](docs/boost_downhill.md), [`docs/boost_flat.md`](docs/boost_flat.md), [`docs/boost_climb.md`](docs/boost_climb.md)

## Features

- Procedural terrain generation (simplex)
- Physics-based lander with fuel and overdrive
- Credits, landing targets, and refueling loop
- Headless deterministic evaluation + benchmark reports
- Unified optimizer bot (`pdg`) for full-envelope flight
- Terminal benchmark bot (`plunge`)

## Setup

```bash
uv sync
```

## Testing

```bash
uv run pytest
```

Pytest now runs in parallel by default via `xdist`. Use `uv run pytest -n 0`
when you want a serial run for debugging.

## Command model

```bash
uv run python main.py <command> [options]
```

Commands:

- `play`: single rendered interactive run
- `run`: single run (`--interactive` kept as a compatibility path, headless otherwise)
- `sim`: single headless simulation run
- `plot`: headless simulation with plotting enabled by default
- `bench`: multi-run benchmark batch

Run `uv run python main.py --help` for full help.

## Running

### Interactive (`play`)

```bash
uv run python main.py play
uv run python main.py play flat --bot pdg
```

Legacy compatibility path:

```bash
uv run python main.py run --interactive
uv run python main.py run --interactive flat --bot pdg
```

### Single headless run (`sim`)

```bash
uv run python main.py sim terminal_normal:mid:0 --bot pdg
uv run python main.py sim boost_downhill:mid_half:boost:0 --bot pdg
uv run python main.py sim terminal_error:mid_wide:3 --bot pdg
uv run python main.py sim boost_climb:mid_half:0 --bot pdg
uv run python main.py sim plunge:mid_normal:0 --bot plunge
```

Selector format:

- play/run/sim/plot selector: `level[:scenario[:goal[:seed]]]`
- Use `level::seed` when setting a seed without a scenario.
- Omit goal to default to `landing`.
- Boost levels use weight-suffixed scenarios like `near_half`, `mid_full`, and `high_empty`.
- Boost-goal support is currently exposed by levels: `boost_downhill`, `boost_flat`, `boost_climb`.
- Bot selector remains bot-only: `--bot <name>`.

### Plot run (`plot`)

```bash
uv run python main.py plot boost_flat:far_half:0 --bot pdg
uv run python main.py plot boost_flat:far_half:0 --bot pdg --plot all --plot-output both
```

Plot outputs are written under `outputs/plots/<selector>_<timestamp>/` when plotting is enabled.

### Benchmark batch (`bench`)

```bash
# Terminal-error subset over seed range
uv run python main.py bench \
  terminal_error:shallow_tight:0-19 \
  terminal_error:mid_wide:0-19 \
  terminal_error:steep_wide:0-19 \
  --bot pdg

# Multi-level benchmark + reports (one selector per level/scenario spec)
uv run python main.py bench \
  plunge \
  terminal_normal \
  terminal_error \
  boost_downhill \
  boost_flat \
  boost_climb \
  --bot pdg \
  --json auto \
  --csv auto
```

Bench selector format:

- `level[:scenario[:goal[:seed_spec]]]`
- `seed_spec` supports comma/range syntax, e.g. `0-9`, `0,2,4`, `3-1`.
- Omit goal to default to `landing`.
- If seed spec is omitted, deterministic scenarios run with seed `0`.
- If seed spec is omitted and the scenario has randomized fields, seeds auto-expand to `0-9`.

Benchmark pack tooling (`skills/pylander-benchmark-runner/scripts/*.py`) now reads
level metadata from `benchmark_profile()`:

- scenario sets: `smoke`, `quick`, `full`
- policy: `normal`, `observe_only`, `excluded`

Default policy profile:

- `flat`, `mountains`: `excluded`
- `plunge`, `terminal_normal`, `terminal_error`, `boost_downhill`, `boost_flat`, `boost_climb`: `normal`

Repo shorthand:

- `terminal levels` means `terminal_normal` + `terminal_error`
- `plunge` is a separate plunge benchmark level

Focused benchmark-pack selectors also accept explicit group aliases:

- `@terminal` / `@terminal_flight` -> `terminal_normal`, `terminal_error`
- `@plunge` / `@terminal_plunge` -> `plunge`

Example:

```bash
uv run python skills/pylander-benchmark-runner/scripts/run_cached_benchmark.py \
  --mode focused \
  --selectors @terminal \
  --seed-spec 0-9 \
  --baseline-ref main
```

## Key options

### `play` / `run` / `sim` / `plot`

- selector: `level[:scenario[:goal[:seed]]]`
- `-b, --bot NAME`
- `--bot-config PATH` (JSON override config for supported bots)
- `-l, --lander NAME`
- `-n, --steps N`
- `-t, --time S`
- `-f, --freq N` (headless print cadence)
- `-p, --plot none|speed|thrust|all`
- `-o, --plot-output combined|split|both`
- `--plot-max-side-px N` (default: 1800)
- `--stop-on-crash`
- `--stop-on-out-of-fuel`
- `--stop-on-first-land`
- `-i, --interactive` (`run` only; compatibility alias for `play`)

### `bench`

- selectors: `level[:scenario[:goal[:seed_spec]]]` (one or more)
- `-b, --bot NAME`
- `--bot-config PATH` (JSON override config for supported bots)
- `-l, --lander NAME`
- `-n, --steps N`
- `-t, --time S`
- `-p, --plot none|speed|thrust|all`
- `-o, --plot-output combined|split|both`
- `--plot-max-side-px N` (default: 1800)
- `-j, --json PATH|auto`
- `-c, --csv PATH|auto`
- `--bot-profile, --no-bot-profile` (default: on)
- `--bot-profile-interval-s S` (optional profiler log interval)
- `--bot-profile-logs, --no-bot-profile-logs` (default: off)
- If worker processes are unavailable, `bench` now errors instead of silently
  falling back. Benchmark runs use the default parallel worker policy.

Benchmark records include bot compute timing metrics (avg plus p90/p99 for
passive, update, and total ms/tick) when profiling is enabled.

Boost-phase evaluation metrics are reported through generic fields such as
`boost_cutoff_*` and `boost_goal_*`. For `terminal_normal` and `terminal_error`,
`boost_cutoff_*` is a spawn-time coast-entry snapshot rather than a post-burn
boost-cutoff latch. Bot-owned diagnostics stay namespaced under
`bot_<botname>_*`, for example `bot_pdg_terminal_entry_projected_dx`,
`bot_pdg_terminal_gate_mode`, and `bot_pdg_shape_curve_rmse`.

When plotting is enabled, runs now emit `plot_paths` and a plot manifest path for bundle-style outputs.

## Project skills

Local project workflows live under `skills/`:

- `pylander-goal-builder`: define/build new eval levels with benchmark profile coverage.
- `pylander-goal-analyzer`: diagnose level-goal failures and produce ranked strategies.
- `pylander-strategy-orchestrator`: run parallel strategy branches and pick a winner.
- `pylander-tune-routing-planner`: decide whether tuning should run through tune-arena or direct tune-loop.
- `pylander-tune-orchestrator`: run parallel tuning branches on the selected strategy winner.
- `pylander-arena-branch-runner`: execute one focused strategy/tuning branch.
- `pylander-tune-loop-manager`: profile-based tuning loop (`light|standard|extensive`) for direct tuning or post-arena polish.
- `pylander-regression-analyzer`: quick/full regression diagnosis before merge.
- `pylander-benchmark-runner` / `pylander-benchmark-analyzer`: benchmark execution and diagnosis.
- `pylander-plot-runner` / `pylander-plot-analyzer`: plot pack generation and visual diagnosis.
- `pylander-telemetry-analyzer`: crash/perf triage from benchmark artifacts and sim/debug logs.
- `pylander-telemetry-builder`: plan-first focused telemetry/probe design when existing signals are insufficient.
- `pylander-docs-sync-planner`: detect docs drift and produce a minimal docs patch plan.
- `pylander-maintenance-planner`: plan test/benchmark maintenance with `mode=test|bench|both`.
- `pylander-refactor-planner`: decision-complete refactor planning with optional patch-set specification.
- `pylander-commit-manager`: plan and execute task-scoped commits with standardized message format.

Workflow this skill set is built for:

1. Define or adjust goal surface with `pylander-goal-builder`.
2. Diagnose failures and produce ranked strategies with `pylander-goal-analyzer`.
3. Run parallel strategy evaluation with `pylander-strategy-orchestrator` and `pylander-arena-branch-runner`.
4. Route tuning depth with `pylander-tune-routing-planner`.
5. Tune via either `pylander-tune-orchestrator` + `pylander-arena-branch-runner` then `pylander-tune-loop-manager`, or direct `pylander-tune-loop-manager`.
6. Run broad gate decision with `pylander-regression-analyzer`.
7. Use `pylander-benchmark-runner` / `pylander-benchmark-analyzer` and
   `pylander-plot-runner` / `pylander-plot-analyzer` at any stage for focused diagnosis.
8. Use `pylander-telemetry-analyzer` for log/data triage and hand off to
   `pylander-telemetry-builder` when additional focused instrumentation is needed.
9. Use `pylander-docs-sync-planner`, `pylander-maintenance-planner`, and
   `pylander-refactor-planner` as cross-cutting planning tools for recurring maintenance work.
10. Use `pylander-commit-manager` to split work into goal-based commits and keep message quality consistent.

For the full skill map (including intent, artifacts, and contracts), see:
[`docs/skills_workflow.md`](docs/skills_workflow.md).

Core orchestration executors:

- `uv run python skills/pylander-tune-routing-planner/scripts/route_tuning.py --input <in.json> --output <out.json>`
- `uv run python skills/pylander-arena-branch-runner/scripts/run_arena_branch.py --input <in.json> --output <out.json> --no-execute-validation`
- `uv run python skills/pylander-strategy-orchestrator/scripts/run_strategy_arena.py --input <in.json> --output <out.json> --no-execute-workers`
- `uv run python skills/pylander-tune-orchestrator/scripts/run_tune_arena.py --input <in.json> --output <out.json> --no-execute-workers`
- `uv run python skills/pylander-tune-loop-manager/scripts/run_tune_loop.py --input <in.json> --output <out.json>`
- `uv run python skills/pylander-regression-analyzer/scripts/gate_regression.py --input <in.json> --output <out.json> --no-execute`

Telemetry diagnostics executors:

- `uv run python skills/pylander-telemetry-analyzer/scripts/analyze_telemetry.py --compare-json <path> --output-report <out.json>`
- `uv run python skills/pylander-telemetry-analyzer/scripts/analyze_telemetry.py --benchmark-json <path> --sim-log <sim.log> --output-report <out.json>`
- `uv run python skills/pylander-telemetry-builder/scripts/plan_telemetry.py --triage-report <triage.json> --output-plan <plan.json>`

## Bot profiling

The game loop now supports lightweight bot-loop profiling in headless mode:

```bash
PYLANDER_BOT_PROFILE=1 uv run python main.py sim terminal_normal:mid:0 --bot pdg
```

Optional interval override (seconds):

```bash
  PYLANDER_BOT_PROFILE=1 PYLANDER_BOT_PROFILE_INTERVAL_S=2 \
  uv run python main.py sim plunge:mid_normal:0 --bot plunge
```

Profiled timing covers passive pre-update work, bot update time, and total
bot-loop time.

For `bench`, profiling is enabled by default with periodic profile logs disabled.

Headless `sim` output now uses:

- compact per-tick lines: `t=... | ship x=... y=... | bot=... mode=... phase=...`
- sectioned final results with generic run/boost fields first and bot-owned
  diagnostics grouped under `Bot Telemetry: <bot>`

See [`docs/overview.md`](docs/overview.md) for the bot API and profiling details.

## Controls (interactive)

- `W`/`UP`: Increase thrust
- `S`/`DOWN`: Decrease thrust
- `A`/`LEFT`: Rotate left
- `D`/`RIGHT`: Rotate right
- `F`: Refuel (when landed)
- `TAB`: Switch actor
- `T`: Toggle ballistic path
- `R`: Reset
- `Q`/`ESC`: Quit
