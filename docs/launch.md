# Launch phase

`launch` is the setup-focused scenario. Default control now uses unified `zem_zev`; the legacy `launch` bot remains available for phase-handoff experiments.

## Phase contract

- Start from rest with the ship upright.
- Do one practical setup burn, not endless trim.
- Aim for a good ballistic path to target center.
- Do not rely on a hard handoff altitude floor; use projection + speed readiness.
- Hand off early to `coast`; later phases own fine correction and terminal quality.

## Level setup

Defined in [`levels/launch.py`](../levels/launch.py):

- Cargo: empty (`0`) for this iteration.
- Terrain: flat, flush/flatten target.
- Target size: `110`.
- Spawn geometry: upper arc around target center with `radius in [700, 900]`.
- Arc base angles from horizon: `15deg`, `45deg`, `75deg`.
- Per-run angle deviation: `[-5deg, +5deg]` from the base angle.
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

Default (`zem_zev`):

- Single in-flight owner with internal phases (`setup -> coast -> terminal`).
- Focused eval ends at `zem_setup_gate_done`.

Legacy (`launch` bot):

- Launch bot: [`bots/launch.py`](../bots/launch.py)
- Shared launch setup helpers: [`bots/_launch_setup.py`](../bots/_launch_setup.py)
- Shared sideburn shaping: [`bots/_sideburn_control.py`](../bots/_sideburn_control.py)
- Shared coast tracking: [`bots/_coast_tracking.py`](../bots/_coast_tracking.py)

Launch flow:

1. Compute projection-guided setup command.
2. Run an initial sideburn with coarse tolerances.
3. End setup burn when alignment is good enough (or near-term impact safety guard trips).
4. Transfer control ownership to `coast` immediately; coast may execute one correction burn or cancel it if projection settles during align.

Handoff semantics:

- Ownership transfer is explicit (`launch` does not keep driving after handoff).
- Shared runtime context is persisted through transfers (for example pinned target UID and evaluation snapshot metadata).
- Downstream chain remains `coast -> flare`, where `flare` is the terminal-burn owner.

## Evaluation notes

`launch` supports staged evaluation:

- `--eval-mode focused`: stop at launch->coast handoff
- `--eval-mode full`: continue through coast and terminal

Focused runs with unified control emit `zem_setup_*` metrics.
Legacy launch bot runs still emit `launch_setup_*` / `launch_handoff_*`.

Common commands:

- `uv run python main.py launch --headless --quick-benchmark`
- `uv run python main.py launch --headless --batch --batch-scenarios air_shallow,air_mid,air_steep`
