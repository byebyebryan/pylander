"""Game orchestration: ECS systems + render loop."""

from __future__ import annotations

import random

from core.bot import Bot
from core.components import (
    ActorControlRole,
    ControlIntent,
    Engine,
    FuelTank,
    LanderState,
    PlayerControlled,
    PlayerSelectable,
    PhysicsState,
    Transform,
)
from core.controllers import PlayerController
from core.ecs import Entity, World, require_component
from core.engine_adapter import EngineAdapter
from core.level import Level
from core.maths import Vector2
from runtime.bootstrap import create_systems
from runtime.bot_loop import BotLoopContext, update_bot_steps
from runtime.loop_timing import LoopTimers
from runtime.metrics import BotLoopProfiler, RunMetricsTracker
from runtime.sensors import (
    build_headless_stats,
    build_vehicle_info,
    resolve_eval_target_pos,
)
from core.level_capabilities import level_name_tag, level_plot_mode, level_scenario_tag
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


def _reset_lander_entity(entity) -> None:
    trans = require_component(entity, Transform)
    phys = require_component(entity, PhysicsState)
    tank = require_component(entity, FuelTank)
    eng = require_component(entity, Engine)
    ls = require_component(entity, LanderState)
    intent = require_component(entity, ControlIntent)
    start_pos = getattr(entity, "start_pos", Vector2(0.0, 0.0))
    trans.pos = Vector2(start_pos)
    trans.rotation = 0.0
    phys.vel.update(0.0, 0.0)
    phys.acc.update(0.0, 0.0)
    tank.fuel = tank.max_fuel
    eng.thrust_level = 0.0
    eng.target_thrust = 0.0
    eng.target_angle = 0.0
    ls.state = "flying"
    intent.target_thrust = None
    intent.target_angle = None
    intent.refuel_requested = False
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
        bot_profile_enabled: bool | None = None,
        bot_profile_interval_s: float | None = None,
        bot_profile_log_lines: bool | None = None,
    ):
        self.headless = headless
        self.bot = bot
        self.level = level
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
        self.actors = self._collect_actor_entities()
        if not self.actors:
            raise RuntimeError("Level did not provide any actor entities")
        self.active_player_actor_uid = self._find_initial_player_actor_uid()
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
        world_bots = getattr(self.level.world, "actor_bots", None)
        if isinstance(world_bots, dict):
            for uid, actor_bot in world_bots.items():
                if isinstance(actor_bot, Bot):
                    self.actor_bots[uid] = actor_bot
        if self.bot is not None:
            bot_uid = self._find_first_actor_for_role("bot")
            if bot_uid is None:
                bot_uid = next(
                    (a.uid for a in self.actors if a.uid != self.active_player_actor_uid),
                    self.active_player_actor_uid,
                )
            if bot_uid is not None:
                self.actor_bots[bot_uid] = self.bot
        for uid, actor_bot in list(self.actor_bots.items()):
            actor = self.ecs_world.get_entity_by_id(uid)
            if actor is None:
                continue
            self._install_actor_bot(uid, actor, actor_bot)
        self._bot_loop_context = BotLoopContext(
            ecs_world=self.ecs_world,
            actor_bots=self.actor_bots,
            sensor_update_system=self.sensor_update_system,
            profiler=self._bot_profiler,
            terrain=self.terrain,
            engine_adapter=self.engine_adapter,
        )
        if self.renderer is not None:
            self.renderer.bot = self._active_actor_bot()

        self.level.start(self)
        self.plotter = Plotter(
            self.terrain,
            self.lander,
            enabled=self.headless,
            mode=level_plot_mode(self.level),
        )
        level_name = level_name_tag(self.level)
        scenario_name = level_scenario_tag(self.level)
        tag_parts = [level_name] if level_name else ["level"]
        if scenario_name and scenario_name != level_name:
            tag_parts.append(scenario_name)
        tag_parts.append(str(self.seed))
        self.plotter.set_selector_tag("_".join(tag_parts))
        self._plot_events_seen: set[tuple[str, str]] = set()

    def _collect_actor_entities(self) -> list[Entity]:
        world = self.level.world
        actors = list(getattr(world, "actors", []) or [])
        if not actors and getattr(world, "lander", None) is not None:
            actors = [world.lander]
        return actors

    @staticmethod
    def _get_actor_control_role(entity: Entity) -> str:
        role = entity.get_component(ActorControlRole)
        if role is None:
            return "none"
        return role.role

    def _find_first_actor_for_role(self, role: str) -> str | None:
        for actor in self.actors:
            if self._get_actor_control_role(actor) == role:
                return actor.uid
        return None

    def _find_initial_player_actor_uid(self) -> str:
        # Explicitly selected actor wins first.
        for actor in self.actors:
            selected = actor.get_component(PlayerControlled)
            if selected is not None and selected.active:
                return actor.uid

        # Otherwise pick the first selectable actor by declared order.
        selectable: list[tuple[int, str]] = []
        for actor in self.actors:
            marker = actor.get_component(PlayerSelectable)
            if marker is not None:
                selectable.append((marker.order, actor.uid))
        if selectable:
            selectable.sort(key=lambda item: item[0])
            return selectable[0][1]

        return self.actors[0].uid

    def get_active_actor(self) -> Entity:
        actor = self.ecs_world.get_entity_by_id(self.active_player_actor_uid)
        if actor is None:
            raise RuntimeError("Active actor is missing from ECS world")
        return actor

    def _set_active_actor(self, uid: str) -> None:
        if self.ecs_world.get_entity_by_id(uid) is None:
            return
        for actor in self.actors:
            marker = actor.get_component(PlayerControlled)
            is_active = actor.uid == uid
            if marker is None and is_active:
                actor.add_component(PlayerControlled(active=True))
            elif marker is not None:
                marker.active = is_active
        self.active_player_actor_uid = uid
        self.lander = self.get_active_actor()  # compatibility alias
        if getattr(self.level, "world", None) is not None:
            self.level.world.primary_actor_uid = uid
            self.level.world.lander = self.lander
        self.engine_adapter.set_primary_actor(uid)

    def _switch_active_actor(self, delta: int = 1) -> None:
        selectable: list[tuple[int, str]] = []
        for actor in self.actors:
            marker = actor.get_component(PlayerSelectable)
            if marker is not None:
                selectable.append((marker.order, actor.uid))
        if not selectable:
            return
        selectable.sort(key=lambda item: item[0])
        ordered_ids = [uid for _, uid in selectable]
        if self.active_player_actor_uid not in ordered_ids:
            self._set_active_actor(ordered_ids[0])
            return
        idx = ordered_ids.index(self.active_player_actor_uid)
        next_uid = ordered_ids[(idx + delta) % len(ordered_ids)]
        self._set_active_actor(next_uid)

    def _active_actor_bot(self) -> Bot | None:
        active_uid = self.active_player_actor_uid
        if active_uid in self.actor_bots:
            return self.actor_bots[active_uid]
        return self.bot

    def _ensure_bot_identity_fields(self, bot: Bot) -> None:
        bot_name = getattr(bot, "_bot_name", None)
        if not isinstance(bot_name, str) or not bot_name:
            setattr(bot, "_bot_name", bot.__class__.__module__.split(".")[-1])

    def _install_actor_bot(
        self,
        uid: str,
        actor: Entity,
        bot: Bot,
    ) -> None:
        self.actor_bots[uid] = bot
        self._ensure_bot_identity_fields(bot)
        if hasattr(bot, "set_vehicle_info"):
            bot.set_vehicle_info(build_vehicle_info(actor))

    def run(
        self,
        print_freq: int = 60,
        max_time: float | None = None,
        max_steps: int | None = None,
    ):
        physics_dt = 1.0 / PHYSICS_FPS
        bot_dt = 1.0 / BOT_FPS
        step_count = 0
        frame_dt = 1.0 / TARGET_RENDERING_FPS
        timers = LoopTimers(physics_dt=physics_dt, bot_dt=bot_dt, frame_dt=frame_dt)

        self.plotter.set_sampling_from_print_freq(print_freq, TARGET_RENDERING_FPS)
        self.plotter.seed_initial_sample()
        self._plot_events_seen.clear()
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
        controls_by_uid: dict[str, ControlTuple | None] = {}
        state_before: dict[str, str] = {}

        while self.running:
            if self.headless and max_time is not None and timers.elapsed_time >= max_time:
                break
            if max_steps is not None and step_count >= max_steps:
                break

            user_controls, _ = self._process_input(frame_dt)
            if not self.running:
                break

            timers.advance_frame(frame_dt)
            self._elapsed_time = timers.elapsed_time

            self._update_physics_steps(timers)
            bot_controls = self._update_bot_steps(timers)
            if self._bot_profiler.enabled:
                for line in self._bot_profiler.maybe_report_lines(timers.elapsed_time):
                    print(line)

            if user_controls is not None:
                self._bot_override_timer = self.bot_override_delay
            else:
                self._bot_override_timer = max(0.0, self._bot_override_timer - frame_dt)

            controls_by_uid.clear()
            if user_controls is not None:
                controls_by_uid[self.active_player_actor_uid] = user_controls
            if self._bot_override_timer == 0.0:
                for uid, controls in bot_controls.items():
                    # Human input only suppresses bot control on the currently active actor.
                    if uid == self.active_player_actor_uid and user_controls is not None:
                        continue
                    controls_by_uid[uid] = controls

            state_before.clear()
            for actor in self.actors:
                ls = actor.get_component(LanderState)
                if ls is not None:
                    state_before[actor.uid] = ls.state

            self.control_routing_system.set_controls_map(controls_by_uid)
            self.control_routing_system.update(frame_dt)
            self.refuel_system.update(frame_dt)
            self.state_transition_system.update(frame_dt)

            if self.engine_adapter.enabled:
                for actor in self.actors:
                    before = state_before.get(actor.uid)
                    ls = actor.get_component(LanderState)
                    trans = actor.get_component(Transform)
                    if before != "landed" or ls is None or trans is None:
                        continue
                    if ls.state == "flying":
                        self.engine_adapter.teleport_lander(
                            trans.pos,
                            angle=trans.rotation,
                            clear_velocity=True,
                            uid=actor.uid,
                        )

            self.sensor_update_system.update(frame_dt)
            self.level.update(self, frame_dt)
            self._track_plot_events()
            self.plotter.update(frame_dt)
            frame_dt = self._render(frame_dt)
            step_count += 1

            if self.headless and print_freq > 0 and step_count % print_freq == 0:
                self._print_headless_stats(timers)

            active_actor = self.get_active_actor()
            metrics.update_for_actor(active_actor, dt_used=max(0.0, float(frame_dt)))
            metrics.update_state_counters(active_actor, elapsed_time=timers.elapsed_time)

            if self.level.should_end(self):
                break

        if self.renderer:
            self.renderer.shutdown()

        self._elapsed_time = timers.elapsed_time
        self._landing_count = metrics.landing_count
        self._crash_count = metrics.crash_count
        self._distance_flown = metrics.distance_flown
        self._fuel_consumed = metrics.fuel_consumed
        self._overdrive_time = metrics.overdrive_time
        self._overdrive_excess = metrics.overdrive_excess
        result = self.level.end(self)
        self._merge_bot_snapshots_into_result(result)
        final_actor = self.get_active_actor()
        metrics.apply_to_result(
            result,
            elapsed_time=timers.elapsed_time,
            final_actor=final_actor,
        )
        self._bot_profiler.apply_to_result(result)
        plot_extras = self.plotter.finalize()
        if plot_extras:
            result.update(plot_extras)
        return result

    def _process_input(self, frame_dt: float) -> tuple[ControlTuple | None, dict]:
        if self.headless or self.input_handler is None:
            return None, {}

        input_events = self.input_handler.get_events()
        if input_events.get("quit"):
            self.running = False
            return None, input_events

        if input_events.get("reset"):
            self._do_reset()
            input_events = {**input_events, "reset": False}
        if input_events.get("switch_actor"):
            self._switch_active_actor()
            input_events = {**input_events, "switch_actor": False}

        user_controls = None
        active_actor = self.get_active_actor()
        ls = require_component(active_actor, LanderState)
        eng = require_component(active_actor, Engine)
        if ls.state in ("flying", "landed") and self.player_controller is not None:
            user_controls = self.player_controller.update(
                input_events,
                frame_dt,
                eng.target_thrust,
                eng.max_thrust,
                eng.target_angle,
                eng.max_rotation_rate,
            )

        if self.renderer is not None:
            cam = self.renderer.main_camera
            if hasattr(cam, "handle_input"):
                cam.handle_input(input_events, frame_dt)
            if input_events.get("toggle_ballistic"):
                toggle_ballistic = getattr(self.renderer, "toggle_ballistic_overlay", None)
                if callable(toggle_ballistic):
                    toggle_ballistic()

        return user_controls, input_events

    def _do_reset(self) -> None:
        active_actor = self.get_active_actor()
        _reset_lander_entity(active_actor)
        trans = require_component(active_actor, Transform)
        if self.engine_adapter.enabled:
            self.engine_adapter.teleport_lander(
                trans.pos,
                angle=trans.rotation,
                clear_velocity=True,
                uid=active_actor.uid,
            )
        if self.renderer is not None:
            cam = self.renderer.main_camera
            cam.x = trans.pos.x
            cam.y = trans.pos.y
            cam.zoom = 2.0
        self._bot_override_timer = self.bot_override_delay

    def _update_physics_steps(self, timers: LoopTimers) -> None:
        physics_dt = timers.physics_dt
        while timers.should_step_physics():
            timers.consume_physics()
            self.scripted_control_system.update(physics_dt)
            self.landing_site_motion_system.update(physics_dt)
            self.landing_site_projection_system.update(physics_dt)
            self.propulsion_system.update(physics_dt)
            self.force_application_system.update(physics_dt)
            if self.engine_adapter.enabled:
                self._sync_actor_masses_to_engine()
                self.engine_adapter.step(physics_dt)
                self.physics_sync_system.update(physics_dt)
                self.contact_system.update(physics_dt)

    def _sync_actor_masses_to_engine(self) -> None:
        for actor in self.actors:
            self.engine_adapter.set_actor_mass(actor.uid, get_mass(actor))

    def _update_bot_steps(self, timers: LoopTimers) -> dict[str, ControlTuple | None]:
        return update_bot_steps(timers, context=self._bot_loop_context)

    def _render(self, frame_dt: float) -> float:
        if not self.headless and self.renderer is not None:
            self.renderer.bot = self._active_actor_bot()
            self.renderer.update(frame_dt)
            self.renderer.draw()
            return self.renderer.tick(TARGET_RENDERING_FPS)
        return 1.0 / TARGET_RENDERING_FPS

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
        for uid, bot in self.actor_bots.items():
            get_snapshot = getattr(bot, "get_evaluation_snapshot", None)
            if not callable(get_snapshot):
                continue
            try:
                snapshot = get_snapshot()
            except Exception:
                continue
            if not isinstance(snapshot, dict):
                continue
            if str(snapshot.get("kind", "")).strip().lower() != "zem_zev":
                continue
            actor = self.ecs_world.get_entity_by_id(uid)
            if actor is None:
                continue
            trans = actor.get_component(Transform)
            if trans is None:
                continue
            for event_name, done_key, projected_dx_key in (
                ("setup_gate", "setup_gate_done", "setup_gate_projected_dx"),
                ("flare_gate", "terminal_gate_done", "terminal_gate_projected_dx"),
            ):
                if not bool(snapshot.get(done_key)):
                    continue
                event_key = (uid, event_name)
                if event_key in self._plot_events_seen:
                    continue
                label = event_name.replace("_", " ")
                projected_dx = snapshot.get(projected_dx_key)
                try:
                    projected_dx_val = float(projected_dx) if projected_dx is not None else None
                except (TypeError, ValueError):
                    projected_dx_val = None
                if projected_dx_val is not None:
                    label = f"{label} pdx={projected_dx_val:.1f}"
                self.plotter.mark_event(
                    name=event_name,
                    x=float(trans.pos.x),
                    y=float(trans.pos.y),
                    label=label,
                )
                self._plot_events_seen.add(event_key)

    def _merge_bot_snapshots_into_result(self, result: dict) -> None:
        for bot in self.actor_bots.values():
            get_snapshot = getattr(bot, "get_evaluation_snapshot", None)
            if not callable(get_snapshot):
                continue
            try:
                snapshot = get_snapshot()
            except Exception:
                continue
            if not isinstance(snapshot, dict):
                continue
            if str(snapshot.get("kind", "")).strip().lower() != "zem_zev":
                continue
            for key, value in snapshot.items():
                if key == "kind":
                    continue
                out_key = key if str(key).startswith("zem_") else f"zem_{key}"
                result.setdefault(out_key, value)

    @property
    def terrain(self):
        return self.level.world.terrain
