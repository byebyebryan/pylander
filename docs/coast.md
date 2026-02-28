# Coast phase

`coast` is the horizontal-correction scenario. Default control now uses unified `zem_zev`; the legacy `coast` bot remains available for explicit coast->flare handoff studies.

## Phase contract

- `launch` should establish a good ballistic path, but it can leave bounded residual error.
- `coast` scenarios start prograde (ship aligned with initial velocity) to mirror launch handoff.
- `coast` plans at most one decisive correction burn against projected impact error.
- `coast` is not trying to fully kill speed unless the projection says it is required.
- `flare` owns terminal burn and touchdown execution.

## Control model

Default (`zem_zev`):

- Single in-flight owner with coupled 2-axis optimizer guidance.
- Focused eval ends at `zem_terminal_gate_done`.

Legacy (`coast` bot):

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

The coast level now mirrors flare-style ranged entry setup and solves initial velocity from an explicit impact target:

- Base entry angles: `15deg`, `45deg`, `75deg`
- Per-run angle deviation: `[-5deg, +5deg]`
- Radius: `[700, 900]`
- Error tiers:
  - `low`: `|projected_dx_error| in [40, 60]`
  - `high`: `|projected_dx_error| in [80, 100]`
- Error sign is randomized per seeded run in full benchmark mode.

Setup flow:

- build start position from sampled angle/radius;
- choose `impact_target_x = target_x + projected_dx_error`;
- sample `t_flight in [10, 12]`;
- solve initial `vx`/`vy` so ballistic impact reaches `(impact_target_x, target_y)` at `t_flight`.

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

Unified focused runs emit `zem_terminal_*` metrics.
Legacy coast bot focused runs continue using `coast_setup_*` / `coast_handoff_*`.

For coast-only regression checks, use a coast-only batch (instead of cross-level quick benchmark):

```bash
uv run python main.py coast --headless --batch \
  --batch-levels coast \
  --batch-scenarios entry_mid_low,entry_mid_high,entry_steep_high
```
