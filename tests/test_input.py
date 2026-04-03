from __future__ import annotations

import pygame

from utils.input import InputHandler


class _Pressed(dict):
    def __getitem__(self, key: int) -> bool:
        return bool(self.get(key, False))


def test_input_handler_keeps_flight_controls_out_of_camera_pan(monkeypatch) -> None:
    monkeypatch.setattr(pygame.event, "get", lambda: [])
    monkeypatch.setattr(
        pygame.key,
        "get_pressed",
        lambda: _Pressed({pygame.K_w: True, pygame.K_a: True}),
    )

    signals = InputHandler().get_events()

    assert signals["thrust_up"] is True
    assert signals["rot_left"] is True
    assert signals["pan_up"] is False
    assert signals["pan_left"] is False


def test_input_handler_uses_ijkl_for_camera_pan(monkeypatch) -> None:
    monkeypatch.setattr(pygame.event, "get", lambda: [])
    monkeypatch.setattr(
        pygame.key,
        "get_pressed",
        lambda: _Pressed({pygame.K_i: True, pygame.K_j: True}),
    )

    signals = InputHandler().get_events()

    assert signals["pan_up"] is True
    assert signals["pan_left"] is True
    assert signals["thrust_up"] is False
    assert signals["rot_left"] is False
