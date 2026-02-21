"""Game orchestration: ties systems together and runs the loop."""

import random
from dataclasses import dataclass
from utils.input import InputHandler
from ui.renderer import Renderer
from core.bot import Bot, BotAction
from core.level import Level
from utils.plot import Plotter
from core.engine_adapter import EngineAdapter
from utils.protocols import ControlTuple
from core.controllers import PlayerController


# Centralized game defaults
from core.config import (
    DEFAULT_SCREEN_WIDTH,
    DEFAULT_SCREEN_HEIGHT,
    TARGET_RENDERING_FPS,
    PHYSICS_FPS,
    BOT_FPS,
)


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


from core.ecs import World
from core.systems.propulsion import PropulsionSystem
from core.systems.force_application import ForceApplicationSystem
from core.systems.physics_sync import PhysicsSyncSystem
from core.systems.contact import ContactSystem

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

        # Game no longer owns screen/clock; renderer manages display

        self.running = True

        # Economy/config now lives on the lander

        # Core systems configured by level
        self.level.setup(self, seed)
        # Expose lander reference for game-managed IO; still level-owned
        self.lander = self.level.world.lander
        # Optional physics engine provided by the level
        self.engine = getattr(self.level, "engine", None)
        self.engine_adapter = EngineAdapter(self.engine)

        # ECS World — pure entity/component registry; systems are called explicitly
        self.ecs_world = World()
        self.ecs_world.add_entity(self.lander)

        # Systems stored as named attributes and called in explicit order each physics step
        self.propulsion_system = PropulsionSystem()
        self.propulsion_system.world = self.ecs_world
        self.force_application_system = ForceApplicationSystem(self.engine_adapter)
        self.force_application_system.world = self.ecs_world
        self.physics_sync_system = PhysicsSyncSystem(self.engine_adapter)
        self.physics_sync_system.world = self.ecs_world
        self.contact_system = ContactSystem(self.engine_adapter, None)  # targets set after level.setup
        self.contact_system.world = self.ecs_world

        # Wire targets into ContactSystem now that level.setup() has run
        self.contact_system.targets = self.targets

        self.bot_override_delay = 1.0
        self._bot_override_timer = 0.0

        # Input/Renderer
        if not headless and InputHandler is not None and Renderer is not None:
            self.input_handler = InputHandler()
            self.renderer = Renderer(self.level, width, height, bot=self.bot)
            self.player_controller = PlayerController()
        else:
            self.input_handler = None
            self.renderer = None
            self.player_controller = None

        # Pass static vehicle info to bot if available
        if self.bot is not None and hasattr(self.bot, "set_vehicle_info"):
            self.bot.set_vehicle_info(self.lander.get_vehicle_info())

        # Level start hook
        self.level.start(self)

        # Headless plotter (handles sampling and file output)
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
        # Fixed update rates
        physics_dt = 1.0 / PHYSICS_FPS
        bot_dt = 1.0 / BOT_FPS

        step_count = 0

        # Event counters (exposed for level)
        landing_count = 0
        crash_count = 0
        prev_state = None

        # For headless timing when no pygame clock
        frame_dt = 1.0 / TARGET_RENDERING_FPS
        timers = LoopTimers(physics_dt=physics_dt, bot_dt=bot_dt, frame_dt=frame_dt)

        # Configure and seed plot sampling
        self.plotter.set_sampling_from_print_freq(print_freq, TARGET_RENDERING_FPS)
        self.plotter.seed_initial_sample()

        self._elapsed_time = 0.0

        while self.running:
            # Prefer time limit in headless mode
            if self.headless:
                if max_time is not None and timers.elapsed_time >= max_time:
                    break
            if max_steps is not None and step_count >= max_steps:
                break

            # Frame timing and event processing
            user_controls, _ = self._process_input(frame_dt)
            if not self.running:
                break

            # frame dt from last frame
            timers.advance_frame(frame_dt)
            self._elapsed_time = timers.elapsed_time

            # update physics at fixed rate
            self._update_physics_steps(timers)

            # Run bot at fixed rate to produce target controls
            bot_controls = self._update_bot_steps(timers)

            # Manage bot override timer
            if user_controls is not None:
                self._bot_override_timer = self.bot_override_delay
            else:
                self._bot_override_timer = max(0.0, self._bot_override_timer - frame_dt)

            # Resolve controls for this frame (user overrides bot)
            if user_controls is not None:
                controls = user_controls
            elif self._bot_override_timer == 0.0 and bot_controls is not None:
                controls = bot_controls
            else:
                controls = None

            if controls is None:
                controls = (None, None, False)

            # Economy / Refueling
            _tgt_thm, _tgt_ang, refuel_requested = controls
            if self.lander.state == "landed" and refuel_requested:
                # Find target under lander
                nearby = self.targets.get_targets(self.lander.x, self.lander.width)
                if nearby:
                    target = nearby[0] # Assume the first one is the platform
                    price = target.info.get("fuel_price", 10.0) # Default if missing
                    self._handle_refueling(frame_dt, price)

            # Apply control targets (Set Intent only)
            _state_before = self.lander.state
            self.lander.apply_controls(frame_dt, controls)
            
            # If we transitioned from landed -> flying, bump the engine body up slightly
            if (
                self.engine_adapter.enabled
                and _state_before == "landed"
                and self.lander.state == "flying"
            ):
                self.engine_adapter.teleport_lander(
                    (self.lander.x, self.lander.y),
                    angle=self.lander.rotation,
                    clear_velocity=True,
                )

            # Level update hook
            self.level.update(self, frame_dt)

            # Headless: sample trajectory via Plotter
            self.plotter.update(frame_dt)

            # Rendering
            frame_dt = self._render(frame_dt)

            # Headless logging at requested frequency
            if self.headless and print_freq > 0 and step_count % print_freq == 0:
                self._print_headless_stats(timers)

            step_count += 1

            # Stop conditions and counters
            state = self.lander.state
            if state != prev_state:
                if state == "landed":
                    landing_count += 1
                elif state == "crashed":
                    crash_count += 1
                prev_state = state

            # Level completion condition
            if self.level.should_end(self):
                break

        if self.renderer:
            self.renderer.shutdown()

        # Expose counters and elapsed time for the level to consume
        self._elapsed_time = timers.elapsed_time
        self._landing_count = landing_count
        self._crash_count = crash_count
        # Let level finalize and produce result dict, then merge plot artifacts
        result = self.level.end(self)
        plot_extras = self.plotter.finalize()
        if plot_extras:
            result.update(plot_extras)
        return result

    def _process_input(self, frame_dt: float) -> tuple[ControlTuple | None, dict]:
        """Process input events and return user controls."""
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
        if self.lander and self.lander.state in ("flying", "landed"):
            if hasattr(self.lander, "handle_input") and callable(getattr(self.lander, "handle_input")):
                uc = self.lander.handle_input(input_events, frame_dt)
            elif self.player_controller:
                current_thrust = self.lander.target_thrust
                current_angle = self.lander.target_angle
                max_rot = self.lander.max_rotation_rate
                uc = self.player_controller.update(
                    input_events,
                    frame_dt,
                    current_thrust,
                    current_angle,
                    max_rot,
                )
            else:
                uc = None
            if uc is not None:
                user_controls = uc

        # Camera input (variable-rate)
        if self.renderer is not None:
            cam = self.renderer.main_camera
            if hasattr(cam, "handle_input"):
                cam.handle_input(input_events, frame_dt)

        return user_controls, input_events

    def _do_reset(self) -> None:
        """Reset game: lander to start position, physics body, camera, and bot override timer."""
        self.lander.reset()
        if self.engine_adapter.enabled:
            self.engine_adapter.teleport_lander(
                (self.lander.x, self.lander.y),
                angle=self.lander.rotation,
                clear_velocity=True,
            )
        if self.renderer is not None:
            cam = self.renderer.main_camera
            cam.x = self.lander.x
            cam.y = self.lander.y
            cam.zoom = 2.0
        self._bot_override_timer = self.bot_override_delay

    def _update_physics_steps(self, timers: LoopTimers) -> None:
        """Run physics steps until timer accumulator is drained.

        Execution order per step:
          1. PropulsionSystem   — thrust/rotation slew + fuel burn
          2. ForceApplicationSystem — push forces + rotation override to physics body
          3. engine_adapter.step()  — physics integration (NEW state computed)
          4. PhysicsSyncSystem  — sync pos/vel FROM physics engine into components
          5. ContactSystem      — landing/crash state transitions
        """
        physics_dt = timers.physics_dt
        while timers.should_step_physics():
            timers.consume_physics()

            self.propulsion_system.update(physics_dt)
            self.force_application_system.update(physics_dt)

            if self.engine_adapter.enabled:
                self.engine_adapter.step(physics_dt)
                self.physics_sync_system.update(physics_dt)
                self.contact_system.update(physics_dt)


    def _update_bot_steps(self, timers: LoopTimers) -> ControlTuple | None:
        """Run bot steps until timer accumulator is drained."""
        bot_controls = None
        bot_dt = timers.bot_dt
        while timers.should_step_bot():
            timers.consume_bot()
            if self.bot:
                passive_sensors, active_sensors = self.lander.update_sensors(
                    self.terrain, self.targets, engine=self.engine_adapter
                )
                action: BotAction = self.bot.update(
                    bot_dt, passive_sensors, active_sensors
                )
                bot_controls = (
                    action.target_thrust,
                    action.target_angle,
                    action.refuel,
                )
        return bot_controls

    def _handle_refueling(self, dt: float, fuel_price: float) -> None:
        """Handle refueling transaction."""
        if self.lander.fuel >= self.lander.max_fuel:
            return

        fuel_needed = self.lander.max_fuel - self.lander.fuel
        max_by_time = self.lander.refuel_rate * dt
        
        if fuel_price > 0:
            max_by_credits = max(0.0, self.lander.credits) / fuel_price
        else:
            max_by_credits = float("inf")
            
        fuel_to_add = min(fuel_needed, max_by_time, max_by_credits)
        
        if fuel_to_add > 0:
            self.lander.fuel += fuel_to_add
            spent = fuel_to_add * max(0.0, fuel_price)
            self.lander.credits = max(0.0, self.lander.credits - spent)

    def _render(self, frame_dt: float) -> float:
        """Update and draw renderer, returning new frame_dt."""
        if not self.headless and self.renderer is not None:
            self.renderer.update(frame_dt)
            self.renderer.draw()
            return self.renderer.tick(TARGET_RENDERING_FPS)
        return 1.0 / TARGET_RENDERING_FPS

    def _print_headless_stats(self, timers: LoopTimers) -> None:
        """Print stats to stdout in headless mode."""
        parts = [f"t:{timers.elapsed_time:6.2f}"]
        parts.append(self.lander.get_headless_stats(self.terrain))
        if self.bot and hasattr(self.bot, "get_headless_stats"):
            bot_str = self.bot.get_headless_stats()
            if bot_str:
                parts.append(bot_str)
        print(" | ".join(parts))

    @property
    def terrain(self):
        return self.level.world.terrain

    @property
    def targets(self):
        return self.level.world.targets
