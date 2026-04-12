"""Web-compatible (pygbag/browser) async game runner.

This module is intentionally free of bot_framework and app package imports
so it can be used in the pygbag web build where those packages are excluded.
"""

from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass
from typing import Any

from game.core.components import LanderState
from game.core.ecs import require_component
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
    _tick_systems,
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


class WebGameSession:
    """Web-compatible game session with tick()/reset_actor() interface.

    Does NOT import from game.integration or bot_framework.
    """

    def __init__(
        self,
        *,
        level_name: str,
        seed: int,
        width: int,
        height: int,
    ):
        if seed is None:
            seed = random.randint(0, 1_000_000)
        self._seed = seed
        self._width = width
        self._height = height

        from game.levels.registry import create_level

        self._level = create_level(level_name)

        self._run_state = GameRunState()
        self._ctx = _WebGameContext(run_state=self._run_state)

        self._level.setup(self._ctx, seed)
        if self._level.world is None:
            raise RuntimeError("Level.setup did not initialize level.world")

        actors = collect_actor_entities(self._level)
        if not actors:
            raise RuntimeError("Level did not provide any actor entities")

        self._active_uid = find_initial_player_actor_uid(actors)
        self._lander = next((a for a in actors if a.uid == self._active_uid), actors[0])
        self._ctx.lander = self._lander

        core = bootstrap_core_runtime(
            level=self._level, actors=actors, active_uid=self._active_uid
        )
        self._ecs_world = core.ecs_world
        self._ctx.ecs_world = core.ecs_world

        interactive = bootstrap_interactive_runtime(
            headless=False,
            level=self._level,
            width=width,
            height=height,
            bot=None,
        )
        self._input_handler = interactive.input_handler
        self._renderer = interactive.renderer
        self._player_controller = interactive.player_controller

        profiler = NullBotProfiler()
        bot_runtime = bootstrap_empty_bot_runtime(
            level=self._level,
            actors=actors,
            ecs_world=core.ecs_world,
            world_bots=getattr(self._level.world, "actor_bots", None),
            primary_bot=None,
            active_uid=self._active_uid,
            systems=core.systems,
            profiler=profiler,
            terrain=self._level.world.terrain,
            engine=core.engine,
        )
        self._actor_bots = bot_runtime.actor_bots
        self._physics_step_context = bot_runtime.physics_step_context

        trace_runtime = bootstrap_null_trace_runtime(
            terrain=self._level.world.terrain,
            ecs_world=core.ecs_world,
            actor_bots=self._actor_bots,
            active_uid_getter=lambda: self._active_uid,
            headless=False,
            level=self._level,
            seed=seed,
        )
        self._trace_recorder = trace_runtime.trace_recorder

        self._actors = actors
        self._engine = core.engine
        self._systems = core.systems

        physics_dt = 1.0 / PHYSICS_FPS
        bot_dt = 1.0 / BOT_FPS
        frame_dt_target = 1.0 / TARGET_RENDERING_FPS
        self._timers = LoopTimers(
            physics_dt=physics_dt, bot_dt=bot_dt, frame_dt=frame_dt_target
        )

        reset_proximity_cache()
        self._level.start(self._ctx)

        self._bot_override_delay = 1.0
        self._bot_override_timer = 0.0
        self._running = True

    @property
    def renderer(self):
        return self._renderer

    def reset_actor(self) -> None:
        """Reset the active actor to start position, keep world."""
        from game.core.components import Engine, FuelTank, PhysicsState, Transform

        trans = require_component(self._lander, Transform)
        phys = require_component(self._lander, PhysicsState)
        tank = require_component(self._lander, FuelTank)
        eng = require_component(self._lander, Engine)
        ls = require_component(self._lander, LanderState)

        from game.core.components import FlightState
        from game.core.maths import Vector2

        start_pos = getattr(self._lander, "start_pos", Vector2(0.0, 0.0))
        trans.pos = Vector2(start_pos)
        trans.rotation = 0.0
        phys.vel.update(0.0, 0.0)
        phys.acc.update(0.0, 0.0)
        tank.fuel = tank.max_fuel
        eng.thrust_level = 0.0
        eng.target_thrust = 0.0
        eng.target_angle = 0.0
        ls.state = FlightState.FLYING

        self._engine.teleport(
            trans.pos, angle=trans.rotation, clear_velocity=True, uid=self._lander.uid
        )

        if self._renderer is not None:
            cam = self._renderer.main_camera
            cam.x = trans.pos.x
            cam.y = trans.pos.y

    def tick(self, *, external_events: list | None = None) -> dict:
        """Execute one frame. Returns {'running': bool, 'actor_state': str}."""
        if not self._running:
            return {"running": False, "actor_state": "flying"}

        if external_events is not None:
            self._input_handler._external_events = external_events

        frame_dt = 1.0 / TARGET_RENDERING_FPS

        input_result = process_interactive_input(
            headless=False,
            input_handler=self._input_handler,
            renderer=self._renderer,
            player_controller=self._player_controller,
            frame_dt=frame_dt,
            get_active_actor=self._ctx.get_active_actor,
            on_reset=self._on_reset,
            on_switch_actor=lambda: None,
        )

        if not input_result.running:
            self._running = False
            return {"running": False, "actor_state": "flying"}

        user_controls = input_result.user_controls
        self._timers.advance_frame(frame_dt)
        self._run_state.elapsed_time = self._timers.elapsed_time

        update_physics_steps(self._timers, context=self._physics_step_context)

        self._bot_override_timer = update_bot_override_timer(
            current_timer=self._bot_override_timer,
            override_delay=self._bot_override_delay,
            frame_dt=frame_dt,
            user_controls=user_controls,
        )

        controls_by_uid: dict[str, Any] = {}
        if user_controls is not None:
            controls_by_uid[self._active_uid] = user_controls

        _tick_systems(
            systems=self._systems,
            trace_recorder=self._trace_recorder,
            actors=self._actors,
            engine=self._engine,
            controls_by_uid=controls_by_uid,
            frame_dt=frame_dt,
            elapsed_time=self._timers.elapsed_time,
            level_update=lambda dt: self._level.update(self._ctx, dt),
        )

        frame_dt = render_frame(
            headless=False,
            renderer=self._renderer,
            active_bot=None,
            frame_dt=frame_dt,
            target_fps=TARGET_RENDERING_FPS,
        )

        if self._level.should_end(self._ctx):
            self._running = False

        ls = self._lander.get_component(LanderState)
        actor_state = str(ls.state) if ls is not None else "flying"

        return {
            "running": self._running,
            "actor_state": actor_state,
        }

    def _on_reset(self) -> None:
        self._bot_override_timer = reset_active_actor_session(
            active_actor=self._lander,
            engine=self._engine,
            renderer=self._renderer,
            bot_override_delay=self._bot_override_delay,
        )


def create_web_session(
    level_name: str, seed: int, width: int, height: int
) -> WebGameSession:
    """Factory function for GameHost integration."""
    return WebGameSession(level_name=level_name, seed=seed, width=width, height=height)


async def run_web_game(
    level_name: str | None = None,
    seed: int | None = None,
    width: int = DEFAULT_SCREEN_WIDTH,
    height: int = DEFAULT_SCREEN_HEIGHT,
) -> None:
    """Run the game in async mode for pygbag/browser execution.

    Yields to the event loop each frame via ``await asyncio.sleep(0)`` so
    the browser stays responsive.  Does not depend on bot_framework or app.
    """
    from game.game_host import GameHost

    host = GameHost(
        session_factory=create_web_session,
        skip_title=level_name is not None,
        level_name=level_name or "flat",
        seed=seed,
        width=width,
        height=height,
    )

    while True:
        if not host.tick():
            break
        await asyncio.sleep(0)

    host.shutdown()
