# Boost Flat family (`boost:flat`)

`boost:flat:*:*` is the flat pad-to-pad transfer scenario family handled end-to-end by `pdg`.

## Level setup

Defined in [`levels/boost_flat.py`](../levels/boost_flat.py):

- Terrain: flat (`y = 0`)
- Two terrain-bound pads: source at `x=0`, destination sampled by scenario
- Pad size: `110`
- Spawn: on source pad
- Cargo tiers: `empty=0`, `half=3000`, `full=6000`

Selector layers:

- `near:empty`, `near:half`, `near:full`: `dx in [150, 250]`
- `mid:empty`, `mid:half`, `mid:full`: `dx in [300, 500]`
- `far:empty`, `far:half`, `far:full`: `dx in [600, 1000]`

Defaults:

- default scenario: `mid:half`
- recommended benchmark subset: `mid:half`

## Runtime behavior

`pdg` handles:

1. destination selection from pad contacts,
2. upright takeoff + pad clear,
3. transfer guidance,
4. terminal descent and touchdown on the destination pad.

Run-end transfer fields:

- `transfer_source_site_uid`
- `transfer_target_site_uid`
- `transfer_landed_site_uid`
- `transfer_arrived`
- `failure_mode="wrong_pad"` when landed on the source pad
- `failure_mode="off_target"` when landed away from both pads

Additional guidance diagnostics from `pdg` are merged into boost-flat results
through the generic `boost_cutoff_*` fields plus retained bot-owned
`bot_pdg_*` telemetry.

## Commands

```bash
uv run python main.py run --interactive boost:flat
uv run python main.py sim boost:flat:near:half:0 --bot pdg
uv run python main.py bench boost:flat:*:* --bot pdg
```
