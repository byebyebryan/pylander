# Setup level (`setup`)

`setup` is the pre-terminal setup benchmark for unified `zem_zev` guidance.

## Purpose

- Start far from target, upright, at rest.
- Force trajectory establishment from a cold state.
- Measure whether the controller reaches a strong setup gate before coast/terminal progression.

Goal-based eval option: run with selector goal `setup` (for example `setup:mid_near:setup:0`) to stop when `zem_setup_gate_done` latches.

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
- recommended benchmark subset: `shallow_near`, `mid_far`, `steep_far`

## Metrics

- `eval_goal`, `eval_early_end`, `eval_end_reason`
- `setup_goal_time`, `setup_goal_fuel_consumed`, `setup_goal_projected_dx`, `setup_goal_time_to_target`
- `zem_setup_gate_done`, `zem_setup_gate_time`, `zem_setup_gate_altitude`, `zem_setup_gate_projected_dx`
- `zem_shape_*` diagnostics for setup-trajectory quality

Common `zem_zev` setup-shape tuning knobs for this level:

- setup gate burn-end latch: `setup_gate_burn_start_thrust`, `setup_gate_idle_thrust_max`, `setup_gate_burn_end_settle_s`
- setup burn taper/cut: `setup_burn_taper_*`, `setup_burn_cut_overshoot_*`
- setup centering tolerance: `setup_center_tol_ratio`
- setup apex shaping: `setup_apex_height_*`, `setup_apex_ref_blend`

## Commands

```bash
uv run python main.py run --interactive setup
uv run python main.py sim setup:mid_near:0 --bot zem_zev
uv run python main.py sim setup:mid_near:setup:0 --bot zem_zev
uv run python main.py bench \
  setup:shallow_near:0-9 \
  setup:mid_far:0-9 \
  setup:steep_far:0-9 \
  --bot zem_zev
```
