# Climb level (`climb`)

`climb` is a launch-like synthetic scenario for uphill pad transfers on sloped terrain without obstacles.

## Purpose

- Start landed on a source pad.
- Require takeoff, transfer, and landing on an uphill destination pad.
- Stress guidance behavior on sustained sloped terrain with large positive altitude deltas.

Guidance note:

- `zem_zev` handles climb with the same optimizer loop used on other levels.
- There is currently no climb-specific trajectory shaping in `zem_zev`; climb is
  a direct stress test of the generic setup controller.

## Scenario design

Defined in [`levels/climb.py`](../levels/climb.py):

- Source pad: `x=0`, flush terrain
- Destination horizontal offset: `dx=400`
- Destination elevation tiers (`dy`): `200`, `400`, `800`
- Terrain profile:
  - `slope_*`: destination is terrain-bound (`flush_flatten`) on a true uphill ramp
    where `slope = dy / dx`

Scenarios:

- `slope_low`, `slope_mid`, `slope_high`

Defaults:

- default scenario: `slope_mid`
- recommended benchmark subset: `slope_low`, `slope_mid`, `slope_high`

## Metrics

- End-to-end objective metrics: `state`, `success`, `climb_arrived`, `climb_landed_site_uid`
- Unified gate telemetry: `zem_setup_gate_*`, `zem_terminal_gate_*`
- Goal metadata when using goal selectors: `eval_goal`, `eval_early_end`, `eval_end_reason`

Additional `zem_zev` diagnostics exported for climb tuning:

- `zem_peak_alt_over_target`
- `zem_lateral_overshoot`
- `zem_hover_time`
- `zem_clearance_margin`
- `zem_clearance_scale`
- `zem_clearance_active`

`zem_clearance_*` fields are retained for compatibility and are expected to be
inactive (`0`/`False`) in the current generic-baseline configuration.

## Commands

```bash
uv run python main.py run --interactive climb
uv run python main.py sim climb:slope_mid:0 --bot zem_zev
uv run python main.py bench \
  climb:slope_low:0-9 \
  climb:slope_mid:0-9 \
  climb:slope_high:0-9 \
  --bot zem_zev
```
