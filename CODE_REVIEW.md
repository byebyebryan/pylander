# Pylander Code Review & Refactoring Plan

## Executive Summary
The Pylander codebase is a well-structured Python project with a clear separation of concerns between game logic, physics (Pymunk), and rendering. The code uses modern Python features like `dataclasses` and `Protocol` for cleaner interfaces. However, as the project has grown, the root directory has become cluttered, and some core classes (like `Lander` and `LanderGame`) have accumulated too many responsibilities.

This document outlines a plan to clean up the project structure and improved code maintainability.

---

## 1. Project Organization (High Priority)

**Current State:**
The root directory contains 24 files, mixing entry points, game logic, physics, and UI components.

**Recommendation:**
Adopt a package-based structure to group related modules.

- **`pylander/ui/`**: Move all rendering and visual components here.
  - `renderer.py`, `camera.py`, `hud.py`, `minimap.py`, `overlays.py`, `fps_overlay.py`, `auto_zoom.py`
- **`pylander/core/`**: Move core simulation logic here.
  - `physics.py`, `terrain.py`, `level.py`, `sensor.py`, `engine_adapter.py`
- **`pylander/entities/`**: Move game entities here.
  - `lander.py`, `bot.py`
- **`pylander/utils/`**: Move utilities.
  - `protocols.py`, `plot.py`, `input.py`

**Action:**
Create a `ui` package immediately to reduce root clutter, as this is the most obvious separation.

## 2. Code Refactoring

### A. Game Loop (`game.py`)
**Issue:** The `LanderGame.run` method is ~200 lines long and handles mixed concerns: input processing, physics stepping loops, bot updates, control application, state transitions, and rendering.
**Refactor Plan:** Extract logic into helper methods:
- `_process_input_events()`
- `_advance_physics(dt)`
- `_update_bot(dt)`
- `_apply_controls(frame_dt)`
- `_render_frame()`

### B. Lander Class (`lander.py`)
**Issue:** `Lander` (540 lines) handles physics state, control logic, *and* rendering helper methods (e.g., `get_thrusts`, `get_body_polygon`).
**Refactor Plan:**
- Extract rendering helpers into a `LanderVisuals` helper or move to `renderer.py`.
- Keep `Lander` focused on physics and game state.

### C. Constants & Configuration
**Issue:** Constants like `GRAVITY` (physics.py), screen dimensions (game.py), and framerates are scattered.
**Refactor Plan:** Create a `config.py` to centralize these values.

## 3. Testing
**Issue:** No automated tests exist.
**Recommendation:** Initialize a `tests/` directory. Add basic tests for:
- Vector math in `physics.py` / `lander.py`.
- Game state transitions (landed/crashed logic).

---

## Proposed Next Steps

I am ready to perform the following actions:

1.  **Restructure Folders**: Create `pylander/ui` and move the 7 UI-related files there. Update imports in `game.py` and `main.py`.
2.  **Refactor Game Loop**: Clean up `LanderGame.run` in `game.py` to be more readable.
3.  **Create Config**: Extract constants to `config.py`.

*Which of these would you like me to prioritize?*
