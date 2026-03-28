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

- All boost route families sample destination distance ranges from the active
  seed and share the sampled route across weight tiers for the same seed.
- Flat routes vary `dx` only; downhill and climb keep their fixed `dy` tiers
  while sampling `dx` from the same `300..500` band centered on the old `400`
  route distance.
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
