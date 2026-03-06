"""Game orchestration: ECS systems + render loop."""

from __future__ import annotations

import random

from core.bot import Bot, BotEvalDecision
from core.components import Transform
from core.controllers import PlayerController
from core.ecs import Entity, World, require_component
from core.eval_goals import EVAL_GOAL_LANDING, normalize_eval_goal
from core.engine_adapter import EngineAdapter
from core.level import Level
from core.maths import Vector2
from runtime.bootstrap import create_systems
from runtime.actor_session import (
    active_actor_bot,
    attach_primary_bot,
    collect_actor_entities,
    find_initial_player_actor_uid,
    install_world_actor_bots,
    set_active_actor,
    switch_active_actor,
)
from runtime.bot_loop import BotLoopContext, update_bot_steps
from runtime.loop_timing import LoopTimers
from runtime.metrics import BotLoopProfiler, RunMetricsTracker
from runtime.physics_steps import PhysicsStepContext, update_physics_steps
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
from runtime.sensors import (
    build_headless_stats,
    resolve_eval_target_pos,
)
from core.level_capabilities import (
    level_name_tag,
    level_plot_max_side_px,
    level_plot_mode,
    level_plot_output,
    level_scenario_tag,
)
from ui.renderer import Renderer
from levels.common import get_mass
from utils.input import InputHandler
from utils.plot import Plotter
from utils.protocols import ControlTuple

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
        self.sites = self.level.world.sites
        self.engine = getattr(self.level, "engine", None)
        self.engine_adapter = EngineAdapter(self.engine)
        self.engine_adapter.set_primary_actor(self.active_player_actor_uid)

        self.ecs_world = World()
        for actor in self.actors:
            self.ecs_world.add_entity(actor)
        for site_entity in getattr(self.level.world, "site_entities", []):
            self.ecs_world.add_entity(site_entity)
        for extra_entity in getattr(self.level.world, "extra_entities", []):
            self.ecs_world.add_entity(extra_entity)
        self._set_active_actor(self.active_player_actor_uid)

        self.systems = create_systems(
            self.ecs_world,
            terrain=self.terrain,
            sites=self.sites,
            engine_adapter=self.engine_adapter,
        )
        # Compatibility aliases for internal methods.
        self.control_routing_system = self.systems.control_routing
        self.state_transition_system = self.systems.state_transition
        self.scripted_control_system = self.systems.scripted_control
        self.landing_site_motion_system = self.systems.landing_site_motion
        self.landing_site_projection_system = self.systems.landing_site_projection
        self.refuel_system = self.systems.refuel
        self.propulsion_system = self.systems.propulsion
        self.force_application_system = self.systems.force_application
        self.physics_sync_system = self.systems.physics_sync
        self.contact_system = self.systems.contact
        self.sensor_update_system = self.systems.sensor_update

        self.bot_override_delay = 1.0
        self._bot_override_timer = 0.0

        if not headless and InputHandler is not None and Renderer is not None:
            self.input_handler = InputHandler()
            self.renderer = Renderer(self.level, width, height, bot=self.bot)
            self.player_controller = PlayerController()
        else:
            self.input_handler = None
            self.renderer = None
            self.player_controller = None

        self.actor_bots: dict[str, Bot] = {}
        install_world_actor_bots(
            actor_bots=self.actor_bots,
            ecs_world=self.ecs_world,
            world_bots=getattr(self.level.world, "actor_bots", None),
        )
        if self.bot is not None:
            attach_primary_bot(
                actors=self.actors,
                actor_bots=self.actor_bots,
                ecs_world=self.ecs_world,
                active_uid=self.active_player_actor_uid,
                bot=self.bot,
            )
        self._bot_loop_context = BotLoopContext(
            ecs_world=self.ecs_world,
            actor_bots=self.actor_bots,
            sensor_update_system=self.sensor_update_system,
            profiler=self._bot_profiler,
            terrain=self.terrain,
        )
        self._physics_step_context = PhysicsStepContext(
            actors=self.actors,
            engine_adapter=self.engine_adapter,
            scripted_control_system=self.scripted_control_system,
            landing_site_motion_system=self.landing_site_motion_system,
            landing_site_projection_system=self.landing_site_projection_system,
            propulsion_system=self.propulsion_system,
            force_application_system=self.force_application_system,
            physics_sync_system=self.physics_sync_system,
            contact_system=self.contact_system,
            mass_resolver=get_mass,
        )
        if self.renderer is not None:
            self.renderer.bot = self._active_actor_bot()

        self.level.start(self)
        self.plotter = Plotter(
            self.terrain,
            self.lander,
            enabled=self.headless,
            mode=level_plot_mode(self.level),
            output_profile=level_plot_output(self.level),
            max_side_px=level_plot_max_side_px(self.level),
        )
        level_name = level_name_tag(self.level)
        scenario_name = level_scenario_tag(self.level)
        tag_parts = [level_name] if level_name else ["level"]
        if scenario_name and scenario_name != level_name:
            tag_parts.append(scenario_name)
        tag_parts.append(str(self.seed))
        self.plotter.set_selector_tag("_".join(tag_parts))
        self._plot_events_seen: set[tuple[str, str]] = set()
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

    def _active_actor_bot(self) -> Bot | None:
        return active_actor_bot(
            actor_bots=self.actor_bots,
            active_uid=self.active_player_actor_uid,
            primary_bot=self.bot,
        )

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

        self.plotter.set_sampling_from_print_freq(print_freq, TARGET_RENDERING_FPS)
        self.plotter.seed_initial_sample()
        self._plot_events_seen.clear()
        self._bot_eval_decision = None
        self._elapsed_time = 0.0
        initial_actor = self.get_active_actor()
        initial_trans = require_component(initial_actor, Transform)
        start_pos = Vector2(getattr(initial_actor, "start_pos", initial_trans.pos))
        eval_target_pos = resolve_eval_target_pos(self.level, self.sites, start_pos)
        if eval_target_pos is not None:
            self.plotter.set_target(
                x=float(eval_target_pos.x),
                y=float(eval_target_pos.y),
                label="landing target",
            )
        metrics = RunMetricsTracker.from_actor(
            initial_actor,
            start_pos=start_pos,
            eval_target_pos=eval_target_pos,
        )
        loop_result = run_session_loop(
            context=SessionLoopContext(
                headless=self.headless,
                actors=self.actors,
                engine_adapter=self.engine_adapter,
                control_routing_system=self.control_routing_system,
                refuel_system=self.refuel_system,
                state_transition_system=self.state_transition_system,
                sensor_update_system=self.sensor_update_system,
                plotter=self.plotter,
                bot_profiler=self._bot_profiler,
                metrics=metrics,
                bot_override_delay=self.bot_override_delay,
                bot_override_timer=self._bot_override_timer,
                is_running=lambda: self.running,
                active_uid=lambda: self.active_player_actor_uid,
                get_active_actor=self.get_active_actor,
                process_input=self._process_input,
                set_elapsed_time=lambda elapsed: setattr(self, "_elapsed_time", elapsed),
                update_physics_steps=self._update_physics_steps,
                update_bot_steps=self._update_bot_steps,
                level_update=lambda dt: self.level.update(self, dt),
                track_plot_events=self._track_plot_events,
                render=self._render,
                print_headless_stats=self._print_headless_stats,
                resolve_headless_bot_eval_decision=self._resolve_headless_bot_eval_decision,
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
        self._merge_bot_snapshots_into_result(result)
        self._apply_bot_eval_to_result(result)
        final_actor = self.get_active_actor()
        metrics.apply_to_result(
            result,
            elapsed_time=timers.elapsed_time,
            final_actor=final_actor,
            eval_goal=self.eval_goal,
        )
        self._bot_profiler.apply_to_result(result)
        plot_extras = self.plotter.finalize()
        if plot_extras:
            result.update(plot_extras)
        return result

    def _process_input(self, frame_dt: float) -> tuple[ControlTuple | None, dict]:
        result = process_interactive_input(
            headless=self.headless,
            input_handler=self.input_handler,
            renderer=self.renderer,
            player_controller=self.player_controller,
            frame_dt=frame_dt,
            get_active_actor=self.get_active_actor,
            on_reset=self._do_reset,
            on_switch_actor=self._switch_active_actor,
        )
        self.running = result.running
        return result.user_controls, result.input_events

    def _do_reset(self) -> None:
        active_actor = self.get_active_actor()
        self._bot_override_timer = reset_active_actor_session(
            active_actor=active_actor,
            engine_adapter=self.engine_adapter,
            renderer=self.renderer,
            bot_override_delay=self.bot_override_delay,
        )

    def _update_physics_steps(self, timers: LoopTimers) -> None:
        update_physics_steps(timers, context=self._physics_step_context)

    def _update_bot_steps(self, timers: LoopTimers) -> dict[str, ControlTuple | None]:
        return update_bot_steps(timers, context=self._bot_loop_context)

    def _render(self, frame_dt: float) -> float:
        return render_frame(
            headless=self.headless,
            renderer=self.renderer,
            active_bot=self._active_actor_bot(),
            frame_dt=frame_dt,
            target_fps=TARGET_RENDERING_FPS,
        )

    def _print_headless_stats(self, timers: LoopTimers) -> None:
        active_actor = self.get_active_actor()
        parts = [f"t:{timers.elapsed_time:6.2f}"]
        parts.append(build_headless_stats(active_actor, self.terrain))
        for uid, bot in self.actor_bots.items():
            if hasattr(bot, "get_headless_stats"):
                bot_str = bot.get_headless_stats()
                if bot_str:
                    parts.append(f"{uid}:{bot_str}")
        print(" | ".join(parts))

    def _track_plot_events(self) -> None:
        track_plot_events(
            actor_bots=self.actor_bots,
            ecs_world=self.ecs_world,
            plotter=self.plotter,
            events_seen=self._plot_events_seen,
        )

    def _merge_bot_snapshots_into_result(self, result: dict) -> None:
        merge_bot_snapshots_into_result(actor_bots=self.actor_bots, result=result)

    def _resolve_headless_bot_eval_decision(self) -> BotEvalDecision | None:
        return resolve_headless_bot_eval_decision(
            headless=self.headless,
            bot=self._active_actor_bot(),
        )

    def _apply_bot_eval_to_result(self, result: dict) -> None:
        apply_bot_eval_to_result(
            result=result,
            eval_goal=self.eval_goal,
            decision=self._bot_eval_decision,
        )

    @property
    def terrain(self):
        return self.level.world.terrain
