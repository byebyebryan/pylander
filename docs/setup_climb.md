# Setup Climb level (`setup_climb`)

`setup_climb` is the uphill member of the setup-transfer trio: a pad-to-pad climb on sloped terrain without obstacles.

## Purpose

- Start landed on a source pad.
- Require takeoff, transfer, and landing on an uphill destination pad.
- Stress guidance behavior on sustained sloped terrain with large positive altitude deltas.

Guidance note:

- `pdg` handles climb with the same optimizer loop used on other levels.
- There is currently no climb-specific trajectory shaping in `pdg`; climb is
  a direct stress test of the generic setup controller.

## Scenario design

Defined in [`levels/setup_climb.py`](../levels/setup_climb.py):

- Source pad: `x=0`, terrain-bound flush pad
- Destination horizontal offset: `dx=400`
- Destination elevation tiers (`dy`): `200`, `400`, `800`
- Terrain profile:
  - destination pad is terrain-bound (`flush_flatten`) on a true uphill ramp where `slope = dy / dx`

Scenarios:

- `low`, `mid`, `high`

Defaults:

- default scenario: `mid`
- recommended benchmark subset: `low`, `mid`, `high`

## Metrics

- End-to-end objective metrics: `state`, `success`, `setup_transfer_arrived`, `setup_transfer_landed_site_uid`
- Unified gate telemetry: `setup_gate_*`, `bot_pdg_flare_entry_*`
- Goal metadata when using goal selectors: `eval_goal`, `eval_early_end`, `eval_end_reason`

Additional retained `pdg` diagnostics exported for climb tuning:

- `bot_pdg_shape_apex_error`
- `bot_pdg_shape_curve_rmse`
- `bot_pdg_shape_projected_dx_abs_mean`
- `bot_pdg_shape_projected_dx_abs_max`
- `bot_pdg_shape_shortfall_ratio`

## Commands

```bash
uv run python main.py run --interactive setup_climb
uv run python main.py sim setup_climb:mid:0 --bot pdg
uv run python main.py bench \
  setup_climb:low:0-9 \
  setup_climb:mid:0-9 \
  setup_climb:high:0-9 \
  --bot pdg
```
