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

# Run unified ZEM/ZEV bot on flare
uv run python main.py flare --bot zem_zev --scenario mid

# Horizontal-control benchmark level + bot
uv run python main.py coast

# Pick a specific coast scenario
uv run python main.py coast --scenario entry_steep_stress

# Launch setup benchmark level + bot
uv run python main.py launch

# Pick a specific launch scenario
uv run python main.py launch --scenario air_steep

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

# Coast-only mini benchmark (same coast scenarios as preset)
uv run python main.py coast --headless --batch \
  --batch-seeds 0,1,2 \
  --batch-levels coast \
  --batch-scenarios entry_mid_trim,entry_mid_energy,entry_steep_stress
```

Quick benchmark preset includes:

- `plunge`: `low_normal`, `mid_normal`, `high_normal`
- `flare`: `shallower`, `mid`, `steeper`
- `coast`: `entry_mid_trim`, `entry_mid_energy`, `entry_steep_stress`
- `launch`: `air_mid`, `air_steep`

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
- `flare`: [`docs/flare.md`](docs/flare.md)
- `coast`: [`docs/coast.md`](docs/coast.md)
- `launch`: [`docs/launch.md`](docs/launch.md)

## Command Line Options

```bash
uv run python main.py [level_name] [options]
```

**Levels:** Run `uv run python main.py --help` to list (e.g. `flat`, `mountains`, `plunge`).

**Bot names:** `plunge`, `flare`, `coast`, `launch`, `zem_zev` (set via `--bot`; see `--help`).

**Options:**
- `--bot NAME` - Select bot (`plunge`, `flare`, `coast`, `launch`, `zem_zev`)
- `--bot-behavior NAME` - Behavior profile for bots that support it (examples: `plunge` => `balanced`; `flare` => `flare`; `coast` => `coast`; `launch` => `launch`)
- `--headless` - Run without graphics (requires bot)
- `--freq N` - Print stats every N frames (60 ≈ 1/s; 0 = off)
- `--steps N` - Limit simulation to N steps (headless)
- `--time S` - Limit simulation to S seconds (headless, default 300)
- `--plot none|speed|thrust|all` - Save trajectory plot (headless)
- `--stop-on-crash`, `--stop-on-out-of-fuel`, `--stop-on-first-land` - End conditions
- `--eval-mode auto|focused|full` - Evaluation mode for staged levels (`coast` and `launch` default to full when auto)
- `--seed N` - Random seed
- `--scenario NAME` - Select a level scenario (if supported)
- `--lander NAME` - Lander variant (classic, differential, simple)
- `--batch` - Enable batch runs (requires `--headless` + bot)
- `--batch-seeds SPEC` - Seeds like `0-19` or `0,1,2,5`
- `--batch-levels CSV` - Level names for batch suites
- `--batch-scenarios CSV` - Scenario names for batch suites
- `--batch-json PATH|auto` - Write JSON report
- `--batch-csv PATH|auto` - Write CSV rows
- `--batch-workers N` - Parallel worker processes for batch runs (`1` = sequential; effective workers are capped by CPU count and run count)
- `--quick-benchmark` - Built-in cross-level core benchmark preset (`plunge` + `flare` + `coast` + `launch` subsets)
- `--help`, `-h` - Show help message

Batch mode defaults to `--freq 0` (quiet) for speed; pass `--freq` to enable per-run stats.
Quiet mode disables per-step stats output, but batch progress lines still print.

Batch/headless eval records include `landing_offset` (absolute horizontal error from target center on landed runs).

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
