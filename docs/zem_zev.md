# ZEM/ZEV Optimizer Bot (`zem_zev`)

Implementation: [`bots/zem_zev.py`](../bots/zem_zev.py), [`bots/_optimizer_pdg.py`](../bots/_optimizer_pdg.py), [`bots/_zem_config.py`](../bots/_zem_config.py), [`bots/_zem_phase.py`](../bots/_zem_phase.py), [`bots/_zem_planner.py`](../bots/_zem_planner.py), [`bots/_zem_actuation.py`](../bots/_zem_actuation.py), [`bots/_zem_telemetry.py`](../bots/_zem_telemetry.py)

`zem_zev` is the unified optimizer-first full-envelope guidance bot used by default in `launch`, `setup`, `coast`, `climb`, and `flare`.

Implementation note:

- `zem_zev` uses the `QueryBot` `plan/act` API.
- Core planning, actuation, phase tracking, and telemetry assembly are split into `_zem_*` helper modules, with `ZemZevBot` acting as the orchestration shell.
- Phase tracking consumes a batched ballistic projection query result each tick.
- Setup/coast phases use stricter center-first terminal-x tolerance and optional apex-shaped y-reference blending.

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

For uphill transfers, setup planning remains generic:

- there is currently no climb-specific trajectory shaping;
- climb behavior reflects the same generic setup/coast/terminal loop used on
  other levels.

Reference path shaping now has two layers:

- base profile from optimizer defaults (`_reference_profiles`),
- setup/coast override that blends a ballistic-like parabolic y-reference when `vy_up > 0`.

The setup/coast y-reference is parameterized by an apex-over-target target:

- `apex_target = clamp(setup_apex_height_per_dx * |dx_anchor|, setup_apex_height_min, setup_apex_height_max)`
- blend by phase (`setup_apex_ref_blend`, `coast_apex_ref_blend`).

Terminal-x tolerance is also phase-specific:

- setup: `setup_center_tol_ratio * target_half_width`
- coast: `coast_center_tol_ratio * target_half_width`
- terminal: `terminal_center_tol_ratio * target_half_width`

This replaces the prior "full pad-width deadband at all phases" behavior and
pushes setup/coast to hold impact projection closer to pad center.

Throttle allocation includes simple on/off hysteresis to reduce min-throttle chatter near cutoff.

## Telemetry fields

`zem_zev` publishes:

- `zem_setup_gate_done`, `zem_setup_gate_time`, `zem_setup_gate_altitude`, `zem_setup_gate_projected_dx`
- `zem_terminal_gate_done`, `zem_terminal_gate_time`, `zem_terminal_gate_altitude`, `zem_terminal_gate_projected_dx`
- `zem_solve_count`, `zem_solve_ms_mean`, `zem_solve_ms_p90`, `zem_fallback_frames`
- `zem_peak_alt_over_target`, `zem_lateral_overshoot`, `zem_hover_time`
- `zem_clearance_margin`, `zem_clearance_scale`, `zem_clearance_active`
- `zem_shape_window_started`, `zem_shape_window_done`
- `zem_shape_window_start_time`, `zem_shape_window_end_time`
- `zem_shape_apex_target_over_target`, `zem_shape_apex_actual_over_target`, `zem_shape_apex_error`
- `zem_shape_curve_rmse`
- `zem_shape_projected_dx_abs_mean`, `zem_shape_projected_dx_abs_max`
- `zem_shape_shortfall_ratio`

`zem_clearance_*` is retained for schema compatibility and is expected to remain
inactive (`0`/`False`) in the current generic-baseline controller.

Setup-gate debug traces can be enabled with:

```bash
PYLANDER_ZEM_DEBUG_SETUP=1 uv run python main.py sim launch:near:0 --bot zem_zev
```

Focused eval boundaries:

- `climb --eval-mode focused` -> `zem_setup_gate_done`
- `setup --eval-mode focused` -> `zem_setup_gate_done`
- `coast --eval-mode focused` -> `zem_terminal_gate_done`

## Tuning knobs

`setup` -> `coast` transition strictness:

- setup gate latches on burn-end settle (reduces under-reporting during active burn):
  `setup_gate_burn_start_thrust`, `setup_gate_idle_thrust_max`,
  `setup_gate_burn_end_settle_s`
- setup burn shaping before gate: `setup_burn_taper_*`, `setup_burn_cut_overshoot_*`
- post-gate coast retention guard: `coast_hold_projected_dx_*`, `coast_hold_vx_track_*`, `coast_hold_overshoot_*`
- terminal handoff strictness: `terminal_gate_*` (telemetry latch) and
  `terminal_entry_*` (control handoff)

Centering pressure by phase:

- `setup_center_tol_ratio`
- `coast_center_tol_ratio`
- `terminal_center_tol_ratio`

Trajectory shape controls:

- `setup_apex_height_per_dx`, `setup_apex_height_min`, `setup_apex_height_max`
- `setup_apex_ref_blend`, `coast_apex_ref_blend`

## Compute cost

Solver load is controlled with phase-adaptive replanning:

- setup: lower replan rate, looser deviation thresholds
- coast: medium replan rate
- terminal: higher replan rate, tighter deviation thresholds

Use `bench --workers N` for throughput when running large benchmark suites.
If process workers are blocked, benchmarking now errors (no implicit fallback);
rerun with `--workers 1` only when you intentionally want sequential execution.
