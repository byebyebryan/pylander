"""Web-compatible (pygbag/browser) async game runner.

This module is intentionally free of bot_framework and app package imports
so it can be used in the pygbag web build where those packages are excluded.
"""

from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass
from typing import Any

from game.core.config import (
    BOT_FPS,
    DEFAULT_SCREEN_HEIGHT,
    DEFAULT_SCREEN_WIDTH,
    PHYSICS_FPS,
    TARGET_RENDERING_FPS,
)
from game.core.level import GameRunState
from game.core.sensor import reset_proximity_cache
from game.runtime.actor_policy import find_initial_player_actor_uid
from game.runtime.actor_registry import collect_actor_entities
from game.runtime.game_bootstrap import (
    bootstrap_core_runtime,
    bootstrap_empty_bot_runtime,
    bootstrap_interactive_runtime,
    bootstrap_null_trace_runtime,
)
from game.runtime.interactive_session import (
    process_interactive_input,
    render_frame,
    reset_active_actor_session,
)
from game.runtime.loop_timing import LoopTimers
from game.runtime.physics_steps import update_physics_steps
from game.runtime.profiler import NullBotProfiler
from game.runtime.session_loop import (
    capture_actor_states,
    sync_landed_to_flying_engine_state,
    update_bot_override_timer,
)


@dataclass
class _WebGameContext:
    """Minimal duck-typed game context for level.setup/start/update/end/should_end."""

    run_state: GameRunState
    headless: bool = False
    lander: Any = None
    ecs_world: Any = None

    def get_active_actor(self) -> Any:
        return self.lander


async def run_web_game(
    level_name: str = "flat",
    seed: int | None = None,
    width: int = DEFAULT_SCREEN_WIDTH,
    height: int = DEFAULT_SCREEN_HEIGHT,
) -> None:
    """Run the game in async mode for pygbag/browser execution.

    Yields to the event loop each frame via ``await asyncio.sleep(0)`` so
    the browser stays responsive.  Does not depend on bot_framework or app.
    """
    if seed is None:
        seed = random.randint(0, 1_000_000)

    from game.levels.registry import create_level

    level = create_level(level_name)

    run_state = GameRunState()
    ctx = _WebGameContext(run_state=run_state)

    level.setup(ctx, seed)
    if level.world is None:
        raise RuntimeError("Level.setup did not initialize level.world")

    actors = collect_actor_entities(level)
    if not actors:
        raise RuntimeError("Level did not provide any actor entities")

    active_uid = find_initial_player_actor_uid(actors)
    lander = next((a for a in actors if a.uid == active_uid), actors[0])
    ctx.lander = lander

    core = bootstrap_core_runtime(level=level, actors=actors, active_uid=active_uid)
    ctx.ecs_world = core.ecs_world

    interactive = bootstrap_interactive_runtime(
        headless=False,
        level=level,
        width=width,
        height=height,
        bot=None,
    )

    profiler = NullBotProfiler()
    bot_runtime = bootstrap_empty_bot_runtime(
        level=level,
        actors=actors,
        ecs_world=core.ecs_world,
        world_bots=getattr(level.world, "actor_bots", None),
        primary_bot=None,
        active_uid=active_uid,
        systems=core.systems,
        profiler=profiler,
        terrain=level.world.terrain,
        engine=core.engine,
    )
    trace_runtime = bootstrap_null_trace_runtime(
        terrain=level.world.terrain,
        ecs_world=core.ecs_world,
        actor_bots=bot_runtime.actor_bots,
        active_uid_getter=lambda: active_uid,
        headless=False,
        level=level,
        seed=seed,
    )

    physics_dt = 1.0 / PHYSICS_FPS
    bot_dt = 1.0 / BOT_FPS
    frame_dt_target = 1.0 / TARGET_RENDERING_FPS
    timers = LoopTimers(physics_dt=physics_dt, bot_dt=bot_dt, frame_dt=frame_dt_target)

    reset_proximity_cache()
    level.start(ctx)

    bot_override_delay = 1.0
    bot_override_timer = 0.0

    def on_reset() -> None:
        nonlocal bot_override_timer
        bot_override_timer = reset_active_actor_session(
            active_actor=ctx.lander,
            engine=core.engine,
            renderer=interactive.renderer,
            bot_override_delay=bot_override_delay,
        )

    frame_dt = frame_dt_target

    while True:
        input_result = process_interactive_input(
            headless=False,
            input_handler=interactive.input_handler,
            renderer=interactive.renderer,
            player_controller=interactive.player_controller,
            frame_dt=frame_dt,
            get_active_actor=ctx.get_active_actor,
            on_reset=on_reset,
            on_switch_actor=lambda: None,
        )

        if not input_result.running:
            break

        user_controls = input_result.user_controls
        timers.advance_frame(frame_dt)
        run_state.elapsed_time = timers.elapsed_time

        update_physics_steps(timers, context=bot_runtime.physics_step_context)

        bot_override_timer = update_bot_override_timer(
            current_timer=bot_override_timer,
            override_delay=bot_override_delay,
            frame_dt=frame_dt,
            user_controls=user_controls,
        )

        controls_by_uid: dict[str, Any] = {}
        if user_controls is not None:
            controls_by_uid[active_uid] = user_controls

        state_before = capture_actor_states(actors)
        core.systems.control_routing.set_controls_map(controls_by_uid)
        core.systems.control_routing.update(frame_dt)
        core.systems.refuel.update(frame_dt)
        core.systems.state_transition.update(frame_dt)
        sync_landed_to_flying_engine_state(
            actors=actors,
            engine=core.engine,
            state_before=state_before,
        )

        core.systems.sensor_update.update(frame_dt)
        level.update(ctx, frame_dt)
        trace_runtime.trace_recorder.update(
            frame_dt, elapsed_time_s=timers.elapsed_time
        )

        frame_dt = render_frame(
            headless=False,
            renderer=interactive.renderer,
            active_bot=None,
            frame_dt=frame_dt,
            target_fps=TARGET_RENDERING_FPS,
        )

        if level.should_end(ctx):
            break

        await asyncio.sleep(0)

    if interactive.renderer is not None:
        interactive.renderer.shutdown()
