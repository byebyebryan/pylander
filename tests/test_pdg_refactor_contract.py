from __future__ import annotations

from types import MethodType

import pytest

from bots import create_bot
from bots._ballistics import BallisticProjection
from bots.pdg import FlightStage, UpdateContext
from core.bot import (
    BotAction,
    FlightPhaseSnapshot,
    PlotMarker,
    Sensors,
    BoostCutoffMetrics,
)
from game import LanderGame
from levels import create_level as create_level_by_name


def _sensors(*, state: str = "flying") -> Sensors:
    return Sensors(
        x=0.0,
        y=120.0,
        altitude=120.0,
        terrain_y=0.0,
        terrain_slope=0.0,
        vx=3.0,
        vy_up=-8.0,
        angle=0.0,
        ax=0.0,
        ay_up=0.0,
        mass=1200.0,
        thrust_level=0.0,
        fuel=100.0,
        max_fuel=100.0,
        state=state,
        radar_contacts=[],
        proximity=None,
    )


def test_pdg_update_returns_action_when_flying() -> None:
    bot = create_bot("pdg")
    action = bot.update(1.0 / 30.0, _sensors(state="flying"))
    assert isinstance(action, BotAction)


def test_pdg_non_flying_status_resets_runtime_state() -> None:
    bot = create_bot("pdg")
    bot._solve_count = 9
    bot._auto_target_uid = "target-1"
    bot._launch_takeoff_active = True

    action = bot.update(1.0 / 30.0, _sensors(state="crashed"))
    assert action.status == "pdg crashed"
    assert action.target_thrust == 0.0
    assert bot._solve_count == 0
    assert bot._auto_target_uid is None
    assert bot._launch_takeoff_active is False


def test_pdg_snapshot_contains_expected_contract_keys() -> None:
    bot = create_bot("pdg")
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
    bot = create_bot("pdg")
    bot._active_phase = "terminal"
    bot._boost_cutoff_done = True
    bot._boost_cutoff_time = 6.0
    bot._boost_cutoff_altitude = 240.0
    bot._boost_cutoff_x = 120.0
    bot._boost_cutoff_y = 240.0
    bot._boost_cutoff_vx = 8.0
    bot._boost_cutoff_vy_up = -12.0
    bot._boost_cutoff_projected_dx = 5.0
    bot._boost_cutoff_projected_apex_y = 260.0
    bot._boost_cutoff_projected_apex_over_target = 40.0
    bot._boost_cutoff_has_target_y_solution = True
    bot._boost_cutoff_projected_impact_dx = 5.0
    bot._boost_cutoff_projected_impact_angle_deg = 63.0
    bot._boost_cutoff_burn_duration_s = 6.0
    bot._boost_cutoff_burn_fuel_used = 18.0
    bot._boost_cutoff_burn_avg_thrust_level = 0.86
    bot._terminal_entry_done = True
    bot._terminal_entry_time = 7.0
    bot._terminal_entry_x = 140.0
    bot._terminal_entry_y = 180.0
    bot._terminal_entry_projected_dx = -4.56

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
    level = create_level_by_name("boost")
    level.set_eval_scenario("flat:far:half")
    game = LanderGame(level=level, seed=1, bot=create_bot("pdg"), headless=True)
    result = game.run(print_freq=0, max_time=15.0)

    boost_cutoff_time = result.get("boost_cutoff_time")
    terminal_entry_time = result.get("bot_pdg_terminal_entry_time")
    assert isinstance(boost_cutoff_time, (int, float))
    assert isinstance(terminal_entry_time, (int, float))
    assert float(boost_cutoff_time) <= float(terminal_entry_time) + 1e-6


def test_boost_cutoff_waits_for_actual_thrust_shutdown() -> None:
    level = create_level_by_name("boost")
    level.set_eval_scenario("flat:mid:half")
    bot = create_bot("pdg")
    bot.set_eval_goal("boost_cutoff")

    gate_samples: list[tuple[float, float, str]] = []
    original_update = bot.update

    def wrapped_update(self, dt: float, passive: Sensors) -> BotAction:
        action = original_update(dt, passive)
        if self._boost_cutoff_done:
            gate_samples.append(
                (
                    float(self._elapsed_time_s),
                    float(passive.thrust_level),
                    str(self._active_phase),
                )
            )
        return action

    bot.update = MethodType(wrapped_update, bot)
    game = LanderGame(level=level, seed=0, bot=bot, headless=True, eval_goal="boost_cutoff")
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
    bot = create_bot("pdg")
    passive = Sensors(
        x=0.0,
        y=60.0,
        altitude=60.0,
        terrain_y=0.0,
        terrain_slope=0.0,
        vx=0.0,
        vy_up=-30.0,
        angle=0.0,
        ax=0.0,
        ay_up=0.0,
        mass=13500.0,
        thrust_level=0.0,
        fuel=100.0,
        max_fuel=100.0,
        state="flying",
        radar_contacts=[],
        proximity=None,
    )
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


def test_boost_controller_honors_touchdown_stage_suggestion_before_boost_cutoff() -> None:
    bot = create_bot("pdg")
    passive = Sensors(
        x=0.0,
        y=60.0,
        altitude=60.0,
        terrain_y=0.0,
        terrain_slope=0.0,
        vx=0.0,
        vy_up=-30.0,
        angle=0.0,
        ax=0.0,
        ay_up=0.0,
        mass=13500.0,
        thrust_level=0.0,
        fuel=100.0,
        max_fuel=100.0,
        state="flying",
        radar_contacts=[],
        proximity=None,
    )
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
        max_power=230000.0,
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
