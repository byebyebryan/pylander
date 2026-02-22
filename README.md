# Pylander

A classic Lunar Lander-inspired game with procedurally generated terrain, scoring system, and AI bot support.

## Features

- Procedural terrain generation with simplex noise
- Physics-based lander with fuel management
- Credits-based landing targets (distance from start)
- Refueling system (exchange credits for fuel)
- Continuous gameplay (land, refuel, take off again)
- AI bot interface for autonomous play

## Setup

```bash
uv sync
```

## Running

You must choose a level first (e.g. `level_1`). List levels with `--help`.

### Human Mode
```bash
uv run python main.py level_1
```

### Bot Mode
Watch an AI bot play using the sensor/action API:
```bash
# Safe landing bot (terrain-aware climb + approach)
uv run python main.py level_1 turtle

# Visual check on a focused eval scenario
uv run python main.py level_eval turtle --eval-scenario climb_to_target --seed 0
```

### Headless Mode (Testing/Training)
Run simulations without graphics for bot development:
```bash
# Run bot in headless mode (prints stats every second by default)
uv run python main.py level_1 turtle --headless

# Print every frame for detailed debugging
uv run python main.py level_1 turtle --headless --freq 1 --steps 300

# Print every 0.5 seconds
uv run python main.py level_1 turtle --headless --freq 30

# Disable output for fastest execution
uv run python main.py level_1 turtle --headless --freq 0 --steps 10000

# Use different seed or lander
uv run python main.py level_1 turtle --headless --seed 123
uv run python main.py level_1 --lander differential
```

Batch evaluation (headless, sequential single-bot runs):
```bash
# Fast preset benchmark (3 seeds x selected eval scenarios)
uv run python main.py level_eval turtle --headless --quick-benchmark

# Custom batch with report artifacts
uv run python main.py level_eval turtle --headless --batch \
  --batch-seeds 0-19 \
  --batch-scenarios spawn_above_target,greater_vertical_distance,climb_to_target \
  --batch-json auto \
  --batch-csv auto
```

By default, generated artifacts (batch JSON/CSV and trajectory plots) are written under `outputs/`.

Stats output format:
```
t=  1.00s | x:  105.4 alt: 106.1 | vx:  5.74 vy: -2.88 | ang:   6.0° thr: 30% | fuel: 99.7%
```
- `t`: simulation time in seconds
- `x`: world x position
- `alt`: altitude above terrain
- `vx, vy`: horizontal and vertical velocity (vy negative = falling)
- `ang`: rotation angle (0° = upright)
- `thr`: current thrust level percentage
- `fuel`: remaining fuel percentage

## Controls (Human Mode)

- **W/UP**: Increase thrust
- **S/DOWN**: Decrease thrust
- **A/LEFT**: Rotate left (discrete steps, auto-snaps to 45° intervals)
- **D/RIGHT**: Rotate right (discrete steps, auto-snaps to 45° intervals)
- **F**: Refuel (when landed, costs 10 pts/fuel unit)
- **R**: Reset game
- **Q/ESC**: Quit

## Bot Interface

Bots operate on limited sensors and emit explicit actions. Extend `Bot` and implement `update(dt, passive, active)`:

```python
from core.bot import Bot, PassiveSensors, ActiveSensors, BotAction

class MyBot(Bot):
    def update(self, dt: float, passive: PassiveSensors, active: ActiveSensors) -> BotAction:
        self.status = "idle"
        return BotAction(0.0, passive.angle, False, status="idle")
```

`PassiveSensors` includes world position (`x`, `y`), terrain-relative clearance (`altitude`), local terrain context (`terrain_y`, `terrain_slope`), kinematics, fuel/state, and radar/proximity contacts.
`ActiveSensors` provides `raycast(angle, max_range)` plus terrain helpers like `terrain_height(x)` and `terrain_profile(x_start, x_end, samples)`.

## Eval Scenarios (`level_eval`)

- `spawn_above_target`
- `greater_vertical_distance`
- `horizontal_travel_flat_descend`
- `increase_horizontal_distance`
- `climb_to_target`
- `complex_terrain_vertical_features`

## Command Line Options

```bash
python main.py <level_name> [bot_name] [options]
```

**Levels:** Run `python main.py --help` to list (e.g. `level_1`).

**Bot names:** `turtle` (see `--help`).

**Options:**
- `--headless` - Run without graphics (requires bot)
- `--freq N` - Print stats every N frames (60 ≈ 1/s; 0 = off)
- `--steps N` - Limit simulation to N steps (headless)
- `--time S` - Limit simulation to S seconds (headless, default 300)
- `--plot none|speed|thrust|all` - Save trajectory plot (headless)
- `--stop-on-crash`, `--stop-on-out-of-fuel`, `--stop-on-first-land` - End conditions
- `--seed N` - Random seed
- `--lander NAME` - Lander variant (classic, differential, simple)
- `--eval-scenario NAME` - Scenario for `level_eval`
- `--batch` - Enable batch runs (requires `--headless` + bot)
- `--batch-seeds SPEC` - Seeds like `0-19` or `0,1,2,5`
- `--batch-scenarios CSV` - Scenario names for `level_eval`
- `--batch-json PATH|auto` - Write JSON report
- `--batch-csv PATH|auto` - Write CSV rows
- `--batch-workers N` - Parallel worker processes for batch runs
- `--quick-benchmark` - Built-in small benchmark preset
- `--help`, `-h` - Show help message

Batch mode defaults to `--freq 0` (quiet) for speed; pass `--freq` to enable per-run stats.

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
