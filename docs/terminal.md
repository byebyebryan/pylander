# Terminal Level (`terminal`)

`terminal` is the coast-to-terminal descent benchmark root. The runtime level is
implemented in [`game/levels/terminal.py`](../game/levels/terminal.py), with scenario
catalog and spawn helpers in `game/levels/terminal_*`.

## Selector layers

- `terminal:normal:{shallower|shallow|mid|steep|steeper}`
- `terminal:error:{shallower|shallow|mid|steep|steeper}:{tight|wide}`

Defaults:

- default scenario: `normal:mid`
- eval goal: `landing`

## Behavior

- All terminal scenarios prime `boost_cutoff_*` at spawn so `pdg` starts in
  `coast` with no upstream boost burn.
- `normal:*` covers clean inbound entries with retrograde spawn attitude.
- `error:*:*` injects projected landing-error bias into the inbound state to
  stress terminal recovery.

## Commands

```bash
uv run python main.py run --interactive terminal
uv run python main.py sim terminal:normal:mid:0 --bot pdg
uv run python main.py sim terminal:error:mid:wide:0 --bot pdg
uv run python main.py bench terminal:* --bot pdg
```

