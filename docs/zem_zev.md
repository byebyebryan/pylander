# ZEM/ZEV Optimizer Bot (`zem_zev`)

Implementation: [`bots/zem_zev.py`](../bots/zem_zev.py), [`bots/_optimizer_pdg.py`](../bots/_optimizer_pdg.py)

`zem_zev` is the unified optimizer-first full-envelope guidance bot used by default in `launch`, `setup`, `coast`, `climb`, and `flare`.

Implementation note:

- `zem_zev` uses the `QueryBot` `plan/act` API.
- Phase tracking consumes a batched ballistic projection query result each tick.
- Optimizer/replan/control allocation behavior is unchanged; only active-sensor integration moved to explicit queries.

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

`g` is parameterized from runtime gravity (`core.config.GRAVITY` magnitude), not hardcoded.

## Constraints

- `ay >= 0`
- `sqrt(ax^2 + ay^2) <= a_max`
- nominal-first envelope with OD slack reserve
- tilt cone: `|ax| <= tan(max_tilt) * ay`
- soft terrain floor guard with dynamic floor (`min(current_y, target_y) - margin`)

## Objective

Cost combines:

- terminal state accuracy (`x/y/vx/vy`)
- effort and smoothness penalties
- path shaping references
- fuel proxy (`thrust_norm`)
- OD slack penalties
- descent-floor and anti-upward-motion penalties

Terminal x-error is deadbanded by pad half-width (corridor): inside-pad centering is lightly penalized compared to outside-pad miss.

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

For uphill transfers, setup planning currently remains generic:

- there is currently no climb-specific trajectory shaping;
- climb behavior reflects the same generic setup/coast/terminal loop used on
  other levels.

Reference path shaping uses an altitude-adaptive two-phase profile:

- high altitude: lateral correction first with shallow y-ref progression,
- later horizon: stronger descent toward target y.

Throttle allocation includes simple on/off hysteresis to reduce min-throttle chatter near cutoff.

## Telemetry fields

`zem_zev` publishes:

- `zem_setup_gate_done`, `zem_setup_gate_time`, `zem_setup_gate_altitude`, `zem_setup_gate_projected_dx`
- `zem_terminal_gate_done`, `zem_terminal_gate_time`, `zem_terminal_gate_altitude`, `zem_terminal_gate_projected_dx`
- `zem_solve_count`, `zem_solve_ms_mean`, `zem_solve_ms_p90`, `zem_fallback_frames`
- `zem_peak_alt_over_target`, `zem_lateral_overshoot`, `zem_hover_time`
- `zem_clearance_margin`, `zem_clearance_scale`, `zem_clearance_active`

`zem_clearance_*` is retained for schema compatibility and is expected to remain
inactive (`0`/`False`) in the current generic-baseline controller.

Focused eval boundaries:

- `climb --eval-mode focused` -> `zem_setup_gate_done`
- `setup --eval-mode focused` -> `zem_setup_gate_done`
- `coast --eval-mode focused` -> `zem_terminal_gate_done`

## Compute cost

Solver load is controlled with phase-adaptive replanning:

- setup: lower replan rate, looser deviation thresholds
- coast: medium replan rate
- terminal: higher replan rate, tighter deviation thresholds

Use `bench --workers N` for throughput when running large benchmark suites.
In restricted environments where process workers are blocked, benchmarking
automatically falls back to sequential execution and prints a warning.
