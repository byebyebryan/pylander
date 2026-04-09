"""Game orchestration: ECS systems + render loop."""

from __future__ import annotations

import random
from typing import Any, Iterable, cast

from core.bot import Bot, BotEvalDecision, resolve_bot_name
from core.components import Transform
from core.ecs import Entity, require_component
from core.eval_goals import EVAL_GOAL_LANDING, normalize_eval_goal
from core.level import GameRunState, Level
from core.level_capabilities import level_name_tag, level_scenario_tag
from core.maths import Range1D, Vector2
from runtime.actor_policy import find_initial_player_actor_uid
from runtime.actor_registry import collect_actor_entities
from runtime.actor_session import active_actor_bot
from runtime.player_session import set_active_actor, switch_active_actor
from runtime.bot_loop import update_bot_steps
from runtime.game_bootstrap import (
    bootstrap_core_runtime,
    bootstrap_interactive_runtime,
)
from runtime.loop_timing import LoopTimers
from runtime.run_metrics import RunMetricsTracker
from runtime.bot_profiler import BotLoopProfiler
from runtime.physics_steps import update_physics_steps
from runtime.interactive_session import (
    process_interactive_input,
    render_frame,
    reset_active_actor_session,
)
from runtime.runtime_adapter import (
    BotRuntimeAdapter,
    EvalHooks,
    make_runtime_adapter,
)
from runtime.session_loop import SessionLoopContext, run_session_loop
from runtime.sensors import resolve_eval_target_pos
from core.sensor import reset_proximity_cache

from core.config import (
    BOT_FPS,
    DEFAULT_SCREEN_HEIGHT,
    DEFAULT_SCREEN_WIDTH,
    PHYSICS_FPS,
    TARGET_RENDERING_FPS,
)


class LanderGame:
    """Main application for lunar lander game."""

    def __init__(
        self,
        level: Level,
        width: int = DEFAULT_SCREEN_WIDTH,
        height: int = DEFAULT_SCREEN_HEIGHT,
        seed: int | None = None,
        bot: Bot | None = None,
        headless: bool = False,
        eval_goal: str = EVAL_GOAL_LANDING,
        bot_profile_enabled: bool | None = None,
        bot_profile_interval_s: float | None = None,
        bot_profile_log_lines: bool | None = None,
        eval_hooks: EvalHooks | None = None,
        runtime_adapter: BotRuntimeAdapter | None = None,
    ):
        self.headless = headless
        self.bot = bot
        self._injected_eval_hooks = eval_hooks
        self.level = level
        self.eval_goal = normalize_eval_goal(eval_goal)
        seed = random.randint(0, 1000000) if seed is None else seed
        self.seed = int(seed)
        self._bot_profiler = BotLoopProfiler.from_settings(
            headless=headless,
            enabled=bot_profile_enabled,
            interval_s=bot_profile_interval_s,
            log_lines=bot_profile_log_lines,
        )

        if headless and not bot:
            raise ValueError("Headless mode requires a bot")

        self.running = True
        self.run_state = GameRunState()
        self.level.setup(self, seed)
        self.actors = collect_actor_entities(self.level)
        if not self.actors:
            raise RuntimeError("Level did not provide any actor entities")
        self.active_player_actor_uid = find_initial_player_actor_uid(self.actors)
        self.lander = next(
            (
                actor
                for actor in self.actors
                if actor.uid == self.active_player_actor_uid
            ),
            self.actors[0],
        )
        core_runtime = bootstrap_core_runtime(
            level=self.level,
            actors=self.actors,
            active_uid=self.active_player_actor_uid,
        )
        self.sites = core_runtime.sites
        self.engine = core_runtime.engine
        self.ecs_world = core_runtime.ecs_world
        self.systems = core_runtime.systems
        self._set_active_actor(self.active_player_actor_uid)

        self.bot_override_delay = 1.0
        self._bot_override_timer = 0.0

        interactive_runtime = bootstrap_interactive_runtime(
            headless=headless,
            level=self.level,
            width=width,
            height=height,
            bot=self.bot,
        )
        self.input_handler = interactive_runtime.input_handler
        self.renderer = interactive_runtime.renderer
        self.player_controller = interactive_runtime.player_controller

        if runtime_adapter is None:
            runtime_adapter = make_runtime_adapter(bot, headless)
        (
            bot_runtime,
            trace_runtime,
            resolved_eval_hooks,
            plot_events_seen,
        ) = runtime_adapter.resolve(
            level=self.level,
            actors=self.actors,
            ecs_world=self.ecs_world,
            world_bots=getattr(self.level.world, "actor_bots", None),
            primary_bot=self.bot,
            active_uid=self.active_player_actor_uid,
            active_uid_getter=lambda: self.active_player_actor_uid,
            systems=self.systems,
            profiler=self._bot_profiler,
            terrain=self.terrain,
            engine=self.engine,
            seed=self.seed,
            headless=headless,
            eval_goal=self.eval_goal,
        )
        self.actor_bots = bot_runtime.actor_bots
        self._bot_loop_context = bot_runtime.bot_loop_context
        self._physics_step_context = bot_runtime.physics_step_context
        self.trace_recorder = trace_runtime.trace_recorder
        self._bot_loop_context.trace_recorder = self.trace_recorder
        self._plot_events_seen = plot_events_seen
        if self._injected_eval_hooks is None:
            self._eval_hooks = resolved_eval_hooks
        else:
            self._eval_hooks = self._injected_eval_hooks

        self.trace_recorder.set_identity(
            level_name=level_name_tag(self.level),
            scenario_name=level_scenario_tag(self.level) or None,
            seed=self.seed,
            bot_name=resolve_bot_name(self.bot) if self.bot is not None else None,
            eval_goal=self.eval_goal,
        )
        self.trace_recorder.set_trace_root_dir(
            getattr(self.level, "trace_root_dir", None)
        )
        self._eval_hooks.prime_boost_cutoff_for_primary_bot(self.level, self.actor_bots)

        self.level.start(self)
        self._bot_eval_decision: BotEvalDecision | None = None

    def get_active_actor(self) -> Entity:
        actor = self.ecs_world.get_entity_by_id(self.active_player_actor_uid)
        if actor is None:
            raise RuntimeError("Active actor is missing from ECS world")
        return actor

    def _set_active_actor(self, uid: str) -> None:
        actor = set_active_actor(
            actors=self.actors,
            ecs_world=self.ecs_world,
            level=self.level,
            engine=self.engine,
            uid=uid,
        )
        if actor is None:
            return
        self.active_player_actor_uid = uid
        self.lander = actor  # compatibility alias

    def _switch_active_actor(self, delta: int = 1) -> None:
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
            target_size: float | None = None
            get_sites = getattr(self.sites, "get_sites", None)
            if callable(get_sites):
                try:
                    site_iterable = cast(
                        Iterable[Any],
                        get_sites(
                            Range1D.from_center(float(eval_target_pos.x), 1000.0)
                        ),
                    )
                    nearby_sites = list(site_iterable)
                except Exception:
                    nearby_sites = []
                if nearby_sites:
                    nearest_site = min(
                        nearby_sites,
                        key=lambda site: (
                            (float(site.x) - float(eval_target_pos.x)) ** 2
                            + (float(site.y) - float(eval_target_pos.y)) ** 2
                        ),
                    )
                    target_size = float(getattr(nearest_site, "size", 0.0) or 0.0)
            self.trace_recorder.set_target(
                x=float(eval_target_pos.x),
                y=float(eval_target_pos.y),
                label="landing target",
                size=target_size,
            )
        metrics = RunMetricsTracker.from_actor(
            initial_actor,
            start_pos=start_pos,
            eval_target_pos=eval_target_pos,
        )

        def process_input_step(
            frame_dt: float,
        ) -> tuple[tuple[float, float, bool] | None, dict]:
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
                update_bot_steps=lambda timers: update_bot_steps(
                    timers,
                    context=self._bot_loop_context,
                ),
                level_update=lambda dt: self.level.update(self, dt),
                track_plot_events=lambda: self._eval_hooks.track_plot_events(
                    actor_bots=self.actor_bots,
                    ecs_world=self.ecs_world,
                    plotter=self.trace_recorder,
                    events_seen=self._plot_events_seen,
                ),
                render=lambda frame_dt: render_frame(
                    headless=self.headless,
                    renderer=self.renderer,
                    active_bot=active_actor_bot(
                        actor_bots=self.actor_bots,
                        active_uid=self.active_player_actor_uid,
                        primary_bot=self.bot,
                    ),
                    frame_dt=frame_dt,
                    target_fps=TARGET_RENDERING_FPS,
                ),
                print_headless_stats=lambda timers: (
                    self._eval_hooks.print_headless_stats(
                        elapsed_time=timers.elapsed_time,
                        active_actor=self.get_active_actor(),
                        terrain=self.terrain,
                        actor_bots=self.actor_bots,
                    )
                ),
                resolve_headless_bot_eval_decision=lambda: (
                    self._eval_hooks.resolve_headless_bot_eval_decision(
                        headless=self.headless,
                        bot=active_actor_bot(
                            actor_bots=self.actor_bots,
                            active_uid=self.active_player_actor_uid,
                            primary_bot=self.bot,
                        ),
                    )
                ),
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
        self._bot_eval_decision = loop_result.bot_eval_decision
        self._bot_override_timer = loop_result.bot_override_timer
        self._elapsed_time = timers.elapsed_time
        self.run_state.elapsed_time = timers.elapsed_time
        self._landing_count = metrics.landing_count
        self.run_state.landing_count = metrics.landing_count
        self._crash_count = metrics.crash_count
        self.run_state.crash_count = metrics.crash_count
        self._distance_flown = metrics.distance_flown
        self.run_state.distance_flown = metrics.distance_flown
        self._fuel_consumed = metrics.fuel_consumed
        self.run_state.fuel_consumed = metrics.fuel_consumed
        self._overdrive_time = metrics.overdrive_time
        self.run_state.overdrive_time = metrics.overdrive_time
        self._overdrive_excess = metrics.overdrive_excess
        self.run_state.overdrive_excess = metrics.overdrive_excess
        result = self.level.end(self)
        self._eval_hooks.merge_bot_snapshots_into_result(
            actor_bots=self.actor_bots, result=result
        )
        self._eval_hooks.apply_bot_eval_to_result(
            result=result,
            eval_goal=self.eval_goal,
            decision=self._bot_eval_decision,
        )
        final_actor = self.get_active_actor()
        metrics.apply_to_result(
            result,
            elapsed_time=timers.elapsed_time,
            final_actor=final_actor,
            eval_goal=self.eval_goal,
        )
        self._bot_profiler.apply_to_result(result)
        trace_extras = self.trace_recorder.finalize(
            result=result,
            elapsed_time_s=timers.elapsed_time,
        )
        if trace_extras:
            result.update(trace_extras)
        return result

    @property
    def terrain(self):
        if self.level.world is None:
            raise RuntimeError("Level world is not initialized")
        return self.level.world.terrain
