"""Controllers for handling user input and translating it to game actions."""

import math
from utils.protocols import ControlTuple


class PlayerController:
    """Translates input signals into control targets for a lander."""

    def __init__(self):
        pass

    def update(
        self,
        signals: dict,
        dt: float,
        current_target_thrust: float,
        current_target_angle: float,
        max_rotation_rate: float,
    ) -> ControlTuple | None:
        """Process input signals and update control targets.

        Returns a ControlTuple (target_thrust, target_angle, refuel) if any input
        is active, otherwise returns None.
        """
        target_thrust = current_target_thrust
        target_angle = current_target_angle
        
        # Thrust control
        if signals.get("thrust_up"):
            target_thrust = min(1.0, target_thrust + 1.5 * dt)
        if signals.get("thrust_down"):
            target_thrust = max(0.0, target_thrust - 1.5 * dt)
        
        # Auto-round to nearest 0.1 when not actively changing
        if not signals.get("thrust_up") and not signals.get("thrust_down"):
            target_thrust = round(target_thrust * 10.0) / 10.0

        # Rotation control
        # Angles are CW-from-up: left = CCW (decrease), right = CW (increase)
        if signals.get("rot_left"):
            target_angle -= max_rotation_rate * dt
        if signals.get("rot_right"):
            target_angle += max_rotation_rate * dt
            
        # Auto-snap to 45 degree increments when not actively rotating
        if not signals.get("rot_left") and not signals.get("rot_right"):
            deg = math.degrees(target_angle)
            snapped = round(deg / 45.0) * 45.0
            if abs(deg - snapped) < 5:
                target_angle = math.radians(snapped)

        refuel = bool(signals.get("refuel"))
        
        any_pressed = (
            signals.get("thrust_up")
            or signals.get("thrust_down")
            or signals.get("rot_left")
            or signals.get("rot_right")
            or refuel
        )

        if any_pressed:
            return (target_thrust, target_angle, refuel)
        return None

    def is_user_active(self, signals: dict) -> bool:
        """Check if user is actively providing input."""
        return (
            signals.get("thrust_up")
            or signals.get("thrust_down")
            or signals.get("rot_left")
            or signals.get("rot_right")
            or signals.get("refuel")
        )
