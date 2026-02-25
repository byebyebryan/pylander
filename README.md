# Pylander

A classic Lunar Lander-inspired game with procedurally generated terrain, scoring system, and AI bot support.

## Docs

- Start here: [`docs/README.md`](docs/README.md)
- Bot dev framework + API: [`docs/overview.md`](docs/overview.md)
- Phase docs: [`docs/plunge.md`](docs/plunge.md), [`docs/flare.md`](docs/flare.md), [`docs/coast.md`](docs/coast.md), [`docs/launch.md`](docs/launch.md)

## Features

- Procedural terrain generation with simplex noise
- Physics-based lander with fuel management
- Credits-based landing targets (distance from start)
- Refueling system (exchange credits for fuel)
- Continuous gameplay (land, refuel, take off again)
- AI bot interface for autonomous play
- Unified plunge benchmark bot (`plunge`)
- Dedicated flare benchmark level (`flare`) with terminal-phase bot (`flare`)
- Horizontal-control benchmark level (`coast`) with coast-first bot (`coast`)
- Launch setup benchmark level (`launch`) with setup+handoff bot (`launch`)

## Setup

```bash
uv sync
```

## Running

Default level is `flat` when omitted. List all levels with `--help`.

### Human Mode
```bash
uv run python main.py
```

### Bot Mode
Watch an AI bot play using the sensor/action API:
```bash
# Canonical plunge benchmark level + bot
uv run python main.py plunge

# Pick a specific plunge scenario
uv run python main.py plunge --scenario mid_normal

# Terminal flare benchmark level + bot
uv run python main.py flare

# Pick a specific flare scenario
uv run python main.py flare --scenario mid

# Horizontal-control benchmark level + bot
uv run python main.py coast

# Pick a specific coast scenario
uv run python main.py coast --scenario glide_long_stress_correction

# Launch setup benchmark level + bot
uv run python main.py launch

# Pick a specific launch scenario
uv run python main.py launch --scenario air_mid_reverse

# Run launch end-to-end (handoff + coast + terminal)
uv run python main.py launch --eval-mode full

# Use plunge bot on other levels if desired
uv run python main.py flat --bot plunge
```

### Headless + batch evaluation

Headless mode runs without graphics (faster, deterministic with a fixed seed):

```bash
# Single run
uv run python main.py plunge --headless --seed 0
```

Useful flags:

- `--freq N` stats print frequency (`60` ~ once/sec, `1` every frame, `0` quiet)
- `--steps N` max simulation steps
- `--time S` max simulation time seconds (default `300`)
- `--seed N` deterministic runs
- `--scenario NAME` pick scenario
- `--bot NAME` and `--bot-behavior NAME` override defaults
- `--plot none|speed|thrust|all` save trajectory plot under `outputs/`

Batch mode:

```bash
# Example batch
uv run python main.py plunge --headless --batch \
  --batch-seeds 0-19 \
  --batch-json auto \
  --batch-csv auto

# Fast regression
uv run python main.py plunge --headless --quick-benchmark
```

Quick benchmark preset includes:

- `plunge`: `low_normal`, `mid_normal`, `high_normal`
- `flare`: `shallower`, `mid`, `steeper`
- `coast`: `glide_mid`, `glide_long_stress_correction`, `handoff_extreme`
- `launch`: `air_mid`, `air_long`, `air_mid_reverse`, `air_long_heavy`

Staged eval (`--eval-mode focused|full`) is mainly for `coast` and `launch`.

## Controls (Human Mode)

- **W/UP**: Increase thrust
- **S/DOWN**: Decrease thrust
- **A/LEFT**: Rotate left (discrete steps, auto-snaps to 45° intervals)
- **D/RIGHT**: Rotate right (discrete steps, auto-snaps to 45° intervals)
- **F**: Refuel (when landed, costs 10 pts/fuel unit)
- **T**: Toggle ballistic trajectory overlay
- **R**: Reset game
- **Q/ESC**: Quit

## Bot development

- Bot framework + API: [`docs/overview.md`](docs/overview.md)
- Phase docs are listed in [`Scenario Levels`](#scenario-levels) below.

## Scenario Levels

Scenario docs:

- `plunge`: [`docs/plunge.md`](docs/plunge.md)
- `flare` (level locked, bot placeholder): [`docs/flare.md`](docs/flare.md)
- `coast` (placeholder for now): [`docs/coast.md`](docs/coast.md)
- `launch` (placeholder for now): [`docs/launch.md`](docs/launch.md)

## Command Line Options

```bash
uv run python main.py [level_name] [options]
```

Use `uv run python main.py --help` for the up-to-date full list.

Common options:

- `--bot NAME` select bot (`plunge`, `flare`, `coast`, `launch`)
- `--bot-behavior NAME` behavior profile for bots that support it
- `--headless` run without graphics
- `--freq N` stats print frequency
- `--steps N`, `--time S` headless run limits
- `--plot none|speed|thrust|all` save trajectory plot
- `--eval-mode auto|focused|full` staged eval mode
- `--seed N` random seed
- `--scenario NAME` pick scenario
- `--lander NAME` choose lander variant
- `--batch` enable batch runs
- `--batch-seeds`, `--batch-levels`, `--batch-scenarios` batch selection
- `--batch-json`, `--batch-csv` output reports
- `--batch-workers N` parallel worker count
- `--quick-benchmark` run fixed cross-level benchmark suite

## Promotion Gates (Plunge Bot)

Moved to [`docs/plunge.md`](docs/plunge.md).

## Game Mechanics

### Credits
- Each landing pad awards credits based on its distance from the start
- Land successfully to collect credits
- Pads turn yellow once collected

### Landing Requirements
- Speed < 15 m/s
- Angle < 20° from vertical
- Both legs on a landing pad

### Refueling
- When landed, hold F to refuel
- Costs 10 credits per fuel unit
- Refuels at 1 unit/second
