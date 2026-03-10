from __future__ import annotations

from types import MethodType

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
    assert result["bot_zem_zev_flare_probe_count"] == 0
    assert result["bot_zem_zev_flare_gate_mode"] in {"nominal_ready", "latest_safe"}
    assert result["bot_zem_zev_solve_count"] > 0


def test_flare_levels_can_force_terminal_from_spawn() -> None:
    level = create_level("flare_normal")
    level.set_eval_scenario("mid")
    bot = create_bot("zem_zev")
    bot.apply_config_override({"force_terminal_from_start": True})

    game = LanderGame(level=level, seed=0, bot=bot, headless=True)

    snapshot = bot.get_flight_phase_snapshot()
    assert snapshot is not None
    assert snapshot.phase == "terminal"
    assert snapshot.milestones == ("setup_gate",)
    result = game.run(print_freq=0, max_steps=1, max_time=1.0)
    assert result["bot_zem_zev_terminal_gate_done"] is True
    assert result["bot_zem_zev_terminal_gate_time"] == pytest.approx(0.0)


@pytest.mark.parametrize(
    ("level_name", "scenario_name", "max_time"),
    (
        ("flare_normal", "mid", 10.0),
        ("flare_error", "mid_wide", 10.0),
    ),
)
def test_flare_gate_handoff_does_not_execute_probe_pulse(
    level_name: str,
    scenario_name: str,
    max_time: float,
) -> None:
    level = create_level(level_name)
    level.set_eval_scenario(scenario_name)
    bot = create_bot("zem_zev")

    command_log: list[tuple[float, float, str]] = []
    original_update = bot.update

    def wrapped_update(self, dt: float, passive):
        action = original_update(dt, passive)
        command_log.append(
            (
                float(self._elapsed_time_s),
                float(action.target_thrust),
                str(self._active_phase),
            )
        )
        return action

    bot.update = MethodType(wrapped_update, bot)

    game = LanderGame(level=level, seed=0, bot=bot, headless=True)
    result = game.run(print_freq=0, max_time=max_time)

    gate_time = result.get("bot_zem_zev_terminal_gate_time")
    assert isinstance(gate_time, (int, float))

    post_gate = [
        (time_s, thrust)
        for time_s, thrust, phase in command_log
        if phase == "terminal" and time_s >= float(gate_time) - 1e-6
    ]
    assert post_gate

    first_positive = next((time_s for time_s, thrust in post_gate if thrust > 1e-3), None)
    assert first_positive is not None
    assert float(first_positive) - float(gate_time) >= 0.30
