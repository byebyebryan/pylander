# Plunge phase (`plunge` level + `plunge` bot)

`plunge` is the "get the last 10 seconds right" sandbox: vertical-first terminal burn timing, flare, and touchdown discipline without worrying about upstream setup/handoffs.

## Scenario setup

Defined in [`levels/plunge.py`](../levels/plunge.py):

- Spawn is centered above the target: `start_x = target_x = 0`
- Terrain: flat, with a flush/flatten target
- Target size: `110`
- Cargo mass varies by scenario tier

## Scenarios

`plunge` is a 3x3 **altitude x weight** matrix.

- Altitude tiers (spawn clearance):
  - `low`: `100`
  - `mid`: `400`
  - `high`: `1600`
- Weight tiers (cargo mass):
  - `light`: `0`
  - `normal`: `2250`
  - `heavy`: `4500`
- Scenario naming: `<alt>_<weight>` (example: `mid_normal`)

All scenarios:

- `low_light`, `low_normal`, `low_heavy`
- `mid_light`, `mid_normal`, `mid_heavy`
- `high_light`, `high_normal`, `high_heavy`

Defaults (also in [`levels/plunge.py`](../levels/plunge.py)):

- Default scenario: `mid_normal`
- Quick benchmark subset: `low_normal`, `mid_normal`, `high_normal`

## Goals and metrics

Primary goals:

- Reliable landing across tiers
- Decisive touchdown (no long hover, no late panic)
- Reasonable fuel usage without trading away safety

Useful metrics to watch (batch summaries come from [`core/eval.py`](../core/eval.py)):

- Outcome: `state`, `success_rate`, `landing_offset`
- Efficiency: `fuel_consumed`, `fuel_per_distance`
- Timing: `time`, `time_to_first_land`

`path_efficiency` exists, but `plunge` is intentionally "boring" horizontally, so it's usually not the main signal here.

## Current bot strategy (what it's doing today)

`PlungeBot` ([`bots/plunge.py`](../bots/plunge.py)) is now a concrete balanced-only bot.

Control loop:

- Pick the first radar target (eval levels currently expose a single target).
- Estimate projected lateral error + time-to-impact (sensor when available, analytic fallback).
- Run a simple terminal state flow:
  - `coast`: free-fall while burn is not required yet.
  - `burn`: start landing burn before the stop window closes.
  - `flare`: drive descent toward `vy ~= 0` as altitude approaches zero.
  - `touchdown`: cut engine when low altitude and low velocity tolerances are met.
- Allocate thrust + angle with rate limits and low-altitude safety caps.

Shared reusable bot libs are split by concern:

- [`bots/_ballistics.py`](../bots/_ballistics.py)
- [`bots/_targeting.py`](../bots/_targeting.py)
- [`bots/_coast_core.py`](../bots/_coast_core.py)
- [`bots/_drop_control.py`](../bots/_drop_control.py)
- [`bots/_bot_math.py`](../bots/_bot_math.py)

## How to run it

Interactive:

```bash
uv run python main.py plunge
```

Headless (single run):

```bash
uv run python main.py plunge --headless --scenario mid_normal --seed 0
```

Quick regression pass:

```bash
uv run python main.py plunge --headless --quick-benchmark
```

## Current "promotion gate" (manual)

From the old README checklist, kept here because it's a useful habit:

```bash
uv run python main.py plunge --headless --batch \
  --batch-seeds 0-9 \
  --batch-scenarios low_normal,mid_normal,high_normal
```

