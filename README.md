# Pylander

A retro-modern Lunar Lander-inspired game with deterministic simulation, procedural terrain, and bot-driven play.

## Docs

- Start here: [`docs/README.md`](docs/README.md)
- Bot framework + API: [`docs/overview.md`](docs/overview.md)
- Bot docs: [`docs/plunge.md`](docs/plunge.md), [`docs/zem_zev.md`](docs/zem_zev.md)
- Scenario docs: [`docs/flare.md`](docs/flare.md), [`docs/coast.md`](docs/coast.md), [`docs/setup.md`](docs/setup.md), [`docs/launch.md`](docs/launch.md)

## Features

- Procedural terrain generation (simplex)
- Physics-based lander with fuel and overdrive
- Credits, landing targets, and refueling loop
- Headless deterministic evaluation + batch reports
- Unified optimizer bot (`zem_zev`) for full-envelope flight
- Terminal benchmark bot (`plunge`)

## Setup

```bash
uv sync
```

## Running

Default level is `flat` when omitted.

### Human mode

```bash
uv run python main.py
```

### Bot mode

```bash
# Unified full-envelope bot
uv run python main.py flare --bot zem_zev
uv run python main.py coast --bot zem_zev
uv run python main.py setup --bot zem_zev
uv run python main.py launch --bot zem_zev

# Dedicated terminal bot
uv run python main.py plunge --bot plunge
```

### Scenario selection

```bash
uv run python main.py coast --scenario mid_wide
uv run python main.py setup --scenario steep_far
uv run python main.py flare --scenario steep
uv run python main.py plunge --scenario mid_normal
```

## Headless + batch evaluation

```bash
# Single deterministic run
uv run python main.py flare --headless --seed 0 --bot zem_zev

# Quick regression suite
uv run python main.py plunge --headless --quick-benchmark --bot plunge
uv run python main.py flare --headless --quick-benchmark --bot zem_zev

# Custom batch
uv run python main.py coast --headless --batch \
  --batch-seeds 0-19 \
  --batch-scenarios shallow_tight,mid_wide,steep_wide \
  --bot zem_zev
```

Quick benchmark subsets:

- `plunge`: `low_normal`, `mid_normal`, `high_normal`
- `flare`: `shallow`, `mid`, `steep`
- `coast`: `shallow_tight`, `mid_wide`, `steep_wide`
- `setup`: `shallow_near`, `mid_far`, `steep_far`

Focused eval (`--eval-mode focused`) is available for `flare`, `coast`, and `setup`.

## CLI summary

```bash
uv run python main.py [level_name] [options]
```

### Bots

- `zem_zev`
- `plunge`

### Key options

- `--bot NAME`
- `--headless`
- `--freq N`
- `--steps N`
- `--time S`
- `--plot none|speed|thrust|all`
- `--stop-on-crash`
- `--stop-on-out-of-fuel`
- `--stop-on-first-land`
- `--eval-mode auto|focused|full`
- `--seed N`
- `--scenario NAME`
- `--lander NAME`
- `--batch`
- `--batch-seeds SPEC`
- `--batch-levels CSV`
- `--batch-scenarios CSV`
- `--batch-json PATH|auto`
- `--batch-csv PATH|auto`
- `--batch-workers N`
- `--quick-benchmark`

Run `uv run python main.py --help` to list available levels and full option descriptions.

## Controls (human mode)

- `W`/`UP`: Increase thrust
- `S`/`DOWN`: Decrease thrust
- `A`/`LEFT`: Rotate left
- `D`/`RIGHT`: Rotate right
- `F`: Refuel (when landed)
- `TAB`: Switch actor
- `T`: Toggle ballistic path
- `R`: Reset
- `Q`/`ESC`: Quit
