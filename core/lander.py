"""Lander physics and game state management."""

import math

# No direct engine usage here; game loop owns engine
from .bot import PassiveSensors, ActiveSensors, VehicleInfo, _ActiveSensorImpl
from utils.protocols import ControlTuple, EngineProtocol
from .lander_visuals import LanderVisuals, Thrust
from core.maths import Vector2
from core.ecs import Entity
from core.components import Transform as TransformComponent, PhysicsState, FuelTank, Engine, LanderGeometry, Radar, LanderState, Wallet


class Lander(Entity, LanderVisuals):
    """Lunar lander entity composed of functional components."""
    
    # Expose Thrust for subclasses and type hints
    Thrust = Thrust

    def __init__(self, start_x: float = 100.0, start_y: float | None = None):
        """Initialize lander components."""
        super().__init__() # Initialize Entity (uid, components)
        
        # 1. Transform Component
        self.trans = TransformComponent()
        self.trans.pos = Vector2(start_x, start_y if start_y is not None else 0.0)
        self.add_component(self.trans)
        
        self.start_pos = Vector2(self.trans.pos) # Keep copy for reset

        # 2. Physics Component
        self.physics = PhysicsState()
        self.add_component(self.physics)
        
        # 3. Fuel Component
        self.tank = FuelTank()
        self.add_component(self.tank)
        
        # 4. Engine Component
        self.engine = Engine()
        self.add_component(self.engine)
        
        # 5. Geometry Component
        self.geo = LanderGeometry()
        self.add_component(self.geo)
        
        # 6. Radar Component
        self.radar = Radar()
        self.add_component(self.radar)

        # 7. LanderState Component
        self.lander_state = LanderState()
        self.add_component(self.lander_state)

        # 8. Wallet Component
        self.wallet = Wallet()
        self.add_component(self.wallet)

        # Physics constants (Legacy overrides or config)
        self.refuel_rate = 1.0
        self.proximity_sensor_range = 500.0

        # Misc
        self.enclosing_radius = math.hypot(self.geo.width / 2.0, self.geo.height / 2.0)

    # -------------------------------------------------------------------------
    # Property Facades (Forwarding to Components)
    # -------------------------------------------------------------------------
    
    # Transform
    @property
    def pos(self) -> Vector2: return self.trans.pos
    @pos.setter
    def pos(self, v: Vector2): self.trans.pos = v
    
    @property
    def rotation(self) -> float: return self.trans.rotation
    @rotation.setter
    def rotation(self, v: float): self.trans.rotation = v

    @property
    def x(self) -> float: return self.trans.x
    @x.setter
    def x(self, v: float): self.trans.x = v

    @property
    def y(self) -> float: return self.trans.y
    @y.setter
    def y(self, v: float): self.trans.y = v

    # Physics
    @property
    def vel(self) -> Vector2: return self.physics.vel
    @vel.setter
    def vel(self, v: Vector2): self.physics.vel = v
    
    @property
    def acc(self) -> Vector2: return self.physics.acc
    @acc.setter
    def acc(self, v: Vector2): self.physics.acc = v
    
    @property
    def vx(self) -> float: return self.physics.vel.x
    @vx.setter
    def vx(self, v: float): self.physics.vel.x = v

    @property
    def vy(self) -> float: return self.physics.vel.y
    @vy.setter
    def vy(self, v: float): self.physics.vel.y = v

    @property
    def ax(self) -> float: return self.physics.acc.x
    @ax.setter
    def ax(self, v: float): self.physics.acc.x = v

    @property
    def ay(self) -> float: return self.physics.acc.y
    @ay.setter
    def ay(self, v: float): self.physics.acc.y = v

    # Fuel/Engine
    @property
    def fuel(self) -> float: return self.tank.fuel
    @fuel.setter
    def fuel(self, v: float): self.tank.fuel = v
    
    @property
    def max_fuel(self) -> float: return self.tank.max_fuel
    @max_fuel.setter
    def max_fuel(self, v: float): self.tank.max_fuel = v
    
    @property
    def fuel_burn_rate(self) -> float: return self.tank.burn_rate
    
    @property
    def fuel_density(self) -> float: return self.tank.density

    @property
    def thrust_level(self) -> float: return self.engine.thrust_level
    @thrust_level.setter
    def thrust_level(self, v: float): self.engine.thrust_level = v
    
    @property
    def target_thrust(self) -> float: return self.engine.target_thrust
    @target_thrust.setter
    def target_thrust(self, v: float): self.engine.target_thrust = v
    
    @property
    def max_thrust_power(self) -> float: return self.engine.max_power
    @max_thrust_power.setter
    def max_thrust_power(self, v: float): self.engine.max_power = v
    
    @property
    def target_angle(self) -> float: return self.engine.target_angle
    @target_angle.setter
    def target_angle(self, v: float): self.engine.target_angle = v
    
    @property
    def thrust_increase_rate(self) -> float: return self.engine.increase_rate
    
    @property
    def thrust_decrease_rate(self) -> float: return self.engine.decrease_rate
    
    @property
    def max_rotation_rate(self) -> float: return self.engine.max_rotation_rate

    # Geometry
    @property
    def width(self) -> float: return self.geo.width
    @width.setter
    def width(self, v: float): self.geo.width = v
    
    @property
    def height(self) -> float: return self.geo.height
    @height.setter
    def height(self, v: float): self.geo.height = v
    
    # Radar
    @property
    def radar_inner_range(self) -> float: return self.radar.inner_range
    @property
    def radar_outer_range(self) -> float: return self.radar.outer_range

    @property
    def dry_mass(self) -> float: return self.physics.mass
    @dry_mass.setter
    def dry_mass(self, v: float): self.physics.mass = v

    # LanderState
    @property
    def state(self) -> str: return self.lander_state.state
    @state.setter
    def state(self, v: str): self.lander_state.state = v

    @property
    def safe_landing_velocity(self) -> float: return self.lander_state.safe_landing_velocity

    @property
    def safe_landing_angle(self) -> float: return self.lander_state.safe_landing_angle

    # Wallet
    @property
    def credits(self) -> float: return self.wallet.credits
    @credits.setter
    def credits(self, v: float): self.wallet.credits = v

    def get_mass(self) -> float:
        """Return the mass of the lander."""
        return self.physics.mass + self.tank.fuel * self.tank.density


    def get_engine_override_angle(self) -> float | None:
        """Return an optional pose override angle (radians) for this frame.

        Default: use current rotation (classic behavior). Variants can return
        0.0 to keep upright, or None to skip overriding this frame.
        """
        return self.rotation

    def get_engine_force(self) -> tuple[float, float, float, float] | None:
        """Helper for rendering/debug (logic duplication with System?).
        
        For now, keep for Visual/Legacy support.
        """
        if self.thrust_level <= 0.0 or self.fuel <= 0.0:
            return None
        thrust = self.thrust_level * self.max_thrust_power
        # Angle convention: rotation is CW from up; convert to world vector
        fx = math.sin(self.rotation) * thrust
        fy = math.cos(self.rotation) * thrust
        # Visual angle is direction of flame (opposite the force direction)
        visual_angle = math.atan2(-fy, -fx)
        return (fx, fy, visual_angle, self.thrust_level)

    def get_controls_text(self) -> list[str]:
        """Return control help lines for UI rendering."""
        return [
            "Controls:",
            "W/UP: Increase thrust",
            "S/DOWN: Decrease thrust",
            "A/LEFT: Rotate left",
            "D/RIGHT: Rotate right",
            "F: Refuel (when landed)",
            "R: Reset",
            "Q/ESC: Quit",
        ]

    def get_physics_polygons(self) -> list[list[tuple[float, float]]]:
        """Return convex polygons in local coordinates for physics shape.

        Default: a single triangle matching visual triangle footprint.
        """
        half_w = self.width / 2.0
        half_h = self.height / 2.0
        return [[(0.0, half_h), (-half_w, -half_h), (half_w, -half_h)]]



    # Visual methods moved to LanderVisuals mixin
    # - get_body_polygon
    # - get_thrusts


    def apply_controls(self, dt: float, controls: ControlTuple):
        """Set target controls.
        
        Logic for slewing and burning fuel has been moved to PropulsionSystem.
        This method now just sets the intent.
        """
        target_thrust, target_angle, refuel = controls

        # Update targets when provided
        if target_thrust is not None:
            self.target_thrust = max(0.0, min(1.0, target_thrust))
        if target_angle is not None:
            self.target_angle = target_angle

        # Logic for takeoff state transition remains as high-level entity logic for now
        # (Could also be in a StateSystem)
        if self.state == "landed":
            if self.target_thrust and self.target_thrust > 0.0:
                self.state = "flying"
                self.y += 1.0


    def reset(self, start_x: float | None = None, start_y: float | None = None):
        """Reset lander to starting state. Caller provides explicit world coords."""
        if start_x is None:
            self.pos.x = self.start_pos.x
        else:
            self.pos.x = start_x
            
        if start_y is not None:
            self.pos.y = start_y
        elif start_x is None: # use start_pos.y only if resetting to default
            self.pos.y = self.start_pos.y
            
        self.vel.update(0.0, 0.0)
        self.rotation = 0.0
        self.acc.update(0.0, 0.0)
        self.fuel = self.max_fuel
        self.thrust_level = 0.0
        self.target_thrust = 0.0
        self.target_angle = 0.0
        self.state = "flying"

    def get_vehicle_info(self) -> VehicleInfo:
        """Return typed vehicle parameters for the bot."""
        return VehicleInfo(
            width=self.width,
            height=self.height,
            dry_mass=self.dry_mass,
            fuel_density=self.fuel_density,
            max_thrust_power=self.max_thrust_power,
            safe_landing_velocity=self.safe_landing_velocity,
            safe_landing_angle=self.safe_landing_angle,
            radar_outer_range=self.radar_outer_range,
            radar_inner_range=self.radar_inner_range,
            proximity_sensor_range=self.proximity_sensor_range,
        )

    def get_radar_contacts(
        self,
        targets,
        outer_range: float | None = None,
        inner_range: float | None = None,
    ) -> list[dict]:
        """Build contact dicts using sensor.get_radar_contacts (x,y based).

        visited is derived from target award (award == 0 => visited).
        Distance is only populated when <= inner_range.
        """
        from core.sensor import get_radar_contacts as _get_radar_contacts

        if outer_range is None:
            outer_range = self.radar_outer_range
        if inner_range is None:
            inner_range = self.radar_inner_range
        contacts = _get_radar_contacts(
            self.pos, targets, inner_range=inner_range, outer_range=outer_range
        )

        return contacts

    def get_proximity_contact(self, terrain):
        """Wrapper over sensor.get_proximity_contact computing angle here."""
        from core.sensor import get_proximity_contact as _get_proximity_contact

        pc = _get_proximity_contact(
            self.pos, terrain, range=self.proximity_sensor_range
        )
        return pc

    def update_sensors(
        self, terrain, targets=None, engine: EngineProtocol | None = None
    ) -> tuple[PassiveSensors, ActiveSensors]:
        """Compute passive and active sensors for this frame.

        Returns a tuple (PassiveSensors, ActiveSensors).
        """
        # Radar contacts
        contacts = self.get_radar_contacts(targets)

        # Proximity (distance/angle to closest terrain point)
        prox = self.get_proximity_contact(terrain)

        passive = PassiveSensors(
            altitude=self.y,
            vx=self.vx,
            vy_up=self.vy,
            angle=self.rotation,
            ax=self.ax,
            ay_up=self.ay,
            mass=self.get_mass(),
            thrust_level=self.thrust_level,
            fuel=self.fuel,
            state=self.state,
            radar_contacts=contacts,
            proximity=prox,
        )

        active: ActiveSensors = _ActiveSensorImpl(
            origin_fn=lambda: (self.x, self.y),
            radar_range_fn=lambda: self.radar_inner_range,
            engine_adapter=engine,
        )

        return passive, active

    # get_proximity_contact removed; use sensor.get_proximity_contact directly

    # handle_input moved to PlayerController via Game


    def get_stats_text(self, terrain) -> list[str]:
        """Return a list of UI text lines describing current lander state.

        The lander chooses which stats to show; caller simply renders lines.
        """
        speed = math.hypot(self.vx, self.vy)
        altitude = self.y - terrain(self.x)
        prox = self.get_proximity_contact(terrain)
        if prox is not None:
            prox_dist = prox.distance
            prox_angle = prox.angle
        else:
            prox_dist = None
            prox_angle = None
        prox_angle_deg = math.degrees(prox_angle) if prox_angle is not None else None

        rotation_deg = math.degrees(self.rotation)
        target_rot_deg = math.degrees(self.target_angle)
        thrust_pct = self.thrust_level * 100.0
        target_thrust_pct = self.target_thrust * 100.0

        lines: list[str] = []
        lines.append("")
        lines.append(f"FUEL: {self.fuel:.1f}%")
        if abs(target_thrust_pct - thrust_pct) < 1e-3:
            lines.append(f"THRUST: {thrust_pct:.0f}%")
        else:
            lines.append(f"THRUST: {thrust_pct:.0f}% -> {target_thrust_pct:.0f}%")

        if abs(target_rot_deg - rotation_deg) < 0.5:
            lines.append(f"ANGLE: {rotation_deg:.1f}°")
        else:
            lines.append(f"ANGLE: {rotation_deg:.1f}° -> {target_rot_deg:.1f}°")

        lines.append("")
        lines.append(f"SPEED: {speed:.1f} m/s")
        lines.append(f"ALT: {altitude:.1f} m")
        lines.append(f"H-SPEED: {self.vx:.1f} m/s")
        lines.append(f"V-SPEED: {self.vy:.1f} m/s")
        if prox_dist is not None and prox_angle_deg is not None:
            lines.append(f"PROX: {prox_dist:.1f} m @ {prox_angle_deg:.0f}°")
        else:
            lines.append("PROX: --")

        lines.append("")
        lines.append(f"STATE: {self.state.upper()}")
        return lines

    def get_headless_stats(self, terrain) -> str:
        """Return a single-line concise stats string for headless logging."""
        altitude = self.y - terrain(self.x)
        angle_deg = math.degrees(self.rotation)
        thrust_pct = self.thrust_level * 100.0
        return (
            f"x:{self.x:6.1f} alt:{altitude:6.1f} | "
            f"vx:{self.vx:6.2f} vy:{self.vy:6.2f} | "
            f"ang:{angle_deg:5.1f} thr:{thrust_pct:3.0f}% | "
            f"fuel:{self.fuel:5.1f}%"
        )
