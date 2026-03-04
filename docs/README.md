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

- Unified optimizer bot: [`zem_zev.md`](zem_zev.md)
- Terminal benchmark bot: [`plunge.md`](plunge.md)
- Query API + profiling details: [`overview.md`](overview.md)
- Scenario levels:
  - `flare`: [`flare.md`](flare.md)
  - `coast`: [`coast.md`](coast.md)
  - `climb`: [`climb.md`](climb.md)
  - `setup`: [`setup.md`](setup.md)
  - `launch`: [`launch.md`](launch.md)

## Artifacts

- Local run artifacts (JSON/CSV/plots) default to `outputs/` and are ignored by git.
- Versioned docs images live in `docs/assets/`.
