# Flare Error level (`flare_error`)

`flare_error` is the horizontal-error correction benchmark scenario for the unified `zem_zev` controller.

## Purpose

- Start from a flare-like inbound arc.
- Inject bounded projected-impact error.
- Measure whether unified guidance can recover track quality before terminal entry.

## Scenario design

Defined in [`levels/flare_error.py`](../levels/flare_error.py):

- Base entry angles: `shallower` (15deg), `shallow` (30deg), `mid` (45deg), `steep` (60deg), `steeper` (75deg)
- Radius: `[700, 900]`
- Angle deviation: `[-5deg, +5deg]`
- Target flight time: `[9.5, 12.5]`
- Error tiers:
  - `tight`: `|projected_dx_error| in [30, 55]`
  - `wide`: `|projected_dx_error| in [75, 110]`

Scenarios:

- `shallower_tight`, `shallower_wide`
- `shallow_tight`, `shallow_wide`
- `mid_tight`, `mid_wide`
- `steep_tight`, `steep_wide`
- `steeper_tight`, `steeper_wide`

Defaults:

- default scenario: `mid_tight`
- recommended benchmark subset: `shallow_tight`, `mid_wide`, `steep_wide`

## Metrics

- End-to-end objective metrics: `state`, `success`, `fuel_consumed`, `path_efficiency`
- Unified gate telemetry: `setup_gate_*`, `bot_zem_zev_terminal_gate_*`
- `setup_gate_*` is emitted at spawn as the coast-entry snapshot; there is no
  setup burn on this level.
- Coast stays passive and points retrograde until flare entry; all correction is
  deferred to the flare/terminal phase.
- Goal metadata: `eval_goal`, `eval_early_end`, `eval_end_reason`

## Commands

```bash
uv run python main.py run --interactive flare_error
uv run python main.py sim flare_error:mid_tight:0 --bot zem_zev
uv run python main.py bench \
  flare_error:shallow_tight:0-19 \
  flare_error:mid_wide:0-19 \
  flare_error:steep_wide:0-19 \
  --bot zem_zev
```
