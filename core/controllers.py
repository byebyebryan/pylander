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
        
        # Even if not pressed, we might return None to indicate "no control overrides"
        # but the original logic returned (targets..., refuel) if any_pressed, else None.
        # However, the auto-rounding/snapping logic happens when keys are NOT pressed.
        # If we return None, those changes are lost if the caller ignores None.
        # In the original code:
        # if any_pressed: return (...)
        # return None
        # AND it updated self.target_thrust/angle in place.
        
        # Since this controller is pure logic (doesn't hold state), it returns the new values.
        # The caller acts on them. current_target_thrust came in, we return potentially modified version.
        # But if we return None, the caller might assumes "no change".
        # But logic like "if not signals... target_thrust = round..." modifies state even if no key pressed.
        
        # Correction: The original code modified `self.target_thrust` regardless of `any_pressed`.
        # `any_pressed` only determined the return value.
        # But `handle_input` was called every frame.
        # If we return None, the game loop might not apply the controls?
        # In `game.py`:
        # uc = self.lander.handle_input(input_events, frame_dt)
        # if uc is not None: user_controls = uc
        
        # If `uc` is None (no keys pressed), `user_controls` remains None.
        # Then `_bot_override_timer` counts down.
        # If `_bot_override_timer` is > 0 and user_controls is None, `controls` is None?
        # Wait, if `user_controls` is None, we check bot timer.
        
        # If we want to preserve "snapping" behavior when keys are released,
        # we must return the snapped values at least once?
        # Or `handle_input` updated the internal state of Lander *permanently*, 
        # and the return value was just to say "User is ACTING, disable bot".
        
        # So we should split this:
        # 1. Update the target state (always happens).
        # 2. Return "User Active" boolean or control tuple if user is acting.
        
        # But here we are just returning values.
        # I'll return the tuple (target_thrust, target_angle, refuel).
        # AND a boolean "is_active" or similar?
        # Or just return the tuple, and let the game decide if it counts as "active input".
        
        # To match original `handle_input` return behavior (only return if keys pressed):
        # We need to return the modified state ALWAYS, because of the snapping/rounding which happens when keys are NOT pressed.
        # But `game.py` only uses the return value to override the bot.
        
        # So:
        # The snapping logic modifies `target_angle`. `Lander` uses `target_angle` in `apply_controls`.
        # `game.py` calls `handle_input`. If it returns None, `user_controls` is None.
        # But `Lander.target_angle` WAS UPDATED side-effectually in `handle_input`.
        # `Lander.apply_controls` uses `self.target_thrust/angle`.
        
        # So `Lander` state was updated even if `handle_input` returned None.
        # `apply_controls` applies that state.
        
        # If we remove `handle_input` from `Lander`, `Game` needs to update `Lander.target_thrust/angle`.
        # So `PlayerController.update` should return `(new_thrust, new_angle, refuel, user_active)`.
        
        return (target_thrust, target_angle, refuel)

    def is_user_active(self, signals: dict) -> bool:
        """Check if user is actively providing input."""
        return (
            signals.get("thrust_up")
            or signals.get("thrust_down")
            or signals.get("rot_left")
            or signals.get("rot_right")
            or signals.get("refuel")
        )
