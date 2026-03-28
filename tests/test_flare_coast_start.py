from __future__ import annotations

from dataclasses import replace
from types import MethodType
from typing import Any, cast

import pytest

import bots.pdg_terminal_gate as terminal_gate
from bots import create_bot
from bots.pdg_terminal_gate import _latest_safe_state
from core.bot import Sensors
from game import LanderGame
from levels import create_level


def _sensors(
    *, vx: float, vy_up: float, altitude: float, thrust_level: float = 0.0
) -> Sensors:
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
    bot = cast(Any, create_bot("pdg"))
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


def test_latest_safe_state_prefers_lower_required_ratio_over_shorter_burn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bot = cast(Any, create_bot("pdg"))
    passive = _sensors(vx=18.0, vy_up=-10.0, altitude=120.0)

    monkeypatch.setattr(
        terminal_gate,
        "_burn_time_candidates",
        lambda *args, **kwargs: ([3.0, 4.0], 0.4, -8.0),
    )

    def fake_evaluate_candidate(**kwargs: Any) -> terminal_gate.TerminalGateCandidate:
        burn_time_s = float(kwargs["burn_time_s"])
        if burn_time_s <= 3.5:
            return terminal_gate.TerminalGateCandidate(
                burn_time_s=burn_time_s,
                required_accel_ratio=0.24,
                upward_accel=1.0,
                tilt_feasible=True,
                ready=True,
            )
        return terminal_gate.TerminalGateCandidate(
            burn_time_s=burn_time_s,
            required_accel_ratio=0.09,
            upward_accel=1.0,
            tilt_feasible=True,
            ready=True,
        )

    monkeypatch.setattr(
        terminal_gate,
        "_evaluate_candidate",
        fake_evaluate_candidate,
    )

    latest_safe = _latest_safe_state(
        bot,
        passive=passive,
        dx=0.0,
        dy=-120.0,
        alt=120.0,
        max_thrust_accel=22.0,
        thrust_ramp_up=2.0,
    )

    assert latest_safe.best_candidate.burn_time_s == pytest.approx(4.0)
    assert latest_safe.best_candidate.required_accel_ratio == pytest.approx(0.09)


def test_should_defer_latest_safe_entry_when_future_nominal_ready(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bot = cast(Any, create_bot("pdg"))
    passive = _sensors(vx=8.0, vy_up=12.0, altitude=120.0)

    monkeypatch.setattr(
        terminal_gate,
        "_passive_coast_step",
        lambda current, *, dt: replace(
            current,
            y=float(current.y) + 3.0,
            altitude=float(current.altitude) + 3.0,
            vy_up=5.0,
        ),
    )
    monkeypatch.setattr(
        terminal_gate,
        "_lookahead_projection",
        lambda **kwargs: (
            0.0,
            -100.0,
            terminal_gate.BallisticProjection(
                projected_dx=0.0,
                t_fall=2.0,
                target_x=0.0,
                impact_x=0.0,
            ),
        ),
    )
    monkeypatch.setattr(
        terminal_gate,
        "_evaluate_terminal_gate_core",
        lambda *args, **kwargs: terminal_gate.TerminalGateEvaluation(
            decision=terminal_gate.TerminalGateDecision(
                mode="nominal_ready",
                burn_time_s=4.0,
                latest_safe_margin_s=0.1,
                required_accel_ratio=0.08,
            ),
            latest_safe_state=terminal_gate.LatestSafeState(
                margin_s=0.1,
                best_candidate=terminal_gate.TerminalGateCandidate(
                    burn_time_s=4.0,
                    required_accel_ratio=0.08,
                    upward_accel=1.0,
                    tilt_feasible=True,
                    ready=True,
                ),
            ),
            best_nominal=terminal_gate.TerminalGateCandidate(
                burn_time_s=4.0,
                required_accel_ratio=0.08,
                upward_accel=1.0,
                tilt_feasible=True,
                ready=True,
            ),
            nominal_ready_ticks=2,
            state_ready_ticks=2,
            required_accel_ratio=0.08,
        ),
    )

    assert terminal_gate._should_defer_latest_safe_entry(
        bot,
        dt=0.25,
        passive=passive,
        dx=0.0,
        dy=-120.0,
        projected_dx=0.0,
        max_thrust_accel=22.0,
        nominal_thrust_accel=18.0,
        thrust_ramp_up=2.0,
        current_latest_safe_feasible=False,
        current_latest_safe_ratio=0.2,
        current_ready_ticks=0,
    )


def test_should_defer_latest_safe_entry_when_future_latest_safe_is_easier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bot = cast(Any, create_bot("pdg"))
    passive = _sensors(vx=8.0, vy_up=12.0, altitude=120.0)

    monkeypatch.setattr(
        terminal_gate,
        "_passive_coast_step",
        lambda current, *, dt: replace(
            current,
            y=float(current.y) + 2.0,
            altitude=float(current.altitude) + 2.0,
            vy_up=4.0,
        ),
    )
    monkeypatch.setattr(
        terminal_gate,
        "_lookahead_projection",
        lambda **kwargs: (
            0.0,
            -100.0,
            terminal_gate.BallisticProjection(
                projected_dx=0.0,
                t_fall=2.0,
                target_x=0.0,
                impact_x=0.0,
            ),
        ),
    )
    monkeypatch.setattr(
        terminal_gate,
        "_evaluate_terminal_gate_core",
        lambda *args, **kwargs: terminal_gate.TerminalGateEvaluation(
            decision=terminal_gate.TerminalGateDecision(
                mode="latest_safe",
                burn_time_s=4.0,
                latest_safe_margin_s=-0.1,
                required_accel_ratio=0.12,
            ),
            latest_safe_state=terminal_gate.LatestSafeState(
                margin_s=-0.1,
                best_candidate=terminal_gate.TerminalGateCandidate(
                    burn_time_s=4.0,
                    required_accel_ratio=0.12,
                    upward_accel=1.0,
                    tilt_feasible=True,
                    ready=False,
                ),
            ),
            best_nominal=None,
            nominal_ready_ticks=0,
            state_ready_ticks=0,
            required_accel_ratio=0.12,
        ),
    )

    assert terminal_gate._should_defer_latest_safe_entry(
        bot,
        dt=0.25,
        passive=passive,
        dx=0.0,
        dy=-120.0,
        projected_dx=0.0,
        max_thrust_accel=22.0,
        nominal_thrust_accel=18.0,
        thrust_ramp_up=2.0,
        current_latest_safe_feasible=True,
        current_latest_safe_ratio=0.2,
        current_ready_ticks=0,
    )


def test_should_not_defer_latest_safe_entry_when_descending() -> None:
    bot = cast(Any, create_bot("pdg"))

    assert not terminal_gate._should_defer_latest_safe_entry(
        bot,
        dt=0.25,
        passive=_sensors(vx=8.0, vy_up=-2.0, altitude=120.0),
        dx=0.0,
        dy=-120.0,
        projected_dx=0.0,
        max_thrust_accel=22.0,
        nominal_thrust_accel=18.0,
        thrust_ramp_up=2.0,
        current_latest_safe_feasible=True,
        current_latest_safe_ratio=0.2,
        current_ready_ticks=0,
    )


def test_should_not_defer_latest_safe_entry_when_outside_terminal_corridor() -> None:
    bot = cast(Any, create_bot("pdg"))

    assert not terminal_gate._should_defer_latest_safe_entry(
        bot,
        dt=0.25,
        passive=_sensors(vx=8.0, vy_up=12.0, altitude=120.0),
        dx=0.0,
        dy=-120.0,
        projected_dx=200.0,
        max_thrust_accel=22.0,
        nominal_thrust_accel=18.0,
        thrust_ramp_up=2.0,
        current_latest_safe_feasible=True,
        current_latest_safe_ratio=0.2,
        current_ready_ticks=0,
    )


def test_should_defer_latest_safe_entry_when_future_latest_safe_becomes_feasible(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bot = cast(Any, create_bot("pdg"))
    passive = _sensors(vx=8.0, vy_up=12.0, altitude=120.0)

    monkeypatch.setattr(
        terminal_gate,
        "_passive_coast_step",
        lambda current, *, dt: replace(
            current,
            y=float(current.y) + 2.0,
            altitude=float(current.altitude) + 2.0,
            vy_up=6.0,
        ),
    )
    monkeypatch.setattr(
        terminal_gate,
        "_lookahead_projection",
        lambda **kwargs: (
            0.0,
            -100.0,
            terminal_gate.BallisticProjection(
                projected_dx=0.0,
                t_fall=2.0,
                target_x=0.0,
                impact_x=0.0,
            ),
        ),
    )
    monkeypatch.setattr(
        terminal_gate,
        "_evaluate_terminal_gate_core",
        lambda *args, **kwargs: terminal_gate.TerminalGateEvaluation(
            decision=terminal_gate.TerminalGateDecision(
                mode="latest_safe",
                burn_time_s=4.0,
                latest_safe_margin_s=-0.1,
                required_accel_ratio=0.18,
            ),
            latest_safe_state=terminal_gate.LatestSafeState(
                margin_s=-0.1,
                best_candidate=terminal_gate.TerminalGateCandidate(
                    burn_time_s=4.0,
                    required_accel_ratio=0.18,
                    upward_accel=1.0,
                    tilt_feasible=True,
                    ready=False,
                ),
            ),
            best_nominal=None,
            nominal_ready_ticks=0,
            state_ready_ticks=0,
            required_accel_ratio=0.18,
        ),
    )

    assert terminal_gate._should_defer_latest_safe_entry(
        bot,
        dt=0.25,
        passive=passive,
        dx=0.0,
        dy=-120.0,
        projected_dx=0.0,
        max_thrust_accel=22.0,
        nominal_thrust_accel=18.0,
        thrust_ramp_up=2.0,
        current_latest_safe_feasible=False,
        current_latest_safe_ratio=0.2,
        current_ready_ticks=0,
    )


def test_predict_terminal_handoff_returns_first_terminal_decision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bot = cast(Any, create_bot("pdg"))
    passive = _sensors(vx=6.0, vy_up=10.0, altitude=120.0)
    evaluations = iter(
        (
            terminal_gate.TerminalGateEvaluation(
                decision=None,
                latest_safe_state=terminal_gate.LatestSafeState(
                    margin_s=1.5,
                    best_candidate=terminal_gate.TerminalGateCandidate(
                        burn_time_s=4.0,
                        required_accel_ratio=0.28,
                        upward_accel=1.0,
                        tilt_feasible=True,
                        ready=False,
                    ),
                ),
                best_nominal=None,
                nominal_ready_ticks=0,
                state_ready_ticks=0,
                required_accel_ratio=0.28,
            ),
            terminal_gate.TerminalGateEvaluation(
                decision=terminal_gate.TerminalGateDecision(
                    mode="latest_safe",
                    burn_time_s=4.0,
                    latest_safe_margin_s=-0.2,
                    required_accel_ratio=0.24,
                ),
                latest_safe_state=terminal_gate.LatestSafeState(
                    margin_s=-0.2,
                    best_candidate=terminal_gate.TerminalGateCandidate(
                        burn_time_s=4.0,
                        required_accel_ratio=0.24,
                        upward_accel=1.0,
                        tilt_feasible=True,
                        ready=False,
                    ),
                ),
                best_nominal=None,
                nominal_ready_ticks=0,
                state_ready_ticks=0,
                required_accel_ratio=0.24,
            ),
        )
    )

    monkeypatch.setattr(
        terminal_gate,
        "_evaluate_terminal_gate_core",
        lambda *args, **kwargs: next(evaluations),
    )
    monkeypatch.setattr(
        terminal_gate,
        "_lookahead_projection",
        lambda **kwargs: (
            0.0,
            -100.0,
            terminal_gate.BallisticProjection(
                projected_dx=72.0,
                t_fall=2.0,
                target_x=0.0,
                impact_x=72.0,
            ),
        ),
    )

    handoff = terminal_gate.predict_terminal_handoff(
        bot,
        dt=0.25,
        passive=passive,
        dx=0.0,
        dy=-120.0,
        max_thrust_accel=22.0,
        nominal_thrust_accel=18.0,
        thrust_ramp_up=2.0,
        boost_cutoff_done=True,
    )

    assert handoff.mode == "latest_safe"
    assert handoff.time_to_entry_s == pytest.approx(0.25)
    assert handoff.entry_altitude == pytest.approx(100.0)
    assert handoff.entry_projected_dx == pytest.approx(72.0)
    assert handoff.required_accel_ratio == pytest.approx(0.24)


def test_assist_ready_triggers_on_large_miss_rising_post_boost_handoff(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bot = cast(Any, create_bot("pdg"))
    bot.state._boost_cutoff_done = True
    passive = _sensors(vx=12.0, vy_up=9.0, altitude=160.0)

    monkeypatch.setattr(
        terminal_gate,
        "_latest_safe_state",
        lambda *args, **kwargs: terminal_gate.LatestSafeState(
            margin_s=1.4,
            best_candidate=terminal_gate.TerminalGateCandidate(
                burn_time_s=4.0,
                required_accel_ratio=0.40,
                upward_accel=1.0,
                tilt_feasible=True,
                ready=False,
            ),
        ),
    )
    monkeypatch.setattr(
        terminal_gate,
        "_burn_time_candidates",
        lambda *args, **kwargs: ([3.0], 0.4, -8.0),
    )
    monkeypatch.setattr(
        terminal_gate,
        "_evaluate_candidate",
        lambda **kwargs: terminal_gate.TerminalGateCandidate(
            burn_time_s=float(kwargs["burn_time_s"]),
            required_accel_ratio=0.60,
            upward_accel=1.0,
            tilt_feasible=True,
            ready=False,
        ),
    )

    evaluation = terminal_gate._evaluate_terminal_gate_core(
        bot,
        current_ready_ticks=0,
        passive=passive,
        dx=180.0,
        projected_dx=130.0,
        dy=-160.0,
        alt=160.0,
        max_thrust_accel=22.0,
        nominal_thrust_accel=18.0,
        thrust_ramp_up=2.0,
    )

    assert evaluation.decision is not None
    assert evaluation.decision.mode == "assist_ready"


def test_assist_ready_does_not_trigger_when_aligned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bot = cast(Any, create_bot("pdg"))
    bot.state._boost_cutoff_done = True
    passive = _sensors(vx=12.0, vy_up=9.0, altitude=160.0)

    monkeypatch.setattr(
        terminal_gate,
        "_latest_safe_state",
        lambda *args, **kwargs: terminal_gate.LatestSafeState(
            margin_s=1.4,
            best_candidate=terminal_gate.TerminalGateCandidate(
                burn_time_s=4.0,
                required_accel_ratio=0.40,
                upward_accel=1.0,
                tilt_feasible=True,
                ready=False,
            ),
        ),
    )
    monkeypatch.setattr(
        terminal_gate,
        "_burn_time_candidates",
        lambda *args, **kwargs: ([3.0], 0.4, -8.0),
    )
    monkeypatch.setattr(
        terminal_gate,
        "_evaluate_candidate",
        lambda **kwargs: terminal_gate.TerminalGateCandidate(
            burn_time_s=float(kwargs["burn_time_s"]),
            required_accel_ratio=0.60,
            upward_accel=1.0,
            tilt_feasible=True,
            ready=False,
        ),
    )

    evaluation = terminal_gate._evaluate_terminal_gate_core(
        bot,
        current_ready_ticks=0,
        passive=passive,
        dx=12.0,
        projected_dx=6.0,
        dy=-160.0,
        alt=160.0,
        max_thrust_accel=22.0,
        nominal_thrust_accel=18.0,
        thrust_ramp_up=2.0,
    )

    assert evaluation.decision is None or evaluation.decision.mode != "assist_ready"


def test_assist_ready_does_not_trigger_when_latest_safe_is_too_hard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bot = cast(Any, create_bot("pdg"))
    bot.state._boost_cutoff_done = True
    passive = _sensors(vx=12.0, vy_up=9.0, altitude=160.0)

    monkeypatch.setattr(
        terminal_gate,
        "_latest_safe_state",
        lambda *args, **kwargs: terminal_gate.LatestSafeState(
            margin_s=1.4,
            best_candidate=terminal_gate.TerminalGateCandidate(
                burn_time_s=4.0,
                required_accel_ratio=0.62,
                upward_accel=1.0,
                tilt_feasible=True,
                ready=False,
            ),
        ),
    )

    evaluation = terminal_gate._evaluate_terminal_gate_core(
        bot,
        current_ready_ticks=0,
        passive=passive,
        dx=180.0,
        projected_dx=130.0,
        dy=-160.0,
        alt=160.0,
        max_thrust_accel=22.0,
        nominal_thrust_accel=18.0,
        thrust_ramp_up=2.0,
    )

    assert evaluation.decision is None or evaluation.decision.mode != "assist_ready"


def test_flare_dynamic_tilt_relaxes_when_vertical_state_has_recovery_margin() -> None:
    bot = cast(Any, create_bot("pdg"))

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
    bot = cast(Any, create_bot("pdg"))

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
    bot = cast(Any, create_bot("pdg"))

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
    level = cast(Any, create_level(level_name))
    level.set_eval_scenario(scenario_name)
    bot = cast(Any, create_bot("pdg"))

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
    level = cast(Any, create_level("terminal"))
    level.set_eval_scenario("error:mid:wide")
    bot = cast(Any, create_bot("pdg"))

    game = LanderGame(level=level, seed=0, bot=bot, headless=True)
    result = game.run(print_freq=0, max_time=7.0)

    assert result["state"] == "flying"
    assert result["bot_pdg_terminal_entry_done"] is True
    assert result["bot_pdg_terminal_entry_time"] is not None
    assert result["bot_pdg_terminal_probe_count"] == 0
    assert result["bot_pdg_terminal_gate_mode"] in {
        "assist_ready",
        "nominal_ready",
        "latest_safe",
    }
    assert result["bot_pdg_solve_count"] > 0


def test_terminal_normal_shallower_seed_one_delays_terminal_gate_entry() -> None:
    level = cast(Any, create_level("terminal"))
    level.set_eval_scenario("normal:shallower")
    bot = cast(Any, create_bot("pdg"))

    game = LanderGame(level=level, seed=1, bot=bot, headless=True)
    result = game.run(print_freq=0, max_time=7.0)

    entry_time = result.get("bot_pdg_terminal_entry_time")
    assert isinstance(entry_time, (int, float))
    assert float(entry_time) > 0.25
    assert result["bot_pdg_terminal_entry_done"] is True


def test_flare_flight_levels_can_force_flare_from_spawn() -> None:
    level = cast(Any, create_level("terminal"))
    level.set_eval_scenario("normal:mid")
    bot = cast(Any, create_bot("pdg"))
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
    level = cast(Any, create_level(level_name))
    level.set_eval_scenario(scenario_name)
    bot = cast(Any, create_bot("pdg"))

    command_log: list[tuple[float, float, str]] = []
    original_update = bot.update

    def wrapped_update(self, dt: float, passive):
        action = original_update(dt, passive)
        command_log.append(
            (
                float(self.state._elapsed_time_s),
                float(action.target_thrust),
                str(self.state._active_phase),
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

    first_positive = next(
        (time_s for time_s, thrust in post_gate if thrust > 1e-3), None
    )
    assert first_positive is not None
    assert float(first_positive) - float(gate_time) >= 0.30
