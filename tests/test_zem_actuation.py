from __future__ import annotations

import math

import pytest

from bots._zem_actuation import command_passive_coast
from bots._zem_config import ZemZevConfig
from core.bot import Sensors


class _Bot:
    def __init__(self) -> None:
        self._cfg = ZemZevConfig()
        self._prev_angle_cmd = 0.0
        self._thrust_enabled = True


def _sensors(*, vx: float, vy_up: float) -> Sensors:
    return Sensors(
        x=0.0,
        y=0.0,
        altitude=100.0,
        terrain_y=0.0,
        terrain_slope=0.0,
        vx=vx,
        vy_up=vy_up,
        angle=0.0,
        ax=0.0,
        ay_up=0.0,
        mass=1000.0,
        thrust_level=0.0,
        fuel=100.0,
        max_fuel=100.0,
        state="flying",
        radar_contacts=[],
        proximity=None,
    )


def test_command_passive_coast_points_retrograde_with_zero_thrust() -> None:
    bot = _Bot()

    action = command_passive_coast(
        bot,
        dt=1.0,
        passive=_sensors(vx=12.0, vy_up=-16.0),
    )

    assert action.target_thrust == 0.0
    assert action.target_angle == pytest.approx(math.atan2(-12.0, 16.0))
    assert bot._prev_angle_cmd == pytest.approx(action.target_angle)
    assert bot._thrust_enabled is False


def test_command_passive_coast_falls_back_to_upright_when_speed_is_tiny() -> None:
    bot = _Bot()
    bot._prev_angle_cmd = 0.3

    action = command_passive_coast(
        bot,
        dt=1.0,
        passive=_sensors(vx=0.0, vy_up=0.0),
    )

    assert action.target_thrust == 0.0
    assert action.target_angle == pytest.approx(0.0)
