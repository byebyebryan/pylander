"""Input collection: translate OS events into simple control signals only.

Mouse input is not used for camera control.
"""

import pygame


class InputHandler:
    """Collects input events and key states, without applying any game logic."""

    def __init__(self):
        pass

    def get_events(self) -> dict:
        """Poll pygame events and return (running, signals).

        Signals include:
          - quit: bool
          - reset: bool
          - zoom_in, zoom_out (keyboard-based)
          - thrust_up, thrust_down, rot_left, rot_right, refuel
          - pan_left, pan_right, pan_up, pan_down
        """
        signals: dict = {"quit": False, "reset": False}
        # No mouse-based camera control; only handle quit/reset keys here

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                signals["quit"] = True
            elif event.type == pygame.KEYDOWN:
                if event.key in (pygame.K_ESCAPE, pygame.K_q):
                    signals["quit"] = True
                elif event.key == pygame.K_r:
                    signals["reset"] = True
                elif event.key == pygame.K_TAB:
                    signals["switch_actor"] = True
        # Keyboard-based zoom flags
        ks = pygame.key.get_pressed()
        signals["zoom_in"] = bool(ks[pygame.K_EQUALS] or ks[pygame.K_PAGEUP])
        signals["zoom_out"] = bool(ks[pygame.K_MINUS] or ks[pygame.K_PAGEDOWN])
        # Merge continuous key state into signals
        signals.update(
            {
                "thrust_up": bool(ks[pygame.K_UP] or ks[pygame.K_w]),
                "thrust_down": bool(ks[pygame.K_DOWN] or ks[pygame.K_s]),
                "rot_left": bool(ks[pygame.K_LEFT] or ks[pygame.K_a]),
                "rot_right": bool(ks[pygame.K_RIGHT] or ks[pygame.K_d]),
                "refuel": bool(ks[pygame.K_f]),
                "pan_left": bool(ks[pygame.K_LEFT] or ks[pygame.K_a]),
                "pan_right": bool(ks[pygame.K_RIGHT] or ks[pygame.K_d]),
                "pan_up": bool(ks[pygame.K_UP] or ks[pygame.K_w]),
                "pan_down": bool(ks[pygame.K_DOWN] or ks[pygame.K_s]),
            }
        )
        signals.setdefault("switch_actor", False)

        return signals
