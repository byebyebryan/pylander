# Boost Downhill level (`boost_downhill`)

`boost_downhill` is the downhill member of the boost-transfer trio for unified `pdg` guidance.

## Purpose

- Start landed on a source pad.
- Force a sustained boost burn that establishes a downhill ballistic transfer to the destination pad.
- Measure whether the controller reaches a strong boost cutoff before coast/terminal progression.

Goal-based eval option: run with selector goal `boost` (for example `boost_downhill:mid_half:boost:0`) to stop when `boost_cutoff_done` latches.

Trajectory-shape diagnostics are also exported through the retained
`bot_pdg_shape_*` fields to quantify boost ballistic quality.

## Scenario design

Defined in [`levels/boost_downhill.py`](../levels/boost_downhill.py):

- Source pad: `x=0`, terrain-bound flush pad
- Destination horizontal offset: `dx=400`
- Destination elevation tiers (`dy`): `-200`, `-400`, `-800`
- Cargo tiers: `empty=0`, `half=3000`, `full=6000`
- Terrain profile: true downhill ramp where `slope = dy / dx`
- Initial state: landed upright on the source pad

Scenarios:

- `low_empty`, `low_half`, `low_full`
- `mid_empty`, `mid_half`, `mid_full`
- `high_empty`, `high_half`, `high_full`

Defaults:

- default scenario: `mid_half`
- recommended benchmark subset: `low_half`, `mid_half`, `high_half`

## Metrics

- `eval_goal`, `eval_early_end`, `eval_end_reason`
- `boost_goal_time`, `boost_goal_projected_dx`, `boost_goal_projected_impact_angle_deg`
- `boost_cutoff_done`, `boost_cutoff_time`, `boost_cutoff_altitude`, `boost_cutoff_projected_dx`
- `transfer_source_site_uid`, `transfer_target_site_uid`, `transfer_landed_site_uid`, `transfer_arrived`
- `bot_pdg_shape_*` diagnostics for boost-trajectory quality

Common `pdg` boost-shape tuning knobs for this level:

- boost cutoff burn-end latch: `boost_cutoff_burn_start_thrust`, `boost_cutoff_idle_thrust_max`, `boost_cutoff_burn_end_settle_s`
- boost burn decisiveness: `boost_active_thrust_floor`, `boost_late_thrust_weight`
- boost centering tolerance: `boost_center_tol_ratio`
- boost apex shaping: `boost_apex_height_*`, `boost_cutoff_apex_tol_*`
- boost descent corridor: `boost_descent_angle_deg_*`

## Commands

```bash
uv run python main.py run --interactive boost_downhill
uv run python main.py sim boost_downhill:mid_half:0 --bot pdg
uv run python main.py sim boost_downhill:mid_half:boost:0 --bot pdg
uv run python main.py bench boost_downhill --bot pdg
```
