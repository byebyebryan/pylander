# Launch phase (`launch` level + `launch` bot)

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

## Bot behavior

Implementation: [`bots/launch.py`](../bots/launch.py)

`launch` is a transfer wrapper that:

1. Locks source pad on initial landed frame.
2. Selects/pins destination pad.
3. Clears pad upright to safe altitude.
4. Hands control to `zem_zev` for in-flight guidance.
5. Holds landed state on destination (`launch:arrived`).

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
