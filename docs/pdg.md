# Staged PDG Bot (`pdg`)

Implementation: [`bots/pdg/__init__.py`](../bots/pdg/__init__.py), [`bots/pdg/stages.py`](../bots/pdg/stages.py), [`bots/pdg/config.py`](../bots/pdg/config.py), [`bots/pdg/tracking.py`](../bots/pdg/tracking.py), [`bots/pdg/planner.py`](../bots/pdg/planner.py), [`bots/pdg/actuation.py`](../bots/pdg/actuation.py), [`bots/pdg/gate.py`](../bots/pdg/gate.py), [`bots/_optimizer_pdg.py`](../bots/_optimizer_pdg.py)

`pdg` is the unified optimizer-first full-envelope guidance bot used by default in `setup_flat`, `setup_downhill`, `flare_error`, `setup_climb`, and `flare_normal`.

Implementation note:

- `pdg` uses the `Bot.update(dt, sensors)` API.
- `PDGBot` is a staged router over concrete guidance controllers.
- Core planning, actuation, tracking, gate logic, and telemetry assembly live under `bots/pdg/`.
- Phase tracking uses analytic ballistic projection against target geometry (target x/y) rather than terrain-impact sensing.
- Setup now has a dedicated controller with its own burn/cut behavior and ballistic-shape objective.

## Naming

Both names appear in literature:

- `ZEM/ZEV` (Zero-Effort-Miss / Zero-Effort-Velocity)
- `ZEV/ZEM` (same terms reversed)

This repo uses `pdg` because the current concrete strategy is PDG-guided burns with a ballistic coast-to-flare handoff.

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

1. update stage tracking (`setup`, `coast`, `flare`, `touchdown`),
2. if in `coast`, hold passive retrograde attitude and evaluate a cheap analytic flare gate,
3. otherwise replan on schedule or state-deviation trigger,
4. track plan between replans,
5. allocate acceleration to thrust+angle with tilt/rate limits,
6. fallback only when optimizer result is infeasible.

For pure direct-descents with no setup shaping window and near-zero lateral
miss, stage tracking may also hand off straight from `setup` to `touchdown`
once ballistic time-to-impact is short enough. That path is intended for
plunge-like terminal descents and bypasses the normal setup-to-coast-to-flare
chain.

Setup planning remains generic across flat/downhill/climb, but it is now handled by a dedicated setup controller rather than the generic stage runner.

The setup solve is now geometry-first and `pdx`-first:

- reduce projected miss over the active handoff window instead of only at the final horizon node,
- keep enough target-y support for the burn to hand off into a valid engine-off transfer,
- penalize excess loft more weakly than lack of loft, so setup prefers "just enough" hang time,
- steepen entry only when the live post-cut transfer is shallower than `setup_descent_angle_deg_target`,
- forbid setup thrust from pointing away from the actual target direction while setup is still outside the `dx` corridor.

Apex is still reported for telemetry, but it is no longer the setup success target.
The optimizer also constrains future projected miss to stay on the target side during setup, which prevents the old "push past zero then correct" behavior without allowing reverse target-direction thrust.

Flare-x tolerance is also phase-specific:

- setup: `setup_center_tol_ratio * target_half_width`
- flare: `flare_center_tol_ratio * target_half_width`

This replaces the prior "full pad-width deadband at all phases" behavior and
pushes setup to hold impact projection closer to pad center before passive
coast begins.

Throttle allocation includes simple on/off hysteresis to reduce min-throttle chatter near cutoff.

Flare tilt is now recoverability-based instead of a single fixed cap:

- start from the normal flare tilt envelope for the current altitude/state
- allow extra sideways tilt up to `flare_dynamic_tilt_max` only when the current
  lateral miss can be corrected while the remaining vertical state still stays
  inside the braking envelope
- use the same dynamic flare tilt helper in gate evaluation, flare planning, and
  final actuation clamping so the controller stack does not disagree about what
  is feasible
- in shallow overshoot cases with strong targetward `vx`, flare may also relax
  past the normal dynamic cap toward a dedicated overshoot tilt ceiling so the
  shared controller can spend more thrust laterally instead of lofting upward

## Telemetry fields

`pdg` publishes generic and bot-owned telemetry:

- generic setup contract: `setup_gate_*`, `setup_goal_*`
  - on `flare_normal` / `flare_error`, `setup_gate_*` is primed from the spawn
    state to indicate coast entry rather than post-burn setup completion
- bot-owned flare handoff: `bot_pdg_flare_entry_done`, `bot_pdg_flare_entry_time`, `bot_pdg_flare_entry_altitude`, `bot_pdg_flare_entry_projected_dx`
- bot-owned flare-gate diagnostics: `bot_pdg_flare_probe_count`, `bot_pdg_flare_gate_mode`, `bot_pdg_flare_gate_horizon_s`, `bot_pdg_flare_gate_terminal_speed`, `bot_pdg_flare_gate_peak_accel_ratio`, `bot_pdg_flare_gate_od_excess_s`, `bot_pdg_flare_gate_latest_safe_margin_s`, `bot_pdg_flare_gate_required_accel_ratio`
  - `flare_probe_*` stays present for schema compatibility but remains zero in the analytic coast path
  - `flare_gate_mode` is `nominal_ready` or `latest_safe`
  - `flare_gate_horizon_s` is the chosen analytic burn-duration estimate
- bot-owned compute/fallback: `bot_pdg_solve_count`, `bot_pdg_solve_ms_mean`, `bot_pdg_solve_ms_p90`, `bot_pdg_fallback_frames`
- bot-owned shape quality: `bot_pdg_shape_apex_error`, `bot_pdg_shape_curve_rmse`, `bot_pdg_shape_projected_dx_abs_mean`, `bot_pdg_shape_projected_dx_abs_max`, `bot_pdg_shape_shortfall_ratio`

Setup-gate debug traces can be enabled with:

```bash
PYLANDER_PDG_DEBUG_SETUP=1 uv run python main.py sim setup_flat:near:0 --bot pdg
```

Goal-based eval boundary:

- selector goal `setup` (for example `setup_downhill:mid:setup:0 --bot pdg`) -> early stop at setup gate
- setup-goal success is metric-gated: valid target-y solution, projected dx inside corridor, and impact angle above `setup_descent_angle_deg_min`
- apex telemetry remains available in `setup_gate_*` / `setup_goal_*`, but apex-band matching is no longer part of the setup verdict

## Tuning knobs

`setup` -> `coast` transition strictness:

- setup cut still uses burn-end settle prediction, but `setup_gate` only finalizes once actual thrust decays to `setup_gate_idle_thrust_max`:
  `setup_gate_burn_start_thrust`, `setup_gate_idle_thrust_max`,
  `setup_gate_burn_end_settle_s`
- direct-descent touchdown handoff: `touchdown_phase_time_to_go`
- setup burn floor / decisiveness: `setup_active_thrust_floor`, `setup_late_thrust_weight`
- flare-gate strictness: `flare_gate_*`
- flare lateral-authority ceiling: `flare_dynamic_tilt_max`
- flare overshoot tilt relaxation:
  `flare_overshoot_tilt_*`

Centering pressure by phase:

- `setup_center_tol_ratio`
- `flare_center_tol_ratio`

Trajectory shape controls:

- `setup_apex_height_per_dx`, `setup_apex_height_min`, `setup_apex_height_max`
  - still used for legacy shape telemetry and fallback reference timing
- `setup_gate_apex_tol_abs`, `setup_gate_apex_tol_ratio`
  - still published in setup telemetry, but no longer used for setup-goal pass/fail
- `setup_descent_angle_deg_min`, `setup_descent_angle_deg_target`, `setup_descent_angle_deg_max`

## Compute cost

Solver load is controlled with setup/flare replanning and a zero-solve coast mode:

- setup: lower replan rate, looser deviation thresholds
- coast: passive retrograde actuation plus analytic flare-gate math only
- flare: higher replan rate, tighter deviation thresholds

Use `bench --workers N` for throughput when running large benchmark suites.
If process workers are blocked, benchmarking now errors (no implicit fallback);
rerun with `--workers 1` only when you intentionally want sequential execution.
