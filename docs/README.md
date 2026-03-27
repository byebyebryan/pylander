# Pylander docs

This folder contains deeper documentation that would otherwise bloat the root `README.md`.

## Start here

- Running the game / CLI / headless / batch: [`../README.md`](../README.md)
- Bot development framework + API: [`overview.md`](overview.md)
- Skill workflow map (goal -> strategy -> tuning -> regression gate): [`skills_workflow.md`](skills_workflow.md)
- Telemetry diagnosis/probe workflow: see skill entries in [`../README.md`](../README.md) and contracts under `.agents/skills/contracts/`.
- Docs sync and maintenance/refactor planning workflows: see project skill entries in [`../README.md`](../README.md).
- Commit hygiene workflow (goal-scoped commits + standardized messages): see `pylander-commit-manager` in [`../README.md`](../README.md).

## Controllers and levels

- Unified optimizer bot: [`pdg.md`](pdg.md)
- Terminal/plunge benchmark level + bot: [`plunge.md`](plunge.md)
- Query API + profiling details: [`overview.md`](overview.md)
- Terminal selector root: [`terminal.md`](terminal.md)
- Boost selector root: [`boost.md`](boost.md)

## Artifacts

- Local run artifacts (JSON/CSV/tracepacks/viewer bundles) default to `outputs/` and are ignored by git.
- Versioned docs images live in `docs/assets/`.

## Experiment notes

- Legacy climb boost-shaping log (March 2026): [`experiments/2026-03-climb-boost-shaping.md`](experiments/2026-03-climb-boost-shaping.md)
