# Ferry phase (`ferry` level + `ferry` bot)

`ferry` is a pad-to-pad transfer scenario: take off from one landing site, fly to the other, and stop after arrival.

## Level setup

Defined in [`levels/ferry.py`](../levels/ferry.py):

- Terrain: flat (`y = 0`)
- Sites: two pads, fixed at `x = 0` (source) and `x = 800` (destination)
- Pad size: `110`
- Spawn: on source pad (`spawn_x = 0`, no jitter)
- Cargo: forced empty (`cargo_mass = 0`)
- Scenario set: `default` only

## Bot behavior

Implementation: [`bots/ferry.py`](../bots/ferry.py)

`ferry` is a wrapper around `launch` guidance with ferry-specific setup and target ownership:

1. **Source lock:** on initial landed frame, record source pad UID.
2. **Destination select:** choose the non-source pad as destination and pin that UID.
3. **Vertical clear:** thrust upright until `altitude > 100`.
4. **Launch handoff:** run `LaunchBot` (`launch -> coast -> flare`) with pinned target selection.
5. **Arrival hold:** if landed on destination, output `ferry:arrived` with zero thrust/angle.

If it later lands on a non-destination pad, arrival latch is cleared and normal ferry flow resumes.

## Commands

- Interactive/headless single run:
  - `uv run python main.py ferry`
  - `uv run python main.py ferry --headless --seed 0`
- Batch:
  - `uv run python main.py ferry --headless --batch --batch-seeds 0-19`
