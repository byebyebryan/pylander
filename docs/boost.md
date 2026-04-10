# Boost Level (`boost`)

`boost` is the pad-to-pad transfer benchmark root. The runtime level is
implemented in [`bot_framework/scenarios/boost.py`](../bot_framework/scenarios/boost.py), with family-specific
catalog and transfer helpers in `bot_framework/scenarios/boost_*`.

## Selector layers

- `boost:flat:{near|mid|far}:{empty|half|full}`
- `boost:downhill:{low|mid|mid_long|high}:{empty|half|full}`
- `boost:climb:{low|mid|mid_long|high}:{empty|half|full}`

Defaults:

- default scenario: `flat:mid:half`
- default eval goal: `landing`
- optional early-stop eval goal: `boost_cutoff`

## Behavior

- All boost route families sample destination distance ranges from the active
  seed and share the sampled route across weight tiers for the same seed.
- Flat routes vary `dx` only and are now spaced around `400`, `800`, and
  `1600` distance medians for `near`, `mid`, and `far`.
- Downhill and climb keep their fixed `dy` tiers while sampling `dx`; the
  `mid_long` route holds the same `mid` vertical delta and stretches the
  transfer into the longer `600..1000` `dx` band.
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
