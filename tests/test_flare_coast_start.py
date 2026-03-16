from __future__ import annotations

from types import MethodType

import pytest

from bots import create_bot
from bots.pdg.terminal_gate import _latest_safe_state
from core.bot import Sensors
from game import LanderGame
from levels import create_level


def _sensors(*, vx: float, vy_up: float, altitude: float, thrust_level: float = 0.0) -> Sensors:
    return Sensors(
        x=0.0,
        y=altitude,
        altitude=altitude,
        terrain_y=0.0,
        terrain_slope=0.0,
        vx=vx,
        vy_up=vy_up,
        angle=0.0,
        ax=0.0,
        ay_up=0.0,
        mass=1000.0,
        thrust_level=thrust_level,
        fuel=100.0,
        max_fuel=100.0,
        state="flying",
        radar_contacts=[],
        proximity=None,
    )


def test_latest_safe_margin_shrinks_when_lateral_overshoot_requires_more_time() -> None:
    bot = create_bot("pdg")
    passive = _sensors(vx=28.0, vy_up=-12.0, altitude=120.0)

    mild_overshoot = _latest_safe_state(
        bot,
        passive=passive,
        dx=-20.0,
        dy=-120.0,
        alt=120.0,
        max_thrust_accel=22.0,
        thrust_ramp_up=2.0,
    )
    larger_overshoot = _latest_safe_state(
        bot,
        passive=passive,
        dx=-60.0,
        dy=-120.0,
        alt=120.0,
        max_thrust_accel=22.0,
        thrust_ramp_up=2.0,
    )

    assert larger_overshoot.margin_s < mild_overshoot.margin_s
    assert (
        larger_overshoot.best_candidate.required_accel_ratio
        > mild_overshoot.best_candidate.required_accel_ratio
    )


def test_flare_dynamic_tilt_relaxes_when_vertical_state_has_recovery_margin() -> None:
    bot = create_bot("pdg")

    base_tilt = bot._resolve_max_tilt(
        180.0,
        260.0,
        60.0,
        dy=-180.0,
        phase="terminal",
    )
    relaxed_tilt = bot._resolve_max_tilt(
        180.0,
        260.0,
        60.0,
        dy=-180.0,
        phase="terminal",
        vy_up=18.0,
        max_thrust_accel=22.0,
        lateral_dx=-180.0,
    )

    assert relaxed_tilt > base_tilt
    assert relaxed_tilt > bot._cfg.terminal_dynamic_tilt_max
    assert relaxed_tilt <= bot._cfg.terminal_overshoot_tilt_max + 1e-6


def test_flare_dynamic_tilt_stays_near_base_when_vertical_margin_is_tight() -> None:
    bot = create_bot("pdg")

    base_tilt = bot._resolve_max_tilt(
        24.0,
        180.0,
        60.0,
        dy=-24.0,
        phase="terminal",
    )
    tight_tilt = bot._resolve_max_tilt(
        24.0,
        180.0,
        60.0,
        dy=-24.0,
        phase="terminal",
        vy_up=-35.0,
        max_thrust_accel=22.0,
        lateral_dx=-90.0,
    )

    assert tight_tilt == pytest.approx(base_tilt)


def test_flare_dynamic_tilt_stays_below_overshoot_cap_without_crossing_case() -> None:
    bot = create_bot("pdg")

    relaxed_tilt = bot._resolve_max_tilt(
        180.0,
        260.0,
        60.0,
        dy=-180.0,
        phase="terminal",
        vy_up=18.0,
        max_thrust_accel=22.0,
        lateral_dx=180.0,
    )

    assert relaxed_tilt <= bot._cfg.terminal_dynamic_tilt_max + 1e-6


@pytest.mark.parametrize(
    ("level_name", "scenario_name"),
    (
        ("terminal", "normal:mid"),
        ("terminal", "error:mid:tight"),
    ),
)
def test_flare_flight_levels_prime_boost_cutoff_and_start_in_coast(
    level_name: str,
    scenario_name: str,
) -> None:
    level = create_level(level_name)
    level.set_eval_scenario(scenario_name)
    bot = create_bot("pdg")

    game = LanderGame(level=level, seed=0, bot=bot, headless=True)

    snapshot = bot.get_flight_phase_snapshot()
    assert snapshot is not None
    assert snapshot.phase == "coast"
    assert snapshot.milestones == ("boost_cutoff",)
    assert snapshot.boost_cutoff is not None
    assert snapshot.boost_cutoff.time_s == pytest.approx(0.0)
    assert snapshot.boost_cutoff.burn_duration_s == pytest.approx(0.0)
    assert snapshot.boost_cutoff.burn_fuel_used == pytest.approx(0.0)
    assert snapshot.boost_cutoff.burn_avg_thrust_level == pytest.approx(0.0)

    result = game.run(print_freq=0, max_steps=5, max_time=5.0)
    assert result["boost_cutoff_done"] is True
    assert result["boost_cutoff_time"] == pytest.approx(0.0)
    assert result["boost_cutoff_burn_duration_s"] == pytest.approx(0.0)
    assert result["boost_cutoff_burn_fuel_used"] == pytest.approx(0.0)
    assert result["bot_pdg_solve_count"] == 0


def test_terminal_error_wide_triggers_terminal_gate_before_impact() -> None:
    level = create_level("terminal")
    level.set_eval_scenario("error:mid:wide")
    bot = create_bot("pdg")

    game = LanderGame(level=level, seed=0, bot=bot, headless=True)
    result = game.run(print_freq=0, max_time=7.0)

    assert result["state"] == "flying"
    assert result["bot_pdg_terminal_entry_done"] is True
    assert result["bot_pdg_terminal_entry_time"] is not None
    assert result["bot_pdg_terminal_probe_count"] == 0
    assert result["bot_pdg_terminal_gate_mode"] in {"nominal_ready", "latest_safe"}
    assert result["bot_pdg_solve_count"] > 0


def test_flare_flight_levels_can_force_flare_from_spawn() -> None:
    level = create_level("terminal")
    level.set_eval_scenario("normal:mid")
    bot = create_bot("pdg")
    bot.apply_config_override({"force_terminal_from_start": True})

    game = LanderGame(level=level, seed=0, bot=bot, headless=True)

    snapshot = bot.get_flight_phase_snapshot()
    assert snapshot is not None
    assert snapshot.phase == "terminal"
    assert snapshot.milestones == ("boost_cutoff",)
    result = game.run(print_freq=0, max_steps=1, max_time=1.0)
    assert result["bot_pdg_terminal_entry_done"] is True
    assert result["bot_pdg_terminal_entry_time"] == pytest.approx(0.0)


@pytest.mark.parametrize(
    ("level_name", "scenario_name", "max_time"),
    (
        ("terminal", "normal:mid", 9.0),
        ("terminal", "error:mid:wide", 7.0),
    ),
)
def test_terminal_gate_handoff_does_not_execute_probe_pulse(
    level_name: str,
    scenario_name: str,
    max_time: float,
) -> None:
    level = create_level(level_name)
    level.set_eval_scenario(scenario_name)
    bot = create_bot("pdg")

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

    gate_time = result.get("bot_pdg_terminal_entry_time")
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
