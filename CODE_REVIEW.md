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

---

# Second Review: Behavior & Regressions

Focused on concrete runtime/behavior bugs and doc drift. Findings below are severity-ordered; each includes affected file/symbol, rationale, repro, and missing test.

## High severity

### 1. Bot override never triggers (user always overrides bot)

**Files:** [core/controllers.py](core/controllers.py) (`PlayerController.update`), [game.py](game.py) (`_process_input`)

**Why it’s a bug:** `PlayerController.update()` always returns `(target_thrust, target_angle, refuel)` (line 123), even when no keys are pressed. The game loop sets `user_controls = uc` only when `uc is not None`, so with a bot in non-headless mode the human is always considered “active” and the bot never gets control after the override delay.

**Repro:** Run with a bot and no keys pressed (e.g. `uv run python main.py level_1 hare`). Expect bot to fly after ~1s; instead the last human input (or default targets) keep being applied.

**Missing test:** Game loop test: with bot and no input, after `bot_override_delay` seconds, `controls` should come from bot, not from a stale user tuple. Or unit test: `PlayerController.update(signals_with_no_keys, ...)` returns `None` when `is_user_active(signals)` is False.

---

### 2. R resets camera only, not game

**Files:** [utils/input.py](utils/input.py) (K_r → `signals["reset"]`), [ui/camera.py](ui/camera.py) (`handle_input`), [game.py](game.py) (`_process_input`)

**Why it’s a bug:** R sets `signals["reset"]`; only the camera’s `handle_input` uses it (pan/zoom reset). The game never resets lander/level. README and HUD say “R: Reset game”.

**Repro:** Crash the lander, press R. Camera resets; lander stays crashed.

**Missing test:** Input integration: when `reset` is True, game (or level) resets lander state / restarts level as documented.

---

### 3. ContactSystem does not sync physics body on land/crash

**File:** [core/systems/contact.py](core/systems/contact.py) (`_apply_landing`, `_apply_crash`)

**Why it’s a bug:** On landing or crash the system updates only ECS (state, `phys.vel`, `trans`). The Pymunk body is unchanged. Next frame, `PhysicsSyncSystem` copies pose/velocity from the engine back into components, so the lander can drift or bounce while logic thinks it’s landed/crashed.

**Repro:** Land within safe speed/angle on a pad. Lander may visibly drift or bounce; state stays “landed” but position/velocity in engine disagree.

**Missing test:** After triggering landing in a test (contact report + valid target), run one physics step; assert engine velocity is zero and position stable (e.g. via adapter `get_velocity()` / `get_pose()`). Fix: after updating ECS, call `engine_adapter.teleport_lander(trans.pos, angle=trans.rotation, clear_velocity=True)`.

---

### 4. README CLI and flags don’t match main.py

**Files:** [README.md](README.md), [main.py](main.py)

**Why it’s a bug:** README shows `uv run python main.py` and `uv run python main.py hare`; argparse requires `level_name` first, then optional `bot_name`. So `python main.py hare` errors. README also documents `--show-bot-msg` and `--verbose`/`-v`, which don’t exist (stats are controlled by `--freq`).

**Repro:** `uv run python main.py` → “the following arguments are required: level_name”. `uv run python main.py level_1 hare --headless --show-bot-msg` → unrecognized `--show-bot-msg`.

**Missing test:** Smoke test that documented invocations (e.g. human, bot, headless with level) run without argparse errors.

---

### 5. Differential and simple landers don’t respond to input

**Files:** [game.py](game.py) (input path), [landers/differential.py](landers/differential.py), [landers/simple.py](landers/simple.py)

**Why it’s a bug:** Game uses a single `PlayerController` and applies its `(target_thrust, target_angle, refuel)` to the lander. Differential and simple landers expect `handle_input()` to drive `left_target`/`right_target` or `target_thrust_up`/`target_thrust_left`/`target_thrust_right`; that method is never called, so those targets stay zero.

**Repro:** `uv run python main.py level_1 --lander differential`. W/A/S/D do nothing; lander falls. Same for `--lander simple`.

**Missing test:** For each lander type (classic, differential, simple), run with simulated key events and assert thrust/attitude or engine targets change (or that input is routed to lander-specific handlers).

---

## Medium severity

### 6. max_time in should_end_default never triggers

**Files:** [levels/common.py](levels/common.py) (`should_end_default`), [game.py](game.py) (loop)

**Why it’s a bug:** `should_end_default` checks `getattr(game, "_elapsed_time", 0.0) >= max_time`. `game._elapsed_time` is set only after the main loop exits (game.py ~260). During the loop it’s never set, so this condition is always False. (Headless exit is done earlier in the loop via `timers.elapsed_time`.)

**Repro:** Non-headless run with a level using `should_end_default` and `max_time`: game won’t end from time. Headless already exits on time in the loop, so this is redundant there.

**Missing test:** Stub game with `_elapsed_time` set; assert `should_end_default(game, max_time=10)` is True when >= 10. Optionally integration test that `game.run(max_time=1.0)` exits within a few seconds.

---

### 7. PhysicsEngine.closest_point calls sensor with wrong signature

**File:** [core/physics.py](core/physics.py) (`closest_point`, ~291)

**Why it’s a bug:** Code calls `sensor_closest_point_on_terrain(self.height_sampler, x0, y0, lod=0, search_radius=search_radius)`. The sensor expects `(height_at, pos, lod=0, search_radius=...)` with `pos` a tuple or Vector2. Here `pos` is `x0` (float), so inside the sensor `pos[0]`, `pos[1]` raises TypeError.

**Repro:** Any call to `engine.closest_point((x, y), radius)` (e.g. from future code or tests). Not currently used in-game.

**Missing test:** `PhysicsEngine.closest_point((x, y), radius)` returns a dict with `x`, `y`, `distance` and does not raise.

---

### 8. ContactSystem target lookup too strict; KeyError on award

**File:** [core/systems/contact.py](core/systems/contact.py) (`_resolve`, `_apply_landing`)

**Why it’s a bug:** (1) `get_targets(trans.pos.x, 0)` uses range 0, so a lander slightly off the pad (e.g. float jitter) can miss the target and be treated as crash. (2) `target.info["award"]` and `target.info["award"] = 0` assume `"award"` exists; custom targets without it raise KeyError.

**Repro:** (1) Land near pad edge or with low FPS; occasional valid landing marked crash. (2) Land on a target whose `info` has no `"award"` key.

**Missing test:** Landing with `trans.pos.x` just outside pad still counts as landing when using a small range (e.g. lander width). Landing on target with `info = {}` or no `"award"` uses default (e.g. `target.info.get("award", 0)`) and doesn’t raise.

---

### 9. SensorOverlay crashes if targets is None

**File:** [ui/overlays.py](ui/overlays.py) (`_draw_proximity`, ~57)

**Why it’s a bug:** `targets.get_targets(proximity.x)` is called without checking `targets`. If `level.targets` is None (e.g. minimal level), AttributeError.

**Repro:** Use a level that doesn’t set `world.targets` or sets it to None; trigger proximity overlay draw.

**Missing test:** `SensorOverlay.draw(..., targets=None)` or level with no targets does not raise.

---

## Low severity

### 10. Minimap assumes t.info is not None

**File:** [ui/minimap.py](ui/minimap.py) (~157)

**Why it’s a bug:** `t.info.get("award", 1)` will raise if `t.info` is None. Current `Target` in terrain has `info: dict`, so low risk unless custom targets omit it.

**Missing test:** Minimap draw with a target-like object with `info=None` (guard with `getattr(t, "info", None) or {}`).

---

### 11. README bot API example is wrong

**File:** [README.md](README.md) (Bot Interface section)

**Why it’s a bug:** README shows `from bot import Bot, SensorData, BotAction`, `get_action(self, dt, sensors: SensorData)`, and `BotAction(False, False, ...)`. Actual API: `from core.bot import Bot, PassiveSensors, ActiveSensors, BotAction`; method is `update(self, dt, passive, active)`; `BotAction(target_thrust, target_angle, refuel, status="", message="")`; status is `self.status`, not `self.status_message`. Copy-paste fails.

**Repro:** Implement a bot from the README snippet; NameError/TypeError.

**Missing test:** N/A (docs). Fix: align README example with [core/bot.py](core/bot.py).

---

## Residual risk (no concrete bug)

- **LoopTimers:** If `PHYSICS_FPS` or `BOT_FPS` were 0, `physics_dt`/`bot_dt` would be inf; step/consume behavior undefined. Config validation or tests for FPS > 0 would lock this.
- **Proximity cache:** `_PROX_CACHE` in [core/sensor.py](core/sensor.py) is module-level; parallel runs or tests could share state.
- **level_viewer.py:** Uses `from camera import Camera`; will fail when run from repo root unless `ui` is on the path or import is `from ui.camera import Camera`.
- **Duplicate end/score logic:** [levels/common.py](levels/common.py) and [core/bot.py](core/bot.py) (if present) both define should_end/score helpers; consolidate to avoid drift.

---

## Prioritized next actions

1. **Fix CLI/docs (High #4):** Update README so all run examples use `level_1` (or another listed level) first, then bot; remove or replace `--show-bot-msg` and `-v` with `--freq` and any real options.
2. **Fix bot override (High #1):** In `PlayerController.update`, return `None` when `not any_pressed` so the game can apply bot controls after the override delay. Ensure lander still receives the last snapped thrust/angle when applying controls (game already applies `controls` from bot or user each frame; snapping can be applied when user is active or via a one-frame “apply current targets” path when switching to bot).
3. **Fix contact/physics sync (High #3):** In `ContactSystem._apply_landing` and `_apply_crash`, after updating ECS, call `engine_adapter.teleport_lander(trans.pos, angle=trans.rotation, clear_velocity=True)` when adapter is enabled.
4. **Reset behavior (High #2):** Either wire R to a level/game reset (lander reset + level start) or change HUD/README to “R: Reset camera”.
5. **Differential/simple input (High #5):** Route input through `lander.handle_input(input_events, frame_dt)` when the lander defines it; use its return value for “user active” and for controls when applicable; otherwise keep using `PlayerController` for classic lander.
6. **Mediums:** Fix `PhysicsEngine.closest_point` signature (pass `(x0, y0)` as second arg). Use `target.info.get("award", 0)` in ContactSystem and a small range (e.g. lander width) for `get_targets`. Guard SensorOverlay and minimap for `targets`/`info` None. Set or document `_elapsed_time` for level end logic if max_time in level is ever needed.
7. **Tests:** Add `tests/` and cover at least: control arbitration (bot vs user), contact sync (land/crash + one physics step), and CLI (documented commands succeed).
