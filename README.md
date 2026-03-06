# Pylander

A retro-modern Lunar Lander-inspired game with deterministic simulation, procedural terrain, and bot-driven play.

## Docs

- Start here: [`docs/README.md`](docs/README.md)
- Bot framework + API: [`docs/overview.md`](docs/overview.md)
- Bot docs: [`docs/plunge.md`](docs/plunge.md), [`docs/zem_zev.md`](docs/zem_zev.md)
- Scenario docs: [`docs/flare.md`](docs/flare.md), [`docs/coast.md`](docs/coast.md), [`docs/climb.md`](docs/climb.md), [`docs/setup.md`](docs/setup.md), [`docs/launch.md`](docs/launch.md)

## Features

- Procedural terrain generation (simplex)
- Physics-based lander with fuel and overdrive
- Credits, landing targets, and refueling loop
- Headless deterministic evaluation + benchmark reports
- Unified optimizer bot (`zem_zev`) for full-envelope flight
- Terminal benchmark bot (`plunge`)

## Setup

```bash
uv sync
```

## Command model

```bash
uv run python main.py <command> [options]
```

Commands:

- `run`: single run (`--interactive` for rendered mode, headless otherwise)
- `sim`: single headless simulation run
- `plot`: headless simulation with plotting enabled by default
- `bench`: multi-run benchmark batch

Run `uv run python main.py --help` for full help.

## Running

### Interactive (`run --interactive`)

```bash
uv run python main.py run --interactive
uv run python main.py run --interactive flat --bot zem_zev
```

### Single headless run (`sim`)

```bash
uv run python main.py sim flare:mid:0 --bot zem_zev
uv run python main.py sim setup:mid_near:0 --bot zem_zev:setup
uv run python main.py sim coast:mid_wide:3 --bot zem_zev
uv run python main.py sim climb:slope_mid:0 --bot zem_zev
uv run python main.py sim plunge:mid_normal:0 --bot plunge
```

Selector format:

- run/sim/plot selector: `level[:scenario[:seed]]`
- Use `level::seed` when setting a seed without a scenario.
- Bot selector: `bot[:goal]` (current non-landing goal support: `zem_zev:setup`).

### Plot run (`plot`)

```bash
uv run python main.py plot launch:far:0 --bot zem_zev
uv run python main.py plot launch:far:0 --bot zem_zev --plot all --plot-output both
```

Plot outputs are written under `outputs/plots/<selector>_<timestamp>/` when plotting is enabled.

### Benchmark batch (`bench`)

```bash
# Coast subset over seed range
uv run python main.py bench \
  coast:shallow_tight:0-19 \
  coast:mid_wide:0-19 \
  coast:steep_wide:0-19 \
  --bot zem_zev

# Multi-level benchmark + reports (one selector per level/scenario spec)
uv run python main.py bench \
  plunge \
  flare \
  coast \
  climb \
  setup \
  launch \
  --bot zem_zev \
  --json auto \
  --csv auto
```

Bench selector format:

- `level[:scenario[:seed_spec]]`
- `seed_spec` supports comma/range syntax, e.g. `0-9`, `0,2,4`, `3-1`.
- If seed spec is omitted, deterministic scenarios run with seed `0`.
- If seed spec is omitted and the scenario has randomized fields, seeds auto-expand to `0-9`.

Benchmark pack tooling (`skills/pylander-benchmark-runner/scripts/*.py`) now reads
level metadata from `benchmark_profile()`:

- scenario sets: `smoke`, `quick`, `full`
- policy: `normal`, `observe_only`, `excluded`

Default policy profile:

- `flat`, `mountains`: `excluded`
- `climb`: `observe_only`
- `plunge`, `flare`, `coast`, `setup`, `launch`: `normal`

## Key options

### `run` / `sim` / `plot`

- selector: `level[:scenario[:seed]]`
- `-b, --bot NAME[:goal]` (for example: `zem_zev:setup`)
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
- `-i, --interactive` (`run` only)

### `bench`

- selectors: `level[:scenario[:seed_spec]]` (one or more)
- `-b, --bot NAME[:goal]`
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

Benchmark records include bot compute timing metrics (avg plus p90/p99 for total,
query, and update ms/tick) when profiling is enabled.

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
PYLANDER_BOT_PROFILE=1 uv run python main.py sim flare:mid:0 --bot zem_zev
```

Optional interval override (seconds):

```bash
PYLANDER_BOT_PROFILE=1 PYLANDER_BOT_PROFILE_INTERVAL_S=2 \
  uv run python main.py sim plunge:mid_normal:0 --bot plunge
```

Profiled timing covers sensor build, bot update time, and total bot-loop time.

For `bench`, profiling is enabled by default with periodic profile logs disabled.

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
