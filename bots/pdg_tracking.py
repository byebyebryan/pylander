from __future__ import annotations

import math

from bots.common_ballistics import BallisticProjection, ballistic_apex_from_state
from bots.pdg_boost import projected_impact_angle_deg as _projected_impact_angle_deg
from core.bot import Sensors, BoostCutoffMetrics
from core.config import GRAVITY

_GRAVITY_MAG = abs(float(GRAVITY))


def _projected_apex(y: float, vy_up: float, target_y: float) -> tuple[float, float]:
    apex = ballistic_apex_from_state(
        x=None,
        y=float(y),
        vx=None,
        vy_up=max(0.0, float(vy_up)),
        gravity_mag=_GRAVITY_MAG,
    )
    apex_y = float(apex.y_apex)
    return apex_y, (apex_y - float(target_y))


def _capture_boost_cutoff_state(bot, *, passive: Sensors) -> None:
    bot._boost_cutoff_x = float(passive.x)
    bot._boost_cutoff_y = float(passive.y)
    bot._boost_cutoff_vx = float(passive.vx)
    bot._boost_cutoff_vy_up = float(passive.vy_up)


def _capture_terminal_entry_state(bot, *, passive: Sensors) -> None:
    bot._terminal_entry_x = float(passive.x)
    bot._terminal_entry_y = float(passive.y)


def finalize_terminal_entry_metrics(
    bot,
    *,
    passive: Sensors,
    alt: float,
    projected_dx: float,
) -> None:
    bot._terminal_entry_done = True
    bot._terminal_entry_time = bot._elapsed_time_s
    bot._terminal_entry_altitude = float(alt)
    bot._terminal_entry_projected_dx = float(projected_dx)
    _capture_terminal_entry_state(bot, passive=passive)


def finalize_boost_cutoff_metrics(
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

    fuel_start = bot._boost_phase_fuel_start
    fuel_used = None
    if fuel_start is not None:
        fuel_used = max(0.0, float(fuel_start) - float(passive.fuel))
    burn_duration_s = max(0.0, float(bot._elapsed_time_s))
    burn_avg_thrust_level = None
    if burn_duration_s > 1e-6:
        burn_avg_thrust_level = bot._boost_phase_thrust_integral / burn_duration_s

    bot._boost_cutoff_done = True
    bot._boost_cutoff_time = bot._elapsed_time_s
    bot._boost_cutoff_altitude = alt
    bot._boost_cutoff_projected_dx = float(projection.projected_dx)
    bot._boost_cutoff_projected_apex_y = apex_y
    bot._boost_cutoff_projected_apex_over_target = apex_over_target
    bot._boost_cutoff_has_target_y_solution = has_target_y_solution
    bot._boost_cutoff_projected_impact_dx = projected_impact_dx
    bot._boost_cutoff_projected_impact_angle_deg = impact_angle_deg
    bot._boost_cutoff_burn_duration_s = burn_duration_s
    bot._boost_cutoff_burn_fuel_used = fuel_used
    bot._boost_cutoff_burn_avg_thrust_level = burn_avg_thrust_level
    bot._boost_cutoff_spawn_primed = False
    _capture_boost_cutoff_state(bot, passive=passive)


def apply_boost_cutoff_metrics(
    bot,
    *,
    boost_cutoff: BoostCutoffMetrics,
) -> None:
    bot._boost_cutoff_done = True
    bot._boost_cutoff_time = boost_cutoff.time_s
    bot._boost_cutoff_altitude = boost_cutoff.altitude
    bot._boost_cutoff_x = boost_cutoff.x
    bot._boost_cutoff_y = boost_cutoff.y
    bot._boost_cutoff_vx = boost_cutoff.vx
    bot._boost_cutoff_vy_up = boost_cutoff.vy_up
    bot._boost_cutoff_projected_apex_y = boost_cutoff.projected_apex_y
    bot._boost_cutoff_projected_apex_over_target = boost_cutoff.projected_apex_over_target
    bot._boost_cutoff_has_target_y_solution = boost_cutoff.has_target_y_solution
    bot._boost_cutoff_projected_dx = (
        boost_cutoff.projected_dx
        if boost_cutoff.projected_dx is not None
        else boost_cutoff.projected_impact_dx
    )
    bot._boost_cutoff_projected_impact_dx = boost_cutoff.projected_impact_dx
    bot._boost_cutoff_projected_impact_angle_deg = boost_cutoff.projected_impact_angle_deg
    bot._boost_cutoff_burn_duration_s = boost_cutoff.burn_duration_s
    bot._boost_cutoff_burn_fuel_used = boost_cutoff.burn_fuel_used
    bot._boost_cutoff_burn_avg_thrust_level = boost_cutoff.burn_avg_thrust_level


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
        bot._debug_boost
        and bot._active_phase == "boost"
        and (bot._elapsed_time_s - bot._debug_boost_last_print_t) >= 0.25
    ):
        bot._debug_boost_last_print_t = bot._elapsed_time_s
        bot._debug_boost_print(
            "boost_track "
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
        (not bot._boost_cutoff_done)
        and (not bot._terminal_entry_done)
        and (not bot._shape_window_started)
        and has_target_y_solution
        and in_touchdown_corridor
        and in_touchdown_projected_corridor
        and abs(float(passive.vx)) <= float(cfg.touchdown_phase_speed)
        and t_fall <= float(cfg.touchdown_phase_time_to_go)
    )
    next_stage = "boost"
    if (
        alt <= cfg.touchdown_phase_altitude
        and speed <= cfg.touchdown_phase_speed
        and in_touchdown_corridor
    ):
        next_stage = "touchdown"
    elif direct_touchdown_terminal:
        next_stage = "touchdown"
    elif bot._terminal_entry_done:
        next_stage = "terminal"
    elif bot._boost_cutoff_done:
        if bot._boost_cutoff_spawn_primed:
            next_stage = "coast"
        else:
            next_stage = "coast"
    bot._stage_tracking_next = next_stage

    if (
        bot._debug_boost
        and bot._boost_cutoff_done
        and bot._debug_boost_post_end_time is not None
        and bot._elapsed_time_s <= bot._debug_boost_post_end_time
        and (bot._elapsed_time_s - bot._debug_boost_last_print_t) >= 0.25
    ):
        bot._debug_boost_last_print_t = bot._elapsed_time_s
        bot._debug_boost_print(
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
    if bot._boost_cutoff_done:
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
    bot._uphill_transfer = float(dy) >= bot._cfg.uphill_boost_dy_min
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
        bot._terminal_entry_done or bot._active_phase in ("terminal", "touchdown")
    ) and not bot._shape_window_done:
        bot._shape_window_done = True
        bot._shape_window_end_time = bot._elapsed_time_s
