# Pylander docs

This folder contains deeper documentation that would otherwise bloat the root `README.md`.

## Start here

- Running the game / CLI / headless / batch: [`../README.md`](../README.md)
- Bot development framework + API: [`overview.md`](overview.md)
- Skill workflow map (goal -> strategy -> tuning -> regression gate): [`skills_workflow.md`](skills_workflow.md)
- Telemetry diagnosis/probe workflow: see skill entries in [`../README.md`](../README.md) and contracts under `skills/contracts/`.
- Docs sync and maintenance/refactor planning workflows: see project skill entries in [`../README.md`](../README.md).
- Commit hygiene workflow (goal-scoped commits + standardized messages): see `pylander-commit-manager` in [`../README.md`](../README.md).

## Controllers and levels

- Unified optimizer bot: [`pdg.md`](pdg.md)
- Terminal/plunge benchmark level + bot: [`plunge.md`](plunge.md)
- Query API + profiling details: [`overview.md`](overview.md)
- Terminal-flight levels:
  - `terminal_normal`: [`terminal_normal.md`](terminal_normal.md)
  - `terminal_error`: [`terminal_error.md`](terminal_error.md)
- Boost levels:
  - `boost_downhill`: [`boost_downhill.md`](boost_downhill.md)
  - `boost_flat`: [`boost_flat.md`](boost_flat.md)
  - `boost_climb`: [`boost_climb.md`](boost_climb.md)

## Artifacts

- Local run artifacts (JSON/CSV/plots) default to `outputs/` and are ignored by git.
- Versioned docs images live in `docs/assets/`.

## Experiment notes

- Legacy climb boost-shaping log (March 2026): [`experiments/2026-03-climb-boost-shaping.md`](experiments/2026-03-climb-boost-shaping.md)
