# Coast phase

`coast` is the efficiency-first correction phase between `launch` setup and `flare` terminal control.

## Phase contract

- `launch` should establish a good ballistic path, but it can leave bounded residual error.
- `coast` scenarios start prograde (ship aligned with initial velocity) to mirror launch handoff.
- `coast` continuously trims projected intercept error toward target center.
- `coast` is not trying to fully kill speed unless the projection says it is required.
- `flare` owns terminal burn and touchdown execution.

## Handoff semantics

Coast->flare handoff is intentionally late:

- being "on track" is necessary but not sufficient;
- handoff also requires burn-imminent conditions plus safety margins;
- handoff requires retrograde orientation (ship opposite velocity) before transfer;
- pass/fail is filtered with consecutive-frame hysteresis to avoid chatter.

This keeps coast active as long as useful, which is important for future disturbances (wind, moving targets, etc.).

## Scenario design

The coast level uses flare-like entry baselines and a single deviation knob:

- `projected_dx_error`: intended horizontal miss at ballistic impact (engine-off projection).

The scenario setup applies that deviation by offsetting initial `vx`, and keeps sign randomization deterministic per `(seed, scenario)`.

## Module ownership

- Coast level/scenarios: [`levels/coast.py`](../levels/coast.py)
- Coast bot + handoff gate: [`bots/coast.py`](../bots/coast.py)
- Shared drop guidance primitives: [`bots/_drop_guidance.py`](../bots/_drop_guidance.py)
- Shared coast tracking helpers: [`bots/_coast_tracking.py`](../bots/_coast_tracking.py)
- Shared burn timing model: [`bots/_terminal_burn.py`](../bots/_terminal_burn.py)

## Evaluation notes

`coast` supports staged evaluation:

- `--eval-mode focused`: end at coast handoff boundary
- `--eval-mode full`: continue downstream (handoff + terminal)

Focused mode success is measured by projected impact quality at handoff (`coast_handoff_projected_dx`), along with setup/handoff metrics (`coast_setup_*`, `coast_handoff_*`) via [`core/eval.py`](../core/eval.py).

