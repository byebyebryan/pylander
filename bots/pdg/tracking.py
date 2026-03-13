from __future__ import annotations

import math

from bots._ballistics import BallisticProjection
from bots.pdg.setup import projected_impact_angle_deg as _projected_impact_angle_deg
from core.bot import Sensors, SetupGateMetrics
from core.config import GRAVITY

_GRAVITY_MAG = abs(float(GRAVITY))


def _projected_apex(y: float, vy_up: float, target_y: float) -> tuple[float, float]:
    vy_pos = max(0.0, float(vy_up))
    if _GRAVITY_MAG <= 1e-6:
        apex_y = float(y)
    else:
        apex_y = float(y) + ((vy_pos * vy_pos) / (2.0 * _GRAVITY_MAG))
    return apex_y, (apex_y - float(target_y))


def _capture_setup_gate_state(bot, *, passive: Sensors) -> None:
    bot._setup_gate_x = float(passive.x)
    bot._setup_gate_y = float(passive.y)
    bot._setup_gate_vx = float(passive.vx)
    bot._setup_gate_vy_up = float(passive.vy_up)


def _capture_flare_entry_state(bot, *, passive: Sensors) -> None:
    bot._flare_entry_x = float(passive.x)
    bot._flare_entry_y = float(passive.y)


def finalize_flare_entry_metrics(
    bot,
    *,
    passive: Sensors,
    alt: float,
    projected_dx: float,
) -> None:
    bot._flare_entry_done = True
    bot._flare_entry_time = bot._elapsed_time_s
    bot._flare_entry_altitude = float(alt)
    bot._flare_entry_projected_dx = float(projected_dx)
    _capture_flare_entry_state(bot, passive=passive)


def finalize_setup_gate_metrics(
    bot,
    *,
    passive: Sensors,
    alt: float,
    projection: BallisticProjection,
) -> None:
    target_y = float(bot._last_target_y)
    apex_y, apex_over_target = _projected_apex(
        y=float(passive.y),
        vy_up=float(passive.vy_up),
        target_y=target_y,
    )
    has_target_y_solution = bool(getattr(projection, "has_target_y_solution", True))
    projected_impact_dx = float(projection.projected_dx) if has_target_y_solution else None
    impact_angle_deg = None
    if has_target_y_solution:
        impact_angle_deg = _projected_impact_angle_deg(
            vx=float(passive.vx),
            vy_up=float(passive.vy_up),
            t_fall=float(projection.t_fall),
        )

    fuel_start = bot._setup_phase_fuel_start
    fuel_used = None
    if fuel_start is not None:
        fuel_used = max(0.0, float(fuel_start) - float(passive.fuel))
    burn_duration_s = max(0.0, float(bot._elapsed_time_s))
    burn_avg_thrust_level = None
    if burn_duration_s > 1e-6:
        burn_avg_thrust_level = bot._setup_phase_thrust_integral / burn_duration_s

    bot._setup_gate_done = True
    bot._setup_gate_time = bot._elapsed_time_s
    bot._setup_gate_altitude = alt
    bot._setup_gate_projected_dx = float(projection.projected_dx)
    bot._setup_gate_projected_apex_y = apex_y
    bot._setup_gate_projected_apex_over_target = apex_over_target
    bot._setup_gate_has_target_y_solution = has_target_y_solution
    bot._setup_gate_projected_impact_dx = projected_impact_dx
    bot._setup_gate_projected_impact_angle_deg = impact_angle_deg
    bot._setup_gate_burn_duration_s = burn_duration_s
    bot._setup_gate_burn_fuel_used = fuel_used
    bot._setup_gate_burn_avg_thrust_level = burn_avg_thrust_level
    bot._setup_gate_spawn_primed = False
    _capture_setup_gate_state(bot, passive=passive)


def apply_setup_gate_metrics(
    bot,
    *,
    setup_gate: SetupGateMetrics,
) -> None:
    bot._setup_gate_done = True
    bot._setup_gate_time = setup_gate.time_s
    bot._setup_gate_altitude = setup_gate.altitude
    bot._setup_gate_x = setup_gate.x
    bot._setup_gate_y = setup_gate.y
    bot._setup_gate_vx = setup_gate.vx
    bot._setup_gate_vy_up = setup_gate.vy_up
    bot._setup_gate_projected_apex_y = setup_gate.projected_apex_y
    bot._setup_gate_projected_apex_over_target = setup_gate.projected_apex_over_target
    bot._setup_gate_has_target_y_solution = setup_gate.has_target_y_solution
    bot._setup_gate_projected_impact_dx = setup_gate.projected_impact_dx
    bot._setup_gate_projected_dx = setup_gate.projected_impact_dx
    bot._setup_gate_projected_impact_angle_deg = setup_gate.projected_impact_angle_deg
    bot._setup_gate_burn_duration_s = setup_gate.burn_duration_s
    bot._setup_gate_burn_fuel_used = setup_gate.burn_fuel_used
    bot._setup_gate_burn_avg_thrust_level = setup_gate.burn_avg_thrust_level


def refresh_stage_tracking(
    bot,
    *,
    passive: Sensors,
    dx: float,
    dy: float,
    alt: float,
    projection: BallisticProjection,
) -> str:
    cfg = bot._cfg
    projected_dx = float(projection.projected_dx)
    t_fall = max(0.0, float(projection.t_fall))
    has_target_y_solution = bool(getattr(projection, "has_target_y_solution", True))
    bot._last_projection_dx = projected_dx
    bot._last_projection_t_fall = t_fall
    bot._last_projection_has_target_y = has_target_y_solution

    thrust_level = float(passive.thrust_level)
    if (
        bot._debug_setup
        and bot._active_phase == "setup"
        and (bot._elapsed_time_s - bot._debug_setup_last_print_t) >= 0.25
    ):
        bot._debug_setup_last_print_t = bot._elapsed_time_s
        bot._debug_setup_print(
            "setup_track "
            f"t={bot._elapsed_time_s:6.2f} "
            f"ph={bot._active_phase:8s} "
            f"dx={dx:8.2f} proj_dx={projected_dx:8.2f} "
            f"has_target={int(has_target_y_solution)} "
            f"thrust={thrust_level:5.2f}"
        )

    speed = math.hypot(float(passive.vx), float(passive.vy_up))
    touchdown_dx_limit = max(12.0, cfg.touchdown_phase_dx_ratio * bot._last_target_half)
    in_touchdown_corridor = abs(float(dx)) <= touchdown_dx_limit
    in_touchdown_projected_corridor = abs(projected_dx) <= touchdown_dx_limit
    direct_touchdown_terminal = (
        (not bot._setup_gate_done)
        and (not bot._flare_entry_done)
        and (not bot._shape_window_started)
        and has_target_y_solution
        and in_touchdown_corridor
        and in_touchdown_projected_corridor
        and abs(float(passive.vx)) <= float(cfg.touchdown_phase_speed)
        and t_fall <= float(cfg.touchdown_phase_time_to_go)
    )
    next_stage = "setup"
    if (
        alt <= cfg.touchdown_phase_altitude
        and speed <= cfg.touchdown_phase_speed
        and in_touchdown_corridor
    ):
        next_stage = "touchdown"
    elif direct_touchdown_terminal:
        next_stage = "touchdown"
    elif bot._flare_entry_done:
        next_stage = "flare"
    elif bot._setup_gate_done:
        if bot._setup_gate_spawn_primed:
            next_stage = "coast"
        else:
            next_stage = "coast"
    bot._stage_tracking_next = next_stage

    if (
        bot._debug_setup
        and bot._setup_gate_done
        and bot._debug_setup_post_end_time is not None
        and bot._elapsed_time_s <= bot._debug_setup_post_end_time
        and (bot._elapsed_time_s - bot._debug_setup_last_print_t) >= 0.25
    ):
        bot._debug_setup_last_print_t = bot._elapsed_time_s
        bot._debug_setup_print(
            "post_gate "
            f"t={bot._elapsed_time_s:6.2f} "
            f"ph={next_stage:8s} "
            f"dx={dx:8.2f} proj_dx={projected_dx:8.2f} "
            f"thrust={float(passive.thrust_level):5.2f}"
        )
    return next_stage


def maybe_start_shape_window(
    bot,
    *,
    passive: Sensors,
    dx: float,
    dy: float,
) -> None:
    if bot._shape_window_started or bot._shape_window_done:
        return
    if bot._setup_gate_done:
        return
    if bot._active_phase == "takeoff":
        return
    if abs(float(dx)) <= 1e-3:
        return
    bot._shape_window_started = True
    bot._shape_window_start_time = bot._elapsed_time_s
    bot._shape_start_x = float(passive.x)
    bot._shape_start_y = float(passive.y)
    bot._shape_target_x = float(passive.x) + float(dx)
    bot._shape_target_y = float(passive.y) + float(dy)
    bot._uphill_transfer = float(dy) >= bot._cfg.uphill_setup_dy_min
    bot._shape_anchor_dx_abs = abs(float(dx))
    bot._shape_apex_target_over_target = bot._shape_apex_target(bot._shape_anchor_dx_abs)
    bot._shape_apex_actual_over_target = max(0.0, float(passive.y) - bot._shape_target_y)
    bot._shape_curve_sq_err_sum = 0.0
    bot._shape_curve_count = 0
    bot._shape_projected_dx_abs_sum = 0.0
    bot._shape_projected_dx_abs_max = 0.0
    bot._shape_projected_dx_count = 0
    bot._shape_shortfall_count = 0
    bot._shape_shortfall_sample_count = 0


def update_shape_window_metrics(
    bot,
    *,
    passive: Sensors,
    dx: float,
    projection: BallisticProjection,
) -> None:
    if (not bot._shape_window_started) or bot._shape_window_done:
        return

    projected_abs = abs(float(projection.projected_dx))
    bot._shape_projected_dx_abs_sum += projected_abs
    bot._shape_projected_dx_count += 1
    bot._shape_projected_dx_abs_max = max(bot._shape_projected_dx_abs_max, projected_abs)

    dx_now = float(dx)
    if abs(dx_now) > 1e-3:
        bot._shape_shortfall_sample_count += 1
        shortfall_metric = float(projection.projected_dx) * math.copysign(1.0, dx_now)
        if shortfall_metric > 0.0:
            bot._shape_shortfall_count += 1

    over_target = max(0.0, float(passive.y) - bot._shape_target_y)
    bot._shape_apex_actual_over_target = max(bot._shape_apex_actual_over_target, over_target)
    y_ref = bot._shape_reference_y_at_x(float(passive.x))
    y_err = float(passive.y) - y_ref
    bot._shape_curve_sq_err_sum += y_err * y_err
    bot._shape_curve_count += 1

    if (
        bot._flare_entry_done or bot._active_phase in ("flare", "touchdown")
    ) and not bot._shape_window_done:
        bot._shape_window_done = True
        bot._shape_window_end_time = bot._elapsed_time_s
