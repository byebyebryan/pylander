from __future__ import annotations

import math

from bots._bot_math import clamp, finite_altitude
from bots._optimizer_pdg import PDGPlan
from core.bot import PassiveSensors
from core.config import GRAVITY

_GRAVITY_MAG = abs(float(GRAVITY))


def _ballistic_apex_profile(
    *,
    n: int,
    y0: float,
    target_y: float,
    apex_target_y: float,
) -> list[float] | None:
    if n <= 0 or _GRAVITY_MAG <= 1e-6:
        return None
    apex_y = max(float(apex_target_y), float(y0) + 1.0, float(target_y) + 1.0)
    rise = apex_y - float(y0)
    if rise <= 1e-3:
        return None

    t_apex = math.sqrt((2.0 * rise) / _GRAVITY_MAG)
    vy0 = _GRAVITY_MAG * t_apex
    disc = (vy0 * vy0) - (2.0 * _GRAVITY_MAG * (float(target_y) - float(y0)))
    if disc < 0.0:
        return None
    sqrt_disc = math.sqrt(max(0.0, disc))
    t_target = (vy0 + sqrt_disc) / _GRAVITY_MAG
    if not math.isfinite(t_target) or t_target <= max(1e-3, t_apex):
        return None

    y_ref: list[float] = []
    for i in range(n + 1):
        alpha = i / max(1, n)
        tk = alpha * t_target
        yk = float(y0) + (vy0 * tk) - (0.5 * _GRAVITY_MAG * tk * tk)
        y_ref.append(float(yk))
    return y_ref


def solve_plan(
    bot,
    *,
    passive: PassiveSensors,
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
    target_vy = bot._desired_terminal_vy(alt_guidance, nominal_thrust_accel, max_tilt)
    descent_floor_vy = bot._descent_floor_vy(alt_guidance, nominal_thrust_accel, max_tilt)
    if phase in ("setup", "coast"):
        if alt > bot._cfg.high_alt_coast_vy_boost_alt:
            vy_alpha = clamp(
                (alt - bot._cfg.high_alt_coast_vy_boost_alt)
                / max(1e-3, 3.0 * bot._cfg.high_alt_coast_vy_boost_alt),
                0.0,
                1.0,
            )
            vy_boost = 1.0 + (
                vy_alpha * max(0.0, bot._cfg.high_alt_coast_vy_boost_max - 1.0)
            )
            target_vy = min(target_vy * vy_boost, -bot._cfg.braking_min_speed)
    optimizer = bot._select_optimizer(
        phase=phase,
        alt=alt_guidance,
        vy_up=float(passive.vy_up),
    )
    setup_apex_active = (
        phase == "setup"
        and bool(getattr(bot, "_uphill_transfer", False))
    )
    anchor_dy = (
        float(bot._shape_target_y - bot._shape_start_y)
        if bool(getattr(bot, "_shape_window_started", False))
        else float(dy)
    )
    projected_dx_now = (
        float(bot._last_projection_dx)
        if bot._last_projection_dx is not None
        else float(dx)
    )
    setup_apex_offset = clamp(
        (
            float(bot._cfg.setup_apex_offset_per_dy) * max(0.0, anchor_dy)
            + (
                float(bot._cfg.setup_apex_offset_per_projected_dx)
                * abs(projected_dx_now)
            )
        ),
        float(bot._cfg.setup_apex_offset_min),
        float(bot._cfg.setup_apex_offset_max),
    )
    terminal_x_tol = bot._phase_terminal_x_tol(phase)
    y_ref_override = None
    shape_blend = bot._shape_ref_blend_for_phase(phase)
    if setup_apex_active and shape_blend > 1e-6 and bot._last_projection_has_target_y:
        n = optimizer.horizon_steps
        apex_target_y = target_y_plan + setup_apex_offset
        shape_ref = _ballistic_apex_profile(
            n=n,
            y0=float(passive.y),
            target_y=target_y_plan,
            apex_target_y=apex_target_y,
        )
        if shape_ref is not None:
            if shape_blend >= 1.0:
                y_ref_override = shape_ref
            else:
                linear_ref = [
                    float(passive.y) + ((target_y_plan - float(passive.y)) * (i / max(1, n)))
                    for i in range(n + 1)
                ]
                y_ref_override = [
                    ((1.0 - shape_blend) * linear_ref[i]) + (shape_blend * shape_ref[i])
                    for i in range(n + 1)
                ]
    elif (
        shape_blend > 1e-6
        and float(passive.vy_up) > 0.0
        and (phase != "setup" or setup_apex_active)
    ):
        n = optimizer.horizon_steps
        apex_dx = bot._shape_anchor_dx_abs if bot._shape_window_started else abs(dx)
        apex_target = bot._shape_apex_target(apex_dx)
        shape_ref = bot._shape_y_ref(
            n=n,
            x0=float(passive.x),
            y0=float(passive.y),
            target_x=target_x_plan,
            target_y=target_y_plan,
            apex_over_target=apex_target,
        )
        if shape_blend >= 1.0:
            y_ref_override = shape_ref
        else:
            linear_ref = [
                float(passive.y) + ((target_y_plan - float(passive.y)) * (i / max(1, n)))
                for i in range(n + 1)
            ]
            y_ref_override = [
                ((1.0 - shape_blend) * linear_ref[i]) + (shape_blend * shape_ref[i])
                for i in range(n + 1)
            ]
    projected_t_fall = bot._last_projection_t_fall
    if projected_t_fall is None or projected_t_fall <= 1e-3:
        fallback_denom = max(1.0, max(0.0, -float(passive.vy_up)) + 1.0)
        projected_t_fall = max(
            0.5,
            max(0.0, float(passive.y) - target_y_plan) / fallback_denom,
        )
    if not bot._last_projection_has_target_y:
        # Before target-y is ballistically reachable, avoid forcing an
        # aggressive lateral intercept off a short apex-time fallback.
        projected_t_fall = max(projected_t_fall, 2.6 + (0.002 * abs(float(dy))))
    apex_target_y = (
        target_y_plan + setup_apex_offset if setup_apex_active else target_y_plan
    )
    goal_projected_dx_tol = max(
        bot._cfg.setup_goal_projected_dx_tol_abs,
        bot._cfg.setup_goal_projected_dx_tol_ratio * bot._last_target_half,
    )
    goal_apex_y_tol = bot._cfg.setup_goal_apex_y_tol
    goal_apex_vy_target = 0.0
    goal_apex_vy_tol = bot._cfg.setup_goal_apex_vy_tol
    if phase == "setup":
        if setup_apex_active:
            # Higher climb deltas are less likely to satisfy tight setup goals before
            # thrust naturally tapers to idle; relax tolerances smoothly with |dy|.
            dy_scale = clamp((abs(float(dy)) - 300.0) / 500.0, 0.0, 1.0)
            goal_projected_dx_tol *= 1.0 + (2.0 * dy_scale)
            goal_apex_y_tol *= 1.0 + (3.0 * dy_scale)
            goal_apex_vy_tol *= 1.0 + (2.0 * dy_scale)
        else:
            # Non-uphill setup runs should not be forced into climb-style apex goals.
            goal_apex_y_tol = max(goal_apex_y_tol, abs(float(dy)) + 300.0)
            goal_apex_vy_target = target_vy
            goal_apex_vy_tol = max(goal_apex_vy_tol, 25.0)
    if phase != "setup":
        goal_projected_dx_tol = max(goal_projected_dx_tol, 3.0 * bot._last_target_half)
        goal_apex_y_tol = max(goal_apex_y_tol, 300.0)
        goal_apex_vy_target = target_vy
        goal_apex_vy_tol = max(goal_apex_vy_tol, 20.0)

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
        projected_t_fall=float(projected_t_fall),
        apex_target_y=float(apex_target_y),
        goal_projected_dx_tol=float(goal_projected_dx_tol),
        goal_apex_y_tol=float(goal_apex_y_tol),
        goal_apex_vy_target=float(goal_apex_vy_target),
        goal_apex_vy_tol=float(goal_apex_vy_tol),
        terminal_x_tol=terminal_x_tol,
        y_ref_override=y_ref_override,
    )
    if plan is not None:
        bot._last_solve_ms = float(plan.solve_time_ms)
        bot._last_solver_status = str(plan.status)
        bot._solve_count += 1
        bot._solve_ms_sum += bot._last_solve_ms
        bot._solve_ms_samples.append(bot._last_solve_ms)
    return plan
