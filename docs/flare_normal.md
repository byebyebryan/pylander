# Flare Normal level (`flare_normal`)

`flare_normal` is the coast-to-flare sandbox for high-energy inbound entries.

## Purpose

- Stress final convergence and touchdown from curved, descending entries.
- Validate robustness and efficiency of unified `pdg` landing behavior.

## Level setup

Defined in [`levels/flare_normal.py`](../levels/flare_normal.py):

- Cargo: `2250`
- Terrain: flat with flush target pad
- Target size: `110`
- Spawn geometry: upper arc around target, radius `[700, 900]`
- Base entry angles: `15deg`, `30deg`, `45deg`, `60deg`, `75deg`
- Angle deviation: `[-5deg, +5deg]`
- Target flight time: `[10, 12]`
- Initial attitude: retrograde to spawned velocity

Scenarios:

- `shallower`, `shallow`, `mid`, `steep`, `steeper`

Defaults:

- default scenario: `mid`
- recommended benchmark subset: `shallow`, `mid`, `steep`

## Eval behavior

- Single landing-goal evaluation path (coast entry to touchdown).
- The run primes `setup_gate_*` at `t=0.0` from the spawn state so `pdg`
  starts directly in `coast` with no setup burn.
- During coast, the vehicle stays passive and points retrograde until flare
  entry.
- Flare entry is no longer gated by ballistic `projected_dx` alone; `pdg`
  uses a cheap analytic readiness check plus a conservative latest-safe fallback
  to decide when to hand off from coast to flare.

## Commands

```bash
uv run python main.py run --interactive flare_normal
uv run python main.py sim flare_normal:mid:0 --bot pdg
uv run python main.py bench \
  flare_normal:shallower:0-9 \
  flare_normal:shallow:0-9 \
  flare_normal:mid:0-9 \
  flare_normal:steep:0-9 \
  flare_normal:steeper:0-9 \
  --bot pdg
```

## Related docs

- Unified controller details: [`pdg.md`](pdg.md)
