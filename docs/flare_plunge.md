# Flare Plunge phase (`flare_plunge` level + `plunge` bot)

`plunge` is the terminal-only benchmark: burn timing, flare, and touchdown without upstream trajectory setup complexity.

Implementation note:

- `plunge` uses the `Bot.update(dt, sensors)` API.
- Planning math uses analytic ballistic projection to target geometry (target x/y/size), without terrain-impact sensor queries.
- Terrain-impact ballistic prediction is reserved for rendering overlays, not bot decision-making.

## Scenario setup

Defined in [`levels/flare_plunge.py`](../levels/flare_plunge.py):

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
- recommended benchmark subset: `low_normal`, `mid_normal`, `high_normal`
- level default bot: `zem_zev`

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
uv run python main.py run --interactive flare_plunge
uv run python main.py sim flare_plunge:mid_normal:0 --bot plunge
uv run python main.py bench \
  flare_plunge:low_normal:0-9 \
  flare_plunge:mid_normal:0-9 \
  flare_plunge:high_normal:0-9 \
  --bot plunge
```
