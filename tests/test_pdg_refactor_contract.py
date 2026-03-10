from __future__ import annotations

from bots import create_bot
from core.bot import BotAction, FlightPhaseSnapshot, PlotMarker, Sensors, SetupGateMetrics
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
    game = LanderGame(level=create_level_by_name("flare_normal"), seed=0, bot=bot, headless=True)
    _ = game.run(print_freq=0, max_steps=60, max_time=20.0)
    snapshot = bot.get_bot_telemetry()

    expected = {
        "flare_entry_done",
        "solve_count",
        "solve_ms_mean",
        "fallback_frames",
        "shape_curve_rmse",
    }
    assert expected.issubset(snapshot.keys())


def test_pdg_plot_marker_contract_exposes_shared_and_diagnostic_markers() -> None:
    bot = create_bot("pdg")
    bot._active_phase = "flare"
    bot._setup_gate_done = True
    bot._setup_gate_time = 6.0
    bot._setup_gate_altitude = 240.0
    bot._setup_gate_x = 120.0
    bot._setup_gate_y = 240.0
    bot._setup_gate_vx = 8.0
    bot._setup_gate_vy_up = -12.0
    bot._setup_gate_projected_apex_y = 260.0
    bot._setup_gate_projected_apex_over_target = 40.0
    bot._setup_gate_has_target_y_solution = True
    bot._setup_gate_projected_impact_dx = 5.0
    bot._setup_gate_projected_impact_angle_deg = 63.0
    bot._setup_gate_burn_duration_s = 6.0
    bot._setup_gate_burn_fuel_used = 18.0
    bot._setup_gate_burn_avg_thrust_level = 0.86
    bot._flare_entry_done = True
    bot._flare_entry_time = 7.0
    bot._flare_entry_x = 140.0
    bot._flare_entry_y = 180.0
    bot._flare_entry_projected_dx = -4.56

    phase_snapshot = bot.get_flight_phase_snapshot()
    markers = bot.get_plot_markers()

    assert phase_snapshot == FlightPhaseSnapshot(
        phase="flare",
        milestones=("setup_gate",),
        setup_gate=SetupGateMetrics(
            time_s=6.0,
            altitude=240.0,
            x=120.0,
            y=240.0,
            vx=8.0,
            vy_up=-12.0,
            projected_apex_y=260.0,
            projected_apex_over_target=40.0,
            has_target_y_solution=True,
            projected_impact_dx=5.0,
            projected_impact_angle_deg=63.0,
            burn_duration_s=6.0,
            burn_fuel_used=18.0,
            burn_avg_thrust_level=0.86,
        ),
    )
    assert markers == (
        PlotMarker(
            id="setup_gate",
            name="setup_gate",
            label="setup gate",
            x=120.0,
            y=240.0,
            metadata={
                "time_s": 6.0,
                "vx": 8.0,
                "vy_up": -12.0,
            },
        ),
        PlotMarker(
            id="flare_entry",
            name="flare_entry",
            label="flare dx=-4.6",
            x=140.0,
            y=180.0,
            metadata={"time_s": 7.0},
        ),
    )


def test_pdg_gate_ordering_invariant_launch_far() -> None:
    level = create_level_by_name("setup_flat")
    level.set_eval_scenario("far")
    game = LanderGame(level=level, seed=1, bot=create_bot("pdg"), headless=True)
    result = game.run(print_freq=0, max_time=120.0)

    setup_gate_time = result.get("setup_gate_time")
    flare_entry_time = result.get("bot_pdg_flare_entry_time")
    if setup_gate_time is not None and flare_entry_time is not None:
        assert float(setup_gate_time) <= float(flare_entry_time) + 1e-6
