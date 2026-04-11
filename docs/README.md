# Pylander docs

This folder contains deeper documentation that would otherwise bloat the root `README.md`.

## Start here

- Running the game / CLI / headless / batch: [`../README.md`](../README.md)
- Bot development framework + API: [`overview.md`](overview.md)
- Benchmark workflow CLI and reports (`pylander-benchmark` / `bot_framework.bench`): see the project skill section in [`../README.md`](../README.md).
- Commit hygiene workflow (goal-scoped commits + standardized messages): see `pylander-commit-manager` in [`../README.md`](../README.md).

## Controllers and levels

- Unified optimizer bot: [`pdg.md`](pdg.md)
- Terminal/plunge benchmark level + bot: [`plunge.md`](plunge.md)
- Query API + profiling details: [`overview.md`](overview.md)
- Terminal selector root: [`terminal.md`](terminal.md)
- Boost selector root: [`boost.md`](boost.md)
- Terrain / obstacle avoidance design: [`terrain_avoidance.md`](terrain_avoidance.md)

## Artifacts

- Local run artifacts (JSON/CSV/tracepacks/viewer bundles) default to `outputs/` and are ignored by git.
- Versioned docs images live in `docs/assets/`.

## Portable builds (PortMaster / pygbag)

- Web build documentation: [`pygbag.md`](pygbag.md)
- Research notes and packaging strategy: [`portable_research.md`](portable_research.md)
- Euler physics backend plan (web fallback): [`euler_backend_plan.md`](euler_backend_plan.md)

## Experiment notes

- Legacy climb boost-shaping log (March 2026): [`experiments/2026-03-climb-boost-shaping.md`](experiments/2026-03-climb-boost-shaping.md)
