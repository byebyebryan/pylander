# Setup Flat level (`setup_flat`)

`setup_flat` is the flat pad-to-pad transfer scenario handled end-to-end by `pdg`.

## Level setup

Defined in [`levels/setup_flat.py`](../levels/setup_flat.py):

- Terrain: flat (`y = 0`)
- Two terrain-bound pads: source at `x=0`, destination sampled by scenario
- Pad size: `110`
- Spawn: on source pad
- Cargo: forced empty (`cargo_mass = 0`)

Scenarios:

- `near`: `dx in [150, 250]`
- `mid`: `dx in [300, 500]`
- `far`: `dx in [600, 1000]`

## Runtime behavior

`pdg` handles:

1. destination selection from pad contacts,
2. upright takeoff + pad clear,
3. transfer guidance,
4. flare and touchdown on the destination pad.

Run-end transfer fields:

- `setup_transfer_source_site_uid`
- `setup_transfer_target_site_uid`
- `setup_transfer_landed_site_uid`
- `setup_transfer_arrived`
- `failure_mode="wrong_pad"` when landed on the source pad
- `failure_mode="off_target"` when landed away from both pads

Additional guidance diagnostics from `pdg` are merged into setup-flat results
through the generic `setup_gate_*` fields plus retained bot-owned
`bot_pdg_*` telemetry.

## Commands

```bash
uv run python main.py run --interactive setup_flat
uv run python main.py sim setup_flat:near:0 --bot pdg
uv run python main.py bench setup_flat:near:0-9 setup_flat:mid:0-9 setup_flat:far:0-9 --bot pdg
```
