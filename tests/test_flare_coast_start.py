from __future__ import annotations

import pytest

from bots import create_bot
from game import LanderGame
from levels import create_level


@pytest.mark.parametrize(
    ("level_name", "scenario_name"),
    (
        ("flare_normal", "mid"),
        ("flare_error", "mid_tight"),
    ),
)
def test_flare_levels_prime_setup_gate_and_start_in_coast(
    level_name: str,
    scenario_name: str,
) -> None:
    level = create_level(level_name)
    level.set_eval_scenario(scenario_name)
    bot = create_bot("zem_zev")

    game = LanderGame(level=level, seed=0, bot=bot, headless=True)

    snapshot = bot.get_flight_phase_snapshot()
    assert snapshot is not None
    assert snapshot.phase == "coast"
    assert snapshot.milestones == ("setup_gate",)
    assert snapshot.setup_gate is not None
    assert snapshot.setup_gate.time_s == pytest.approx(0.0)
    assert snapshot.setup_gate.burn_duration_s == pytest.approx(0.0)
    assert snapshot.setup_gate.burn_fuel_used == pytest.approx(0.0)
    assert snapshot.setup_gate.burn_avg_thrust_level == pytest.approx(0.0)

    result = game.run(print_freq=0, max_steps=5, max_time=5.0)
    assert result["setup_gate_done"] is True
    assert result["setup_gate_time"] == pytest.approx(0.0)
    assert result["setup_gate_burn_duration_s"] == pytest.approx(0.0)
    assert result["setup_gate_burn_fuel_used"] == pytest.approx(0.0)
    assert result["bot_zem_zev_solve_count"] == 0


def test_flare_error_wide_triggers_flare_gate_before_impact() -> None:
    level = create_level("flare_error")
    level.set_eval_scenario("mid_wide")
    bot = create_bot("zem_zev")

    game = LanderGame(level=level, seed=0, bot=bot, headless=True)
    result = game.run(print_freq=0, max_time=12.0)

    assert result["state"] == "flying"
    assert result["bot_zem_zev_terminal_gate_done"] is True
    assert result["bot_zem_zev_terminal_gate_time"] is not None
    assert result["bot_zem_zev_flare_probe_count"] > 0
    assert result["bot_zem_zev_flare_gate_mode"] in {"green_exact", "amber_min_error"}
    assert result["bot_zem_zev_solve_count"] > 0
