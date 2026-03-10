from __future__ import annotations

import pytest

from bots import create_bot
from bots._ballistics import (
    BallisticProjection,
    estimate_ground_time_to_impact,
    estimate_target_y_projection,
)
from core.bot import Bot, BotAction, Sensors
from core.terrain import ballistic_fall_time
from game import LanderGame
from levels import create_level as create_level_by_name


def test_sensors_only_bot_path_and_profile_metrics(monkeypatch: pytest.MonkeyPatch) -> None:
    class _CountingBot(Bot):
        def __init__(self) -> None:
            super().__init__()
            self.update_calls = 0

        def update(self, dt: float, sensors: Sensors) -> BotAction:
            _ = dt, sensors
            self.update_calls += 1
            return BotAction(target_thrust=0.0, target_angle=0.0, refuel=False)

    monkeypatch.setenv("PYLANDER_BOT_PROFILE", "1")
    monkeypatch.setenv("PYLANDER_BOT_PROFILE_INTERVAL_S", "0.25")
    level = create_level_by_name("flat")
    bot = _CountingBot()
    game = LanderGame(level=level, seed=0, bot=bot, headless=True)
    result = game.run(print_freq=0, max_steps=30, max_time=10.0)

    assert bot.update_calls > 0
    assert result["bot_profile_enabled"] is True
    assert result["bot_profile_ticks"] > 0
    assert "bot_profile_query_total" not in result


def test_target_y_projection_returns_crossing_for_descending_target() -> None:
    projection = estimate_target_y_projection(
        dx=20.0,
        dy=-200.0,
        vx=15.0,
        vy_up=-30.0,
        x=10.0,
        y=200.0,
        min_t_fall=0.0,
    )
    assert isinstance(projection, BallisticProjection)
    assert projection.has_target_y_solution is True
    assert projection.t_fall > 0.0
    assert projection.target_x == pytest.approx(30.0)
    assert projection.impact_x is not None
    assert projection.projected_dx == pytest.approx(projection.target_x - projection.impact_x)


def test_target_y_projection_reports_no_solution_when_apex_below_target() -> None:
    projection = estimate_target_y_projection(
        dx=80.0,
        dy=150.0,
        vx=10.0,
        vy_up=5.0,
        x=25.0,
        y=100.0,
        min_t_fall=0.0,
    )
    assert projection.has_target_y_solution is False
    assert projection.t_fall >= 0.0


def test_estimate_ground_time_to_impact_matches_ballistic_fall_time() -> None:
    t = estimate_ground_time_to_impact(altitude=150.0, vy_up=-10.0, min_t_fall=0.0)
    expected = ballistic_fall_time(altitude=150.0, vy_up=-10.0)
    assert t == pytest.approx(expected)


def test_plunge_and_pdg_are_bots(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PYLANDER_BOT_PROFILE", "1")

    plunge = create_bot("plunge")
    assert isinstance(plunge, Bot)
    plunge_game = LanderGame(
        level=create_level_by_name("plunge"),
        seed=0,
        bot=plunge,
        headless=True,
    )
    plunge_result = plunge_game.run(print_freq=0, max_steps=40, max_time=20.0)
    assert float(plunge_result["bot_profile_update_ms_per_tick"]) >= 0.0

    pdg = create_bot("pdg")
    assert isinstance(pdg, Bot)
    pdg_game = LanderGame(
        level=create_level_by_name("flare_normal"),
        seed=0,
        bot=pdg,
        headless=True,
    )
    pdg_result = pdg_game.run(print_freq=0, max_steps=40, max_time=20.0)
    assert float(pdg_result["bot_profile_update_ms_per_tick"]) >= 0.0
