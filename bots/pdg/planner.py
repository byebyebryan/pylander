from __future__ import annotations

from bots._ballistics import estimate_target_y_projection
from bots._bot_math import finite_altitude
from bots._optimizer_pdg import PDGPlan
from bots.pdg.setup import (
    apex_target_and_tolerance,
    select_reference_times,
)
from core.bot import Sensors
from core.config import GRAVITY

_GRAVITY_MAG = abs(float(GRAVITY))


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
    )
    target_vy = bot._desired_flare_vy(alt_guidance, nominal_thrust_accel, max_tilt)
    descent_floor_vy = bot._descent_floor_vy(alt_guidance, nominal_thrust_accel, max_tilt)
    optimizer = bot._select_optimizer(
        phase=phase,
        alt=alt_guidance,
        vy_up=float(passive.vy_up),
        dy=dy,
    )
    flare_x_tol = bot._phase_flare_x_tol(phase)
    y_ref_override = None
    setup_t_cross_ref = 0.0
    setup_t_apex_ref = 0.0
    setup_apex_target = 0.0
    setup_apex_tol = 0.0
    if phase == "setup":
        dx_anchor_abs, setup_t_apex_ref, setup_t_cross_ref = select_reference_times(
            bot,
            passive=passive,
            dx=dx,
            dy=dy,
            plan=bot._plan,
        )
        setup_apex_target, setup_apex_tol = apex_target_and_tolerance(
            bot,
            dx_anchor_abs=dx_anchor_abs,
            dy=dy,
        )
        # Keep projected target-y crossing grounded in a descending ballistic solution.
        if setup_t_cross_ref <= setup_t_apex_ref:
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
            if bool(projection.has_target_y_solution):
                setup_t_cross_ref = max(setup_t_apex_ref + 0.05, float(projection.t_fall))

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
        terminal_x_tol=flare_x_tol,
        y_ref_override=y_ref_override,
        setup_t_cross_ref=setup_t_cross_ref,
        setup_t_apex_ref=setup_t_apex_ref,
        setup_apex_target=setup_apex_target,
        setup_apex_tol=setup_apex_tol,
    )
    if plan is not None:
        bot._last_solve_ms = float(plan.solve_time_ms)
        bot._last_solver_status = str(plan.status)
        bot._solve_count += 1
        bot._solve_ms_sum += bot._last_solve_ms
        bot._solve_ms_samples.append(bot._last_solve_ms)
    return plan
