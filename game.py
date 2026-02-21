"""Game orchestration: ECS systems + render loop."""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Type, TypeVar

from core.bot import Bot, BotAction, PassiveSensors, VehicleInfo, _ActiveSensorImpl
from core.components import (
    ControlIntent,
    Engine,
    FuelTank,
    LanderGeometry,
    LanderState,
    PhysicsState,
    Radar,
    RefuelConfig,
    SensorReadings,
    Transform,
)
from core.controllers import PlayerController
from core.ecs import World
from core.engine_adapter import EngineAdapter
from core.level import Level
from core.maths import Vector2
from core.systems.contact import ContactSystem
from core.systems.control_routing import ControlRoutingSystem
from core.systems.force_application import ForceApplicationSystem
from core.systems.landing_site_motion import LandingSiteMotionSystem
from core.systems.landing_site_projection import LandingSiteProjectionSystem
from core.systems.physics_sync import PhysicsSyncSystem
from core.systems.propulsion import PropulsionSystem
from core.systems.refuel import RefuelSystem
from core.systems.sensor_update import SensorUpdateSystem
from core.systems.state_transition import StateTransitionSystem
from ui.renderer import Renderer
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

T = TypeVar("T")


def _require_component(entity, component_type: Type[T]) -> T:
    comp = entity.get_component(component_type)
    if comp is None:
        raise RuntimeError(f"Entity {entity.uid} missing component {component_type.__name__}")
    return comp


def _get_mass(entity) -> float:
    phys = _require_component(entity, PhysicsState)
    tank = _require_component(entity, FuelTank)
    return phys.mass + tank.fuel * tank.density


def _build_vehicle_info(entity) -> VehicleInfo:
    geo = _require_component(entity, LanderGeometry)
    phys = _require_component(entity, PhysicsState)
    tank = _require_component(entity, FuelTank)
    eng = _require_component(entity, Engine)
    ls = _require_component(entity, LanderState)
    radar = _require_component(entity, Radar)
    refuel = _require_component(entity, RefuelConfig)
    return VehicleInfo(
        width=geo.width,
        height=geo.height,
        dry_mass=phys.mass,
        fuel_density=tank.density,
        max_thrust_power=eng.max_power,
        safe_landing_velocity=ls.safe_landing_velocity,
        safe_landing_angle=ls.safe_landing_angle,
        radar_outer_range=radar.outer_range,
        radar_inner_range=radar.inner_range,
        proximity_sensor_range=refuel.proximity_sensor_range,
    )


def _build_active_sensors(entity, engine_adapter):
    trans = _require_component(entity, Transform)
    radar = _require_component(entity, Radar)
    return _ActiveSensorImpl(
        origin_fn=lambda: Vector2(trans.pos),
        radar_range_fn=lambda: radar.inner_range,
        engine_adapter=engine_adapter,
    )


def _build_passive_sensors(entity) -> PassiveSensors:
    trans = _require_component(entity, Transform)
    phys = _require_component(entity, PhysicsState)
    tank = _require_component(entity, FuelTank)
    eng = _require_component(entity, Engine)
    ls = _require_component(entity, LanderState)
    readings = _require_component(entity, SensorReadings)
    return PassiveSensors(
        altitude=trans.pos.y,
        vx=phys.vel.x,
        vy_up=phys.vel.y,
        angle=trans.rotation,
        ax=phys.acc.x,
        ay_up=phys.acc.y,
        mass=_get_mass(entity),
        thrust_level=eng.thrust_level,
        fuel=tank.fuel,
        state=ls.state,
        radar_contacts=readings.radar_contacts,
        proximity=readings.proximity,
    )


def _build_headless_stats(entity, terrain) -> str:
    trans = _require_component(entity, Transform)
    phys = _require_component(entity, PhysicsState)
    eng = _require_component(entity, Engine)
    tank = _require_component(entity, FuelTank)
    altitude = trans.pos.y - terrain(trans.pos.x)
    angle_deg = math.degrees(trans.rotation)
    thrust_pct = eng.thrust_level * 100.0
    return (
        f"x:{trans.pos.x:6.1f} alt:{altitude:6.1f} | "
        f"vx:{phys.vel.x:6.2f} vy:{phys.vel.y:6.2f} | "
        f"ang:{angle_deg:5.1f} thr:{thrust_pct:3.0f}% | "
        f"fuel:{tank.fuel:5.1f}%"
    )


def _reset_lander_entity(entity) -> None:
    trans = _require_component(entity, Transform)
    phys = _require_component(entity, PhysicsState)
    tank = _require_component(entity, FuelTank)
    eng = _require_component(entity, Engine)
    ls = _require_component(entity, LanderState)
    intent = _require_component(entity, ControlIntent)
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


@dataclass
class LoopTimers:
    physics_dt: float
    bot_dt: float
    frame_dt: float
    time_accum_physics: float = 0.0
    time_accum_bot: float = 0.0
    elapsed_time: float = 0.0

    def advance_frame(self, dt: float) -> None:
        self.frame_dt = dt
        self.time_accum_physics += dt
        self.time_accum_bot += dt
        self.elapsed_time += dt

    def should_step_physics(self) -> bool:
        return self.time_accum_physics >= self.physics_dt

    def should_step_bot(self) -> bool:
        return self.time_accum_bot >= self.bot_dt

    def consume_physics(self) -> None:
        self.time_accum_physics -= self.physics_dt

    def consume_bot(self) -> None:
        self.time_accum_bot -= self.bot_dt


class LanderGame:
    """Main application for lunar lander game."""

    def __init__(
        self,
        level: Level,
        width: int = DEFAULT_SCREEN_WIDTH,
        height: int = DEFAULT_SCREEN_HEIGHT,
        seed: int = None,
        bot: Bot | None = None,
        headless: bool = False,
    ):
        self.headless = headless
        self.bot = bot
        self.level = level
        seed = random.randint(0, 1000000) if seed is None else seed

        if headless and not bot:
            raise ValueError("Headless mode requires a bot")

        self.running = True
        self.level.setup(self, seed)
        self.lander = self.level.world.lander
        self.sites = self.level.world.sites
        self.engine = getattr(self.level, "engine", None)
        self.engine_adapter = EngineAdapter(self.engine)

        self.ecs_world = World()
        self.ecs_world.add_entity(self.lander)
        for site_entity in getattr(self.level.world, "site_entities", []):
            self.ecs_world.add_entity(site_entity)

        self.control_routing_system = ControlRoutingSystem()
        self.state_transition_system = StateTransitionSystem()
        self.landing_site_motion_system = LandingSiteMotionSystem()
        self.landing_site_projection_system = LandingSiteProjectionSystem(self.sites)
        self.refuel_system = RefuelSystem(self.sites)
        self.propulsion_system = PropulsionSystem()
        self.force_application_system = ForceApplicationSystem(self.engine_adapter)
        self.physics_sync_system = PhysicsSyncSystem(self.engine_adapter)
        self.contact_system = ContactSystem(self.engine_adapter, self.sites)
        self.sensor_update_system = SensorUpdateSystem(self.terrain, self.sites)

        for system in (
            self.control_routing_system,
            self.state_transition_system,
            self.landing_site_motion_system,
            self.landing_site_projection_system,
            self.refuel_system,
            self.propulsion_system,
            self.force_application_system,
            self.physics_sync_system,
            self.contact_system,
            self.sensor_update_system,
        ):
            system.world = self.ecs_world

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

        if self.bot is not None and hasattr(self.bot, "set_vehicle_info"):
            self.bot.set_vehicle_info(_build_vehicle_info(self.lander))

        self.level.start(self)
        self.plotter = Plotter(
            self.terrain,
            self.lander,
            enabled=self.headless,
            mode=getattr(self.level, "plot_mode", "none"),
        )

    def run(
        self,
        print_freq: int = 60,
        max_time: float | None = None,
        max_steps: int | None = None,
    ):
        physics_dt = 1.0 / PHYSICS_FPS
        bot_dt = 1.0 / BOT_FPS
        step_count = 0
        landing_count = 0
        crash_count = 0
        prev_state = None
        frame_dt = 1.0 / TARGET_RENDERING_FPS
        timers = LoopTimers(physics_dt=physics_dt, bot_dt=bot_dt, frame_dt=frame_dt)

        self.plotter.set_sampling_from_print_freq(print_freq, TARGET_RENDERING_FPS)
        self.plotter.seed_initial_sample()
        self._elapsed_time = 0.0

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

            if user_controls is not None:
                self._bot_override_timer = self.bot_override_delay
            else:
                self._bot_override_timer = max(0.0, self._bot_override_timer - frame_dt)

            if user_controls is not None:
                controls = user_controls
            elif self._bot_override_timer == 0.0 and bot_controls is not None:
                controls = bot_controls
            else:
                controls = (None, None, False)

            ls = _require_component(self.lander, LanderState)
            trans = _require_component(self.lander, Transform)
            state_before = ls.state

            self.control_routing_system.set_controls(controls)
            self.control_routing_system.update(frame_dt)
            self.refuel_system.update(frame_dt)
            self.state_transition_system.update(frame_dt)

            if (
                self.engine_adapter.enabled
                and state_before == "landed"
                and ls.state == "flying"
            ):
                self.engine_adapter.teleport_lander(
                    trans.pos,
                    angle=trans.rotation,
                    clear_velocity=True,
                )

            self.sensor_update_system.update(frame_dt)
            self.level.update(self, frame_dt)
            self.plotter.update(frame_dt)
            frame_dt = self._render(frame_dt)

            if self.headless and print_freq > 0 and step_count % print_freq == 0:
                self._print_headless_stats(timers)

            step_count += 1
            state = ls.state
            if state != prev_state:
                if state == "landed":
                    landing_count += 1
                elif state == "crashed":
                    crash_count += 1
                prev_state = state

            if self.level.should_end(self):
                break

        if self.renderer:
            self.renderer.shutdown()

        self._elapsed_time = timers.elapsed_time
        self._landing_count = landing_count
        self._crash_count = crash_count
        result = self.level.end(self)
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

        user_controls = None
        ls = _require_component(self.lander, LanderState)
        eng = _require_component(self.lander, Engine)
        if ls.state in ("flying", "landed") and self.player_controller is not None:
            user_controls = self.player_controller.update(
                input_events,
                frame_dt,
                eng.target_thrust,
                eng.target_angle,
                eng.max_rotation_rate,
            )

        if self.renderer is not None:
            cam = self.renderer.main_camera
            if hasattr(cam, "handle_input"):
                cam.handle_input(input_events, frame_dt)

        return user_controls, input_events

    def _do_reset(self) -> None:
        _reset_lander_entity(self.lander)
        trans = _require_component(self.lander, Transform)
        if self.engine_adapter.enabled:
            self.engine_adapter.teleport_lander(
                trans.pos,
                angle=trans.rotation,
                clear_velocity=True,
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
            self.landing_site_motion_system.update(physics_dt)
            self.landing_site_projection_system.update(physics_dt)
            self.propulsion_system.update(physics_dt)
            self.force_application_system.update(physics_dt)
            if self.engine_adapter.enabled:
                self.engine_adapter.step(physics_dt)
                self.physics_sync_system.update(physics_dt)
                self.contact_system.update(physics_dt)

    def _update_bot_steps(self, timers: LoopTimers) -> ControlTuple | None:
        bot_controls = None
        bot_dt = timers.bot_dt
        while timers.should_step_bot():
            timers.consume_bot()
            if self.bot:
                self.sensor_update_system.update(bot_dt)
                passive_sensors = _build_passive_sensors(self.lander)
                active_sensors = _build_active_sensors(self.lander, self.engine_adapter)
                action: BotAction = self.bot.update(bot_dt, passive_sensors, active_sensors)
                bot_controls = (action.target_thrust, action.target_angle, action.refuel)
        return bot_controls

    def _render(self, frame_dt: float) -> float:
        if not self.headless and self.renderer is not None:
            self.renderer.update(frame_dt)
            self.renderer.draw()
            return self.renderer.tick(TARGET_RENDERING_FPS)
        return 1.0 / TARGET_RENDERING_FPS

    def _print_headless_stats(self, timers: LoopTimers) -> None:
        parts = [f"t:{timers.elapsed_time:6.2f}"]
        parts.append(_build_headless_stats(self.lander, self.terrain))
        if self.bot and hasattr(self.bot, "get_headless_stats"):
            bot_str = self.bot.get_headless_stats()
            if bot_str:
                parts.append(bot_str)
        print(" | ".join(parts))

    @property
    def terrain(self):
        return self.level.world.terrain
