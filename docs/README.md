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
- Flare-flight levels:
  - `flare_normal`: [`flare_normal.md`](flare_normal.md)
  - `flare_error`: [`flare_error.md`](flare_error.md)
- Setup levels:
  - `setup_downhill`: [`setup_downhill.md`](setup_downhill.md)
  - `setup_flat`: [`setup_flat.md`](setup_flat.md)
  - `setup_climb`: [`setup_climb.md`](setup_climb.md)

## Artifacts

- Local run artifacts (JSON/CSV/plots) default to `outputs/` and are ignored by git.
- Versioned docs images live in `docs/assets/`.

## Experiment notes

- Climb setup shaping log (March 2026): [`experiments/2026-03-climb-setup-shaping.md`](experiments/2026-03-climb-setup-shaping.md)
