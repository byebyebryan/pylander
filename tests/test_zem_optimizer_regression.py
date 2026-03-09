from __future__ import annotations

import pytest

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


def test_zem_smoke_flare_plunge_climb_launch_seed0() -> None:
    # Fast envelope smoke: verify stable in-flight behavior without crashes.
    cases = [
        ("flare_normal", "mid", 20.0, 15.0),
        ("flare_plunge", "mid_normal", 20.0, 10.0),
        ("setup_climb", "mid", 25.0, 40.0),
        ("setup_flat", "mid", 20.0, 25.0),
    ]
    for level_name, scenario, max_time, max_offset in cases:
        result, _bot = _run_level(level_name=level_name, scenario=scenario, max_time=max_time)
        assert result.get("state") != "crashed"
        landing_offset = result.get("landing_offset")
        if isinstance(landing_offset, (int, float)):
            assert abs(float(landing_offset)) <= max_offset


def test_zem_launch_landing_offset_bound_seed0() -> None:
    result, _bot = _run_level(level_name="setup_flat", scenario="near", max_time=35.0)
    assert result.get("state") == "landed"
    landing_offset = result.get("landing_offset")
    assert isinstance(landing_offset, (int, float))
    # Corridor-aware objective trades centering precision for fuel efficiency.
    assert abs(float(landing_offset)) <= 40.0


def test_zem_passive_coast_suppresses_solver_work_mid_flare() -> None:
    # Early flare run should remain ungated before control solves begin.
    _result, bot = _run_level(
        level_name="flare_normal",
        scenario="mid",
        max_steps=180,
        max_time=20.0,
    )
    snapshot = bot.get_bot_telemetry()
    assert int(snapshot.get("solve_count") or 0) == 0
    assert int(snapshot.get("flare_probe_count") or 0) <= 1
    assert snapshot.get("terminal_gate_done") is False
    assert snapshot.get("flare_gate_mode") is None
    assert int(snapshot.get("fallback_frames") or 0) == 0
    assert snapshot.get("shape_curve_rmse") is None
    assert snapshot.get("shape_projected_dx_abs_max") == pytest.approx(0.0)


def test_pdg_optimizer_solution_changes_with_runtime_gravity() -> None:
    optimizer = PDGOptimizer(PDGOptimizerConfig(horizon_steps=10, step_dt=0.2))
    common = dict(
        x=0.0,
        y=600.0,
        vx=25.0,
        vy=-20.0,
        target_x=80.0,
        target_y=0.0,
        y_floor=-8.0,
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


def test_pdg_optimizer_uphill_target_is_feasible() -> None:
    optimizer = PDGOptimizer(PDGOptimizerConfig(horizon_steps=36, step_dt=0.2))
    plan = optimizer.solve(
        x=0.0,
        y=5.0,
        vx=0.0,
        vy=0.0,
        target_x=400.0,
        target_y=800.0,
        y_floor=-3.0,
        target_vy=-4.0,
        max_thrust_accel=22.0,
        min_thrust_accel=2.0,
        nominal_thrust_accel=12.0,
        max_tilt_rad=0.78,
        descent_floor_vy=-8.0,
        gravity_mag=1.62,
        pad_half_width=55.0,
        altitude_hint=5.0,
        warm_start=None,
    )
    assert plan is not None
    assert plan.feasible


def test_pdg_optimizer_supports_runtime_path_override_and_rejects_bad_length() -> None:
    cfg = PDGOptimizerConfig(horizon_steps=12, step_dt=0.2)
    optimizer = PDGOptimizer(cfg)
    assert optimizer.horizon_steps == 12
    assert optimizer.step_dt == pytest.approx(0.2)

    common = dict(
        x=0.0,
        y=600.0,
        vx=20.0,
        vy=-15.0,
        target_x=150.0,
        target_y=0.0,
        y_floor=-8.0,
        target_vy=-2.0,
        max_thrust_accel=22.0,
        min_thrust_accel=2.0,
        nominal_thrust_accel=12.0,
        max_tilt_rad=0.6,
        descent_floor_vy=-11.0,
        gravity_mag=1.62,
        pad_half_width=55.0,
        altitude_hint=600.0,
        warm_start=None,
    )

    with pytest.raises(ValueError, match="y_ref_override"):
        optimizer.solve(y_ref_override=[0.0] * 10, **common)

    n = cfg.horizon_steps
    y_override = [600.0 - (50.0 * (i / n)) for i in range(n + 1)]
    plan = optimizer.solve(
        terminal_x_tol=8.0,
        y_ref_override=y_override,
        **common,
    )
    assert plan is not None
    assert plan.feasible
