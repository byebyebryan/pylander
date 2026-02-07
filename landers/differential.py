from __future__ import annotations

import math
from core.lander import Lander


class DifferentialLander(Lander):
    """Hard lander: two engines; rotation via differential thrust.

    Keys:
    - W/S: increase/decrease LEFT engine power
    - A/D: increase/decrease RIGHT engine power
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.left_target = 0.0
        self.right_target = 0.0
        self.left = 0.0
        self.right = 0.0
        # Wider body
        self.width = 10.0
        self.height = 7.0

    def handle_input(self, signals: dict, dt: float):
        if self.state not in ("flying", "landed"):
            return None
        # Map keys directly to individual engines
        if signals.get("thrust_up"):
            self.left_target = min(1.0, self.left_target + 1.5 * dt)
        if signals.get("thrust_down"):
            self.left_target = max(0.0, self.left_target - 1.5 * dt)
        if signals.get("rot_right"):
            self.right_target = min(1.0, self.right_target + 1.5 * dt)
        if signals.get("rot_left"):
            self.right_target = max(0.0, self.right_target - 1.5 * dt)

        refuel = bool(signals.get("refuel"))

        if self.state == "landed" and (self.left_target > 0.0 or self.right_target > 0.0):
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

    def apply_controls(self, dt: float, _controls):
        # Slew each throttle
        def _slew(cur, tgt):
            d = tgt - cur
            if d > 0:
                return min(1.0, cur + self.thrust_increase_rate * dt)
            if d < 0:
                return max(0.0, cur - self.thrust_decrease_rate * dt)
            return cur

        self.left = _slew(self.left, self.left_target)
        self.right = _slew(self.right, self.right_target)

        # Update target_angle from torque due to differential
        diff = max(0.0, self.right) - max(0.0, self.left)
        if abs(diff) > 1e-3:
            self.target_angle += math.copysign(self.max_rotation_rate * dt, diff)
        # Let base smoothing move rotation toward target angle (thrust unaffected)
        super().apply_controls(dt, (None, self.target_angle, False))

    def get_engine_override_angle(self) -> float | None:
        # Use current smoothed rotation as pose
        return self.rotation

    def get_engine_force(self):
        if self.fuel <= 0.0:
            return None
        thrust_left = self.left * self.max_thrust_power
        thrust_right = self.right * self.max_thrust_power
        thrust = thrust_left + thrust_right
        if thrust <= 0.0:
            return None
        # Force direction by current pose
        fx = math.sin(self.rotation) * thrust
        fy = math.cos(self.rotation) * thrust
        visual_angle = math.atan2(-fy, -fx)
        power = min(1.0, thrust / max(1e-6, self.max_thrust_power))
        return (fx, fy, visual_angle, power)

    def get_fuel_burn(self, dt: float) -> float:
        usage = max(0.0, min(1.0, 0.5 * (self.left + self.right)))
        return max(0.0, self.fuel_burn_rate * usage * dt)

    def get_thrusts(self) -> list["Lander.Thrust"]:
        # Two nozzles under left and right
        thrusts: list[Lander.Thrust] = []
        half_w = self.width / 2.0
        half_h = self.height / 2.0
        cos_r = math.cos(self.rotation)
        sin_r = math.sin(self.rotation)
        # Base offsets left/right
        for side, power, xsign in (("left", self.left, -1.0), ("right", self.right, 1.0)):
            if power <= 1e-3:
                continue
            # Local base under the hull near each side
            local_x = xsign * (half_w * 0.5)
            local_y = -half_h * 1.1
            base_x = self.x + local_x * cos_r + local_y * sin_r
            base_y = self.y - local_x * sin_r + local_y * cos_r
            angle = math.atan2(-cos_r, -sin_r)
            thrusts.append(
                Lander.Thrust(
                    x=base_x,
                    y=base_y,
                    angle=angle,
                    width=self.width / 3.0,
                    length=20.0,
                    power=power,
                )
            )
        return thrusts

    def get_controls_text(self) -> list[str]:
        return [
            "Controls:",
            "W/UP: Increase lift",
            "S/DOWN: Decrease lift",
            "A/LEFT: Bias left engine (rotate left)",
            "D/RIGHT: Bias right engine (rotate right)",
            "F: Refuel (when landed)",
            "R: Reset",
            "Q/ESC: Quit",
        ]

    def get_physics_polygons(self):
        # Wide hex-like body: two triangles joined
        w = self.width
        h = self.height
        half_w = w / 2.0
        half_h = h / 2.0
        # Simple convex hex approximated by rectangle with beveled corners (as one convex poly)
        return [[
            (-half_w, -half_h * 0.6),
            (-half_w * 0.6, -half_h),
            (half_w * 0.6, -half_h),
            (half_w, -half_h * 0.6),
            (half_w, half_h),
            (-half_w, half_h),
        ]]


def create_lander() -> Lander:
    return DifferentialLander()


