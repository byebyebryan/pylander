# Setup Flat level (`setup_flat`)

`setup_flat` is the flat pad-to-pad transfer scenario handled end-to-end by `pdg`.

## Level setup

Defined in [`levels/setup_flat.py`](../levels/setup_flat.py):

- Terrain: flat (`y = 0`)
- Two terrain-bound pads: source at `x=0`, destination sampled by scenario
- Pad size: `110`
- Spawn: on source pad
- Cargo tiers: `empty=0`, `half=3000`, `full=6000`

Scenarios:

- `near_empty`, `near_half`, `near_full`: `dx in [150, 250]`
- `mid_empty`, `mid_half`, `mid_full`: `dx in [300, 500]`
- `far_empty`, `far_half`, `far_full`: `dx in [600, 1000]`

Defaults:

- default scenario: `mid_half`
- recommended benchmark subset: `mid_half`

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
uv run python main.py sim setup_flat:near_half:0 --bot pdg
uv run python main.py bench setup_flat --bot pdg
```
