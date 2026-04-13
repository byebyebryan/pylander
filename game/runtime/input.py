"""Input collection: translate OS events into simple control signals only.

Handles both keyboard and gamepad (joystick) input.
Mouse input is not used for camera control.
"""

from __future__ import annotations

import pygame

_AXIS_DEADZONE = 0.3

# Standard SDL gamepad layout (nintendo button labelling):
# a:b0, b:b1, x:b2, y:b3, leftshoulder:b4, rightshoulder:b5, start:b6, back:b7
# D-pad: hat 0 — (x, y) where y=1 up, y=-1 down, x=-1 left, x=1 right
# Left stick: axis 0 (X), axis 1 (Y, up = negative)

_JOY_THRUST_BTN = 2    # X button → thrust (held)
_JOY_REFUEL_BTN = 6    # Start → refuel (held)

# Buttons that generate one-shot signals directly (not held continuous controls)
# Button 0 (A) and 1 (B) are intercepted by GameHost for menu navigation / pause
_JOY_SIGNAL_BTNS: dict[int, str] = {
    3: "reset",         # Y → reset
    4: "switch_actor",  # L1 → switch actor
    5: "switch_actor",  # R1 → switch actor
    7: "toggle_ballistic",  # Select → toggle ballistic
}


class InputHandler:
    """Collects input events and key states, without applying any game logic."""

    def __init__(self):
        self._external_events: list | None = None
        self._joystick: pygame.joystick.Joystick | None = None
        self._joy_held: set[int] = set()
        self._joy_hat: tuple[int, int] = (0, 0)
        self._joy_axis: dict[int, float] = {}
        self._init_joystick()

    def _init_joystick(self) -> None:
        try:
            pygame.joystick.init()
            if pygame.joystick.get_count() > 0:
                self._joystick = pygame.joystick.Joystick(0)
        except Exception:
            pass

    def get_events(self) -> dict:
        """Poll pygame events and return signals dict.

        Signals:
          quit, reset, toggle_ballistic, switch_actor
          thrust_up, thrust_down, rot_left, rot_right
          refuel, zoom_in, zoom_out
          pan_left, pan_right, pan_up, pan_down
        """
        signals: dict = {"quit": False, "reset": False, "toggle_ballistic": False}

        if self._external_events is not None:
            events = self._external_events
        else:
            events = pygame.event.get()

        for event in events:
            if event.type == pygame.QUIT:
                signals["quit"] = True
            elif event.type == pygame.KEYDOWN:
                if event.key in (pygame.K_ESCAPE, pygame.K_q):
                    signals["quit"] = True
                elif event.key == pygame.K_r:
                    signals["reset"] = True
                elif event.key == pygame.K_TAB:
                    signals["switch_actor"] = True
                elif event.key == pygame.K_t:
                    signals["toggle_ballistic"] = True
            elif event.type == pygame.JOYBUTTONDOWN:
                btn = event.button
                self._joy_held.add(btn)
                sig = _JOY_SIGNAL_BTNS.get(btn)
                if sig:
                    signals[sig] = True
            elif event.type == pygame.JOYBUTTONUP:
                self._joy_held.discard(event.button)
            elif event.type == pygame.JOYHATMOTION:
                self._joy_hat = event.value
            elif event.type == pygame.JOYAXISMOTION:
                self._joy_axis[event.axis] = event.value

        ks = pygame.key.get_pressed()

        hat_x, hat_y = self._joy_hat
        ax = self._joy_axis.get(0, 0.0)   # left stick X
        ay = self._joy_axis.get(1, 0.0)   # left stick Y (push up → negative)

        joy_up = (hat_y > 0) or (ay < -_AXIS_DEADZONE) or (_JOY_THRUST_BTN in self._joy_held)
        joy_down = (hat_y < 0) or (ay > _AXIS_DEADZONE)
        joy_left = (hat_x < 0) or (ax < -_AXIS_DEADZONE)
        joy_right = (hat_x > 0) or (ax > _AXIS_DEADZONE)

        signals["zoom_in"] = bool(ks[pygame.K_EQUALS] or ks[pygame.K_PAGEUP])
        signals["zoom_out"] = bool(ks[pygame.K_MINUS] or ks[pygame.K_PAGEDOWN])
        signals.update({
            "thrust_up":  bool(ks[pygame.K_UP]   or ks[pygame.K_w]) or joy_up,
            "thrust_down": bool(ks[pygame.K_DOWN] or ks[pygame.K_s]) or joy_down,
            "rot_left":   bool(ks[pygame.K_LEFT]  or ks[pygame.K_a]) or joy_left,
            "rot_right":  bool(ks[pygame.K_RIGHT] or ks[pygame.K_d]) or joy_right,
            "refuel":     bool(ks[pygame.K_f]) or (_JOY_REFUEL_BTN in self._joy_held),
            "pan_left":   bool(ks[pygame.K_j]),
            "pan_right":  bool(ks[pygame.K_l]),
            "pan_up":     bool(ks[pygame.K_i]),
            "pan_down":   bool(ks[pygame.K_k]),
        })
        signals.setdefault("switch_actor", False)
        signals.setdefault("toggle_ballistic", False)

        return signals
