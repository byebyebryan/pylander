# Flare Normal level (`flare_normal`)

`flare_normal` is the terminal-approach sandbox for high-energy inbound entries.

## Purpose

- Stress final convergence and touchdown from curved, descending entries.
- Validate robustness and efficiency of unified `zem_zev` landing behavior.

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

- Single end-to-end evaluation path (entry-to-touchdown).
- Optional goal metadata is emitted when using goal selectors (for example `flare_normal:mid:setup:0 --bot zem_zev`).

## Commands

```bash
uv run python main.py run --interactive flare_normal
uv run python main.py sim flare_normal:mid:0 --bot zem_zev
uv run python main.py bench \
  flare_normal:shallower:0-9 \
  flare_normal:shallow:0-9 \
  flare_normal:mid:0-9 \
  flare_normal:steep:0-9 \
  flare_normal:steeper:0-9 \
  --bot zem_zev
```

## Related docs

- Unified controller details: [`zem_zev.md`](zem_zev.md)
