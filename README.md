# Pylander

A classic Lunar Lander-inspired game with procedurally generated terrain, scoring system, and AI bot support.

## Features

- Procedural terrain generation with simplex noise
- Physics-based lander with fuel management
- Credits-based landing targets (distance from start)
- Refueling system (exchange credits for fuel)
- Continuous gameplay (land, refuel, take off again)
- AI bot interface for autonomous play
- Scenario-first specialist bots (`drop`, `plunge`, `drift`, `ferry`)

## Setup

```bash
uv sync
```

## Running

Default level is `level_flat` when omitted. List all levels with `--help`.

### Human Mode
```bash
uv run python main.py
```

### Bot Mode
Watch an AI bot play using the sensor/action API:
```bash
# Vertical descent specialist
uv run python main.py level_drop

# Horizontal transfer specialist
uv run python main.py level_drift

# Legacy baseline bot (kept for comparison during migration)
uv run python main.py level_flat turtle
```

### Headless Mode (Testing/Training)
Run simulations without graphics for bot development:
```bash
# Run bot in headless mode (prints stats every second by default)
uv run python main.py level_drop --headless

# Print every frame for detailed debugging
uv run python main.py level_drift --headless --freq 1 --steps 300

# Print every 0.5 seconds
uv run python main.py level_plunge --headless --freq 30

# Disable output for fastest execution
uv run python main.py level_ferry --headless --freq 0 --steps 10000

# Use different seed or lander
uv run python main.py level_drop --headless --seed 123
uv run python main.py level_flat --lander differential
```

Batch evaluation (headless, sequential single-bot runs):
```bash
# Fast preset benchmark (3 seeds x wave-1 levels)
uv run python main.py level_drop --headless --quick-benchmark

# Scenario-specific batch using level default bot
uv run python main.py level_ferry --headless --batch \
  --batch-seeds 0-19 \
  --batch-json auto \
  --batch-csv auto

# Full wave-1 matrix using explicit level suite
uv run python main.py level_drop --headless --batch \
  --batch-seeds 0-19 \
  --batch-levels level_drop,level_plunge,level_drift,level_ferry \
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

## Scenario Levels

Dedicated scenario levels (default bot in parentheses):
- `level_drop` (`drop`) - vertical descent
- `level_plunge` (`plunge`) - greater vertical distance
- `level_drift` (`drift`) - horizontal travel then descent
- `level_ferry` (`ferry`) - long horizontal transfer then descent
- `level_climb` (`drift`) - climb to elevated target
- `level_obstacles` (`ferry`) - complex terrain with vertical features

## Command Line Options

```bash
python main.py [level_name] [bot_name] [options]
```

**Levels:** Run `python main.py --help` to list (e.g. `level_flat`, `level_mountains`, `level_drop`).

**Bot names:** `drop`, `plunge`, `drift`, `ferry`, `turtle` (see `--help`).

**Options:**
- `--headless` - Run without graphics (requires bot)
- `--freq N` - Print stats every N frames (60 ≈ 1/s; 0 = off)
- `--steps N` - Limit simulation to N steps (headless)
- `--time S` - Limit simulation to S seconds (headless, default 300)
- `--plot none|speed|thrust|all` - Save trajectory plot (headless)
- `--stop-on-crash`, `--stop-on-out-of-fuel`, `--stop-on-first-land` - End conditions
- `--seed N` - Random seed
- `--lander NAME` - Lander variant (classic, differential, simple)
- `--batch` - Enable batch runs (requires `--headless` + bot)
- `--batch-seeds SPEC` - Seeds like `0-19` or `0,1,2,5`
- `--batch-levels CSV` - Level names for batch suites
- `--batch-json PATH|auto` - Write JSON report
- `--batch-csv PATH|auto` - Write CSV rows
- `--batch-workers N` - Parallel worker processes for batch runs (`1` = sequential; effective workers are capped by CPU count and run count)
- `--quick-benchmark` - Built-in small benchmark preset
- `--help`, `-h` - Show help message

Batch mode defaults to `--freq 0` (quiet) for speed; pass `--freq` to enable per-run stats.
Quiet mode disables per-step stats output, but batch progress lines still print.

## Promotion Gates (Specialist Bots)

Current wave-1 promotion checks:
- Home scenario success rate >= 95% on seeds `0-9`
- No `out_of_fuel` failures on seeds `0-9`
- No regression vs `turtle` baseline on home scenario success rate

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
