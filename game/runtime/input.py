"""Input collection: translate OS events into simple control signals only.

Mouse input is not used for camera control.
"""

import pygame


class InputHandler:
    """Collects input events and key states, without applying any game logic."""

    def __init__(self):
        self._external_events: list | None = None

    def get_events(self) -> dict:
        """Poll pygame events and return (running, signals).

        Signals include:
          - quit: bool
          - reset: bool
          - toggle_ballistic: bool
          - zoom_in, zoom_out (keyboard-based)
          - thrust_up, thrust_down, rot_left, rot_right, refuel
          - pan_left, pan_right, pan_up, pan_down (I/J/K/L)
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
                "pan_left": bool(ks[pygame.K_j]),
                "pan_right": bool(ks[pygame.K_l]),
                "pan_up": bool(ks[pygame.K_i]),
                "pan_down": bool(ks[pygame.K_k]),
            }
        )
        signals.setdefault("switch_actor", False)
        signals.setdefault("toggle_ballistic", False)

        return signals
