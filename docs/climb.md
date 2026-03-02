# Climb level (`climb`)

`climb` is a launch-like synthetic scenario for uphill/elevated pad transfers without obstacles.

## Purpose

- Start landed on a source pad.
- Require takeoff, transfer, and landing on an elevated destination pad.
- Stress guidance behavior when terrain/surface cues differ between flat and sloped ground.

Focused evaluation for this level ends at `zem_setup_gate_done`.

## Scenario design

Defined in [`levels/climb.py`](../levels/climb.py):

- Source pad: `x=0`, flush terrain
- Destination horizontal offset: `dx=400`
- Destination elevation tiers (`dy`): `200`, `400`, `800`
- Terrain profiles:
  - `flat_*`: destination uses elevated supports (`target y_offset = dy`)
  - `slope_*`: destination is terrain-bound (`flush_flatten`) on a true uphill ramp
    where `slope = dy / dx`

Scenarios:

- `flat_low`, `flat_mid`, `flat_high`
- `slope_low`, `slope_mid`, `slope_high`

Defaults:

- default scenario: `flat_mid`
- quick benchmark subset: `flat_mid`, `slope_mid`, `slope_high`

## Focused metrics

- `climb_phase_done`
- `climb_phase_time`
- `climb_phase_altitude`
- `climb_phase_projected_dx`
- `climb_phase_distance`
- `climb_phase_fuel_consumed`
- `climb_phase_fuel_per_distance`
- `climb_phase_path_efficiency`

## Commands

```bash
uv run python main.py play climb
uv run python main.py bench climb --quick --bot zem_zev
uv run python main.py bench climb --bot zem_zev --scenarios flat_mid,slope_mid,slope_high
```
