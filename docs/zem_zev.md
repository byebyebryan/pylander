# ZEM/ZEV Optimizer Bot (`zem_zev`)

Implementation: [`bots/zem_zev.py`](../bots/zem_zev.py), [`bots/_optimizer_pdg.py`](../bots/_optimizer_pdg.py)

`zem_zev` is the unified optimizer-first full-envelope guidance bot used by default in `launch`, `setup`, `coast`, and `flare`.

## Naming

Both names appear in literature:

- `ZEM/ZEV` (Zero-Effort-Miss / Zero-Effort-Velocity)
- `ZEV/ZEM` (same terms reversed)

This repo uses `zem_zev` for consistency with bot naming.

## Guidance model

At each replan, the bot solves a finite-horizon convex optimization in acceleration space.

State:

- `x, y, vx, vy` (`vy` positive up)

Controls:

- `ax, ay` (thrust acceleration components)

Discrete dynamics:

- `x[k+1] = x[k] + vx[k] * dt + 0.5 * ax[k] * dt^2`
- `y[k+1] = y[k] + vy[k] * dt + 0.5 * (ay[k] - g) * dt^2`
- `vx[k+1] = vx[k] + ax[k] * dt`
- `vy[k+1] = vy[k] + (ay[k] - g) * dt`

## Constraints

- `ay >= 0`
- `sqrt(ax^2 + ay^2) <= a_max`
- nominal-first envelope with OD slack reserve
- tilt cone: `|ax| <= tan(max_tilt) * ay`
- soft terrain floor guard

## Objective

Cost combines:

- terminal state accuracy (`x/y/vx/vy`)
- effort and smoothness penalties
- path shaping references
- fuel proxy (`thrust_norm`)
- OD slack penalties
- descent-floor and anti-upward-motion penalties

## Nominal-first braking schedule

Vertical targets are derived from a braking envelope using nominal thrust authority (`a_nom`), so OD is reserve by design.

This is why optimization is solved against nominal limits first and only uses OD when needed for robustness.

## Runtime loop

Each frame:

1. update phase tracking (`setup`, `coast`, `terminal`, `touchdown`),
2. replan on schedule or state-deviation trigger,
3. track plan between replans,
4. allocate acceleration to thrust+angle with tilt/rate limits,
5. fallback only when optimizer result is infeasible.

## Telemetry fields

`zem_zev` publishes:

- `zem_setup_gate_done`, `zem_setup_gate_time`, `zem_setup_gate_altitude`, `zem_setup_gate_projected_dx`
- `zem_terminal_gate_done`, `zem_terminal_gate_time`, `zem_terminal_gate_altitude`, `zem_terminal_gate_projected_dx`
- `zem_solve_count`, `zem_solve_ms_mean`, `zem_solve_ms_p90`, `zem_fallback_frames`

Focused eval boundaries:

- `setup --eval-mode focused` -> `zem_setup_gate_done`
- `coast --eval-mode focused` -> `zem_terminal_gate_done`

## Compute cost

Solver load is controlled with phase-adaptive replanning:

- setup: lower replan rate, looser deviation thresholds
- coast: medium replan rate
- terminal: higher replan rate, tighter deviation thresholds

Use `--batch-workers` for throughput when running large benchmark suites.
