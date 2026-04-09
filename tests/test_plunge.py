from __future__ import annotations

import pytest

import bot_framework.bots.common_math as common_math
import bot_framework.bots.plunge as plunge_module
from bot_framework.bots.common_ballistics import BallisticProjection
from bot_framework.bots.plunge import PlungeBot
from conftest import make_sensors
from core.sensor import RadarContact


def _target(*, x: float = 0.0, y: float = 0.0) -> RadarContact:
    return RadarContact(
        uid="target",
        x=x,
        y=y,
        size=100.0,
        angle=0.0,
        distance=0.0,
        rel_x=0.0,
        rel_y=0.0,
        is_inner_lock=True,
        info=None,
    )


def test_vehicle_limits_uses_runtime_gravity(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(common_math, "_GRAVITY_MAG", 1.62)

    mass, up_acc_max = common_math.vehicle_limits(
        make_sensors(mass=8.0, y=50.0, altitude=50.0, vy_up=-5.0), 40.0
    )

    assert mass == pytest.approx(8.0)
    assert up_acc_max == pytest.approx((40.0 / 8.0) - 1.62)


def test_plunge_vertical_controller_uses_runtime_gravity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(plunge_module, "_GRAVITY_MAG", 1.62)
    bot = PlungeBot()
    passive = make_sensors(vy_up=-1.2, y=50.0, altitude=50.0, mass=10.0)

    terminal = bot._vertical_controller(
        passive,
        vy_sp=-1.5,
        alt=10.0,
        vertical_mode="terminal_burn",
        up_acc_max=4.0,
    )
    flare = bot._vertical_controller(
        passive,
        vy_sp=-2.0,
        alt=20.0,
        vertical_mode="flare",
        up_acc_max=4.0,
    )

    assert terminal == pytest.approx(
        1.62 + (bot._policy.terminal_brake_gain_high_alt * 4.0)
    )
    assert flare == pytest.approx(1.62 + (0.38 * (-0.8)))


def test_plunge_guidance_uses_half_runtime_gravity_for_spool_distance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(common_math, "_GRAVITY_MAG", 1.62)
    monkeypatch.setattr(plunge_module, "_GRAVITY_MAG", 1.62)
    bot = PlungeBot()
    passive = make_sensors(y=50.0, altitude=50.0, vy_up=-5.0, mass=10.0)
    projection = BallisticProjection(
        projected_dx=0.0,
        t_fall=100.0,
        target_x=0.0,
        impact_x=0.0,
        has_target_y_solution=True,
    )

    guidance = bot._guidance(
        passive,
        _target(),
        max_force=40.0,
        max_throttle=1.0,
        ramp_up=1.0,
        projection=projection,
        time_to_impact=100.0,
    )

    down_speed = 5.0
    flare_speed = 2.2
    up_acc_max = (40.0 / 10.0) - 1.62
    speed_to_kill = down_speed - flare_speed
    expected_spool_distance = down_speed + (0.5 * 1.62)
    expected_stop_distance = (speed_to_kill * speed_to_kill) / (2.0 * up_acc_max)
    expected_burn_altitude = expected_stop_distance + expected_spool_distance + 2.1

    assert guidance.burn_altitude == pytest.approx(expected_burn_altitude)
