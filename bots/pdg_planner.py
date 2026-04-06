from __future__ import annotations

import math

from bots.common_ballistics import estimate_target_y_projection
from bots.common_math import _GRAVITY_MAG, finite_altitude
from bots.pdg_boost import (
    select_reference_times,
    boost_dx_limit,
    boost_objective_geometry,
)
from bots.pdg_optimizer import PDGPlan
from core.bot import Sensors


def solve_plan(
    bot,
    *,
    passive: Sensors,
    dx: float,
    dy: float,
    max_thrust_accel: float,
    min_thrust_accel: float,
    nominal_thrust_accel: float,
    phase: str,
    projection=None,
) -> PDGPlan | None:
    alt = max(0.0, finite_altitude(passive))
    target_x = float(passive.x) + dx
    target_y = float(passive.y) + dy
    target_x_plan = target_x
    target_y_plan = target_y
    alt_guidance = alt
    y_floor: float | tuple[float, float] = min(float(passive.y), target_y_plan) - 8.0
    max_tilt = bot._resolve_max_tilt(
        alt,
        dx,
        float(passive.vx),
        dy=dy,
        phase=phase,
        vy_up=float(passive.vy_up) if phase == "terminal" else None,
        max_thrust_accel=max_thrust_accel if phase == "terminal" else None,
        lateral_dx=(
            float(projection.projected_dx)
            if phase == "terminal" and projection is not None
            else None
        ),
    )
    target_vy = bot._desired_terminal_vy(alt_guidance, nominal_thrust_accel, max_tilt)
    descent_floor_vy = bot._descent_floor_vy(
        alt_guidance, nominal_thrust_accel, max_tilt
    )
    optimizer = bot._select_optimizer(
        phase=phase,
        alt=alt_guidance,
        vy_up=float(passive.vy_up),
        dy=dy,
    )
    terminal_x_tol = bot._phase_terminal_x_tol(phase)
    y_ref_override = None
    boost_t_cross_ref = 0.0
    boost_t_angle_ref = 0.0
    boost_no_away_ax_sign = 0.0
    boost_angle_scale = 0.0
    if phase == "boost":
        if projection is None:
            projection = estimate_target_y_projection(
                dx=dx,
                dy=dy,
                vx=float(passive.vx),
                vy_up=float(passive.vy_up),
                x=float(passive.x),
                y=float(passive.y),
                min_t_fall=0.0,
                gravity_mag=_GRAVITY_MAG,
            )
        _dx_anchor_abs, boost_t_apex_ref, boost_t_cross_ref = select_reference_times(
            bot,
            passive=passive,
            dx=dx,
            dy=dy,
            plan=bot._plan,
        )
        # Keep projected target-y crossing grounded in a descending ballistic solution.
        if boost_t_cross_ref <= boost_t_apex_ref and bool(
            projection.has_target_y_solution
        ):
            boost_t_cross_ref = max(boost_t_apex_ref + 0.05, float(projection.t_fall))
        if bool(projection.has_target_y_solution):
            boost_t_angle_ref = max(0.0, float(projection.t_fall))
        objective_geometry = boost_objective_geometry(
            bot,
            passive=passive,
            dx=dx,
            projection=projection,
            boost_t_cross_ref=boost_t_cross_ref,
        )
        if abs(float(dx)) > float(boost_dx_limit(bot)):
            lateral_accel_cap = max(
                1e-3, float(max_thrust_accel) * math.sin(float(max_tilt))
            )
            lateral_dx = max(0.0, abs(float(dx)) - float(objective_geometry.dx_limit))
            boost_t_cross_ref = max(
                boost_t_cross_ref,
                math.sqrt((2.0 * lateral_dx) / lateral_accel_cap),
            )
            objective_geometry = boost_objective_geometry(
                bot,
                passive=passive,
                dx=dx,
                projection=projection,
                boost_t_cross_ref=boost_t_cross_ref,
            )
        boost_no_away_ax_sign = objective_geometry.no_away_ax_sign
        boost_angle_scale = objective_geometry.angle_scale

    plan = optimizer.solve(
        x=float(passive.x),
        y=float(passive.y),
        vx=float(passive.vx),
        vy=float(passive.vy_up),
        target_x=target_x_plan,
        target_y=target_y_plan,
        y_floor=y_floor,
        target_vy=target_vy,
        max_thrust_accel=max_thrust_accel,
        min_thrust_accel=min_thrust_accel,
        nominal_thrust_accel=nominal_thrust_accel,
        max_tilt_rad=max_tilt,
        descent_floor_vy=descent_floor_vy,
        gravity_mag=_GRAVITY_MAG,
        pad_half_width=bot._last_target_half,
        altitude_hint=alt_guidance,
        warm_start=bot._plan,
        terminal_x_tol=terminal_x_tol,
        y_ref_override=y_ref_override,
        boost_t_cross_ref=boost_t_cross_ref,
        boost_t_angle_ref=boost_t_angle_ref,
        boost_no_away_dir=boost_no_away_ax_sign,
        boost_angle_active=boost_angle_scale,
    )
    if plan is not None:
        bot._last_solve_ms = float(plan.solve_time_ms)
        bot._last_solver_status = str(plan.status)
        bot._solve_count += 1
        bot._solve_ms_sum += bot._last_solve_ms
        bot._solve_ms_samples.append(bot._last_solve_ms)
    return plan
