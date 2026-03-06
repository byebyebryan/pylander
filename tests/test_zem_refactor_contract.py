from __future__ import annotations

from bots import create_bot
from core.bot import BotAction, FlightPhaseSnapshot, PlotMarker, Sensors
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


def test_zem_update_returns_action_when_flying() -> None:
    bot = create_bot("zem_zev")
    action = bot.update(1.0 / 30.0, _sensors(state="flying"))
    assert isinstance(action, BotAction)


def test_zem_non_flying_status_resets_runtime_state() -> None:
    bot = create_bot("zem_zev")
    bot._solve_count = 9
    bot._auto_target_uid = "target-1"
    bot._launch_takeoff_active = True

    action = bot.update(1.0 / 30.0, _sensors(state="crashed"))
    assert action.status == "zem_zev:crashed"
    assert action.target_thrust == 0.0
    assert bot._solve_count == 0
    assert bot._auto_target_uid is None
    assert bot._launch_takeoff_active is False


def test_zem_snapshot_contains_expected_contract_keys() -> None:
    bot = create_bot("zem_zev")
    game = LanderGame(level=create_level_by_name("flare"), seed=0, bot=bot, headless=True)
    _ = game.run(print_freq=0, max_steps=60, max_time=20.0)
    snapshot = bot.get_evaluation_snapshot()

    expected = {
        "kind",
        "phase",
        "setup_gate_done",
        "terminal_gate_done",
        "solve_count",
        "solve_ms_mean",
        "fallback_frames",
        "shape_window_started",
        "shape_window_done",
        "shape_curve_rmse",
    }
    assert expected.issubset(snapshot.keys())
    assert snapshot["kind"] == "zem_zev"


def test_zem_plot_marker_contract_exposes_shared_and_diagnostic_markers() -> None:
    bot = create_bot("zem_zev")
    bot._active_phase = "terminal"
    bot._setup_gate_done = True
    bot._terminal_gate_done = True
    bot._terminal_gate_projected_dx = -4.56

    phase_snapshot = bot.get_flight_phase_snapshot()
    markers = bot.get_plot_markers()

    assert phase_snapshot == FlightPhaseSnapshot(
        phase="terminal",
        milestones=("setup_gate",),
    )
    assert markers == (
        PlotMarker(
            id="terminal_entry",
            name="terminal_entry",
            label="terminal entry pdx=-4.6",
        ),
    )


def test_zem_gate_ordering_invariant_launch_far() -> None:
    level = create_level_by_name("launch")
    level.set_eval_scenario("far")
    game = LanderGame(level=level, seed=1, bot=create_bot("zem_zev"), headless=True)
    result = game.run(print_freq=0, max_time=120.0)

    setup_gate_time = result.get("zem_setup_gate_time")
    terminal_gate_time = result.get("zem_terminal_gate_time")
    assert setup_gate_time is not None
    if terminal_gate_time is not None:
        assert float(setup_gate_time) <= float(terminal_gate_time) + 1e-6
