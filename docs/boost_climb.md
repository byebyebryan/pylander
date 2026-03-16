# Boost Climb family (`boost:climb`)

`boost:climb:*:*` is the uphill member of the boost-transfer trio: a pad-to-pad climb on sloped terrain without obstacles.

## Purpose

- Start landed on a source pad.
- Require takeoff, transfer, and landing on an uphill destination pad.
- Stress guidance behavior on sustained sloped terrain with large positive altitude deltas.

Guidance note:

- `pdg` now routes climb through the same dedicated boost controller used by
  `boost:flat` and `boost:downhill`.
- `boost:climb` is a normal benchmark/gating family, not observe-only.

## Scenario design

Defined in [`levels/boost_climb.py`](../levels/boost_climb.py):

- Source pad: `x=0`, terrain-bound flush pad
- Destination horizontal offset: `dx=400`
- Destination elevation tiers (`dy`): `200`, `400`, `800`
- Cargo tiers: `empty=0`, `half=3000`, `full=6000`
- Terrain profile:
  - destination pad is terrain-bound (`flush_flatten`) on a true uphill ramp where `slope = dy / dx`

Selector layers:

- `low:empty`, `low:half`, `low:full`
- `mid:empty`, `mid:half`, `mid:full`
- `high:empty`, `high:half`, `high:full`

Defaults:

- default scenario: `mid:half`
- recommended benchmark subset: `low:half`, `mid:half`, `high:half`

## Metrics

- End-to-end objective metrics: `state`, `success`, `transfer_arrived`, `transfer_landed_site_uid`
- Unified gate telemetry: `boost_cutoff_*`, `bot_pdg_terminal_entry_*`
- Goal metadata when using goal selectors: `eval_goal`, `eval_early_end`, `eval_end_reason`

Additional retained `pdg` diagnostics exported for climb tuning:

- `bot_pdg_shape_apex_error`
- `bot_pdg_shape_curve_rmse`
- `bot_pdg_shape_projected_dx_abs_mean`
- `bot_pdg_shape_projected_dx_abs_max`
- `bot_pdg_shape_shortfall_ratio`

## Commands

```bash
uv run python main.py run --interactive boost:climb
uv run python main.py sim boost:climb:mid:half:0 --bot pdg
uv run python main.py bench boost:climb:*:* --bot pdg
```
