# Launch phase (placeholder)

`launch` is the "approach setup" phase: establish a useful ballistic-ish trajectory from larger offsets, then hand off to `coast`.

This phase is currently being reworked, so this page is intentionally light for now.

## Where to look in code

- Level scenarios: [`levels/launch.py`](../levels/launch.py)
- Bot implementation: [`bots/launch.py`](../bots/launch.py)
- Shared guidance core: [`bots/_launch_core.py`](../bots/_launch_core.py)

## Evaluation notes

`launch` supports staged evaluation:

- `--eval-mode focused`: end at the launch handoff boundary
- `--eval-mode full`: continue downstream (handoff + coast + terminal)

Focused-mode runs emit handoff/setup snapshot metrics like `launch_handoff_*` / `launch_setup_*` (see [`core/eval.py`](../core/eval.py)).

