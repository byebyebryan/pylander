from __future__ import annotations

from bots import create_bot
from core.bot import PassiveSensors
from game import LanderGame
from levels import create_level as create_level_by_name


def _passive(*, state: str = "flying") -> PassiveSensors:
    return PassiveSensors(
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


def test_zem_plan_emits_projection_query_id() -> None:
    bot = create_bot("zem_zev")
    queries = bot.plan(1.0 / 30.0, _passive(state="flying"))
    assert len(queries) == 1
    assert queries[0].id == "zem_projection"


def test_zem_non_flying_status_resets_runtime_state() -> None:
    bot = create_bot("zem_zev")
    bot._solve_count = 9
    bot._auto_target_uid = "target-1"
    bot._launch_takeoff_active = True

    action = bot.act(1.0 / 30.0, _passive(state="crashed"), results={})
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
