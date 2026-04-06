from __future__ import annotations

import math

from bots.common_ballistics import BallisticProjection, ballistic_apex_from_state
from bots.common_math import _GRAVITY_MAG
from bots.pdg_boost import projected_impact_angle_deg as _projected_impact_angle_deg
from core.bot import Sensors, BoostCutoffMetrics


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
    state = bot.state
    state._boost_cutoff_x = float(passive.x)
    state._boost_cutoff_y = float(passive.y)
    state._boost_cutoff_vx = float(passive.vx)
    state._boost_cutoff_vy_up = float(passive.vy_up)


def _capture_terminal_entry_state(bot, *, passive: Sensors) -> None:
    state = bot.state
    state._terminal_entry_x = float(passive.x)
    state._terminal_entry_y = float(passive.y)


def finalize_terminal_entry_metrics(
    bot,
    *,
    passive: Sensors,
    alt: float,
    projected_dx: float,
    dx: float | None = None,
) -> None:
    state = bot.state
    runtime_state = bot.state
    state._terminal_entry_done = True
    state._terminal_entry_time = runtime_state._elapsed_time_s
    state._terminal_entry_altitude = float(alt)
    state._terminal_entry_projected_dx = float(projected_dx)
    _capture_terminal_entry_state(bot, passive=passive)
    state._terminal_post_entry_apex_gain = 0.0
    state._terminal_post_entry_time_to_apex = 0.0
    state._terminal_post_entry_peak_abs_dx = abs(float(dx)) if dx is not None else None


def finalize_boost_cutoff_metrics(
    bot,
    *,
    passive: Sensors,
    alt: float,
    projection: BallisticProjection,
) -> None:
    state = bot.state
    runtime_state = bot.state
    target_y = float(runtime_state._last_target_y)
    apex_y, apex_over_target = _projected_apex(
        y=float(passive.y),
        vy_up=float(passive.vy_up),
        target_y=target_y,
    )
    has_target_y_solution = bool(getattr(projection, "has_target_y_solution", True))
    projected_impact_dx = (
        float(projection.projected_dx) if has_target_y_solution else None
    )
    impact_angle_deg = None
    if has_target_y_solution:
        impact_angle_deg = _projected_impact_angle_deg(
            vx=float(passive.vx),
            vy_up=float(passive.vy_up),
            t_fall=float(projection.t_fall),
        )

    fuel_start = state._boost_phase_fuel_start
    fuel_used = None
    if fuel_start is not None:
        fuel_used = max(0.0, float(fuel_start) - float(passive.fuel))
    burn_duration_s = max(0.0, float(runtime_state._elapsed_time_s))
    burn_avg_thrust_level = None
    if burn_duration_s > 1e-6:
        burn_avg_thrust_level = state._boost_phase_thrust_integral / burn_duration_s

    state._boost_cutoff_done = True
    state._boost_cutoff_time = runtime_state._elapsed_time_s
    state._boost_cutoff_altitude = alt
    state._boost_cutoff_projected_dx = float(projection.projected_dx)
    state._boost_cutoff_projected_apex_y = apex_y
    state._boost_cutoff_projected_apex_over_target = apex_over_target
    state._boost_cutoff_has_target_y_solution = has_target_y_solution
    state._boost_cutoff_projected_impact_dx = projected_impact_dx
    state._boost_cutoff_projected_impact_angle_deg = impact_angle_deg
    state._boost_cutoff_burn_duration_s = burn_duration_s
    state._boost_cutoff_burn_fuel_used = fuel_used
    state._boost_cutoff_burn_avg_thrust_level = burn_avg_thrust_level
    state._boost_cutoff_spawn_primed = False
    _capture_boost_cutoff_state(bot, passive=passive)


def apply_boost_cutoff_metrics(
    bot,
    *,
    boost_cutoff: BoostCutoffMetrics,
) -> None:
    state = bot.state
    state._boost_cutoff_done = True
    state._boost_cutoff_time = boost_cutoff.time_s
    state._boost_cutoff_altitude = boost_cutoff.altitude
    state._boost_cutoff_x = boost_cutoff.x
    state._boost_cutoff_y = boost_cutoff.y
    state._boost_cutoff_vx = boost_cutoff.vx
    state._boost_cutoff_vy_up = boost_cutoff.vy_up
    state._boost_cutoff_projected_apex_y = boost_cutoff.projected_apex_y
    state._boost_cutoff_projected_apex_over_target = (
        boost_cutoff.projected_apex_over_target
    )
    state._boost_cutoff_has_target_y_solution = boost_cutoff.has_target_y_solution
    state._boost_cutoff_projected_dx = (
        boost_cutoff.projected_dx
        if boost_cutoff.projected_dx is not None
        else boost_cutoff.projected_impact_dx
    )
    state._boost_cutoff_projected_impact_dx = boost_cutoff.projected_impact_dx
    state._boost_cutoff_projected_impact_angle_deg = (
        boost_cutoff.projected_impact_angle_deg
    )
    state._boost_cutoff_burn_duration_s = boost_cutoff.burn_duration_s
    state._boost_cutoff_burn_fuel_used = boost_cutoff.burn_fuel_used
    state._boost_cutoff_burn_avg_thrust_level = boost_cutoff.burn_avg_thrust_level


def refresh_stage_tracking(
    bot,
    *,
    passive: Sensors,
    dx: float,
    dy: float,
    alt: float,
    projection: BallisticProjection,
) -> str:
    state = bot.state
    terminal_state = bot.state
    boost_state = bot.state
    runtime_state = bot.state
    cfg = bot._cfg
    projected_dx = float(projection.projected_dx)
    t_fall = max(0.0, float(projection.t_fall))
    has_target_y_solution = bool(getattr(projection, "has_target_y_solution", True))
    runtime_state._last_projection_dx = projected_dx
    runtime_state._last_projection_t_fall = t_fall
    runtime_state._last_projection_has_target_y = has_target_y_solution

    thrust_level = float(passive.thrust_level)
    if (
        bot._debug_boost
        and runtime_state._active_phase == "boost"
        and (runtime_state._elapsed_time_s - runtime_state._debug_boost_last_print_t)
        >= 0.25
    ):
        runtime_state._debug_boost_last_print_t = runtime_state._elapsed_time_s
        bot._debug_boost_print(
            "boost_track "
            f"t={runtime_state._elapsed_time_s:6.2f} "
            f"ph={runtime_state._active_phase:8s} "
            f"dx={dx:8.2f} proj_dx={projected_dx:8.2f} "
            f"has_target={int(has_target_y_solution)} "
            f"thrust={thrust_level:5.2f}"
        )

    speed = math.hypot(float(passive.vx), float(passive.vy_up))
    touchdown_dx_limit = max(12.0, cfg.touchdown_phase_dx_ratio * bot._last_target_half)
    in_touchdown_corridor = abs(float(dx)) <= touchdown_dx_limit
    in_touchdown_projected_corridor = abs(projected_dx) <= touchdown_dx_limit
    direct_touchdown_terminal = (
        (not boost_state._boost_cutoff_done)
        and (not terminal_state._terminal_entry_done)
        and (not state._shape_window_started)
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
    elif terminal_state._terminal_entry_done:
        next_stage = "terminal"
    elif boost_state._boost_cutoff_done:
        if boost_state._boost_cutoff_spawn_primed:
            next_stage = "coast"
        else:
            next_stage = "coast"
    bot._stage_tracking_next = next_stage

    if (
        bot._debug_boost
        and boost_state._boost_cutoff_done
        and runtime_state._debug_boost_post_end_time is not None
        and runtime_state._elapsed_time_s <= runtime_state._debug_boost_post_end_time
        and (runtime_state._elapsed_time_s - runtime_state._debug_boost_last_print_t)
        >= 0.25
    ):
        runtime_state._debug_boost_last_print_t = runtime_state._elapsed_time_s
        bot._debug_boost_print(
            "post_gate "
            f"t={runtime_state._elapsed_time_s:6.2f} "
            f"ph={next_stage:8s} "
            f"dx={dx:8.2f} proj_dx={projected_dx:8.2f} "
            f"thrust={float(passive.thrust_level):5.2f}"
        )
    return next_stage


def update_terminal_post_entry_metrics(
    bot,
    *,
    passive: Sensors,
    dx: float,
) -> None:
    state = bot.state
    if not state._terminal_entry_done:
        return

    peak_abs_dx = abs(float(dx))
    current_peak_abs_dx = state._terminal_post_entry_peak_abs_dx
    if current_peak_abs_dx is None or peak_abs_dx > float(current_peak_abs_dx):
        state._terminal_post_entry_peak_abs_dx = peak_abs_dx

    entry_y = state._terminal_entry_y
    entry_time = state._terminal_entry_time
    if entry_y is None or entry_time is None:
        return

    apex_gain = max(0.0, float(passive.y) - float(entry_y))
    best_apex_gain = state._terminal_post_entry_apex_gain
    if best_apex_gain is None or apex_gain > float(best_apex_gain):
        state._terminal_post_entry_apex_gain = apex_gain
        state._terminal_post_entry_time_to_apex = max(
            0.0, float(state._elapsed_time_s) - float(entry_time)
        )


def maybe_start_shape_window(
    bot,
    *,
    passive: Sensors,
    dx: float,
    dy: float,
) -> None:
    state = bot.state
    boost_state = bot.state
    if state._shape_window_started or state._shape_window_done:
        return
    if boost_state._boost_cutoff_done:
        return
    if bot.state._active_phase == "takeoff":
        return
    if abs(float(dx)) <= 1e-3:
        return
    state._shape_window_started = True
    state._shape_window_start_time = bot.state._elapsed_time_s
    state._shape_start_x = float(passive.x)
    state._shape_start_y = float(passive.y)
    state._shape_target_x = float(passive.x) + float(dx)
    state._shape_target_y = float(passive.y) + float(dy)
    state._uphill_transfer = float(dy) >= bot._cfg.uphill_boost_dy_min
    state._shape_anchor_dx_abs = abs(float(dx))
    state._shape_apex_target_over_target = bot._shape_apex_target(
        state._shape_anchor_dx_abs
    )
    state._shape_apex_actual_over_target = max(
        0.0, float(passive.y) - state._shape_target_y
    )
    state._shape_curve_sq_err_sum = 0.0
    state._shape_curve_count = 0
    state._shape_projected_dx_abs_sum = 0.0
    state._shape_projected_dx_abs_max = 0.0
    state._shape_projected_dx_count = 0
    state._shape_shortfall_count = 0
    state._shape_shortfall_sample_count = 0


def update_shape_window_metrics(
    bot,
    *,
    passive: Sensors,
    dx: float,
    projection: BallisticProjection,
) -> None:
    state = bot.state
    if (not state._shape_window_started) or state._shape_window_done:
        return

    projected_abs = abs(float(projection.projected_dx))
    state._shape_projected_dx_abs_sum += projected_abs
    state._shape_projected_dx_count += 1
    state._shape_projected_dx_abs_max = max(
        state._shape_projected_dx_abs_max, projected_abs
    )

    dx_now = float(dx)
    if abs(dx_now) > 1e-3:
        state._shape_shortfall_sample_count += 1
        shortfall_metric = float(projection.projected_dx) * math.copysign(1.0, dx_now)
        if shortfall_metric > 0.0:
            state._shape_shortfall_count += 1

    over_target = max(0.0, float(passive.y) - state._shape_target_y)
    state._shape_apex_actual_over_target = max(
        state._shape_apex_actual_over_target, over_target
    )
    y_ref = bot._shape_reference_y_at_x(float(passive.x))
    y_err = float(passive.y) - y_ref
    state._shape_curve_sq_err_sum += y_err * y_err
    state._shape_curve_count += 1

    if (
        bot.state._terminal_entry_done
        or bot.state._active_phase in ("terminal", "touchdown")
    ) and not state._shape_window_done:
        state._shape_window_done = True
        state._shape_window_end_time = bot.state._elapsed_time_s
