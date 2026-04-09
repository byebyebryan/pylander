from __future__ import annotations

from types import MethodType, SimpleNamespace
from typing import Any, cast

import pytest

from bot_framework.bots import create_bot
from bot_framework.bots.common_ballistics import BallisticProjection
from bot_framework.bots.pdg import FlightStage, UpdateContext
from conftest import make_sensors
from core.bot import (
    BotAction,
    BotEnvironment,
    BotTarget,
    FlightPhaseSnapshot,
    PlotMarker,
    Sensors,
    BoostCutoffMetrics,
)
from game import LanderGame
from levels import create_level as create_level_by_name


def _pdg_bot() -> Any:
    return cast(Any, create_bot("pdg"))


def test_pdg_update_returns_action_when_flying() -> None:
    bot = _pdg_bot()
    action = bot.update(
        1.0 / 30.0,
        make_sensors(y=120.0, vx=3.0, vy_up=-8.0, mass=1200.0, state="flying"),
    )
    assert isinstance(action, BotAction)


def test_pdg_non_flying_status_resets_runtime_state() -> None:
    bot = _pdg_bot()
    bot._solve_count = 9
    bot._auto_target_uid = "target-1"
    bot._launch_takeoff_active = True

    action = bot.update(
        1.0 / 30.0,
        make_sensors(y=120.0, vx=3.0, vy_up=-8.0, mass=1200.0, state="crashed"),
    )
    assert action.status == "pdg crashed"
    assert action.target_thrust == 0.0
    assert bot._solve_count == 0
    assert bot._auto_target_uid is None
    assert bot._launch_takeoff_active is False


def test_pdg_instances_keep_runtime_state_isolated() -> None:
    first = _pdg_bot()
    second = _pdg_bot()

    first.state._boost_cutoff_done = True
    first.state._terminal_entry_done = True
    first._solve_count = 11

    assert second.state._boost_cutoff_done is False
    assert second.state._terminal_entry_done is False
    assert second._solve_count == 0


def test_pdg_snapshot_contains_expected_contract_keys() -> None:
    bot = _pdg_bot()
    game = LanderGame(
        level=create_level_by_name("terminal"), seed=0, bot=bot, headless=True
    )
    _ = game.run(print_freq=0, max_steps=60, max_time=20.0)
    snapshot = bot.get_bot_telemetry()

    expected = {
        "terminal_entry_done",
        "solve_count",
        "solve_ms_mean",
        "fallback_frames",
        "shape_curve_rmse",
    }
    assert expected.issubset(snapshot.keys())


def test_pdg_plot_marker_contract_exposes_shared_and_diagnostic_markers() -> None:
    bot = _pdg_bot()
    state = bot.state
    state._active_phase = "terminal"
    state._boost_cutoff_done = True
    state._boost_cutoff_time = 6.0
    state._boost_cutoff_altitude = 240.0
    state._boost_cutoff_x = 120.0
    state._boost_cutoff_y = 240.0
    state._boost_cutoff_vx = 8.0
    state._boost_cutoff_vy_up = -12.0
    state._boost_cutoff_projected_dx = 5.0
    state._boost_cutoff_projected_apex_y = 260.0
    state._boost_cutoff_projected_apex_over_target = 40.0
    state._boost_cutoff_has_target_y_solution = True
    state._boost_cutoff_projected_impact_dx = 5.0
    state._boost_cutoff_projected_impact_angle_deg = 63.0
    state._boost_cutoff_burn_duration_s = 6.0
    state._boost_cutoff_burn_fuel_used = 18.0
    state._boost_cutoff_burn_avg_thrust_level = 0.86
    state._terminal_entry_done = True
    state._terminal_entry_time = 7.0
    state._terminal_entry_x = 140.0
    state._terminal_entry_y = 180.0
    state._terminal_entry_projected_dx = -4.56

    phase_snapshot = bot.get_flight_phase_snapshot()
    markers = bot.get_plot_markers()

    assert phase_snapshot == FlightPhaseSnapshot(
        phase="terminal",
        milestones=("boost_cutoff",),
        boost_cutoff=BoostCutoffMetrics(
            time_s=6.0,
            altitude=240.0,
            x=120.0,
            y=240.0,
            vx=8.0,
            vy_up=-12.0,
            projected_apex_y=260.0,
            projected_apex_over_target=40.0,
            has_target_y_solution=True,
            projected_dx=5.0,
            projected_impact_dx=5.0,
            projected_impact_angle_deg=63.0,
            burn_duration_s=6.0,
            burn_fuel_used=18.0,
            burn_avg_thrust_level=0.86,
        ),
    )
    assert markers == (
        PlotMarker(
            id="boost_cutoff",
            name="boost_cutoff",
            label="boost cutoff",
            x=120.0,
            y=240.0,
            metadata={
                "time_s": 6.0,
                "vx": 8.0,
                "vy_up": -12.0,
            },
        ),
        PlotMarker(
            id="terminal_entry",
            name="terminal_entry",
            label="terminal dx=-4.6",
            x=140.0,
            y=180.0,
            metadata={"time_s": 7.0},
        ),
    )


def test_pdg_gate_ordering_invariant_launch_far() -> None:
    level = cast(Any, create_level_by_name("boost"))
    level.set_eval_scenario("flat:far:half")
    game = LanderGame(level=level, seed=1, bot=_pdg_bot(), headless=True)
    result = game.run(print_freq=0, max_time=15.0)

    boost_cutoff_time = result.get("boost_cutoff_time")
    terminal_entry_time = result.get("bot_pdg_terminal_entry_time")
    assert isinstance(boost_cutoff_time, (int, float))
    assert isinstance(terminal_entry_time, (int, float))
    assert float(boost_cutoff_time) <= float(terminal_entry_time) + 1e-6


def test_boost_cutoff_waits_for_actual_thrust_shutdown() -> None:
    level = cast(Any, create_level_by_name("boost"))
    level.set_eval_scenario("flat:mid:half")
    bot = _pdg_bot()
    bot.set_eval_goal("boost_cutoff")

    gate_samples: list[tuple[float, float, str]] = []
    original_update = bot.update

    def wrapped_update(self, dt: float, passive: Sensors) -> BotAction:
        action = original_update(dt, passive)
        if self.state._boost_cutoff_done:
            gate_samples.append(
                (
                    float(self.state._elapsed_time_s),
                    float(passive.thrust_level),
                    str(self.state._active_phase),
                )
            )
        return action

    bot.update = MethodType(wrapped_update, bot)
    game = LanderGame(
        level=level, seed=0, bot=bot, headless=True, eval_goal="boost_cutoff"
    )
    result = game.run(print_freq=0, max_time=9.0)

    assert gate_samples
    assert result["boost_cutoff_done"] is True
    gate_time = float(result["boost_cutoff_time"])
    gate_time_s, gate_thrust, gate_phase = next(
        sample for sample in gate_samples if sample[0] >= (gate_time - 1e-6)
    )
    assert gate_time_s == pytest.approx(gate_time)
    assert gate_thrust <= float(bot._cfg.boost_cutoff_idle_thrust_max) + 1e-6
    assert gate_phase in {"boost", "coast"}


def test_direct_descent_terminal_handoff_prefers_touchdown() -> None:
    bot = _pdg_bot()
    passive = make_sensors(y=60.0, vx=0.0, vy_up=-30.0, mass=13500.0, state="flying")
    stage = bot._refresh_stage_tracking(
        passive=passive,
        dx=0.0,
        dy=-60.0,
        alt=60.0,
        projection=BallisticProjection(
            projected_dx=0.0,
            t_fall=1.7,
            target_x=0.0,
            impact_x=0.0,
            has_target_y_solution=True,
        ),
    )

    assert stage == FlightStage.TOUCHDOWN


def test_boost_controller_honors_touchdown_stage_suggestion_before_boost_cutoff() -> (
    None
):
    bot = _pdg_bot()
    passive = make_sensors(y=60.0, vx=0.0, vy_up=-30.0, mass=13500.0, state="flying")
    ctx = UpdateContext(
        dt=1.0 / 30.0,
        passive=passive,
        target=None,
        dx=0.0,
        dy=-60.0,
        alt=60.0,
        projection=BallisticProjection(
            projected_dx=0.0,
            t_fall=1.7,
            target_x=0.0,
            impact_x=0.0,
            has_target_y_solution=True,
        ),
        max_power=240000.0,
        min_throttle=0.25,
        max_throttle=1.6,
        ramp_up=1.1,
        max_thrust_accel=27.0,
        nominal_thrust_accel=17.0,
        min_thrust_accel=4.0,
        suggested_stage=FlightStage.TOUCHDOWN,
    )

    result = bot._run_boost_controller(ctx=ctx)

    assert result.next_stage == FlightStage.TOUCHDOWN
    assert result.action is None


def test_boost_clearance_vetoes_stage_transition_while_rise_is_unresolved() -> None:
    class _SourceRiseTerrain:
        def sample_height(self, x: float, lod: int = 0) -> float:
            _ = lod
            xx = float(x)
            if xx < 85.0:
                return 0.0
            if xx < 110.0:
                return (xx - 85.0) * 3.2
            if xx < 160.0:
                return 80.0
            if xx < 230.0:
                return max(0.0, 80.0 - ((xx - 160.0) * 1.142857142857143))
            return 0.0

        def sample_slope(self, x: float, lod: int = 0) -> float:
            _ = x, lod
            return 0.0

        def profile(
            self,
            x0: float,
            x1: float,
            *,
            step: float,
            lod: int = 0,
        ) -> list[tuple[float, float]]:
            _ = x0, x1, step, lod
            return []

        def resolution(self, lod: int = 0) -> float:
            _ = lod
            return 2.0

    bot = _pdg_bot()
    bot.vehicle_info = SimpleNamespace(height=20.0)
    bot.environment = BotEnvironment(
        terrain=_SourceRiseTerrain(),
        gravity_mag=9.8,
        target=BotTarget(uid="target", x=800.0, y=0.0, size=110.0),
        level_name="boost",
        scenario_name="boost:climb:high:full",
    )
    bot._evaluate_boost_quality = MethodType(
        lambda self, **_: SimpleNamespace(
            verdict="rise",
            passed=False,
            projected_dx=None,
        ),
        bot,
    )
    bot._run_pdg_stage = MethodType(
        lambda self, **_: BotAction(0.95, 0.45, False, status="pdg opt/boost"),
        bot,
    )
    bot._evaluate_boost_quality_after_settle = MethodType(
        lambda self, **_: SimpleNamespace(
            verdict="rise",
            passed=False,
            projected_dx=None,
        ),
        bot,
    )
    passive = make_sensors(
        x=40.0, y=10.0, vx=22.0, vy_up=6.0, mass=1200.0, state="flying"
    )
    ctx = UpdateContext(
        dt=1.0 / 30.0,
        passive=passive,
        target=None,
        dx=760.0,
        dy=0.0,
        alt=10.0,
        projection=BallisticProjection(
            projected_dx=0.0,
            t_fall=4.0,
            target_x=800.0,
            impact_x=800.0,
            has_target_y_solution=True,
        ),
        max_power=24000.0,
        min_throttle=0.25,
        max_throttle=1.6,
        ramp_up=1.1,
        max_thrust_accel=27.0,
        nominal_thrust_accel=17.0,
        min_thrust_accel=4.0,
        suggested_stage=FlightStage.TERMINAL,
    )

    result = bot._run_boost_controller(ctx=ctx)

    assert result.next_stage is None
    assert result.action is not None
    assert bot.state._boost_clearance_active is True
