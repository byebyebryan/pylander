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
- `levels/`: scenarios/levels (often define `default_bot_name` + scenario selection).
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
- The primary controller is the unified `zem_zev` bot; avoid re-introducing split-phase bot stacks.
- Scenario-first: solve focused selectors/scenarios first, then widen to cross-level coverage.
- Define measurable outcomes for each tuning objective (success criteria + efficiency + stability), not just end-of-run state.
- Use meaningful metrics (success rate, landing quality, fuel use, stability, consistency across seeds).
- Include compute-cost metrics in evaluations (avg plus p90/p99 bot ms/tick) to catch hot-path regressions.
- Require reproducible evals (seed + scenario + bot + config).
- Use benchmarks/evals to guide decisions and catch regressions.
- Use metric gates for bot changes: require measurable improvement or document explicit tradeoffs.
- Validate downstream impact after focused tuning with a cross-level check (`plunge`/`flare`/`coast`/`setup`/`launch`) before merge.

## Skill-driven workflow
- Preferred loop:
  - `pylander-goal-builder` to define/build the new goal level/scenarios.
  - `pylander-goal-doctor` to diagnose current failure modes and propose strategies.
  - `pylander-strategy-arena` + `pylander-strategy-worker` to run parallel strategy experiments.
  - `pylander-tune-loop-lite` to do bounded winner tuning.
  - `pylander-regression-doctor` for broad regression decisioning.
- Use `pylander-benchmark` / `pylander-benchmark-doctor` for metric-grounded benchmark execution and diagnosis.
- Use `pylander-plot` / `pylander-plot-doctor` for visual trajectory/thrust analysis and anomaly triage.

## CLI and benchmark conventions
- Command model: `uv run python main.py <command> ...` where command is `run`, `sim`, `plot`, or `bench`.
- Selector model:
  - run/sim/plot: `level[:scenario[:seed]]`
  - bench: `level[:scenario[:seed_spec]]`
- Prefer explicit selectors in evals/benchmarks for reproducibility.
- Use `--bot-config <path>` for tuned bot overrides; ensure comparisons use like-for-like bot config.
- For broad regression checks, prefer `skills/pylander-benchmark/scripts/run_cached_benchmark.py` (cache-aware baseline compare).
- Benchmark worker behavior is fail-fast when worker pools are unavailable; no implicit sequential fallback.

## Change acceptance checklist (definition of done)
- `uv run pytest`
- `uv run ruff check .`
- If behavior changed: run a relevant headless eval and compare metrics to a baseline
 - Example focused eval: `uv run python main.py sim launch:far:0 --bot zem_zev`
 - Example quick regression compare: `uv run python skills/pylander-benchmark/scripts/run_cached_benchmark.py --mode quick --baseline-ref main --bot zem_zev`
- If CLI/defaults/workflows changed: update `README.md`
- Don’t check in artifacts (`outputs/` stays local/ignored), including benchmark caches and generated plots.
