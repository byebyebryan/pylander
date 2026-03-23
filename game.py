"""Game orchestration: ECS systems + render loop."""

from __future__ import annotations

import random

from core.bot import Bot, BotEvalDecision
from core.components import Transform
from core.ecs import Entity, require_component
from core.eval_goals import EVAL_GOAL_LANDING, normalize_eval_goal
from core.level import Level
from core.level_capabilities import level_name_tag, level_scenario_tag
from core.maths import Range1D, Vector2
from runtime.actor_session import (
    active_actor_bot,
    collect_actor_entities,
    find_initial_player_actor_uid,
    set_active_actor,
    switch_active_actor,
)
from runtime.bot_loop import update_bot_steps
from runtime.game_bootstrap import (
    bind_system_aliases,
    bootstrap_bot_runtime,
    bootstrap_core_runtime,
    bootstrap_interactive_runtime,
    bootstrap_trace_runtime,
)
from runtime.headless_stats import print_headless_stats
from runtime.loop_timing import LoopTimers
from runtime.metrics import BotLoopProfiler, RunMetricsTracker
from runtime.physics_steps import update_physics_steps
from runtime.interactive_session import (
    process_interactive_input,
    render_frame,
    reset_active_actor_session,
)
from runtime.plot_events import track_plot_events
from runtime.result_pipeline import (
    apply_bot_eval_to_result,
    merge_bot_snapshots_into_result,
    resolve_headless_bot_eval_decision,
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
    ):
        self.headless = headless
        self.bot = bot
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
        self.level.setup(self, seed)
        self.actors = collect_actor_entities(self.level)
        if not self.actors:
            raise RuntimeError("Level did not provide any actor entities")
        self.active_player_actor_uid = find_initial_player_actor_uid(self.actors)
        self.lander = next(
            (actor for actor in self.actors if actor.uid == self.active_player_actor_uid),
            self.actors[0],
        )
        core_runtime = bootstrap_core_runtime(
            level=self.level,
            actors=self.actors,
            active_uid=self.active_player_actor_uid,
        )
        self.sites = core_runtime.sites
        self.engine = core_runtime.engine
        self.engine_adapter = core_runtime.engine_adapter
        self.ecs_world = core_runtime.ecs_world
        self.systems = core_runtime.systems
        self._set_active_actor(self.active_player_actor_uid)
        bind_system_aliases(self, self.systems)

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

        bot_runtime = bootstrap_bot_runtime(
            actors=self.actors,
            ecs_world=self.ecs_world,
            world_bots=getattr(self.level.world, "actor_bots", None),
            primary_bot=self.bot,
            active_uid=self.active_player_actor_uid,
            sensor_update_system=self.sensor_update_system,
            profiler=self._bot_profiler,
            terrain=self.terrain,
            engine_adapter=self.engine_adapter,
            systems_owner=self,
        )
        self.actor_bots = bot_runtime.actor_bots
        self._bot_loop_context = bot_runtime.bot_loop_context
        self._physics_step_context = bot_runtime.physics_step_context
        if self.renderer is not None:
            self.renderer.bot = active_actor_bot(
                actor_bots=self.actor_bots,
                active_uid=self.active_player_actor_uid,
                primary_bot=self.bot,
            )

        self.level.start(self)
        trace_runtime = bootstrap_trace_runtime(
            terrain=self.terrain,
            ecs_world=self.ecs_world,
            actor_bots=self.actor_bots,
            active_uid_getter=lambda: self.active_player_actor_uid,
            headless=self.headless,
            level=self.level,
            seed=self.seed,
        )
        self.trace_recorder = trace_runtime.trace_recorder
        self.trace_recorder.set_identity(
            level_name=level_name_tag(self.level),
            scenario_name=level_scenario_tag(self.level) or None,
            seed=self.seed,
            bot_name=getattr(self.bot, "_bot_name", None),
            eval_goal=self.eval_goal,
        )
        self.trace_recorder.set_trace_root_dir(getattr(self.level, "trace_root_dir", None))
        self._bot_loop_context.trace_recorder = self.trace_recorder
        self._plot_events_seen = trace_runtime.events_seen
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
            engine_adapter=self.engine_adapter,
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
            engine_adapter=self.engine_adapter,
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
        initial_actor = self.get_active_actor()
        initial_trans = require_component(initial_actor, Transform)
        start_pos = Vector2(getattr(initial_actor, "start_pos", initial_trans.pos))
        eval_target_pos = resolve_eval_target_pos(self.level, self.sites, start_pos)
        if eval_target_pos is not None:
            target_size: float | None = None
            get_sites = getattr(self.sites, "get_sites", None)
            if callable(get_sites):
                try:
                    nearby_sites = list(get_sites(Range1D.from_center(float(eval_target_pos.x), 1000.0)))
                except Exception:
                    nearby_sites = []
                if nearby_sites:
                    nearest_site = min(
                        nearby_sites,
                        key=lambda site: (float(site.x) - float(eval_target_pos.x)) ** 2
                        + (float(site.y) - float(eval_target_pos.y)) ** 2,
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
        def process_input_step(frame_dt: float) -> tuple[tuple[float, float, bool] | None, dict]:
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
                        engine_adapter=self.engine_adapter,
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
                engine_adapter=self.engine_adapter,
                control_routing_system=self.control_routing_system,
                refuel_system=self.refuel_system,
                state_transition_system=self.state_transition_system,
                sensor_update_system=self.sensor_update_system,
                trace_recorder=self.trace_recorder,
                bot_profiler=self._bot_profiler,
                metrics=metrics,
                bot_override_delay=self.bot_override_delay,
                bot_override_timer=self._bot_override_timer,
                is_running=lambda: self.running,
                active_uid=lambda: self.active_player_actor_uid,
                get_active_actor=self.get_active_actor,
                process_input=process_input_step,
                set_elapsed_time=lambda elapsed: setattr(self, "_elapsed_time", elapsed),
                update_physics_steps=lambda timers: update_physics_steps(
                    timers,
                    context=self._physics_step_context,
                ),
                update_bot_steps=lambda timers: update_bot_steps(
                    timers,
                    context=self._bot_loop_context,
                ),
                level_update=lambda dt: self.level.update(self, dt),
                track_plot_events=lambda: track_plot_events(
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
                print_headless_stats=lambda timers: print_headless_stats(
                    elapsed_time=timers.elapsed_time,
                    active_actor=self.get_active_actor(),
                    terrain=self.terrain,
                    actor_bots=self.actor_bots,
                ),
                resolve_headless_bot_eval_decision=lambda: resolve_headless_bot_eval_decision(
                    headless=self.headless,
                    bot=active_actor_bot(
                        actor_bots=self.actor_bots,
                        active_uid=self.active_player_actor_uid,
                        primary_bot=self.bot,
                    ),
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
        self._landing_count = metrics.landing_count
        self._crash_count = metrics.crash_count
        self._distance_flown = metrics.distance_flown
        self._fuel_consumed = metrics.fuel_consumed
        self._overdrive_time = metrics.overdrive_time
        self._overdrive_excess = metrics.overdrive_excess
        result = self.level.end(self)
        merge_bot_snapshots_into_result(actor_bots=self.actor_bots, result=result)
        apply_bot_eval_to_result(
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
        return self.level.world.terrain
