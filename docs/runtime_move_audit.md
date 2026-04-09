# Phase 0.3: runtime/ Audit — DELETE / MOVE / DECIDE

Audit date: 2026-04-09
Purpose: classify every Python file under `runtime/` in preparation for the future
top-level `game/runtime/` move.

---

## DELETE (legacy compatibility shims — remove after updating callers)

| File | Reason |
|------|--------|
| `runtime/actor_session.py` | Deprecated shim (since 2026-04-09). Re-exports from `bot_framework.bot_actor_session` with a `DeprecationWarning`. All callers should switch to importing directly from `bot_framework.bot_actor_session`. No loss of functionality. |
| `runtime/boost_cutoff.py` | Thin re-export shim. Delegates 100% to `bot_framework.eval.boost_cutoff`. `runtime/__init__.py` never even re-exports it (it goes through `runtime/eval/`). Dead import path. |
| `runtime/headless_stats.py` | Thin re-export shim. Delegates 100% to `bot_framework.eval.headless_stats`. |
| `runtime/plot_events.py` | Thin re-export shim. Delegates 100% to `bot_framework.eval.plot_events`. |
| `runtime/result_pipeline.py` | Thin re-export shim. Delegates 100% to `bot_framework.eval.result_pipeline`. `utils/tracepack.py` imports `_safe_phase_snapshot` from here — update that import to `bot_framework.eval.result_pipeline`. |
| `runtime/eval/__init__.py` | Pure re-export of `bot_framework.eval`. `runtime/runtime_adapter.py` still imports sibling `runtime.eval.*` shim paths, so those callers must be updated before deletion. |
| `runtime/eval/boost_cutoff.py` | Thin re-export of `bot_framework.eval.boost_cutoff`. |
| `runtime/eval/headless_stats.py` | Thin re-export of `bot_framework.eval.headless_stats`. |
| `runtime/eval/plot_events.py` | Thin re-export of `bot_framework.eval.plot_events`. |
| `runtime/eval/result_pipeline.py` | Thin re-export of `bot_framework.eval.result_pipeline`. |

**Note on `runtime/eval/`**: The `runtime/eval/` directory is entirely composed of re-export shims whose canonical implementations live in `bot_framework/eval/`. The `runtime_adapter.py` file imports from `runtime.eval.*` paths, but those in turn resolve to `bot_framework.eval.*`. After deleting the above 10 files, update `runtime_adapter.py` imports to go directly to `bot_framework.eval.*`.

---

## MOVE (genuine engine/runtime modules — migrate as-is to `game/runtime/`)

| File | Reason |
|------|--------|
| `runtime/actor_policy.py` | Pure game logic: selects initial player actor by `PlayerControlled`/`PlayerSelectable` components. No bot or eval dependency. `game.py` imports it directly. Belongs in `game/runtime/`. |
| `runtime/actor_registry.py` | Actor enumeration and role queries. `bot_framework/bot_actor_session.py` imports `find_first_actor_for_role` from here. Belongs in `game/runtime/`. |
| `runtime/bootstrap.py` | Wires all ECS systems (`SystemsBundle`, `create_systems`). Core engine bootstrapping, no bot dependency. `game_bootstrap.py` imports it. Belongs in `game/runtime/`. |
| `runtime/interactive_session.py` | Handles interactive input, player session reset, and rendering. `game.py` imports `process_interactive_input`, `render_frame`, `reset_active_actor_session`. No bot dependency. Belongs in `game/runtime/`. |
| `runtime/loop_timing.py` | `LoopTimers` dataclass — pure timing state, no imports beyond stdlib. `session_loop.py` and `game_bootstrap.py` use it. Belongs in `game/runtime/`. |
| `runtime/physics_steps.py` | `PhysicsStepContext` and `update_physics_steps()`. Orchestrates per-tick physics systems. `game.py` and `session_loop.py` use it. Belongs in `game/runtime/`. |
| `runtime/player_session.py` | Player/actor session management: `set_active_actor`, `switch_active_actor`. `game.py` uses it directly. No bot dependency. Belongs in `game/runtime/`. |
| `runtime/run_metrics.py` | `RunMetricsTracker` — accumulates distance flown, fuel, overdrive, landing/crash counts. `session_loop.py`, `game.py`, and `game_bootstrap.py` use it. Belongs in `game/runtime/`. |
| `runtime/sensors.py` | Builds `Sensors`, `VehicleInfo`, `BotTarget` for bots. `bot_framework/bot_loop.py` and `bot_framework/bot_actor_session.py` import `build_sensors`, `build_vehicle_info`, `resolve_eval_target_pos`. Even though bots consume these, they are game-side sensor builders, not bot logic. Belongs in `game/runtime/`. |
| `runtime/session_loop.py` | `SessionLoopContext` and `run_session_loop()` — the main game loop driver. Heavy internal runtime deps. **Dependency note:** currently imports `runtime.bot_profiler`, so this MOVE depends on resolving the `bot_profiler.py` DECIDE path first. |
| `runtime/terrain_intel.py` | Builds `BotEnvironment` with terrain summary and boundaries for bot setup. `bot_framework/bot_actor_session.py` imports `build_bot_environment`. This is game-provided terrain data, not bot logic. Belongs in `game/runtime/`. |
| `runtime/types.py` | `BotLoopContext` dataclass — used by `session_loop.py` and `bot_loop.py`. No bot logic itself. Belongs in `game/runtime/`. |

---

## DECIDE (mixed/shared — needs design call before migrating)

| File | Reason / Design Question |
|------|--------------------------|
| `runtime/__init__.py` | Compatibility package that re-exports from sibling modules and lazily imports `update_bot_steps` / `BotLoopProfiler` from `bot_framework`. If `runtime/` is dissolved into `game/runtime/`, this `__init__.py` either disappears or becomes a thin redirect. Decision needed: should there be a `game/runtime/__init__.py` that re-exports the same surface, or do callers just import submodules directly? |
| `runtime/bot_loop.py` | Lazy-import shim (`update_bot_steps`). The real implementation is `bot_framework/bot_loop.py`. `game.py` imports `update_bot_steps` from here. If this shim goes away, `game.py` must import from `bot_framework.bot_loop` directly — which is a valid import but changes the coupling. Decision: keep shim (preserves `runtime` as the single import point) or cut it (fewer layers, direct coupling). |
| `runtime/bot_profiler.py` | Lazy-import shim (`BotLoopProfiler`, `BotProfileCounter`). Real implementation is `bot_framework/bot_profiler.py`. `game_bootstrap.py` imports `BotLoopProfiler` from here. Same trade-off as `bot_loop.py`. Decision: keep shim or eliminate it. |
| `runtime/game_bootstrap.py` | Orchestrates `CoreRuntimeBootstrap`, `InteractiveRuntimeBootstrap`, `BotRuntimeBootstrap`, `TraceRuntimeBootstrap`, but **currently imports `bot_framework.bot_actor_session` directly**. Decision needed: keep it as an engine-owned module with injected bot attachment helpers, or accept a `game.runtime -> bot_framework` dependency. Do not bulk-move as-is without resolving that coupling. |
| `runtime/metrics.py` | Thin re-export convenience module: `RunMetricsTracker` from `runtime.run_metrics`, `BotProfileCounter`/`BotLoopProfiler` from `runtime.bot_profiler`. No independent logic and no meaningful callers. Decision is likely delete/inlining by callers rather than preserving it. |
| `runtime/runtime_adapter.py` | `BotRuntimeAdapter` protocol + `FullBotRuntimeAdapter` / `NoBotRuntimeAdapter` + `build_default_eval_hooks`. Uses `runtime.eval.*` for eval hooks (which resolve to `bot_framework.eval.*`). This is the bot↔game wiring adapter — it belongs in `game/runtime/` conceptually, but its `build_default_eval_hooks()` currently uses shim paths. After DELETE of `runtime/eval/*`, update those imports to `bot_framework.eval.*`. Decision: does this adapter belong in `game/runtime/` or in `bot_framework/`? It currently lives in `runtime/` and is imported by `app/run_single.py` and `game.py`. |

---

## Files that should explicitly NOT move to `game/runtime/`

- `runtime/eval/*` — all deleted (see DELETE above). The real implementations are in `bot_framework/eval/`.
- `runtime/actor_session.py` — deleted. Successor is `bot_framework/bot_actor_session.py`.
- `runtime/boost_cutoff.py`, `runtime/headless_stats.py`, `runtime/plot_events.py`, `runtime/result_pipeline.py` — deleted. Successors are in `bot_framework/eval/`.

---

## Migration Sequence (for future Phase 1)

1. **Update all callers** of the DELETE files to import from `bot_framework.eval.*` (or `bot_framework.bot_actor_session`) directly.
   - Key production files to update: `utils/tracepack.py` (`_safe_phase_snapshot`), `runtime_adapter.py` (eval hook imports).
   - Key test files to update: `tests/test_runtime_result_pipeline.py`, `tests/test_runtime_plot_events.py`, `tests/test_runtime_headless_stats.py`.
   - Also resolve `bot_framework/eval/headless_stats.py -> runtime.sensors` before moving `sensors.py` to `game/runtime/`.
2. **Delete** the 10 DELETE files above.
3. **Move** the 12 MOVE files to `game/runtime/`, preserving import paths as `game.runtime.*`.
4. **Handle** the DECIDE files per the design decision made in that step.
5. **Remove** `runtime/__init__.py` shim layer or replace with `game/runtime/__init__.py` per decision.

---

## Summary Count

| Bucket | Count |
|--------|-------|
| DELETE | 10 files |
| MOVE   | 12 files |
| DECIDE | 6 files |
| **Total** | **28 Python files** (excluding `__pycache__`) |
