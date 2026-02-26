# Launch phase

`launch` is the setup phase between static spawn and `coast`: build a usable ballistic path quickly, then hand off.

## Phase contract

- Start from rest with the ship upright.
- Do one practical setup burn, not endless trim.
- Aim for a good ballistic path to target center.
- Hand off early to `coast`; later phases own fine correction and terminal quality.

## Level setup

Defined in [`levels/launch.py`](../levels/launch.py):

- Cargo: empty (`0`) for this iteration.
- Terrain: flat, flush/flatten target.
- Target size: `110`.
- Spawn geometry: radius-`800` upper arc around target center.
- Arc angles from horizon: `15deg`, `45deg`, `75deg`.
- Spawn side (left/right) is deterministic from `(seed, scenario)`.
- Initial attitude and velocity are fixed:
  - `angle = 0` (upright)
  - `vx = 0`, `vy_up = 0`

## Scenarios

- `air_shallow` (`15deg`)
- `air_mid` (`45deg`)
- `air_steep` (`75deg`)

Defaults:

- Default scenario: `air_mid`
- Quick benchmark subset: `air_mid`, `air_steep`

## Bot ownership and flow

- Launch bot: [`bots/launch.py`](../bots/launch.py)
- Shared launch setup helpers: [`bots/_launch_setup.py`](../bots/_launch_setup.py)
- Shared sideburn shaping: [`bots/_sideburn_control.py`](../bots/_sideburn_control.py)
- Shared coast tracking: [`bots/_coast_tracking.py`](../bots/_coast_tracking.py)

Launch flow:

1. Compute projection-guided setup command.
2. Run an initial sideburn with coarse tolerances.
3. End setup burn when alignment is good enough (or safety guard trips).
4. Handoff to coast immediately.

## Evaluation notes

`launch` supports staged evaluation:

- `--eval-mode focused`: stop at launch->coast handoff
- `--eval-mode full`: continue through coast and terminal

Focused runs emit setup/handoff metrics (`launch_setup_*`, `launch_handoff_*`) via [`core/eval.py`](../core/eval.py).

Common commands:

- `uv run python main.py launch --headless --quick-benchmark`
- `uv run python main.py launch --headless --batch --batch-seeds 0-9 --batch-scenarios air_shallow,air_mid,air_steep`

