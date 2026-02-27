# Coast phase

`coast` is the efficiency-first correction phase between `launch` setup and `flare` terminal control.

## Phase contract

- `launch` should establish a good ballistic path, but it can leave bounded residual error.
- `coast` scenarios start prograde (ship aligned with initial velocity) to mirror launch handoff.
- `coast` plans at most one decisive correction burn against projected impact error.
- `coast` is not trying to fully kill speed unless the projection says it is required.
- `flare` owns terminal burn and touchdown execution.

## Control model

Coast now uses a single-burn model tied to the mandatory prograde->retrograde flip.

Inputs per tick:

- `e = projected_dx` (predicted miss at impact)
- `t_go = t_fall`
- `m = mass`
- `u in [u_min, u_max]` (throttle)
- `theta` (candidate angle on the current flip arc)

Acceleration model:

- `a_x(theta, u, m) = (u * P_max / m) * sin(theta)`
- `a_y_up(theta, u, m) = (u * P_max / m) * cos(theta) - g`

Planning:

- sample candidate `theta` values between current angle and retrograde;
- reject angles with wrong lateral sign (`sin(theta) * e <= 0`) or poor authority;
- for each feasible `(theta, u)`, compute available burn window:
  - `T = t_go - t_align - t_spool - margin`;
- solve burn duration from:
  - `|e| = |a_x| * tau * (T - tau/2)`
  - `tau = T - sqrt(max(0, T^2 - 2*|e|/|a_x|))`;
- reject infeasible solutions (`T <= 0`, negative discriminant, out-of-range `tau`);
- choose the best feasible plan by minimum fuel proxy (`u * tau`).

Execution (closed loop):

- while still in align (burn not active), cancel the queued plan if projection is already inside deadband or has crossed the target;
- rotate to planned burn angle;
- burn while recomputing projection every tick;
- stop on first condition:
  - elapsed `>= tau_plan`,
  - sign(`projected_dx`) flips,
  - `abs(projected_dx)` below deadband;
- continue to retrograde and do not re-arm another coast burn in that coast phase.

## Handoff semantics

Coast->flare handoff is intentionally late:

- being "on track" is necessary but not sufficient;
- handoff also requires burn-imminent conditions plus safety margins;
- handoff requires retrograde orientation (ship opposite velocity) before transfer;
- pass/fail is filtered with consecutive-frame hysteresis to avoid chatter.

When the handoff gate passes, `coast` emits explicit ownership transfer to `flare` (not delegated nested update).
The handoff payload carries shared context (for example pinned target UID and handoff snapshot fields) so terminal phase starts with continuity.

This keeps coast active as long as useful, which is important for future disturbances (wind, moving targets, etc.).

## Scenario design

The coast level uses flare-like entry baselines and a single deviation knob:

- `projected_dx_error`: intended horizontal miss at ballistic impact (engine-off projection).

The scenario setup applies that deviation by offsetting initial `vx`, and keeps sign randomization deterministic per `(seed, scenario)`.

## Module ownership

- Coast level/scenarios: [`levels/coast.py`](../levels/coast.py)
- Coast bot + single-burn planner + handoff gate: [`bots/coast.py`](../bots/coast.py)
- Shared drop guidance primitives: [`bots/_drop_guidance.py`](../bots/_drop_guidance.py)
- Shared coast limits/helpers (cone/brake window): [`bots/_coast_tracking.py`](../bots/_coast_tracking.py)
- Shared burn timing model: [`bots/_terminal_burn.py`](../bots/_terminal_burn.py)

## Evaluation notes

`coast` supports staged evaluation:

- `--eval-mode focused`: end at coast handoff boundary
- `--eval-mode full`: continue downstream (handoff + terminal)

Focused mode success is measured by projected impact quality at handoff (`coast_handoff_projected_dx`), along with setup/handoff metrics (`coast_setup_*`, `coast_handoff_*`) via [`core/eval.py`](../core/eval.py).

For coast-only regression checks, use a coast-only batch (instead of cross-level quick benchmark):

```bash
uv run python main.py coast --headless --batch \
  --batch-seeds 0,1,2 \
  --batch-levels coast \
  --batch-scenarios entry_mid_trim,entry_mid_energy,entry_steep_stress
```

