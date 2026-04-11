"""pygbag web entrypoint: minimal browser-playable build using game-only path.

This module starts interactive gameplay directly without importing bot_framework,
tooling, or app CLI code at module load time.

Scope: gameplay only, no bots, no benchmark/report tooling.
Supported levels: flat, mountains (if low-risk).

Import contract:
- Only game/* and standard-library modules at module level
- No bot_framework, app/*, or tooling/* imports at module level
"""

from __future__ import annotations

import sys

from game.core.eval_goals import EVAL_GOAL_LANDING
from game.core.level import GameRunState

EMSCRIPTEN = hasattr(sys, "emscripten")


def is_browser() -> bool:
    """Return True when running under emscripten/pygbag."""
    return EMSCRIPTEN


def run_web_interactive(
    level_name: str = "flat",
    seed: int | None = None,
    width: int = 1280,
    height: int = 720,
) -> None:
    """Run interactive gameplay in browser environment.

    This is the primary entrypoint for the pygbag build. It configures
    browser-safe pygame environment and starts the game loop.

    Args:
        level_name: Level to play ("flat" or "mountains")
        seed: Random seed for deterministic terrain (None = random)
        width: Screen width in pixels
        height: Screen height in pixels

    Raises:
        RuntimeError: If called outside of browser environment
    """
    if not is_browser():
        raise RuntimeError(
            "run_web_interactive is only valid under pygbag/emscripten. "
            "Use 'uv run python main.py play' for desktop play."
        )

    if seed is None:
        import random

        seed = random.randint(0, 1_000_000)

    game = build_web_game(level_name, seed, width, height)
    game.run(print_freq=0, max_time=None, max_steps=None)


def build_web_game(
    level_name: str,
    seed: int,
    width: int,
    height: int,
) -> "WebGame":
    """Build a minimal game instance for web play without importing game.__main__.

    This creates a stripped-down game object that can run the session loop
    without needing bot_framework or tooling imports. It uses:
    - NullBotProfiler instead of bot_framework profiler
    - NoBotRuntimeAdapter for no-bot gameplay
    - Direct game runtime component assembly

    Returns:
        WebGame instance ready to call run() on
    """
    import random

    from game.levels.registry import create_level
    from game.runtime.actor_policy import find_initial_player_actor_uid
    from game.runtime.actor_registry import collect_actor_entities
    from game.runtime.game_bootstrap import (
        bootstrap_core_runtime,
        bootstrap_interactive_runtime,
    )
    from game.runtime.profiler import NullBotProfiler
    from game.runtime.runtime_adapter import NoBotRuntimeAdapter

    _seed = int(seed) if seed is not None else random.randint(0, 1_000_000)

    level = create_level(level_name)
    level.setup(None, _seed)

    actors = collect_actor_entities(level)
    if not actors:
        raise RuntimeError("Level did not provide any actor entities")

    active_player_actor_uid = find_initial_player_actor_uid(actors)

    core_runtime = bootstrap_core_runtime(
        level=level,
        actors=actors,
        active_uid=active_player_actor_uid,
    )

    interactive_runtime = bootstrap_interactive_runtime(
        headless=False,
        level=level,
        width=width,
        height=height,
        bot=None,
    )

    profiler = NullBotProfiler()

    runtime_adapter = NoBotRuntimeAdapter()
    (
        bot_runtime,
        trace_runtime,
        eval_hooks,
        plot_events_seen,
    ) = runtime_adapter.resolve(
        level=level,
        actors=actors,
        ecs_world=core_runtime.ecs_world,
        world_bots=getattr(level.world, "actor_bots", None),
        primary_bot=None,
        active_uid=active_player_actor_uid,
        active_uid_getter=lambda: active_player_actor_uid,
        systems=core_runtime.systems,
        profiler=profiler,
        terrain=level.terrain,
        engine=core_runtime.engine,
        seed=_seed,
        headless=False,
        eval_goal=EVAL_GOAL_LANDING,
    )

    game = WebGame(
        level=level,
        width=width,
        height=height,
        seed=_seed,
        actors=actors,
        active_player_actor_uid=active_player_actor_uid,
        core_runtime=core_runtime,
        interactive_runtime=interactive_runtime,
        bot_runtime=bot_runtime,
        trace_runtime=trace_runtime,
        eval_hooks=eval_hooks,
        plot_events_seen=plot_events_seen,
        profiler=profiler,
    )

    return game


class WebGame:
    """Minimal game object for browser play.

    This is a stripped-down version that avoids importing game.__main__ (which
    pulls in bot_framework via game.integration). It only supports:
    - Interactive player gameplay (no bots)
    - flat level
    """

    def __init__(
        self,
        level,
        width: int,
        height: int,
        seed: int,
        actors,
        active_player_actor_uid: str,
        core_runtime,
        interactive_runtime,
        bot_runtime,
        trace_runtime,
        eval_hooks,
        plot_events_seen,
        profiler,
    ):
        self.level = level
        self.width = width
        self.height = height
        self.seed = seed
        self.headless = False
        self.bot = None

        self.actors = actors
        self.active_player_actor_uid = active_player_actor_uid
        self.lander = next(
            (
                actor
                for actor in self.actors
                if actor.uid == self.active_player_actor_uid
            ),
            self.actors[0],
        )

        self.sites = core_runtime.sites
        self.engine = core_runtime.engine
        self.ecs_world = core_runtime.ecs_world
        self.systems = core_runtime.systems

        self.input_handler = interactive_runtime.input_handler
        self.renderer = interactive_runtime.renderer
        self.player_controller = interactive_runtime.player_controller

        self.actor_bots = bot_runtime.actor_bots
        self._bot_loop_context = bot_runtime.bot_loop_context
        self._physics_step_context = bot_runtime.physics_step_context
        self.trace_recorder = trace_runtime.trace_recorder
        self._plot_events_seen = plot_events_seen
        self._eval_hooks = eval_hooks
        self._bot_profiler = profiler

        self.run_state = GameRunState()
        self.running = True
        self._elapsed_time = 0.0
        self._bot_eval_decision = None
        self._bot_override_timer = 0.0
        self.bot_override_delay = 1.0

        self.eval_goal = EVAL_GOAL_LANDING

        self.level.start(self)

    def get_active_actor(self):
        actor = self.ecs_world.get_entity_by_id(self.active_player_actor_uid)
        if actor is None:
            raise RuntimeError("Active actor is missing from ECS world")
        return actor

    def _switch_active_actor(self, delta: int = 1) -> None:
        from game.runtime.player_session import switch_active_actor

        switched = switch_active_actor(
            actors=self.actors,
            ecs_world=self.ecs_world,
            level=self.level,
            engine=self.engine,
            active_uid=self.active_player_actor_uid,
            delta=delta,
        )
        if switched is None:
            return
        self.active_player_actor_uid, self.lander = switched

    def run(
        self,
        print_freq: int = 60,
        max_time: float | None = None,
        max_steps: int | None = None,
    ):
        from game.core.components import Transform
        from game.core.maths import Vector2
        from game.core.sensor import reset_proximity_cache
        from game.core.ecs import require_component
        from game.runtime.interactive_session import (
            process_interactive_input,
            render_frame,
            reset_active_actor_session,
        )
        from game.runtime.loop_timing import LoopTimers
        from game.runtime.physics_steps import update_physics_steps
        from game.runtime.run_metrics import RunMetricsTracker
        from game.runtime.session_loop import SessionLoopContext, run_session_loop
        from game.runtime.sensors import resolve_eval_target_pos
        from game.core.config import BOT_FPS, PHYSICS_FPS, TARGET_RENDERING_FPS

        physics_dt = 1.0 / PHYSICS_FPS
        bot_dt = 1.0 / BOT_FPS
        frame_dt = 1.0 / TARGET_RENDERING_FPS
        timers = LoopTimers(physics_dt=physics_dt, bot_dt=bot_dt, frame_dt=frame_dt)

        reset_proximity_cache()
        self.trace_recorder.seed_initial_sample()
        self._plot_events_seen.clear()
        self._bot_eval_decision = None
        self._elapsed_time = 0.0
        self.run_state.elapsed_time = 0.0
        initial_actor = self.get_active_actor()
        initial_trans = require_component(initial_actor, Transform)
        start_pos = Vector2(getattr(initial_actor, "start_pos", initial_trans.pos))
        eval_target_pos = resolve_eval_target_pos(self.level, self.sites, start_pos)

        if eval_target_pos is not None:
            self.trace_recorder.set_target(
                x=float(eval_target_pos.x),
                y=float(eval_target_pos.y),
                label="landing target",
                size=None,
            )

        metrics = RunMetricsTracker.from_actor(
            initial_actor,
            start_pos=start_pos,
            eval_target_pos=eval_target_pos,
        )

        def process_input_step(frame_dt: float):
            result = process_interactive_input(
                headless=self.headless,
                input_handler=self.input_handler,
                renderer=self.renderer,
                player_controller=self.player_controller,
                frame_dt=frame_dt,
                get_active_actor=self.get_active_actor,
                on_reset=lambda: setattr(
                    self,
                    "_bot_override_timer",
                    reset_active_actor_session(
                        active_actor=self.get_active_actor(),
                        engine=self.engine,
                        renderer=self.renderer,
                        bot_override_delay=self.bot_override_delay,
                    ),
                ),
                on_switch_actor=self._switch_active_actor,
            )
            self.running = result.running
            return result.user_controls, result.input_events

        loop_result = run_session_loop(
            context=SessionLoopContext(
                headless=self.headless,
                actors=self.actors,
                engine=self.engine,
                systems=self.systems,
                trace_recorder=self.trace_recorder,
                bot_profiler=self._bot_profiler,
                metrics=metrics,
                bot_override_delay=self.bot_override_delay,
                bot_override_timer=self._bot_override_timer,
                is_running=lambda: self.running,
                active_uid=lambda: self.active_player_actor_uid,
                get_active_actor=self.get_active_actor,
                process_input=process_input_step,
                set_elapsed_time=lambda elapsed: setattr(
                    self, "_elapsed_time", elapsed
                ),
                update_physics_steps=lambda timers: update_physics_steps(
                    timers,
                    context=self._physics_step_context,
                ),
                update_bot_steps=lambda timers: {},
                level_update=lambda dt: self.level.update(self, dt),
                track_plot_events=lambda: None,
                render=lambda frame_dt: render_frame(
                    headless=self.headless,
                    renderer=self.renderer,
                    active_bot=None,
                    frame_dt=frame_dt,
                    target_fps=TARGET_RENDERING_FPS,
                ),
                print_headless_stats=lambda timers: None,
                resolve_headless_bot_eval_decision=lambda: None,
                level_should_end=lambda: self.level.should_end(self),
            ),
            timers=timers,
            print_freq=print_freq,
            max_time=max_time,
            max_steps=max_steps,
        )

        if self.renderer:
            self.renderer.shutdown()

        timers = loop_result.timers
        metrics = loop_result.metrics
        self._bot_override_timer = loop_result.bot_override_timer
        self._elapsed_time = timers.elapsed_time
        self.run_state.elapsed_time = timers.elapsed_time
        self.run_state.landing_count = metrics.landing_count
        self.run_state.crash_count = metrics.crash_count
        self.run_state.distance_flown = metrics.distance_flown
        self.run_state.fuel_consumed = metrics.fuel_consumed
        self.run_state.overdrive_time = metrics.overdrive_time
        self.run_state.overdrive_excess = metrics.overdrive_excess

        result = self.level.end(self)
        self._bot_profiler.apply_to_result(result)
        self.trace_recorder.finalize(result=result, elapsed_time_s=timers.elapsed_time)
        return result

    @property
    def terrain(self):
        if self.level.world is None:
            raise RuntimeError("Level world is not initialized")
        return self.level.world.terrain


def main() -> None:
    """Entry point called by pygbag runtime.

    This function is called by pygbag's JavaScript glue code when
    the WASM module is loaded.
    """
    run_web_interactive(level_name="flat", seed=None, width=1280, height=720)


if __name__ == "__main__":
    main()
