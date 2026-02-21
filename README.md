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
# Cautious bot (flies to nearest targets)
uv run python main.py level_1 turtle

# Hare / Magpie (same behavior as turtle for now)
uv run python main.py level_1 hare
uv run python main.py level_1 magpie
```

### Headless Mode (Testing/Training)
Run simulations without graphics for bot development:
```bash
# Run bot in headless mode (prints stats every second by default)
uv run python main.py level_1 hare --headless

# Print every frame for detailed debugging
uv run python main.py level_1 hare --headless --freq 1 --steps 300

# Print every 0.5 seconds
uv run python main.py level_1 hare --headless --freq 30

# Disable output for fastest execution
uv run python main.py level_1 hare --headless --freq 0 --steps 10000

# Use different seed or lander
uv run python main.py level_1 hare --headless --seed 123
uv run python main.py level_1 --lander differential
```

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

`PassiveSensors` includes altitude, velocities, angle, thrust_level, fuel, state, and radar/proximity contacts. `ActiveSensors` provides e.g. `raycast(angle, max_range)`.

## Command Line Options

```bash
python main.py <level_name> [bot_name] [options]
```

**Levels:** Run `python main.py --help` to list (e.g. `level_1`).

**Bot names:** `turtle`, `hare`, `magpie` (see `--help`).

**Options:**
- `--headless` - Run without graphics (requires bot)
- `--freq N` - Print stats every N frames (60 ≈ 1/s; 0 = off)
- `--steps N` - Limit simulation to N steps (headless)
- `--time S` - Limit simulation to S seconds (headless, default 300)
- `--plot none|speed|thrust|all` - Save trajectory plot (headless)
- `--stop-on-crash`, `--stop-on-out-of-fuel`, `--stop-on-first-land` - End conditions
- `--seed N` - Random seed
- `--lander NAME` - Lander variant (classic, differential, simple)
- `--help`, `-h` - Show help message

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
