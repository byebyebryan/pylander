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

### Human Mode
```bash
uv run python main.py
```

### Bot Mode
Watch an AI bot play using the sensor/action API:
```bash
# Simple bot (cautious, flies to nearest targets)
# Note: Currently has landing difficulty, use for testing/iteration
uv run python main.py turtle

# Aggressive bot (prioritizes high-value distant targets)
uv run python main.py hare
```

### Headless Mode (Testing/Training)
Run simulations without graphics for bot development:
```bash
# Run bot in headless mode (prints stats every second by default)
uv run python main.py hare --headless

# Print every frame for detailed debugging
uv run python main.py hare --headless --freq 1 --steps 300

# Print every 0.5 seconds with bot messages
uv run python main.py hare --headless --freq 30 --show-bot-msg

# Disable output for fastest execution
uv run python main.py hare --headless --freq 0 --steps 10000

# Use different seed
uv run python main.py hare --headless --seed 123
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

Bots operate on limited sensors and emit explicit actions. Extend `Bot` and implement `get_action(dt, sensors)`:

```python
from bot import Bot, SensorData, BotAction

class MyBot(Bot):
    def get_action(self, dt: float, sensors: SensorData) -> BotAction:
        # Simple idle bot example
        self.status_message = "idle"
        return BotAction(False, False, False, False, False)
```

Sensors include altitude, velocities, angle, thrust_level, fuel, credits, state, and radar contacts.

## Command Line Options

```bash
python main.py [bot_type] [options]
```

**Bot types:**
- `turtle` - Cautious bot (TurtleBot)
- `hare` - Faster/aggressive bot

**Options:**
- `--headless` - Run without graphics (requires bot)
- `--verbose`, `-v` - Print statistics during headless run
- `--steps N` - Limit simulation to N steps
- `--seed N` - Use specific random seed
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
