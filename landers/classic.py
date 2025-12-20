from __future__ import annotations

import math
from lander import Lander


class ClassicLander(Lander):
    """Classic lander: rotation + single main engine (default behavior)."""

    def get_engine_override_angle(self) -> float | None:
        return self.rotation

    def get_engine_force(self):
        if self.thrust_level <= 0.0 or self.fuel <= 0.0:
            return None
        thrust = self.thrust_level * self.max_thrust_power
        fx = math.sin(self.rotation) * thrust
        fy = math.cos(self.rotation) * thrust
        visual_angle = math.atan2(-fy, -fx)
        return (fx, fy, visual_angle, self.thrust_level)

    def get_controls_text(self) -> list[str]:
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


def create_lander() -> Lander:
    return ClassicLander()



