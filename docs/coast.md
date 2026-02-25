# Coast phase (placeholder)

`coast` is the pre-terminal correction phase and the handoff gate into `flare`.

This phase is currently being reworked, so this page is intentionally light for now.

## Where to look in code

- Level scenarios: [`levels/coast.py`](../levels/coast.py)
- Bot implementation: [`bots/coast.py`](../bots/coast.py)
- Shared guidance core: [`bots/_coast_core.py`](../bots/_coast_core.py)

## Evaluation notes

`coast` supports staged evaluation:

- `--eval-mode focused`: end at the coast handoff boundary
- `--eval-mode full`: continue downstream (handoff + terminal)

Focused-mode runs emit handoff/setup snapshot metrics like `coast_handoff_*` / `coast_setup_*` (see [`core/eval.py`](../core/eval.py)).

