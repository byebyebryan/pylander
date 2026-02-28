# Plunge phase (`plunge` level + `plunge` bot)

`plunge` is the terminal-only benchmark: burn timing, flare, and touchdown without upstream trajectory setup complexity.

## Scenario setup

Defined in [`levels/plunge.py`](../levels/plunge.py):

- Spawn centered above target (`start_x = target_x = 0`)
- Initial attitude upright (`angle = 0`)
- Flat terrain with flush target
- Target size `110`
- Cargo varies by scenario tier

## Scenarios

`plunge` is a `3 x 3` altitude x weight matrix.

- Altitude tiers:
  - `low`: `100`
  - `mid`: `400`
  - `high`: `1600`
- Weight tiers:
  - `light`: `0`
  - `normal`: `2250`
  - `heavy`: `4500`

Scenario naming: `<alt>_<weight>` (example: `mid_normal`).

Defaults:

- default scenario: `mid_normal`
- quick benchmark subset: `low_normal`, `mid_normal`, `high_normal`

## Goals and metrics

Primary goals:

- reliable landing across tiers
- decisive touchdown (no long hover, no late panic)
- reasonable fuel usage without sacrificing safety

Metrics to watch:

- Outcome: `state`, `success_rate`, `landing_offset`
- Efficiency: `fuel_consumed`, `fuel_per_distance`
- Timing: `time`, `time_to_first_land`

## Commands

```bash
uv run python main.py plunge
uv run python main.py plunge --headless --scenario mid_normal --seed 0
uv run python main.py plunge --headless --quick-benchmark
```
