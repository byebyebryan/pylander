# Staged PDG Bot (`pdg`)

Implementation: [`bots/pdg.py`](../bots/pdg.py), [`bots/pdg_stages.py`](../bots/pdg_stages.py), [`bots/pdg_config.py`](../bots/pdg_config.py), [`bots/pdg_tracking.py`](../bots/pdg_tracking.py), [`bots/pdg_planner.py`](../bots/pdg_planner.py), [`bots/pdg_actuation.py`](../bots/pdg_actuation.py), [`bots/pdg_terminal_gate.py`](../bots/pdg_terminal_gate.py), [`bots/pdg_boost.py`](../bots/pdg_boost.py), [`bots/pdg_optimizer.py`](../bots/pdg_optimizer.py)

`pdg` is the unified optimizer-first full-envelope guidance bot used by default in the `boost:*` and `terminal:*` selector roots.

Implementation note:

- `pdg` uses the `Bot.update(dt, sensors)` API.
- `PDGBot` is a staged router over concrete guidance controllers.
- Core planning, actuation, tracking, gate logic, and telemetry assembly live in the `pdg_*` helper modules next to `bots/pdg.py`.
- Phase tracking uses analytic ballistic projection against target geometry (target x/y) rather than terrain-impact sensing.
- Boost now has a dedicated controller with its own burn/cut behavior and ballistic-shape objective.

## Naming

Both names appear in literature:

- `ZEM/ZEV` (Zero-Effort-Miss / Zero-Effort-Velocity)
- `ZEV/ZEM` (same terms reversed)

This repo uses `pdg` because the current concrete strategy is PDG-guided burns with a ballistic coast-to-terminal handoff.

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

1. update stage tracking (`boost`, `coast`, `terminal`, `touchdown`),
2. if in `coast`, hold passive retrograde attitude and evaluate a cheap analytic terminal gate,
   optionally extended by a terrain-feasibility probe on terrain-aware scenarios,
3. otherwise replan on schedule or state-deviation trigger,
4. track plan between replans,
5. allocate acceleration to thrust+angle with tilt/rate limits,
6. fallback only when optimizer result is infeasible.

For pure direct-descents with no boost shaping window and near-zero lateral
miss, stage tracking may also hand off straight from `boost` to `touchdown`
once ballistic time-to-impact is short enough. That path is intended for
plunge-like terminal descents and bypasses the normal boost-to-coast-to-terminal
chain.

Boost planning remains generic across flat/downhill/climb, but it is now handled by a dedicated boost controller rather than the generic stage runner.

The boost solve is now geometry-first and `pdx`-first:

- reduce projected miss over the active handoff window instead of only at the final horizon node,
- keep enough target-y support for the burn to hand off into a valid engine-off transfer,
- penalize excess loft more weakly than lack of loft, so boost prefers "just enough" hang time,
- steepen entry only when the live post-cut transfer is shallower than `boost_descent_angle_deg_target`,
- forbid boost thrust from pointing away from the actual target direction while boost is still outside the `dx` corridor.

Apex is still reported for telemetry, but it is no longer the boost success target.
The optimizer also constrains future projected miss to stay on the target side during boost, which prevents the old "push past zero then correct" behavior without allowing reverse target-direction thrust.

Lateral centering tolerance is phase-specific:

- boost: `boost_center_tol_ratio * target_half_width`
- terminal: `terminal_center_tol_ratio * target_half_width`

This replaces the prior "full pad-width deadband at all phases" behavior and
pushes boost to hold impact projection closer to pad center before passive
coast begins.

Throttle allocation includes simple on/off hysteresis to reduce min-throttle chatter near cutoff.

Terminal tilt is now recoverability-based instead of a single fixed cap:

- start from the normal terminal tilt envelope for the current altitude/state
- allow extra sideways tilt up to `terminal_dynamic_tilt_max` only when the current
  lateral miss can be corrected while the remaining vertical state still stays
  inside the braking envelope
- use the same dynamic terminal tilt helper in gate evaluation, terminal planning, and
  final actuation clamping so the controller stack does not disagree about what
  is feasible
- in shallow overshoot cases with strong targetward `vx`, terminal may also relax
  past the normal dynamic cap toward a dedicated overshoot tilt ceiling so the
  shared controller can spend more thrust laterally instead of lofting upward

## Telemetry fields

`pdg` publishes generic and bot-owned telemetry:

- generic boost contract: `boost_cutoff_*`, `boost_goal_*`
  - on `terminal:normal:*` / `terminal:error:*:*`, `boost_cutoff_*` is primed from the spawn
    state to indicate coast entry rather than post-burn boost completion
- bot-owned terminal handoff: `bot_pdg_terminal_entry_done`, `bot_pdg_terminal_entry_time`, `bot_pdg_terminal_entry_altitude`, `bot_pdg_terminal_entry_projected_dx`
- bot-owned terminal-gate diagnostics: `bot_pdg_terminal_gate_mode`, `bot_pdg_terminal_gate_horizon_s`, `bot_pdg_terminal_gate_terminal_speed`, `bot_pdg_terminal_gate_peak_accel_ratio`, `bot_pdg_terminal_gate_od_excess_s`, `bot_pdg_terminal_gate_latest_safe_margin_s`, `bot_pdg_terminal_gate_required_accel_ratio`
  - `terminal_gate_mode` is `nominal_ready`, `latest_safe`, `terrain_divert`, or `terrain_clip`
  - `terminal_gate_horizon_s` is the chosen analytic burn-duration estimate
  - on terrain-aware scenarios, `terrain_divert` means the target-side gate was still deferrable but target-side containment recoverability was not
  - `terrain_clip` means the short-horizon coast/terminal path was already intersecting terrain, so terminal entry was forced immediately
- bot-owned terrain-divert diagnostics: `bot_pdg_terrain_divert_mode`, `bot_pdg_terrain_divert_margin_min`, `bot_pdg_terrain_divert_first_limit_t`, `bot_pdg_terrain_divert_worst_x`, `bot_pdg_terrain_divert_horizon_s`, `bot_pdg_terrain_divert_sample_count`
  - v1 uses this path for target-side `backstop` containment and `descent_clip` telemetry
  - when `terrain_divert_mode=lateral_containment`, terminal commands add a narrow inward lateral bias against wall-side overshoot while keeping the same landing target
  - when `terrain_divert_mode=descent_clip`, terminal commands add a short-lived targetward, lift-preserving mix-in while the near-horizon path still clips the downhill shoulder
- bot-owned boost-clearance diagnostics: `bot_pdg_boost_clearance_active`, `bot_pdg_boost_clearance_margin_min`, `bot_pdg_boost_clearance_worst_x`, `bot_pdg_boost_clearance_angle_cap`, `bot_pdg_boost_clearance_sample_count`
  - this path is scoped to `terrain:reactive:boost_clearance`
  - it runs only in `BOOST`
  - while active, it temporarily caps targetward tilt and floors thrust so the ship clears the source-side rise before resuming normal boost behavior
- bot-owned compute/fallback: `bot_pdg_solve_count`, `bot_pdg_solve_ms_mean`, `bot_pdg_solve_ms_p90`, `bot_pdg_fallback_frames`
- bot-owned shape quality: `bot_pdg_shape_apex_error`, `bot_pdg_shape_curve_rmse`, `bot_pdg_shape_projected_dx_abs_mean`, `bot_pdg_shape_projected_dx_abs_max`, `bot_pdg_shape_shortfall_ratio`

Boost-cutoff debug traces can be enabled with:

```bash
PYLANDER_PDG_DEBUG_BOOST=1 uv run python main.py sim boost:flat:near:half:0 --bot pdg
```

Goal-based eval boundary:

- selector goal `boost_cutoff` (for example `boost:downhill:mid:half:boost_cutoff:0 --bot pdg`) -> early stop at boost cutoff
- boost-goal success is metric-gated: valid target-y solution, projected dx inside corridor, and impact angle above `boost_descent_angle_deg_min`
- apex telemetry remains available in `boost_cutoff_*` / `boost_goal_*`, but apex-band matching is no longer part of the boost verdict

Terrain-awareness validation:

- master switch: `terrain_awareness_enable`
- path-specific switches remain available underneath it:
  `terrain_divert_enable`, `terrain_clip_enable`, `progress_clearance_enable`
- repo preset for terrain-blind PDG runs:
  `configs/pdg_terrain_blind.json`
- example:
  `uv run python main.py sim terrain:reactive:terminal_backstop:0 --bot pdg --bot-config configs/pdg_terrain_blind.json`
- intended use:
  compare terrain-aware vs terrain-blind runs on the same selector/seed to validate that the scenario is testing a real reactive hazard rather than a generic transfer

## Tuning knobs

`boost` -> `coast` transition strictness:

- boost cut still uses burn-end settle prediction, but `boost_cutoff` only finalizes once actual thrust decays to `boost_cutoff_idle_thrust_max`:
  `boost_cutoff_burn_start_thrust`, `boost_cutoff_idle_thrust_max`,
  `boost_cutoff_burn_end_settle_s`
- direct-descent touchdown handoff: `touchdown_phase_time_to_go`
- boost burn floor / decisiveness: `boost_active_thrust_floor`, `boost_late_thrust_weight`
- terminal-gate strictness: `terminal_gate_*`
- terminal lateral-authority ceiling: `terminal_dynamic_tilt_max`
- terminal overshoot tilt relaxation:
  `terminal_overshoot_tilt_*`
- terrain awareness:
  `terrain_awareness_enable`, `terrain_divert_enable`, `terrain_clip_enable`,
  `progress_clearance_enable`

Centering pressure by phase:

- `boost_center_tol_ratio`
- `terminal_center_tol_ratio`

Trajectory shape controls:

- `boost_apex_height_per_dx`, `boost_apex_height_min`, `boost_apex_height_max`
  - still used for legacy shape telemetry and fallback reference timing
- `boost_cutoff_apex_tol_abs`, `boost_cutoff_apex_tol_ratio`
  - still published in boost telemetry, but no longer used for boost-goal pass/fail
- `boost_descent_angle_deg_min`, `boost_descent_angle_deg_target`, `boost_descent_angle_deg_max`

## Compute cost

Solver load is controlled with boost/terminal replanning and a zero-solve coast mode:

- boost: lower replan rate, looser deviation thresholds
- coast: passive retrograde actuation plus analytic terminal-gate math only
- terminal: higher replan rate, tighter deviation thresholds

Benchmarking uses the default worker policy from `main.py bench`.
If process workers are blocked, benchmarking errors instead of falling back to sequential execution.
