# Setup Downhill level (`setup_downhill`)

`setup_downhill` is the downhill member of the setup-transfer trio for unified `pdg` guidance.

## Purpose

- Start landed on a source pad.
- Force a sustained setup burn that establishes a downhill ballistic transfer to the destination pad.
- Measure whether the controller reaches a strong setup gate before coast/flare progression.

Goal-based eval option: run with selector goal `setup` (for example `setup_downhill:mid:setup:0`) to stop when `setup_gate_done` latches.

Trajectory-shape diagnostics are also exported through the retained
`bot_pdg_shape_*` fields to quantify setup ballistic quality.

## Scenario design

Defined in [`levels/setup_downhill.py`](../levels/setup_downhill.py):

- Source pad: `x=0`, terrain-bound flush pad
- Destination horizontal offset: `dx=400`
- Destination elevation tiers (`dy`): `-200`, `-400`, `-800`
- Terrain profile: true downhill ramp where `slope = dy / dx`
- Initial state: landed upright on the source pad

Scenarios:

- `low`, `mid`, `high`

Defaults:

- default scenario: `mid`
- recommended benchmark subset: `low`, `mid`, `high`

## Metrics

- `eval_goal`, `eval_early_end`, `eval_end_reason`
- `setup_goal_time`, `setup_goal_projected_dx`, `setup_goal_projected_impact_angle_deg`
- `setup_gate_done`, `setup_gate_time`, `setup_gate_altitude`, `setup_gate_projected_dx`
- `setup_transfer_source_site_uid`, `setup_transfer_target_site_uid`, `setup_transfer_landed_site_uid`, `setup_transfer_arrived`
- `bot_pdg_shape_*` diagnostics for setup-trajectory quality

Common `pdg` setup-shape tuning knobs for this level:

- setup gate burn-end latch: `setup_gate_burn_start_thrust`, `setup_gate_idle_thrust_max`, `setup_gate_burn_end_settle_s`
- setup burn taper/cut: `setup_burn_taper_*`, `setup_burn_cut_overshoot_*`
- setup centering tolerance: `setup_center_tol_ratio`
- setup apex shaping: `setup_apex_height_*`, `setup_apex_ref_blend`

## Commands

```bash
uv run python main.py run --interactive setup_downhill
uv run python main.py sim setup_downhill:mid:0 --bot pdg
uv run python main.py sim setup_downhill:mid:setup:0 --bot pdg
uv run python main.py bench \
  setup_downhill:low:0-9 \
  setup_downhill:mid:0-9 \
  setup_downhill:high:0-9 \
  --bot pdg
```
