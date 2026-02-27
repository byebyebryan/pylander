# Ferry phase (`ferry` level + `ferry` bot)

`ferry` is a pad-to-pad transfer scenario: take off from one landing site, fly to the other, and stop after arrival.

## Level setup

Defined in [`levels/ferry.py`](../levels/ferry.py):

- Terrain: flat (`y = 0`)
- Sites: source pad fixed at `x = 0`; destination pad sampled by scenario range
- Pad size: `110`
- Spawn: on source pad (`spawn_x = 0`, no jitter)
- Cargo: forced empty (`cargo_mass = 0`)
- Scenario set:
  - `near`: `dx in [150, 250]`
  - `mid`: `dx in [300, 500]`
  - `far`: `dx in [600, 1000]`

## Bot behavior

Implementation: [`bots/ferry.py`](../bots/ferry.py)

`ferry` is a transfer wrapper with ferry-specific setup/target ownership, then explicit ownership handoff into the `launch -> coast -> flare` chain:

1. **Source lock:** on initial landed frame, record source pad UID.
2. **Destination select:** choose the non-source pad as destination and pin that UID.
3. **Vertical clear:** thrust upright until `altitude > 100`.
4. **Launch handoff:** emit ownership transfer to `LaunchBot` once clear, carrying pinned target context.
5. **Arrival hold:** if landed on destination, output `ferry:arrived` with zero thrust/angle.

If it later lands on a non-destination pad, arrival latch is cleared and normal ferry flow resumes.

## Commands

- Interactive/headless single run:
  - `uv run python main.py ferry`
  - `uv run python main.py ferry --headless --seed 0`
- Batch:
  - `uv run python main.py ferry --headless --batch --batch-scenarios near,mid,far`
