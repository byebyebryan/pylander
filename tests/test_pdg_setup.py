from __future__ import annotations

from types import SimpleNamespace

import pytest

from bots._ballistics import estimate_target_y_projection
from bots.pdg.config import PDGConfig
from bots.pdg.setup import (
    evaluate_setup_quality,
    evaluate_setup_quality_after_settle,
    setup_cut_wind_down_s,
    setup_objective_geometry,
)
from core.config import GRAVITY


class _Bot:
    def __init__(self) -> None:
        self._cfg = PDGConfig()
        self._shape_window_started = False
        self._shape_anchor_dx_abs = 0.0
        self._last_target_half = 55.0
        self._last_target_y = 0.0
        self.vehicle_info = None

    def _shape_apex_target(self, dx_abs: float) -> float:
        cfg = self._cfg
        apex = float(cfg.setup_apex_height_per_dx) * max(0.0, float(dx_abs))
        return max(float(cfg.setup_apex_height_min), min(float(cfg.setup_apex_height_max), apex))


def _passive(*, x: float = 0.0, y: float = 120.0, vx: float = 0.0, vy_up: float = -12.0):
    return SimpleNamespace(x=x, y=y, vx=vx, vy_up=vy_up)


def _projection(*, projected_dx: float, t_fall: float, has_target_y_solution: bool = True):
    return SimpleNamespace(
        projected_dx=projected_dx,
        t_fall=t_fall,
        has_target_y_solution=has_target_y_solution,
    )


def test_setup_objective_geometry_uses_reference_miss_when_target_y_is_unreachable() -> None:
    bot = _Bot()

    geometry = setup_objective_geometry(
        bot,
        passive=_passive(vx=12.0, vy_up=6.0),
        dx=140.0,
        projection=_projection(projected_dx=120.0, t_fall=2.0, has_target_y_solution=False),
        setup_t_cross_ref=3.0,
    )

    assert geometry.has_target_y_solution is False
    assert geometry.projected_dx == pytest.approx(104.0)
    assert geometry.no_away_ax_sign == pytest.approx(1.0)
    assert geometry.angle_scale == pytest.approx(0.0)


def test_setup_objective_geometry_enables_angle_for_shallow_reachable_entry() -> None:
    bot = _Bot()

    geometry = setup_objective_geometry(
        bot,
        passive=_passive(vx=20.0, vy_up=2.0),
        dx=-90.0,
        projection=_projection(projected_dx=-90.0, t_fall=3.0),
        setup_t_cross_ref=3.0,
    )

    assert geometry.has_target_y_solution is True
    assert geometry.no_away_ax_sign == pytest.approx(-1.0)
    assert geometry.angle_scale == pytest.approx(1.0)


def test_setup_objective_geometry_disables_angle_term_when_entry_is_already_steep() -> None:
    bot = _Bot()

    geometry = setup_objective_geometry(
        bot,
        passive=_passive(vx=4.0, vy_up=-15.0),
        dx=30.0,
        projection=_projection(projected_dx=30.0, t_fall=2.0),
        setup_t_cross_ref=2.0,
    )

    assert geometry.no_away_ax_sign == pytest.approx(0.0)
    assert geometry.angle_scale == pytest.approx(0.0)
    assert float(geometry.impact_angle_deg or 0.0) > float(bot._cfg.setup_descent_angle_deg_target)


def test_setup_objective_geometry_keeps_no_away_thrust_aligned_with_target_direction() -> None:
    bot = _Bot()

    geometry = setup_objective_geometry(
        bot,
        passive=_passive(vx=30.0, vy_up=6.0),
        dx=90.0,
        projection=_projection(projected_dx=-60.0, t_fall=5.0),
        setup_t_cross_ref=5.0,
    )

    assert geometry.projected_dx == pytest.approx(-60.0)
    assert geometry.no_away_ax_sign == pytest.approx(1.0)


def test_evaluate_setup_quality_ignores_apex_mismatch_and_steep_entry() -> None:
    bot = _Bot()

    quality = evaluate_setup_quality(
        bot,
        passive=_passive(y=80.0, vx=2.0, vy_up=-18.0),
        dx=20.0,
        dy=-120.0,
        projection=_projection(projected_dx=8.0, t_fall=3.0),
        dx_anchor_abs=20.0,
    )

    assert quality.verdict == "pass"
    assert quality.passed is True
    assert abs(float(quality.projected_apex_over_target) - float(quality.apex_target)) > float(
        quality.apex_tolerance
    )
    assert float(quality.impact_angle_deg or 0.0) > float(bot._cfg.setup_descent_angle_deg_target)


def test_evaluate_setup_quality_after_settle_matches_ballistic_propagation_without_thrust() -> None:
    bot = _Bot()
    passive = _passive(x=10.0, y=90.0, vx=8.0, vy_up=-6.0)
    dx = 25.0
    dy = -90.0
    settle_s = 0.5

    settled_quality = evaluate_setup_quality_after_settle(
        bot,
        passive=passive,
        dx=dx,
        dy=dy,
        settle_s=settle_s,
        dx_anchor_abs=25.0,
    )

    gravity = abs(float(GRAVITY))
    x_settle = float(passive.x) + (float(passive.vx) * settle_s)
    y_settle = float(passive.y) + (float(passive.vy_up) * settle_s) - (
        0.5 * gravity * settle_s * settle_s
    )
    vy_settle = float(passive.vy_up) - (gravity * settle_s)
    dx_settle = (float(passive.x) + dx) - x_settle
    dy_settle = (float(passive.y) + dy) - y_settle
    settled_passive = _passive(x=x_settle, y=y_settle, vx=8.0, vy_up=vy_settle)
    projection = estimate_target_y_projection(
        dx=dx_settle,
        dy=dy_settle,
        vx=float(settled_passive.vx),
        vy_up=float(settled_passive.vy_up),
        x=float(settled_passive.x),
        y=float(settled_passive.y),
        min_t_fall=0.0,
        gravity_mag=gravity,
    )
    direct_quality = evaluate_setup_quality(
        bot,
        passive=settled_passive,
        dx=dx_settle,
        dy=dy_settle,
        projection=projection,
        dx_anchor_abs=25.0,
    )

    assert settled_quality.verdict == direct_quality.verdict
    assert settled_quality.passed is direct_quality.passed
    assert settled_quality.projected_dx == pytest.approx(direct_quality.projected_dx)
    assert settled_quality.impact_angle_deg == pytest.approx(direct_quality.impact_angle_deg)


def test_setup_cut_wind_down_s_uses_idle_decay_time_when_longer_than_minimum() -> None:
    bot = _Bot()
    bot.vehicle_info = SimpleNamespace(thrust_decrease_rate=1.8)
    passive = SimpleNamespace(thrust_level=1.6)

    settle_s = setup_cut_wind_down_s(
        bot,
        passive=passive,
        minimum_s=0.25,
    )

    assert settle_s == pytest.approx((1.6 - 0.03) / 1.8)


def test_setup_cut_wind_down_s_respects_minimum_when_already_near_idle() -> None:
    bot = _Bot()
    bot.vehicle_info = SimpleNamespace(thrust_decrease_rate=1.8)
    passive = SimpleNamespace(thrust_level=0.02)

    settle_s = setup_cut_wind_down_s(
        bot,
        passive=passive,
        minimum_s=0.25,
    )

    assert settle_s == pytest.approx(0.25)
