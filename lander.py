"""Lander physics and game state management."""

import math
from dataclasses import dataclass

# No direct engine usage here; game loop owns engine
from bot import PassiveSensors, ActiveSensors
from protocols import ControlTuple, EngineProtocol


class Lander:
    """Lunar lander with physics simulation and game state."""

    def __init__(self, start_x: float = 100.0, start_y: float | None = None):
        """Initialize lander at starting position.

        Args:
            start_x: Starting x position in world coordinates
            start_y: Starting y position (world). If None, caller sets before use.
        """
        self.start_x = start_x

        # Physics state
        self.x = start_x
        self.y = start_y if start_y is not None else 0.0
        self.vx = 0.0
        self.vy = 0.0
        # Acceleration (populated by physics step)
        self.ax = 0.0
        self.ay = 0.0
        self.rotation = 0.0  # Radians, 0 = upright

        # Physics constants
        self.max_thrust_power = 50.0
        # Max rotation rate (rad/s)
        self.max_rotation_rate = math.radians(90.0)

        # Thrust control (actual applied)
        self.thrust_level = 0.0  # 0.0 to 1.0
        # Target-based control inputs
        self.target_thrust = 0.0  # 0.0 to 1.0
        self.target_angle = 0.0  # radians
        # Slew rates for approaching targets
        self.thrust_increase_rate = 2.0  # per second (slow up)
        self.thrust_decrease_rate = 4.0  # per second (fast down)

        # Fuel system
        self.fuel = 100.0
        self.max_fuel = 100.0
        self.fuel_burn_rate = 1.0  # Per second at full thrust
        # Economy/refuel now owned by the lander
        self.refuel_rate = 1.0  # Fuel units per second when refueling
        self.fuel_price = 10.0  # credits per fuel unit
        self.credits = 0.0

        self.dry_mass = 1.0
        self.fuel_density = 0.01

        # Lander geometry (world units)
        self.width = 8.0
        self.height = 8.0
        # No legs: default body is a simple triangle

        # Game state
        self.state = "flying"  # flying, landed, crashed
        self.safe_landing_velocity = 10.0  # Max safe landing speed
        self.safe_landing_angle = math.radians(15)  # Max tilt angle for safe landing

        # Credits owned here

        # Broad-phase collision circle radius
        # Enclose a triangle-ish body using half-height and half-width
        self.enclosing_radius = math.hypot(self.width / 2.0, self.height / 2.0)

        # Radar configuration
        self.radar_outer_range = 5000.0
        self.radar_inner_range = 2000.0

        self.proximity_sensor_range = 500.0

        # No persistent legacy body; engine owns the dynamic body
        # Physics frame counter (used by game loop for caching/invalidation)
        self._physics_frame_id = 0

    # -------- Engine/physics intent API (to be overridden by variants) --------

    def get_engine_override_angle(self) -> float | None:
        """Return an optional pose override angle (radians) for this frame.

        Default: use current rotation (classic behavior). Variants can return
        0.0 to keep upright, or None to skip overriding this frame.
        """
        return self.rotation

    def get_engine_force(self) -> tuple[float, float, float, float] | None:
        """Return an optional world-space force to apply this frame.

        Returns a tuple (fx, fy, visual_angle, visual_power).
        - fx, fy: force components in world coordinates (Newtons)
        - visual_angle: direction for rendering flame (radians, world space)
        - visual_power: 0..1 for flame size

        Default: map single main thruster based on rotation + thrust_level.
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

    def get_fuel_burn(self, dt: float) -> float:
        """Compute fuel units to burn this frame (variants may override)."""
        return max(0.0, self.fuel_burn_rate * max(0.0, min(1.0, self.thrust_level)) * dt)

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

    def get_mass(self) -> float:
        """Return the mass of the lander."""
        return self.dry_mass + self.fuel * self.fuel_density

    def get_body_polygon(self) -> list[tuple[float, float]]:
        """Return the lander body polygon vertices in world space.

        Default shape is a triangle defined in local space, rotated and translated
        into world coordinates.
        """
        cos_r = math.cos(self.rotation)
        sin_r = math.sin(self.rotation)
        half_w = self.width / 2.0
        half_h = self.height / 2.0
        # Local-space triangle points (nose up in y-up)
        local_pts: list[tuple[float, float]] = [
            (0.0, half_h),  # top (nose)
            (-half_w, -half_h),  # bottom-left
            (half_w, -half_h),  # bottom-right
        ]
        world_pts: list[tuple[float, float]] = []
        for px, py in local_pts:
            # Rotate local by -rotation (CW-positive convention)
            wx = self.x + px * cos_r + py * sin_r
            wy = self.y - px * sin_r + py * cos_r
            world_pts.append((wx, wy))
        return world_pts

    @dataclass
    class Thrust:
        x: float
        y: float
        angle: float
        width: float
        length: float
        power: float

    def get_thrusts(self) -> list["Lander.Thrust"]:
        """Return a list of simple thrust descriptors for renderer.

        Each thrust has base center (x,y) in world coords, direction angle (radians),
        base width, flame length, and power [0,1]. Angle follows standard math
        convention in world coordinates (0 along +x, CCW positive, y-up).
        """

        # Geometry in local space (y-up): base sits below body
        half_h = self.height / 2.0
        base_offset_local = half_h * 1.5  # distance from center to base along -y

        # Base width scales with thrust; small flicker for life
        base_width = self.width / 2.0

        # Length scales with thrust with a bit of flicker
        base_length = 20.0

        # Compute base center in world coordinates by rotating local (0, -base_offset)
        cos_r = math.cos(self.rotation)
        sin_r = math.sin(self.rotation)
        base_x = self.x + (0.0 * cos_r) + (-base_offset_local) * sin_r
        base_y = self.y + (-0.0 * sin_r) + (-base_offset_local) * cos_r

        # Direction of flame (local -y) mapped to world angle
        # Local (0,-1) -> world vector (-sin(r), -cos(r)); angle = atan2(dy, dx)
        angle = math.atan2(-cos_r, -sin_r)

        return [
            Lander.Thrust(
                x=base_x,
                y=base_y,
                angle=angle,
                width=base_width,
                length=base_length,
                power=self.thrust_level,
            )
        ]

    def apply_controls(self, dt: float, controls: ControlTuple):
        """Apply target controls to internal actuators (thrust_level, rotation).

        This is a variable-rate operation; it does not integrate physics.
        """
        target_thrust, target_angle, refuel = controls

        # Update targets when provided
        if target_thrust is not None:
            self.target_thrust = max(0.0, min(1.0, target_thrust))
        if target_angle is not None:
            self.target_angle = target_angle

        # Allow takeoff from landed state when a nonzero target is requested
        if self.state == "landed":
            if self.target_thrust and self.target_thrust > 0.0:
                self.state = "flying"
                self.y += 1.0

        if self.state != "flying":
            # Allow refueling while landed
            if self.state == "landed" and refuel:
                fuel_needed = max(0.0, self.max_fuel - self.fuel)
                if fuel_needed > 0:
                    max_by_time = max(0.0, self.refuel_rate * dt)
                    if self.fuel_price > 0:
                        max_by_credits = max(0.0, self.credits) / self.fuel_price
                    else:
                        max_by_credits = float("inf")
                    fuel_to_add = min(fuel_needed, max_by_time, max_by_credits)
                    if fuel_to_add > 0:
                        self.fuel += fuel_to_add
                        spent = fuel_to_add * max(0.0, self.fuel_price)
                        self.credits = max(0.0, self.credits - spent)
            return

        # Slew thrust toward target with different rates for up and down
        delta_thrust = self.target_thrust - self.thrust_level
        if delta_thrust > 0:
            step = self.thrust_increase_rate * dt
            self.thrust_level = min(1.0, self.thrust_level + min(step, delta_thrust))
        elif delta_thrust < 0:
            step = self.thrust_decrease_rate * dt
            self.thrust_level = max(0.0, self.thrust_level - min(step, -delta_thrust))

        # Rotate toward target angle with easing near the target
        def _angle_diff(a: float, b: float) -> float:
            d = (b - a + math.pi) % (2 * math.pi) - math.pi
            return d

        d_ang = _angle_diff(self.rotation, self.target_angle)
        max_step = self.max_rotation_rate * dt
        ease_band = math.radians(15.0)
        step_mag = (
            max_step
            if abs(d_ang) >= ease_band
            else max_step * (abs(d_ang) / max(ease_band, 1e-6))
        )
        if abs(d_ang) <= step_mag:
            self.rotation = self.target_angle
        else:
            self.rotation += math.copysign(step_mag, d_ang)

    def resolve_contact(self, report: dict, targets) -> str | None:
        """Resolve landing or crash based on a contact report.

        Returns the new state ("landed"/"crashed") if a transition occurs.
        """
        if (
            self.state != "flying"
            or not report.get("colliding")
            or self.vy > 0.0
        ):
            return None

        speed = math.hypot(self.vx, self.vy)
        angle_ok = abs(self.rotation) < self.safe_landing_angle
        speed_ok = speed < self.safe_landing_velocity

        target = None
        if targets is not None:
            nearby = targets.get_targets(self.x, 0)
            target = nearby[0] if nearby else None

        if angle_ok and speed_ok and target is not None:
            self._apply_landing(target)
            return "landed"

        self._apply_crash()
        return "crashed"

    def _apply_landing(self, target) -> None:
        self.state = "landed"
        self.vx = 0.0
        self.vy = 0.0
        self.thrust_level = 0.0
        self.rotation = 0.0
        self.target_thrust = 0.0
        self.target_angle = 0.0
        platform_height = target.y
        self.y = platform_height + self.height / 2.0
        self.credits += target.info["award"]
        target.info["award"] = 0

    def _apply_crash(self) -> None:
        self.state = "crashed"
        self.vx = 0.0
        self.vy = 0.0
        self.thrust_level = 0.0
        self.target_thrust = 0.0

    def update_physics(self, terrain, targets, dt: float):
        """Legacy no-op; physics is managed by the engine via game loop."""
        return

    def reset(self, start_x: float | None = None, start_y: float | None = None):
        """Reset lander to starting state. Caller provides explicit world coords."""
        if start_x is None:
            start_x = self.start_x
        self.x = start_x
        if start_y is not None:
            self.y = start_y
        self.vx = 0.0
        self.vy = 0.0
        self.rotation = 0.0
        self.ax = 0.0
        self.ay = 0.0
        self.fuel = self.max_fuel
        self.thrust_level = 0.0
        self.target_thrust = 0.0
        self.target_angle = 0.0
        self.state = "flying"

    def get_vehicle_info(self) -> dict:
        """Return a dict of vehicle information for the bot."""
        return {
            "width": self.width,
            "height": self.height,
            "dry_mass": self.dry_mass,
            "fuel_density": self.fuel_density,
            "max_thrust_power": self.max_thrust_power,
            "safe_landing_velocity": self.safe_landing_velocity,
            "safe_landing_angle": self.safe_landing_angle,
            "radar_outer_range": self.radar_outer_range,
            "radar_inner_range": self.radar_inner_range,
            "proximity_sensor_range": self.proximity_sensor_range,
        }

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
        from sensor import get_radar_contacts as _get_radar_contacts

        if outer_range is None:
            outer_range = self.radar_outer_range
        if inner_range is None:
            inner_range = self.radar_inner_range
        contacts = _get_radar_contacts(
            self.x, self.y, targets, inner_range=inner_range, outer_range=outer_range
        )

        return contacts

    def get_proximity_contact(self, terrain):
        """Wrapper over sensor.get_proximity_contact computing angle here."""
        from sensor import get_proximity_contact as _get_proximity_contact

        pc = _get_proximity_contact(
            self.x, self.y, terrain, range=self.proximity_sensor_range
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

        # Active sensor interfaces
        pass

        # Provide a simple object implementing the ActiveSensors protocol
        class _Active:
            def raycast(self, dir_angle: float, max_range: float | None = None):
                rng = self_outer.radar_inner_range if max_range is None else max_range
                if engine is None:
                    return {"hit": False, "hit_x": 0.0, "hit_y": 0.0, "distance": None}
                res = engine.raycast((self_outer.x, self_outer.y), dir_angle, rng)
                return res

        self_outer = self
        active: ActiveSensors = _Active()

        return passive, active

    # get_proximity_contact removed; use sensor.get_proximity_contact directly

    def handle_input(self, signals: dict, dt: float) -> ControlTuple | None:
        """Update target controls from input signals and optionally return user controls.

        Returns a tuple (target_thrust, target_angle, refuel) when inputs are active,
        otherwise returns None.
        """
        if self.state not in ("flying", "landed"):
            return None
        if signals.get("thrust_up"):
            self.target_thrust = min(1.0, self.target_thrust + 1.5 * dt)
        if signals.get("thrust_down"):
            self.target_thrust = max(0.0, self.target_thrust - 1.5 * dt)
        if not signals.get("thrust_up") and not signals.get("thrust_down"):
            self.target_thrust = round(self.target_thrust * 10.0) / 10.0
        # Angles are CW-from-up: left = CCW (decrease), right = CW (increase)
        if signals.get("rot_left"):
            self.target_angle -= self.max_rotation_rate * dt
        if signals.get("rot_right"):
            self.target_angle += self.max_rotation_rate * dt
        if not signals.get("rot_left") and not signals.get("rot_right"):
            deg = math.degrees(self.target_angle)
            snapped = round(deg / 45.0) * 45.0
            if abs(deg - snapped) < 5:
                self.target_angle = math.radians(snapped)
        refuel = bool(signals.get("refuel"))
        any_pressed = (
            signals.get("thrust_up")
            or signals.get("thrust_down")
            or signals.get("rot_left")
            or signals.get("rot_right")
            or refuel
        )
        if any_pressed:
            return (self.target_thrust, self.target_angle, refuel)
        return None

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
