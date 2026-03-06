from __future__ import annotations

from bots._bot_math import clamp, finite_altitude
from bots._optimizer_pdg import PDGPlan
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
    terminal_x_tol = bot._phase_terminal_x_tol(phase)
    y_ref_override = None
    shape_blend = bot._shape_ref_blend_for_phase(phase)
    if shape_blend > 1e-6 and float(passive.vy_up) > 0.0:
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
    )
    if plan is not None:
        bot._last_solve_ms = float(plan.solve_time_ms)
        bot._last_solver_status = str(plan.status)
        bot._solve_count += 1
        bot._solve_ms_sum += bot._last_solve_ms
        bot._solve_ms_samples.append(bot._last_solve_ms)
    return plan
