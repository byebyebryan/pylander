from __future__ import annotations

import warnings
from typing import Any, cast

import pytest

from bot_framework.bots import create_bot
from bot_framework.bots.pdg_optimizer import PDGOptimizer, PDGOptimizerConfig
from bot_framework.scenarios import create_scenario_level
from game import LanderGame
from game.levels import create_level as create_gameplay_level


def _create_level(name: str):
    if name in ("flat", "mountains"):
        return create_gameplay_level(name)
    return create_scenario_level(name)


def _run_level(
    *,
    level_name: str,
    scenario: str,
    max_steps: int | None = None,
    max_time: float = 300.0,
    eval_goal: str | None = None,
):
    level = cast(Any, _create_level(level_name))
    if hasattr(level, "set_eval_scenario"):
        level.set_eval_scenario(scenario)
    # Keep smoke runs bounded and stop as soon as a terminal condition is reached.
    level.stop_on_crash = True
    level.stop_on_out_of_fuel = True
    level.stop_on_first_land = True
    bot = cast(Any, create_bot("pdg"))
    if eval_goal is not None:
        bot.set_eval_goal(eval_goal)
    if eval_goal is None:
        game = LanderGame(level=level, seed=0, bot=bot, headless=True)
    else:
        game = LanderGame(
            level=level, seed=0, bot=bot, headless=True, eval_goal=eval_goal
        )
    result = game.run(print_freq=0, max_steps=max_steps, max_time=max_time)
    return result, bot


@pytest.mark.parametrize(
    ("level_name", "scenario", "eval_goal", "max_time", "key", "expected"),
    (
        ("boost", "climb:mid:half", "boost_cutoff", 10.0, "boost_cutoff_done", True),
        ("boost", "flat:mid:half", "boost_cutoff", 9.0, "boost_cutoff_done", True),
    ),
)
def test_pdg_smoke_plunge_and_setup_milestones_seed0(
    level_name: str,
    scenario: str,
    eval_goal: str | None,
    max_time: float,
    key: str,
    expected: object,
) -> None:
    # Keep broad regression coverage, but stop setup scenarios at their boost cutoff.
    result, _bot = _run_level(
        level_name=level_name,
        scenario=scenario,
        max_time=max_time,
        eval_goal=eval_goal,
    )
    assert result.get("state") != "crashed"
    assert result.get(key) == expected


@pytest.mark.parametrize(
    ("scenario", "max_time"),
    (
        ("mid:half", 12.0),
        ("low:empty", 8.5),
    ),
)
def test_pdg_smoke_plunge_reaches_touchdown_seed0(
    scenario: str,
    max_time: float,
) -> None:
    result, bot = _run_level(
        level_name="plunge",
        scenario=scenario,
        max_time=max_time,
    )
    assert result.get("state") != "crashed"
    assert bot.state._active_phase in {"touchdown", "landed"}


def test_pdg_launch_landing_offset_bound_seed0() -> None:
    result, _bot = _run_level(
        level_name="boost", scenario="flat:near:half", max_time=25.0
    )
    assert result.get("state") == "landed"
    landing_offset = result.get("landing_offset")
    assert isinstance(landing_offset, (int, float))
    # Corridor-aware objective trades centering precision for fuel efficiency.
    assert abs(float(landing_offset)) <= 40.0


def test_pdg_passive_coast_suppresses_solver_work_mid_flare() -> None:
    # Early flare run should remain ungated before control solves begin.
    _result, bot = _run_level(
        level_name="terminal",
        scenario="normal:mid",
        max_steps=180,
        max_time=20.0,
    )
    snapshot = bot.get_bot_telemetry()
    assert int(snapshot.get("solve_count") or 0) == 0
    assert int(snapshot.get("terminal_probe_count") or 0) == 0
    assert snapshot.get("terminal_entry_done") is False
    assert snapshot.get("terminal_gate_mode") is None
    assert int(snapshot.get("fallback_frames") or 0) == 0
    assert snapshot.get("shape_curve_rmse") is None
    assert snapshot.get("shape_projected_dx_abs_max") == pytest.approx(0.0)


def test_pdg_terminal_optimizer_uses_fixed_terminal_weights() -> None:
    bot = cast(Any, create_bot("pdg"))

    terminal_cfg = bot._optimizer_terminal._cfg
    boost_cfg = bot._optimizer_boost._cfg

    assert terminal_cfg.w_path_x == pytest.approx(0.03)
    assert terminal_cfg.w_path_y == pytest.approx(0.015)
    assert terminal_cfg.w_upward_vy == pytest.approx(1.20)
    assert terminal_cfg.w_altitude_progress == pytest.approx(0.0)
    assert boost_cfg.w_path_x == pytest.approx(0.09)
    assert boost_cfg.w_path_y == pytest.approx(0.025)
    assert boost_cfg.w_upward_vy == pytest.approx(1.20)


def test_pdg_optimizer_solution_changes_with_runtime_gravity() -> None:
    optimizer = PDGOptimizer(PDGOptimizerConfig(horizon_steps=10, step_dt=0.2))
    common: dict[str, Any] = dict(
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


def test_pdg_optimizer_problem_is_dpp() -> None:
    optimizer = PDGOptimizer()
    assert optimizer._problem is not None
    assert optimizer._problem.is_dpp()


def test_pdg_optimizer_problem_is_dpp_and_avoids_non_dpp_warning() -> None:
    optimizer = PDGOptimizer(PDGOptimizerConfig(horizon_steps=10, step_dt=0.2))
    assert optimizer._problem is not None
    assert optimizer._problem.is_dpp()

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        plan = optimizer.solve(
            x=0.0,
            y=140.0,
            vx=25.0,
            vy=6.0,
            target_x=120.0,
            target_y=0.0,
            y_floor=-8.0,
            target_vy=-2.0,
            max_thrust_accel=22.0,
            min_thrust_accel=2.0,
            nominal_thrust_accel=12.0,
            max_tilt_rad=1.0,
            descent_floor_vy=-8.0,
            gravity_mag=1.62,
            pad_half_width=55.0,
            altitude_hint=140.0,
            warm_start=None,
            boost_t_cross_ref=4.0,
            boost_t_angle_ref=4.0,
            boost_no_away_dir=1.0,
            boost_angle_active=1.0,
        )

    assert plan is not None
    assert plan.feasible
    assert not any("not DPP" in str(w.message) for w in caught)


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

    common: dict[str, Any] = dict(
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


def test_pdg_optimizer_setup_no_away_constraint_follows_target_direction() -> None:
    optimizer = PDGOptimizer(
        PDGOptimizerConfig(
            horizon_steps=10,
            step_dt=0.2,
            w_terminal_x=0.0,
            w_terminal_y=0.0,
            w_terminal_vx=0.0,
            w_terminal_vy=0.0,
            w_path_x=0.0,
            w_path_y=0.0,
            w_upward_vy=0.0,
            w_boost_projected_dx=40.0,
            w_boost_target_y_cross=20.0,
            w_boost_apex=8.0,
            w_boost_angle=0.0,
        )
    )

    plan = optimizer.solve(
        x=0.0,
        y=140.0,
        vx=25.0,
        vy=6.0,
        target_x=120.0,
        target_y=0.0,
        y_floor=-8.0,
        target_vy=-2.0,
        max_thrust_accel=22.0,
        min_thrust_accel=2.0,
        nominal_thrust_accel=12.0,
        max_tilt_rad=1.0,
        descent_floor_vy=-8.0,
        gravity_mag=1.62,
        pad_half_width=55.0,
        altitude_hint=140.0,
        warm_start=None,
        boost_t_cross_ref=4.0,
        boost_no_away_dir=1.0,
    )

    assert plan is not None
    assert plan.feasible
    assert min(float(ax) for ax in plan.ax) >= -1e-6
