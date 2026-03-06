# Coast level (`coast`)

`coast` is the horizontal-error correction benchmark scenario for the unified `zem_zev` controller.

## Purpose

- Start from a flare-like inbound arc.
- Inject bounded projected-impact error.
- Measure whether unified guidance can recover track quality before terminal entry.

## Scenario design

Defined in [`levels/coast.py`](../levels/coast.py):

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
- Goal metadata when using goal selectors: `eval_goal`, `eval_early_end`, `eval_end_reason`

## Commands

```bash
uv run python main.py run --interactive coast
uv run python main.py sim coast:mid_tight:0 --bot zem_zev
uv run python main.py bench \
  coast:shallow_tight:0-19 \
  coast:mid_wide:0-19 \
  coast:steep_wide:0-19 \
  --bot zem_zev
```
