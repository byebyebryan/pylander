from __future__ import annotations

from bots import create_bot
from bots._optimizer_pdg import PDGOptimizer, PDGOptimizerConfig
from game import LanderGame
from levels import create_level as create_level_by_name


def _run_level(
    *,
    level_name: str,
    scenario: str,
    max_steps: int | None = None,
    max_time: float = 300.0,
):
    level = create_level_by_name(level_name)
    if hasattr(level, "set_eval_scenario"):
        level.set_eval_scenario(scenario)
    # Keep smoke runs bounded and stop as soon as a terminal condition is reached.
    level.stop_on_crash = True
    level.stop_on_out_of_fuel = True
    level.stop_on_first_land = True
    bot = create_bot("zem_zev")
    game = LanderGame(level=level, seed=0, bot=bot, headless=True)
    result = game.run(print_freq=0, max_steps=max_steps, max_time=max_time)
    return result, bot


def test_zem_smoke_flare_plunge_launch_seed0() -> None:
    # Fast envelope smoke: verify stable in-flight behavior without crashes.
    cases = [
        ("flare", "mid", 20.0, 15.0),
        ("plunge", "mid_normal", 20.0, 10.0),
        ("launch", "mid", 20.0, 25.0),
    ]
    for level_name, scenario, max_time, max_offset in cases:
        result, _bot = _run_level(level_name=level_name, scenario=scenario, max_time=max_time)
        assert result.get("state") != "crashed"
        landing_offset = result.get("landing_offset")
        if isinstance(landing_offset, (int, float)):
            assert abs(float(landing_offset)) <= max_offset


def test_zem_launch_landing_offset_bound_seed0() -> None:
    result, _bot = _run_level(level_name="launch", scenario="near", max_time=35.0)
    assert result.get("state") == "landed"
    landing_offset = result.get("landing_offset")
    assert isinstance(landing_offset, (int, float))
    # Corridor-aware objective trades centering precision for fuel efficiency.
    assert abs(float(landing_offset)) <= 40.0


def test_zem_solver_progress_and_fallback_cap_mid_flare() -> None:
    # Partial run keeps the bot in-flight so solve/fallback telemetry remains populated.
    _result, bot = _run_level(
        level_name="flare",
        scenario="mid",
        max_steps=180,
        max_time=20.0,
    )
    snapshot = bot.get_evaluation_snapshot()
    assert snapshot.get("kind") == "zem_zev"
    assert int(snapshot.get("solve_count") or 0) >= 5
    assert int(snapshot.get("fallback_frames") or 0) <= 2
    assert snapshot.get("phase") in {"setup", "coast", "terminal", "touchdown"}


def test_pdg_optimizer_solution_changes_with_runtime_gravity() -> None:
    optimizer = PDGOptimizer(PDGOptimizerConfig(horizon_steps=10, step_dt=0.2))
    common = dict(
        x=0.0,
        y=600.0,
        vx=25.0,
        vy=-20.0,
        target_x=80.0,
        target_y=0.0,
        target_vy=-2.0,
        max_thrust_accel=22.0,
        min_thrust_accel=2.0,
        nominal_thrust_accel=12.0,
        max_tilt_rad=0.45,
        descent_floor_vy=-12.0,
        pad_half_width=55.0,
        altitude_hint=600.0,
        warm_start=None,
    )
    moon_plan = optimizer.solve(gravity_mag=1.62, **common)
    earth_plan = optimizer.solve(gravity_mag=9.8, **common)

    assert moon_plan is not None and moon_plan.feasible
    assert earth_plan is not None and earth_plan.feasible
    # The acceleration profile should change when gravity changes materially.
    assert abs(float(moon_plan.vy[-1]) - float(earth_plan.vy[-1])) > 5.0
