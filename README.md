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

- `play`: interactive rendered mode
- `run`: single headless simulation run
- `bench`: multi-run benchmark batch

Run `uv run python main.py --help` for full help.

## Running

### Interactive (`play`)

```bash
uv run python main.py play
uv run python main.py play flat --bot zem_zev
```

### Single headless run (`run`)

```bash
uv run python main.py run flare --bot zem_zev --seed 0
uv run python main.py run coast --bot zem_zev --scenario mid_wide --seed 3
uv run python main.py run climb --bot zem_zev --scenario slope_mid --seed 0
uv run python main.py run plunge --bot plunge --scenario mid_normal --seed 0
uv run python main.py run flare --bot query_demo --seed 0
```

### Benchmark batch (`bench`)

```bash
# Quick regression suite (fixed seeds/scenarios)
uv run python main.py bench plunge --quick --workers 8

# Custom benchmark matrix
uv run python main.py bench coast \
  --bot zem_zev \
  --seeds 0-19 \
  --scenarios shallow_tight,mid_wide,steep_wide \
  --workers 8

# Multi-level benchmark + reports
uv run python main.py bench plunge \
  --levels plunge,flare,coast,climb,setup,launch \
  --bot zem_zev \
  --seeds 0-9 \
  --json auto \
  --csv auto
```

Quick benchmark subsets:

- `plunge`: `low_normal`, `mid_normal`, `high_normal`
- `flare`: `shallow`, `mid`, `steep`
- `coast`: `shallow_tight`, `mid_wide`, `steep_wide`
- `climb`: `flat_mid`, `slope_mid`, `slope_high`
- `setup`: `shallow_near`, `mid_far`, `steep_far`

Focused eval (`--eval-mode focused`) is available for `flare`, `coast`, `climb`, and `setup`.

## Key options

### `play` / `run`

- `--bot NAME`
- `--seed N`
- `--scenario NAME`
- `--lander NAME`
- `--eval-mode auto|focused|full`
- `--steps N`
- `--time S`
- `--plot none|speed|thrust|all`
- `--stop-on-crash`
- `--stop-on-out-of-fuel`
- `--stop-on-first-land`

### `bench`

- `--bot NAME`
- `--levels CSV`
- `--seeds SPEC`
- `--scenarios CSV`
- `--scenario NAME`
- `--quick`
- `--workers N`
- `--json PATH|auto`
- `--csv PATH|auto`
- `--eval-mode auto|focused|full`

## Bot profiling and query API

The game loop now supports lightweight bot-loop profiling in headless mode:

```bash
PYLANDER_BOT_PROFILE=1 uv run python main.py run flare --bot zem_zev --seed 0
```

Optional interval override (seconds):

```bash
PYLANDER_BOT_PROFILE=1 PYLANDER_BOT_PROFILE_INTERVAL_S=2 \
  uv run python main.py run flare --bot query_demo --seed 0
```

Profiled timing covers passive sensor build, active sensor build (legacy bots), query evaluation (query bots), and bot update time.

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
