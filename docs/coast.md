# Coast level (`coast`)

`coast` is the horizontal-error correction benchmark scenario for the unified `zem_zev` controller.

## Purpose

- Start from a flare-like inbound arc.
- Inject bounded projected-impact error.
- Measure whether unified guidance can recover track quality before terminal entry.

Focused evaluation for this level ends at `zem_terminal_gate_done`.

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
- quick benchmark subset: `shallow_tight`, `mid_wide`, `steep_wide`

## Focused metrics

- `coast_phase_done`
- `coast_phase_time`
- `coast_phase_altitude`
- `coast_phase_projected_dx`
- `coast_phase_distance`
- `coast_phase_fuel_consumed`
- `coast_phase_fuel_per_distance`
- `coast_phase_path_efficiency`

## Commands

```bash
uv run python main.py coast
uv run python main.py coast --headless --quick-benchmark
uv run python main.py coast --headless --batch --batch-scenarios shallow_tight,mid_wide,steep_wide
```
