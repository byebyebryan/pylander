# Launch level (`launch`)

`launch` is the pad-to-pad transfer scenario handled end-to-end by `zem_zev`.

## Level setup

Defined in [`levels/launch.py`](../levels/launch.py):

- Terrain: flat (`y = 0`)
- Two pads: source at `x=0`, destination sampled by scenario
- Pad size: `110`
- Spawn: on source pad
- Cargo: forced empty (`cargo_mass = 0`)

Scenarios:

- `near`: `dx in [150, 250]`
- `mid`: `dx in [300, 500]`
- `far`: `dx in [600, 1000]`

## Runtime behavior

`zem_zev` handles:

1. destination selection from pad contacts,
2. upright takeoff + pad clear,
3. transfer guidance,
4. terminal landing on destination pad.

Run-end success fields:

- `launch_arrived`
- `launch_landed_site_uid`
- `failure_mode="wrong_pad"` when landed on non-destination pad

Additional guidance diagnostics from `zem_zev` are merged into launch results
through the generic `setup_gate_*` fields plus retained bot-owned
`bot_zem_zev_*` telemetry.

## Commands

```bash
uv run python main.py run --interactive launch
uv run python main.py sim launch:near:0 --bot zem_zev
uv run python main.py bench launch:near:0-9 launch:mid:0-9 launch:far:0-9 --bot zem_zev
```
