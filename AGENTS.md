# project

lander game inspired by the classic Atari Lunar Lander

# technical constraints
- use uv for project/package management; treat this as locked-in.
- use pygame for rendering for now (pragmatic default in python).
- use pymunk for physics for now; swap only with clear justification.
- use opensimplex for noise/terrain for now; swap only with clear justification.

# game design direction
- build a retro-modern take on Atari Lunar Lander.
- modernize with sophisticated bots, stronger physics simulation, economy/progression systems, and richer decision-making.
- aim for dynamic gameplay through multiple autonomous agents interacting in the same scene/world.
- keep presentation simple/minimal for now, but maintain a clean rendering abstraction so visual styles can change later (pixel art, 2d sprites, etc.).
- keep simulation/game rules independent from rendering so headless eval and visual play stay consistent.
- favor emergent behavior with controllable complexity: systems should interact in interesting ways without becoming impossible to reason about.
- design core systems to be data-driven where practical (scenarios, tuning constants, difficulty/economy knobs) to speed iteration.

# engineering tenets
- keep separation of concerns: physics, rendering, level generation, and bot logic stay decoupled.
- unless instructed otherwise, prefer clean breaking changes over legacy compatibility layers and tech debt.
- optimize for clarity over cleverness: choose readable, obvious code and explicit names.
- avoid speculative abstractions; extract shared components after 2-3 real use cases.
- keep runs deterministic when seeded; behavior should match between headless and interactive modes.
- fail fast on invalid config/scenario inputs with actionable error messages.
- preserve clean boundaries: bots should use sensor/action APIs, not engine internals.
- treat tests as part of the change: update/add focused tests for new behavior and bug fixes.
- keep the repo clean: remove temporary debug code, dead paths, and stale comments in the same change.
- keep docs aligned with behavior: update CLI docs/README when flags, defaults, or workflows change.
- protect hot paths: avoid unnecessary per-frame allocations and expensive work in tight loops; measure before/after when touched.

# bot development and evaluation
- treat bot build/eval/optimization as a first-class project goal, not a side task.
- keep iterating on the eval/test harness so bot changes are easy to validate and compare.
- follow a scenario-first strategy: solve focused/simple scenarios, then generalize and extract reusable control components.
- use meaningful metrics to quantify progress (success rate, landing quality, fuel use, stability, consistency across seeds/scenarios).
- use benchmarks/evals to guide development decisions and catch regressions; when behavior changes, run or add the most relevant evals.
- require reproducible evals: results should be traceable to seed + scenario + bot + config.
- use metric gates for bot changes: require measurable improvement or document explicit tradeoffs.

# change acceptance checklist
- behavior-change done criteria: tests updated/passing, relevant evals run, metrics compared to baseline, and docs/CLI updated when needed.
