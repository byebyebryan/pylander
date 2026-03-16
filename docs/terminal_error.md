# Terminal Error family (`terminal:error`)

`terminal:error:*:*` is the horizontal-error correction benchmark scenario family for the unified `pdg` controller.

## Purpose

- Start from a terminal-like inbound arc.
- Inject bounded projected-impact error.
- Measure whether unified guidance can recover track quality before terminal entry.

## Scenario design

Defined in [`levels/terminal_error.py`](../levels/terminal_error.py):

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
- Unified gate telemetry: `boost_cutoff_*`, `bot_pdg_terminal_entry_*`
- `boost_cutoff_*` is emitted at spawn as the coast-entry snapshot; there is no
  boost burn on this level.
- Coast stays passive and points retrograde until terminal entry; all correction is
  deferred to the terminal phase.
- Terminal entry uses the same analytic readiness check as `terminal:normal:*`, with a
  conservative latest-safe fallback so wide-error cases still ignite even when
  ballistic `projected_dx` remains large during coast.
- Goal metadata: `eval_goal`, `eval_early_end`, `eval_end_reason`

## Commands

```bash
uv run python main.py run --interactive terminal:error
uv run python main.py sim terminal:error:mid:tight:0 --bot pdg
uv run python main.py bench \
  terminal:error:shallow:tight:0-19 \
  terminal:error:mid:wide:0-19 \
  terminal:error:steep:wide:0-19 \
  --bot pdg
```
