# Flare level (`flare`)

`flare` is the terminal-approach sandbox for high-energy inbound entries.

## Purpose

- Stress final convergence and touchdown from curved, descending entries.
- Validate robustness and efficiency of unified `zem_zev` landing behavior.

## Level setup

Defined in [`levels/flare.py`](../levels/flare.py):

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
- quick benchmark subset: `shallow`, `mid`, `steep`

## Eval modes

- `full` (default): full entry-to-touchdown run.
- `focused`: trims passive ballistic coast and starts closer to terminal-burn-relevant conditions.

## Commands

```bash
uv run python main.py flare
uv run python main.py flare --headless --quick-benchmark
uv run python main.py flare --headless --batch --batch-scenarios shallower,shallow,mid,steep,steeper
```

## Related docs

- Unified controller details: [`zem_zev.md`](zem_zev.md)
