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
- Include compute-cost metrics in evaluations (avg plus p90/p99 passive/update/total ms/tick) to catch hot-path regressions.
- Prefer generic evaluation metrics first (`setup_gate_*`, `setup_goal_*`) and treat bot-owned diagnostics as namespaced telemetry (`bot_<botname>_*`).
- Require reproducible evals (seed + scenario + bot + config).
- Use benchmarks/evals to guide decisions and catch regressions.
- Use metric gates for bot changes: require measurable improvement or document explicit tradeoffs.
- Validate downstream impact after focused tuning with a cross-level check (`flare_plunge`/`flare_normal`/`flare_error`/`setup_downhill`/`setup_flat`/`setup_climb`) before merge.

## Skill-driven workflow
- Preferred loop:
  - `pylander-goal-builder` to define/build the new goal level/scenarios.
  - `pylander-goal-analyzer` to diagnose current failure modes and propose strategies.
  - `pylander-strategy-orchestrator` + `pylander-arena-branch-runner` to run parallel strategy experiments.
  - `pylander-tune-routing-planner` to choose route:
    - `pylander-tune-orchestrator` -> `pylander-tune-loop-manager` -> `pylander-regression-analyzer`, or
    - `pylander-tune-loop-manager` -> `pylander-regression-analyzer`.
  - `pylander-regression-analyzer` for broad regression decisioning.
- Use `pylander-benchmark-runner` / `pylander-benchmark-analyzer` for metric-grounded benchmark execution and diagnosis.
- Use `pylander-plot-runner` / `pylander-plot-analyzer` for visual trajectory/thrust analysis and anomaly triage.
- Use `pylander-telemetry-analyzer` for log/data-first crash/perf triage.
- Use `pylander-telemetry-builder` when diagnosis needs additional focused probes; default to plan-first, then implement probes only when explicitly requested.
- Use `pylander-docs-sync-planner` for drift checks and patch planning across README/docs/AGENTS.
- Use `pylander-maintenance-planner` for recurring test/benchmark maintenance planning (`test|bench|both`).
- Use `pylander-refactor-planner` for phased refactor plans and optional patch-set specs before execution.
- Use `pylander-commit-manager` to plan task-scoped commits and standardize commit messages.

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
  - run/sim/plot: `level[:scenario[:goal[:seed]]]`
  - bench: `level[:scenario[:goal[:seed_spec]]]`
- Prefer explicit selectors in evals/benchmarks for reproducibility.
- Use `--bot-config <path>` for tuned bot overrides; ensure comparisons use like-for-like bot config.
- For broad regression checks, prefer `skills/pylander-benchmark-runner/scripts/run_cached_benchmark.py` (cache-aware baseline compare).
- Benchmark runs use default worker count; do not pass `--workers`.
- Benchmark worker behavior is fail-fast when worker pools are unavailable; no implicit sequential fallback.

## Change acceptance checklist (definition of done)
- `uv run pytest`
- `uv run ruff check .`
- If behavior changed: run a relevant headless eval and compare metrics to a baseline
 - Example focused eval: `uv run python main.py sim setup_flat:far:0 --bot zem_zev`
 - Example quick regression compare: `uv run python skills/pylander-benchmark-runner/scripts/run_cached_benchmark.py --mode quick --baseline-ref main --bot zem_zev`
- If CLI/defaults/workflows changed: update `README.md`
- Don’t check in artifacts (`outputs/` stays local/ignored), including benchmark caches and generated plots.
