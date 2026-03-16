# Boost Level (`boost`)

`boost` is the pad-to-pad transfer benchmark root. The runtime level is
implemented in [`levels/boost.py`](../levels/boost.py), with family-specific
catalog and transfer helpers in `levels/boost_*`.

## Selector layers

- `boost:flat:{near|mid|far}:{empty|half|full}`
- `boost:downhill:{low|mid|high}:{empty|half|full}`
- `boost:climb:{low|mid|high}:{empty|half|full}`

Defaults:

- default scenario: `flat:mid:half`
- default eval goal: `landing`
- optional early-stop eval goal: `boost_cutoff`

## Behavior

- Flat routes sample destination distance ranges and share the sampled route
  across weight tiers for the same seed.
- Downhill and climb routes use fixed slope families with fixed destination `dx`
  / `dy` geometry.
- All boost scenarios end with the same transfer result fields:
  `transfer_source_site_uid`, `transfer_target_site_uid`,
  `transfer_landed_site_uid`, `transfer_arrived`.

## Commands

```bash
uv run python main.py run --interactive boost
uv run python main.py sim boost:flat:near:half:0 --bot pdg
uv run python main.py sim boost:downhill:mid:half:boost_cutoff:0 --bot pdg
uv run python main.py bench boost:* --bot pdg
```

