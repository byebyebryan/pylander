# Launch phase (`launch` level)

`launch` is the pad-to-pad transfer scenario: take off from one site, fly to the other, and finish on the destination pad.

## Level setup

Defined in [`levels/launch.py`](../levels/launch.py):

- Terrain: flat (`y = 0`)
- Sites: source pad fixed at `x = 0`; destination pad sampled by scenario range
- Pad size: `110`
- Spawn: on source pad (`spawn_x = 0`, no jitter)
- Cargo: forced empty (`cargo_mass = 0`)
- Scenarios:
  - `near`: `dx in [150, 250]`
  - `mid`: `dx in [300, 500]`
  - `far`: `dx in [600, 1000]`

## Default bot behavior

Default implementation: [`bots/zem_zev.py`](../bots/zem_zev.py)

`launch` now defaults to `zem_zev` end-to-end:

1. Selects destination when starting landed on the source pad.
2. Performs upright takeoff and low-altitude pad-clear (`~10` altitude).
3. Transitions directly to optimizer guidance for transfer + terminal landing.
4. Holds landed state once on the selected destination pad.

Optional wrapper implementation: [`bots/launch.py`](../bots/launch.py)

- `launch` bot remains available via `--bot launch`.
- Wrapper behavior is still upright pad-clear then ownership handoff to `zem_zev`.

Run-end scoring fields:

- `launch_arrived` (boolean success gate)
- `launch_landed_site_uid`
- `failure_mode="wrong_pad"` when landed away from destination

## Commands

- Interactive/headless:
  - `uv run python main.py launch`
  - `uv run python main.py launch --headless --seed 0`
- Batch:
  - `uv run python main.py launch --headless --batch --batch-scenarios near,mid,far`
