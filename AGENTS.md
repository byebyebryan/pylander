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
- Scenario-first: solve focused scenarios, then generalize and extract reusable control components.
- Use meaningful metrics (success rate, landing quality, fuel use, stability, consistency across seeds).
- Require reproducible evals (seed + scenario + bot + config).
- Use benchmarks/evals to guide decisions and catch regressions.
- Use metric gates for bot changes: require measurable improvement or document explicit tradeoffs.

## Change acceptance checklist (definition of done)
- `uv run pytest`
- `uv run ruff check .`
- If behavior changed: run a relevant headless eval and compare metrics to a baseline
  - Example smoke test: `uv run python main.py level_descent --headless --quick-benchmark`
- If CLI/defaults/workflows changed: update `README.md`
- Don’t check in artifacts (`outputs/` stays local/ignored)
