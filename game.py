"""Game orchestration: ties systems together and runs the loop."""

import random
from dataclasses import dataclass
from input import InputHandler
from renderer import Renderer
from bot import Bot, BotAction
from level import Level
from plot import Plotter
from engine_adapter import EngineAdapter
from protocols import ControlTuple


# Centralized game defaults
DEFAULT_SCREEN_WIDTH = 1280
DEFAULT_SCREEN_HEIGHT = 720

TARGET_RENDERING_FPS = 60
PHYSICS_FPS = 120
BOT_FPS = 60


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

        self.bot_override_delay = 1.0
        self._bot_override_timer = 0.0

        # Input/Renderer
        if not headless and InputHandler is not None and Renderer is not None:
            self.input_handler = InputHandler()
            self.renderer = Renderer(self.level, width, height)
        else:
            self.input_handler = None
            self.renderer = None

        # Pass static vehicle info to bot if available
        if self.bot is not None and hasattr(self.bot, "set_vehicle_info"):
            self.bot.set_vehicle_info(self.lander.get_vehicle_info())
        # Expose bot on level for renderer/UI access
        if self.bot is not None:
            setattr(self.level, "bot", self.bot)

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

        while self.running:
            # Prefer time limit in headless mode
            if self.headless:
                if max_time is not None and timers.elapsed_time >= max_time:
                    break
            if max_steps is not None and step_count >= max_steps:
                break

            # Frame timing and event processing
            if not self.headless and self.input_handler is not None:
                input_events = self.input_handler.get_events()
                if input_events.get("quit"):
                    self.running = False
                    break
            else:
                input_events = {}

            # frame dt from last frame
            timers.advance_frame(frame_dt)

            # update physics at fixed rate
            while timers.should_step_physics():
                timers.consume_physics()
                # Fuel bookkeeping via lander intent
                fuel_consumption = self.lander.get_fuel_burn(physics_dt)
                if fuel_consumption > 0.0 and self.lander.fuel > 0.0:
                    actual = min(fuel_consumption, self.lander.fuel)
                    self.lander.fuel = max(0.0, self.lander.fuel - actual)
                    self.engine_adapter.set_lander_mass(self.lander.get_mass())

                # Apply control intents to engine
                if self.engine_adapter.enabled:
                    oa = self.lander.get_engine_override_angle()
                    if oa is not None:
                        self.engine_adapter.override(oa)

                    force = self.lander.get_engine_force()
                    if force is not None:
                        fx, fy, visual_angle, visual_power = force
                        self.engine_adapter.apply_force(
                            fx, fy, visual_angle, visual_power
                        )
                    else:
                        # Fallback to legacy single-thrust path
                        thrust_force = 0.0
                        if self.lander.thrust_level > 0 and self.lander.fuel > 0:
                            thrust_force = (
                                self.lander.thrust_level * self.lander.max_thrust_power
                            )
                        self.engine_adapter.set_lander_controls(
                            thrust_force, self.lander.rotation
                        )
                    self.engine_adapter.step(physics_dt)
                    # Advance physics frame id for caching
                    self.lander._physics_frame_id += 1

                    # Sync pose/vel back to lander
                    px, py, _pang = self.engine_adapter.get_pose()
                    vx, vy, _av = self.engine_adapter.get_velocity()
                    self.lander.x, self.lander.y = px, py
                    self.lander.vx, self.lander.vy = vx, vy

                    # Landing/crash resolution using contact report
                    report = self.engine_adapter.get_contact_report()
                    self.lander.resolve_contact(report, self.targets)

            # Run bot at fixed rate to produce target controls
            bot_controls: ControlTuple | None = None
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

            # Collect player inputs once per frame
            user_controls: ControlTuple | None = None
            if not self.headless and self.input_handler is not None:
                # Update lander control targets from input
                if self.lander and self.lander.state in ("flying", "landed"):
                    uc = self.lander.handle_input(input_events, frame_dt)
                    if uc is not None:
                        user_controls = uc

                # Camera input (variable-rate)
                if self.renderer is not None:
                    cam = self.renderer.main_camera
                    cam.handle_input(input_events, frame_dt)

            if user_controls is not None:
                self._bot_override_timer = self.bot_override_delay
            else:
                self._bot_override_timer = max(0.0, self._bot_override_timer - frame_dt)

            # Resolve controls for this frame (user overrides bot)
            if user_controls is not None:
                controls = user_controls
            elif self._bot_override_timer == 0.0:
                controls = bot_controls
            else:
                controls = None

            if controls is None:
                controls = (None, None, False)

            # Apply control targets and actuator smoothing at frame rate
            # Also process refuel when landed via the lander itself
            _state_before = self.lander.state
            self.lander.apply_controls(frame_dt, controls)
            # If we transitioned from landed -> flying, bump the engine body up slightly
            if (
                self.engine_adapter.enabled
                and _state_before == "landed"
                and self.lander.state == "flying"
            ):
                self.engine_adapter.teleport_lander(
                    self.lander.x,
                    self.lander.y,
                    angle=self.lander.rotation,
                    clear_velocity=True,
                )

            # Level update hook
            self.level.update(self, frame_dt)

            # Headless: sample trajectory via Plotter
            self.plotter.update(frame_dt)

            # Rendering at display rate (renderer handles camera and zoom)
            if not self.headless and self.renderer is not None:
                self.renderer.update(frame_dt)
                self.renderer.draw()
                frame_dt = self.renderer.tick(TARGET_RENDERING_FPS)

            # Headless logging at requested frequency (based on frame count)
            if self.headless and print_freq > 0 and step_count % print_freq == 0:
                parts = [f"t:{timers.elapsed_time:6.2f}"]
                parts.append(self.lander.get_headless_stats(self.terrain))
                if self.bot and hasattr(self.bot, "get_headless_stats"):
                    bot_str = self.bot.get_headless_stats()
                    if bot_str:
                        parts.append(bot_str)
                print(" | ".join(parts))

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

    # Forwarding properties to level-owned world for compatibility
    @property
    def terrain(self):
        return self.level.world.terrain

    @property
    def targets(self):
        return self.level.world.targets
