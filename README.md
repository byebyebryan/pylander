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
- Query-API demo bot (`query_demo`) for batched sensor requests

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
uv run python main.py sim coast:mid_wide:3 --bot zem_zev
uv run python main.py sim climb:slope_mid:0 --bot zem_zev
uv run python main.py sim plunge:mid_normal:0 --bot plunge
uv run python main.py sim flare:mid:0 --bot query_demo
```

Selector format:

- run/sim/plot selector: `level[:scenario[:seed]]`
- Use `level::seed` when setting a seed without a scenario.

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
  --bot zem_zev \
  --workers 8

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

Focused eval (`--eval-mode focused`) is available for `flare`, `coast`, `climb`, and `setup`.

Benchmark pack tooling (`skills/pylander-benchmark/scripts/*.py`) now reads
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
- `-b, --bot NAME`
- `--bot-config PATH` (JSON override config for supported bots)
- `-l, --lander NAME`
- `-e, --eval-mode auto|focused|full`
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
- `-b, --bot NAME`
- `--bot-config PATH` (JSON override config for supported bots)
- `-l, --lander NAME`
- `-e, --eval-mode auto|focused|full`
- `-w, --workers N` (default: `max(1, CPU cores - 2)`)
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
  falling back. Use `--workers 1` only when you explicitly want sequential mode.

Benchmark records include bot compute timing metrics (avg plus p90/p99 for total,
query, and update ms/tick) when profiling is enabled.

When plotting is enabled, runs now emit `plot_paths` and a plot manifest path for bundle-style outputs.

## Project skills

Local project workflows live under `skills/`:

- `pylander-goal-builder`: define/build new eval levels with benchmark profile coverage.
- `pylander-goal-doctor`: diagnose level-goal failures and produce ranked strategies.
- `pylander-strategy-arena`: run parallel strategy branches and pick a winner.
- `pylander-tune-router`: decide whether tuning should run through tune-arena or direct tune-loop.
- `pylander-tune-arena`: run parallel tuning branches on the selected strategy winner.
- `pylander-arena-worker`: execute one focused strategy/tuning branch.
- `pylander-tune-loop`: profile-based tuning loop (`light|standard|extensive`) for direct tuning or post-arena polish.
- `pylander-regression-doctor`: quick/full regression diagnosis before merge.
- `pylander-benchmark` / `pylander-benchmark-doctor`: benchmark execution and diagnosis.
- `pylander-plot` / `pylander-plot-doctor`: plot pack generation and visual diagnosis.

Core orchestration executors:

- `uv run python skills/pylander-tune-router/scripts/route_tuning.py --input <in.json> --output <out.json>`
- `uv run python skills/pylander-arena-worker/scripts/run_arena_branch.py --input <in.json> --output <out.json> --no-execute-validation`
- `uv run python skills/pylander-strategy-arena/scripts/run_strategy_arena.py --input <in.json> --output <out.json> --no-execute-workers`
- `uv run python skills/pylander-tune-arena/scripts/run_tune_arena.py --input <in.json> --output <out.json> --no-execute-workers`
- `uv run python skills/pylander-tune-loop/scripts/run_tune_loop.py --input <in.json> --output <out.json>`
- `uv run python skills/pylander-regression-doctor/scripts/gate_regression.py --input <in.json> --output <out.json> --no-execute`

## Bot profiling and query API

The game loop now supports lightweight bot-loop profiling in headless mode:

```bash
PYLANDER_BOT_PROFILE=1 uv run python main.py sim flare:mid:0 --bot zem_zev
```

Optional interval override (seconds):

```bash
PYLANDER_BOT_PROFILE=1 PYLANDER_BOT_PROFILE_INTERVAL_S=2 \
  uv run python main.py sim flare:mid:0 --bot query_demo
```

Profiled timing covers passive sensor build, active sensor build (legacy bots), query evaluation (query bots), and bot update time.

For `bench`, profiling is enabled by default with periodic profile logs disabled.

See [`docs/overview.md`](docs/overview.md) for the new `QueryBot plan/act` interface and query payload types.

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
