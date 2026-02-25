# Pylander

A classic Lunar Lander-inspired game with procedurally generated terrain, scoring system, and AI bot support.

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
uv run python main.py plunge --scenario alt_400

# Terminal flare benchmark level + bot
uv run python main.py flare

# Pick a specific flare scenario
uv run python main.py flare --scenario shallow_fast_centered

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

### Headless Mode (Testing/Training)
Run simulations without graphics for bot development:
```bash
# Run bot in headless mode (prints stats every second by default)
uv run python main.py plunge --headless

# Print every frame for detailed debugging
uv run python main.py plunge --headless --freq 1 --steps 300

# Print every 0.5 seconds
uv run python main.py plunge --headless --freq 30

# Disable output for fastest execution
uv run python main.py plunge --headless --freq 0 --steps 10000

# Use different seed or lander
uv run python main.py plunge --headless --seed 123
uv run python main.py plunge --headless --scenario speed_high --seed 123
uv run python main.py flare --headless --scenario shallow_fast_centered --seed 123
uv run python main.py coast --headless --scenario flat_correction --seed 123
uv run python main.py launch --headless --scenario air_mid_reverse --seed 123
uv run python main.py launch --headless --scenario air_mid_reverse --eval-mode full --seed 123
uv run python main.py flat --lander differential
```

Batch evaluation (headless, sequential single-bot runs):
```bash
# Fast cross-level benchmark (39 runs = 3 seeds x 13 core scenarios)
uv run python main.py plunge --headless --quick-benchmark

# Scenario-specific batch using level default bot
uv run python main.py plunge --headless --batch \
  --batch-seeds 0-19 \
  --batch-json auto \
  --batch-csv auto

# Explicit batch list
uv run python main.py plunge --headless --batch \
  --batch-seeds 0-19 \
  --batch-levels plunge \
  --batch-scenarios alt_400,speed_high \
  --batch-json auto \
  --batch-csv auto

# Coast-focused horizontal-control batch
uv run python main.py coast --headless --batch \
  --batch-seeds 0-19 \
  --batch-scenarios glide_mid,glide_long_stress_correction \
  --batch-json auto \
  --batch-csv auto
```

By default, generated artifacts (batch JSON/CSV and trajectory plots) are written under `outputs/`.

`--quick-benchmark` runs a fixed core suite:
- `plunge`: `alt_400`, `speed_high`, `upward_low`
- `flare`: `shallow_fast_centered`, `steep_offset_centered`, `handoff_high_speed`
- `coast`: `glide_mid`, `glide_long_stress_correction`, `handoff_extreme`
- `launch`: `air_mid`, `air_long`, `air_mid_reverse`, `air_long_heavy`

Use `--batch-scenarios` when you want a narrower or custom scenario slice.
When comparing benchmark runs, keep `--eval-mode` fixed (focused vs full are different goals).

Suggested phase-first eval workflow:
- Tune launch setup in focused mode (`--eval-mode focused`) using handoff metrics.
- Tune coast correction/handoff in focused mode (`--eval-mode focused`) with `coast_handoff_*` metrics.
- Tune terminal burn timing and final control on plunge/flare scenarios.
- Validate full launch completion in full mode (`--eval-mode full`).

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
- **T**: Toggle ballistic trajectory overlay
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
`ActiveSensors` provides `raycast(angle, max_range)`, terrain helpers like `terrain_height(x)` and `terrain_profile(x_start, x_end, samples)`, and `ballistic_trajectory(x, y, vx, vy_up, ...)` for engine-off path prediction to terrain/max distance, including hit point/time plus impact velocity (`hit_vx`, `hit_vy_up`) and speed (`hit_speed`) when a terrain impact is found.

## Scenario Levels

Dedicated scenario levels (default bot in parentheses):
- `plunge` (`plunge`) - vertical-only benchmark focused on coast->terminal burn timing and decisive touchdown:
  - `alt_100`
  - `alt_400`
  - `alt_1600`
  - `speed_low`
  - `speed_high`
  - `upward_low`
  - cargo variants for `alt_400`, `speed_high`, and `upward_low`:
    - `*_cargo_low`
    - `*_cargo_high`
- `flare` (`flare`) - terminal 2-axis landing benchmark from near-ballistic entry:
  - `shallow_fast_undershoot`
  - `shallow_fast_centered`
  - `shallow_fast_overshoot`
  - `steep_offset_undershoot`
  - `steep_offset_centered`
  - `steep_offset_overshoot`
  - `handoff_high_speed`
- `coast` (`coast`) - correction-focused horizontal-control benchmark:
  - base scenarios span two dimensions:
    - ballistic profile (`glide_short|mid|long|flat`) -> `flat` includes a mild positive initial vertical speed to validate upward-pointing ballistic starts
    - trajectory error (no suffix vs `_correction` vs `_stress_correction`) -> correction tiers inject seeded random bias direction, so runs need re-centering work in either direction
  - scenario names:
    - `glide_short`
    - `glide_short_correction`
    - `glide_mid`
    - `glide_mid_correction`
    - `glide_long`
    - `glide_long_correction`
    - `glide_long_stress_correction`
    - `flat`
    - `flat_correction`
    - `flat_stress_correction`
    - `handoff_extreme`
    - `handoff_extreme_fast`
      - explicit launch-handoff mirrors for high horizontal-speed terminal tuning
  - targeted heavy-cargo variants (`*_cargo_high`) exist only for:
    - `glide_mid_correction`
    - `glide_long_correction`
    - `glide_long_stress_correction`
- `launch` (`launch`) - air-start trajectory-establishment benchmark with coast handoff:
  - base scenarios are proportional profile steps:
    - `air_mid`: medium offset with medium clearance
    - `air_long`: longer offset with proportionally higher clearance
  - default eval mode is **full**: run continues through coast/terminal to landing/crash
  - use `--eval-mode focused` for launch-only handoff evaluation
  - launch setup emphasizes a hard side-burn to establish a ballistic path early, then hands off to coast/terminal phases
  - stress variants:
    - opposite horizontal speed with extra room: `air_mid_reverse`
  - heavy-cargo variants (`*_heavy`) exist for:
    - `air_long`
    - `air_mid_reverse`
## Command Line Options

```bash
uv run python main.py [level_name] [options]
```

**Levels:** Run `uv run python main.py --help` to list (e.g. `flat`, `mountains`, `plunge`).

**Bot names:** `plunge`, `flare`, `coast`, `launch` (set via `--bot`; see `--help`).

**Options:**
- `--bot NAME` - Select bot (`plunge`, `flare`, `coast`, `launch`)
- `--bot-behavior NAME` - Behavior profile for bots that support it (examples: `plunge` => `balanced|speed|econ`; `flare` => `flare`; `coast` => `coast`; `launch` => `launch`)
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

Current checks (manual gate until automated):
- Home scenario success rate >= 95% on seeds `0-9`
- No `out_of_fuel` failures on seeds `0-9`
- Suggested command:
  - `uv run python main.py plunge --headless --batch --batch-seeds 0-9 --batch-scenarios alt_400,speed_high,upward_low`

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
