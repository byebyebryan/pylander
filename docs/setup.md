# Setup level (`setup`)

`setup` is the pre-terminal setup benchmark for unified `zem_zev` guidance.

## Purpose

- Start far from target, upright, at rest.
- Force trajectory establishment from a cold state.
- Measure whether the controller reaches a strong setup gate before coast/terminal progression.

Focused evaluation for this level ends at `zem_setup_gate_done`.

Trajectory-shape diagnostics are also exported through `zem_shape_*` fields to
quantify setup ballistic quality (apex target/actual, curve RMSE, projected-dx
mean/max, shortfall ratio).

## Scenario design

Defined in [`levels/setup.py`](../levels/setup.py):

- Base entry angles: `shallower` (15deg), `shallow` (30deg), `mid` (45deg), `steep` (60deg), `steeper` (75deg)
- Radius tiers:
  - `near`: `[620, 780]`
  - `far`: `[860, 1050]`
- Angle deviation: `[-5deg, +5deg]`
- Initial state: upright, `vx=0`, `vy_up=0`

Scenarios:

- `shallower_near`, `shallower_far`
- `shallow_near`, `shallow_far`
- `mid_near`, `mid_far`
- `steep_near`, `steep_far`
- `steeper_near`, `steeper_far`

Defaults:

- default scenario: `mid_near`
- quick benchmark subset: `shallow_near`, `mid_far`, `steep_far`

## Focused metrics

- `setup_phase_done`
- `setup_phase_time`
- `setup_phase_altitude`
- `setup_phase_projected_dx`
- `setup_phase_distance`
- `setup_phase_fuel_consumed`
- `setup_phase_fuel_per_distance`
- `setup_phase_path_efficiency`

Common `zem_zev` setup-shape tuning knobs for this level:

- setup gate burn-end latch: `setup_gate_burn_start_thrust`, `setup_gate_idle_thrust_max`, `setup_gate_burn_end_settle_s`
- setup burn taper/cut: `setup_burn_taper_*`, `setup_burn_cut_overshoot_*`
- setup centering tolerance: `setup_center_tol_ratio`
- setup apex shaping: `setup_apex_height_*`, `setup_apex_ref_blend`

## Commands

```bash
uv run python main.py play setup
uv run python main.py bench setup --quick --bot zem_zev
uv run python main.py bench setup --bot zem_zev --scenarios shallow_near,mid_far,steep_far
```
