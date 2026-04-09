# Pylander agent guide

Retro-modern Lunar Lander with deterministic simulation, procedural terrain, and bot-driven play.

## Non-negotiables (tools/deps)
- Python: 3.13+ (see `pyproject.toml`).
- Use `uv` for dependency management and running commands (`uv sync`, `uv run ...`).
- Don’t hand-edit `uv.lock` (use `uv add` / `uv remove`).
- Rendering: `pygame-ce` (pragmatic Python default).
- Physics: `pymunk` (swap only with clear justification).
- Noise/terrain: `opensimplex` (swap only with clear justification).

## Repo map (where things live)
- `main.py`: CLI entrypoint (interactive + headless + batch eval).
- `game.py`: game orchestration (ECS systems + render loop).
- `core/`: simulation primitives (ECS, physics, terrain, sensors, systems).
- `core/systems/`: per-tick systems (treat as hot-path code).
- `levels/`: scenarios/levels and scenario selection.
- `bots/`: bot implementations (must use sensor/action API).
- `ui/`: rendering, camera, HUD/overlays.
- `tests/`: pytest suite.
- `level_viewer.py`: quick interactive level/terrain viewer.

## Game design direction
- Build a retro-modern take on Atari Lunar Lander.
- Modernize with better bots, stronger physics, economy/progression, and richer decision-making.
- Aim for dynamic gameplay via multiple autonomous agents in the same world.
- Keep presentation minimal for now, but keep rendering abstract enough to swap styles later.
- Keep simulation/game rules independent from rendering so headless eval == visual play.
- Favor emergent behavior with controllable complexity (interesting systems, still debuggable).
- Prefer data-driven knobs where practical (scenarios + tuning constants) to speed iteration.

## Engineering tenets
- Keep separation of concerns: physics, rendering, level/scenario logic, and bots stay decoupled.
- Prefer clarity over cleverness: readable code, explicit names, type hints.
- Avoid speculative abstractions; extract shared components after 2-3 real use cases.
- Keep runs deterministic when seeded.
- Fail fast on invalid config/scenario inputs with actionable errors.
- Preserve clean boundaries: bots use sensor/action APIs, not engine internals.
- Keep diffs tight: avoid drive-by refactors/renames/reformats outside the touched area.
- Breaking changes are allowed when they simplify the system, but update tests + docs in the same change.
- Protect hot paths: avoid per-frame allocations/expensive work in tight loops; measure before/after when touched.
- Keep docs aligned with behavior: update `README.md` when flags/defaults/workflows change.
- Keep the repo clean: remove temporary debug code, dead paths, and stale comments in the same change.

## Bot development and evaluation
- Treat bot build/eval/optimization as first-class (not a side quest).
- The primary controller is the unified `pdg` bot; avoid re-introducing split-phase bot stacks.
- Scenario-first: solve focused selectors/scenarios first, then widen to cross-level coverage.
- Define measurable outcomes for each tuning objective (success criteria + efficiency + stability), not just end-of-run state.
- Use meaningful metrics (success rate, landing quality, fuel use, stability, consistency across seeds).
- Include compute-cost metrics in evaluations (avg plus p90/p99 passive/update/total ms/tick) to catch hot-path regressions.
- Prefer generic evaluation metrics first (`boost_cutoff_*`, `boost_goal_*`) and treat bot-owned diagnostics as namespaced telemetry (`bot_<botname>_*`).
- Require reproducible evals (seed + scenario + bot + config).
- Use benchmarks/evals to guide decisions and catch regressions.
- Use metric gates for bot changes: require measurable improvement or document explicit tradeoffs.
- Validate downstream impact after focused tuning with a cross-level check (`plunge` / `terminal` / `boost`) before merge.

## Project skills
- Keep project skills minimal: `pylander-benchmark` and `pylander-commit-manager`.
- Use `pylander-benchmark` for the full benchmark workflow: inspect context, infer or honor scope, resolve a baseline, reuse cache, analyze results, render HTML reports, serve outputs, and promote validated dirty caches after commit.
- Prefer `uv run python -m app.bench <selectors|inspect|run|analyze|report|bundle|serve|promote> ...` for benchmark workflows.
- Keep benchmark implementation in reusable app modules; do not add skill-local wrapper scripts.
- Use `pylander-commit-manager` to plan goal-scoped commits, exact staging boundaries, and standardized commit messages.

## Commit hygiene
- Treat each commit as PR scope: one problem/goal/task per commit.
- Do not split commits by file type alone; keep code/tests/docs together when they serve the same goal.
- Split into separate commits when goals are distinct and independently reviewable.
- Subject format: `<type>: <goal summary>` where type is one of `feat|fix|refactor|docs|test|bench|skills|chore`.
- Keep subject lines imperative and <=72 chars.
- For non-trivial commits (recommended generally), include body sections:
  - `Why:` intent/problem.
  - `What:` concise bullets of key changes.
  - `Validation:` commands run, or explicit reason when not run.

## CLI and benchmark conventions
- Command model: `uv run python main.py <command> ...` where command is `run`, `sim`, `plot`, or `bench`.
- Selector model:
  - run/sim/plot: `level[:layer[:...]][:goal[:seed]]`
  - bench: `level[:layer[:...]][:goal[:seed_spec]]`
  - omitted layers resolve through defaults
  - wildcard expansion uses explicit `*` and is bench-only
- Terminology:
  - `terminal` means the public terminal selector root (`terminal:normal:*` + `terminal:error:*:*`)
  - `plunge` is a separate terminal/plunge benchmark and should be included only when explicitly named
- Prefer explicit selectors in evals/benchmarks for reproducibility.
- Use `--bot-config <path>` for tuned bot overrides; ensure comparisons use like-for-like bot config.
- For broad regression checks, prefer `uv run python -m app.bench bundle --mode quick --baseline-ref auto --missing-baseline seed` so the report records context, baseline rationale, and outcome analysis even when the ancestor cache is cold.
- Benchmark runs use default worker count; do not pass `--workers`.
- Benchmark worker behavior is fail-fast when worker pools are unavailable; no implicit sequential fallback.

## Change acceptance checklist (definition of done)
- `uv run pytest`
- `uv run ruff check .`
- If behavior changed: run a relevant headless eval and compare metrics to a baseline
 - Example focused eval: `uv run python main.py sim boost:flat:far:half:0 --bot pdg`
 - Example quick regression compare: `uv run python -m app.bench bundle --mode quick --baseline-ref auto --missing-baseline seed --bot pdg`
- If CLI/defaults/workflows changed: update `README.md`
- Don’t check in artifacts (`outputs/` stays local/ignored), including benchmark caches and generated trace/viewer artifacts.
