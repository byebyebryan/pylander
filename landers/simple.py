from __future__ import annotations

import math
from core.lander import Lander
from core.maths import RigidTransform2, Vector2


class SimpleLander(Lander):
    """Simple lander: always upright; direct lateral/vertical thrust mapping.

    Controls (keys as in InputHandler):
    - thrust_up/thrust_down adjust upward thrust target
    - rot_left/rot_right are repurposed for left/right lateral thrust
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Separate targets for up and lateral thrust (0..1)
        self.target_thrust_up = 0.0
        self.target_thrust_left = 0.0
        self.target_thrust_right = 0.0
        self.thrust_up = 0.0
        self.thrust_left = 0.0
        self.thrust_right = 0.0

        # Shape: capsule-like rectangle for visual distinction
        self.width = 8.0
        self.height = 10.0

    def get_engine_override_angle(self) -> float | None:
        # lock upright
        return 0.0

    def handle_input(self, signals: dict, dt: float):
        if self.state not in ("flying", "landed"):
            return None
        # Up/down maps to vertical thrust
        if signals.get("thrust_up"):
            self.target_thrust_up = min(1.0, self.target_thrust_up + 1.5 * dt)
        if signals.get("thrust_down"):
            self.target_thrust_up = max(0.0, self.target_thrust_up - 1.5 * dt)
        if not signals.get("thrust_up") and not signals.get("thrust_down"):
            self.target_thrust_up = round(self.target_thrust_up * 10.0) / 10.0

        # Left/right maps to side thrusters (press left -> fire RIGHT-side thruster)
        if signals.get("rot_left"):
            self.target_thrust_right = min(1.0, self.target_thrust_right + 2.0 * dt)
        else:
            self.target_thrust_right = max(0.0, self.target_thrust_right - 4.0 * dt)
        if signals.get("rot_right"):
            self.target_thrust_left = min(1.0, self.target_thrust_left + 2.0 * dt)
        else:
            self.target_thrust_left = max(0.0, self.target_thrust_left - 4.0 * dt)

        refuel = bool(signals.get("refuel"))

        # Allow takeoff from landed state when any nonzero target is requested
        if self.state == "landed":
            if self.target_thrust_up > 0.0 or self.target_thrust_left > 0.0 or self.target_thrust_right > 0.0:
                self.state = "flying"
                self.y += 1.0

        any_pressed = (
            signals.get("thrust_up")
            or signals.get("thrust_down")
            or signals.get("rot_left")
            or signals.get("rot_right")
            or refuel
        )
        if any_pressed:
            return (None, None, refuel)
        return None

    def apply_controls(self, dt: float, controls):
        # Handle refuel when landed
        refuel = False
        if isinstance(controls, tuple) and len(controls) == 3:
            refuel = bool(controls[2])
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

        # Smooth thrust actuators toward targets
        up_delta = self.target_thrust_up - self.thrust_up
        if up_delta > 0:
            self.thrust_up = min(1.0, self.thrust_up + self.thrust_increase_rate * dt)
        elif up_delta < 0:
            self.thrust_up = max(0.0, self.thrust_up - self.thrust_decrease_rate * dt)

        def _slew(cur, tgt, up_rate, down_rate):
            d = tgt - cur
            if d > 0:
                return min(1.0, cur + up_rate * dt)
            if d < 0:
                return max(0.0, cur - down_rate * dt)
            return cur

        self.thrust_left = _slew(self.thrust_left, self.target_thrust_left, 4.0, 8.0)
        self.thrust_right = _slew(self.thrust_right, self.target_thrust_right, 4.0, 8.0)

    def get_engine_force(self):
        if self.fuel <= 0.0:
            return None
        # Net lateral (right - left), vertical = up
        # Positive fx to the right; right-side thruster pushes left (negative fx)
        lateral = max(0.0, self.thrust_left) - max(0.0, self.thrust_right)
        up = max(0.0, self.thrust_up)
        # Scale by max_thrust_power; consider lateral and vertical having same max
        fx = lateral * self.max_thrust_power
        fy = up * self.max_thrust_power
        if fx == 0.0 and fy == 0.0:
            return None
        # Visual: flame direction opposite the force vector
        visual_angle = math.atan2(-fy, -fx) if (fx != 0.0 or fy != 0.0) else -math.pi / 2
        power = min(1.0, math.hypot(fx, fy) / max(1e-6, self.max_thrust_power))
        return (fx, fy, visual_angle, power)

    def get_controls_text(self) -> list[str]:
        return [
            "Controls:",
            "W/UP: Increase vertical thrust",
            "S/DOWN: Decrease vertical thrust",
            "A/LEFT: Thrust left",
            "D/RIGHT: Thrust right",
            "F: Refuel (when landed)",
            "R: Reset",
            "Q/ESC: Quit",
        ]

    def get_physics_polygons(self):
        # Rectangle for physics
        half_w = self.width / 2.0
        half_h = self.height / 2.0
        return [[(-half_w, -half_h), (half_w, -half_h), (half_w, half_h), (-half_w, half_h)]]

    def get_fuel_burn(self, dt: float) -> float:
        # Burn proportional to combined usage of up and lateral thrusters
        usage = max(0.0, min(1.0, self.thrust_up + 0.5 * (self.thrust_left + self.thrust_right)))
        return max(0.0, self.fuel_burn_rate * usage * dt)

    def get_body_polygon(self) -> list[Vector2]:
        # Upright rectangle in world space using current pose (always 0)
        half_w = self.width / 2.0
        half_h = self.height / 2.0
        local_pts = [
            Vector2(-half_w, -half_h),
            Vector2(half_w, -half_h),
            Vector2(half_w, half_h),
            Vector2(-half_w, half_h),
        ]
        
        pos = getattr(self, "pos", Vector2(self.x, self.y))
        tf = RigidTransform2(pos, self.rotation)
        
        world_pts = []
        for pt in local_pts:
            world_pts.append(tf.apply(pt))
            
        return world_pts

    def get_thrusts(self) -> list["Lander.Thrust"]:
        thrusts: list[Lander.Thrust] = []
        # Vertical thruster at bottom center
        if self.thrust_up > 1e-3:
            half_h = self.height / 2.0
            cos_r = math.cos(self.rotation)
            sin_r = math.sin(self.rotation)
            base_x = self.x + (0.0 * cos_r) + (-half_h * 1.2) * sin_r
            base_y = self.y + (-0.0 * sin_r) + (-half_h * 1.2) * cos_r
            thrusts.append(
                Lander.Thrust(
                    x=base_x,
                    y=base_y,
                    angle=-math.pi / 2.0,
                    width=self.width / 2.0,
                    length=20.0,
                    power=self.thrust_up,
                )
            )
        # Right-side thruster (pressing LEFT): flame from right side toward -x
        if self.thrust_right > 1e-3:
            half_w = self.width / 2.0
            base_x = self.x + half_w
            base_y = self.y
            thrusts.append(
                Lander.Thrust(
                    x=base_x,
                    y=base_y,
                    angle=0.0,
                    width=self.height / 3.0,
                    length=14.0,
                    power=self.thrust_right,
                )
            )
        # Left-side thruster (pressing RIGHT): flame from left side toward +x
        if self.thrust_left > 1e-3:
            half_w = self.width / 2.0
            base_x = self.x - half_w
            base_y = self.y
            thrusts.append(
                Lander.Thrust(
                    x=base_x,
                    y=base_y,
                    angle=math.pi,
                    width=self.height / 3.0,
                    length=14.0,
                    power=self.thrust_left,
                )
            )
        return thrusts


def create_lander() -> Lander:
    return SimpleLander()


