from __future__ import annotations

import math

from bots._ballistics import BallisticProjection
from core.bot import Sensors
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


def _capture_terminal_gate_state(bot, *, passive: Sensors) -> None:
    bot._terminal_gate_x = float(passive.x)
    bot._terminal_gate_y = float(passive.y)


def _projected_impact_angle_deg(*, vx: float, vy_up: float, t_fall: float) -> float:
    vy_down = abs(float(vy_up) - (_GRAVITY_MAG * max(0.0, float(t_fall))))
    vx_abs = abs(float(vx))
    return math.degrees(math.atan2(vy_down, vx_abs))


def _finalize_setup_gate_metrics(
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
    projected_impact_angle_deg = None
    if has_target_y_solution:
        projected_impact_angle_deg = _projected_impact_angle_deg(
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
    bot._setup_gate_projected_impact_angle_deg = projected_impact_angle_deg
    bot._setup_gate_burn_duration_s = burn_duration_s
    bot._setup_gate_burn_fuel_used = fuel_used
    bot._setup_gate_burn_avg_thrust_level = burn_avg_thrust_level
    _capture_setup_gate_state(bot, passive=passive)


def update_phase_tracking(
    bot,
    *,
    passive: Sensors,
    dx: float,
    dy: float,
    alt: float,
    projection: BallisticProjection,
) -> None:
    cfg = bot._cfg
    projected_dx = float(projection.projected_dx)
    t_fall = max(0.0, float(projection.t_fall))
    has_target_y_solution = bool(getattr(projection, "has_target_y_solution", True))
    bot._last_projection_dx = projected_dx
    bot._last_projection_t_fall = t_fall
    bot._last_projection_has_target_y = has_target_y_solution

    track_vx = dx / max(0.75, t_fall)
    setup_dx_limit = max(
        cfg.setup_gate_projected_dx_abs,
        cfg.setup_gate_projected_dx_target_ratio * bot._last_target_half,
    )
    setup_vx_limit = max(
        cfg.setup_gate_vx_track_abs,
        cfg.setup_gate_vx_track_ratio * abs(track_vx),
    )
    shortfall_guard = max(
        cfg.setup_gate_shortfall_abs,
        cfg.setup_gate_shortfall_ratio * bot._last_target_half,
    )
    shortfall_metric = (
        projected_dx * math.copysign(1.0, float(dx)) if abs(float(dx)) > 1e-3 else 0.0
    )
    not_falling_short = shortfall_metric <= shortfall_guard
    not_overshooting_setup = shortfall_metric >= -shortfall_guard
    thrust_level = float(passive.thrust_level)
    setup_ready_diag = (
        abs(projected_dx) <= setup_dx_limit
        and abs(float(passive.vx) - track_vx) <= setup_vx_limit
        and float(passive.vy_up) <= cfg.setup_gate_vy_up_max
        and not_falling_short
        and not_overshooting_setup
    )
    if (not bot._setup_gate_done) and (not bot._terminal_gate_done):
        if (not bot._setup_burn_started) and (thrust_level >= cfg.setup_gate_burn_start_thrust):
            bot._setup_burn_started = True
            bot._setup_burn_idle_since = None
            bot._debug_setup_print(
                "burn_start "
                f"t={bot._elapsed_time_s:6.2f} "
                f"dx={dx:8.2f} proj_dx={projected_dx:8.2f} "
                f"thrust={thrust_level:5.2f}"
            )
        if bot._setup_burn_started:
            if thrust_level <= cfg.setup_gate_idle_thrust_max:
                if bot._setup_burn_idle_since is None:
                    bot._setup_burn_idle_since = bot._elapsed_time_s
                idle_elapsed = bot._elapsed_time_s - bot._setup_burn_idle_since
                if idle_elapsed >= cfg.setup_gate_burn_end_settle_s:
                    _finalize_setup_gate_metrics(
                        bot,
                        passive=passive,
                        alt=alt,
                        projection=projection,
                    )
                    bot._debug_setup_post_end_time = bot._elapsed_time_s + 4.0
                    bot._debug_setup_print(
                        "gate_latch_burn_end "
                        f"t={bot._elapsed_time_s:6.2f} "
                        f"dx={dx:8.2f} proj_dx={projected_dx:8.2f} "
                        f"proj_apex_over_target={bot._setup_gate_projected_apex_over_target:8.2f} "
                        f"signed={shortfall_metric:8.2f} "
                        f"thrust={thrust_level:5.2f}"
                    )
            else:
                bot._setup_burn_idle_since = None
            if (
                bot._debug_setup
                and (bot._elapsed_time_s - bot._debug_setup_last_print_t) >= 0.25
            ):
                idle_elapsed = 0.0
                if bot._setup_burn_idle_since is not None:
                    idle_elapsed = bot._elapsed_time_s - bot._setup_burn_idle_since
                bot._debug_setup_last_print_t = bot._elapsed_time_s
                bot._debug_setup_print(
                    "setup_track "
                    f"t={bot._elapsed_time_s:6.2f} "
                    f"ph={bot._active_phase:8s} "
                    f"dx={dx:8.2f} proj_dx={projected_dx:8.2f} "
                    f"signed={shortfall_metric:8.2f} "
                    f"thrust={thrust_level:5.2f} "
                    f"ready={int(setup_ready_diag)} "
                    f"idle_elapsed={idle_elapsed:5.2f}"
                )

    coast_dx_limit = max(
        cfg.coast_hold_projected_dx_abs,
        cfg.coast_hold_projected_dx_target_ratio * bot._last_target_half,
    )
    coast_vx_limit = max(
        cfg.coast_hold_vx_track_abs,
        cfg.coast_hold_vx_track_ratio * abs(track_vx),
    )
    coast_overshoot_guard = max(
        cfg.coast_hold_overshoot_abs,
        cfg.coast_hold_overshoot_ratio * bot._last_target_half,
    )
    not_overshooting_far = shortfall_metric >= -coast_overshoot_guard
    coast_hold = (
        abs(projected_dx) <= coast_dx_limit
        and abs(float(passive.vx) - track_vx) <= coast_vx_limit
        and float(passive.vy_up) <= cfg.setup_gate_vy_up_max
        and not_overshooting_far
    )

    terminal_dx_limit = max(
        cfg.terminal_gate_projected_dx_abs,
        cfg.terminal_gate_projected_dx_target_ratio * bot._last_target_half,
    )
    terminal_entry_dx_limit = max(
        cfg.terminal_entry_projected_dx_abs,
        cfg.terminal_entry_projected_dx_target_ratio * bot._last_target_half,
    )
    terminal_ready = (
        t_fall <= cfg.terminal_gate_t_fall_s
        and abs(projected_dx) <= terminal_dx_limit
        and float(passive.vy_up) <= cfg.terminal_gate_vy_up_max
    )
    terminal_entry_ready = (
        t_fall <= cfg.terminal_gate_t_fall_s
        and alt <= cfg.terminal_entry_altitude_max
        and abs(projected_dx) <= terminal_entry_dx_limit
        and float(passive.vy_up) <= cfg.terminal_entry_vy_up_max
    )
    terminal_phase_ready = terminal_ready or terminal_entry_ready
    if terminal_ready and (not bot._terminal_gate_done):
        bot._terminal_gate_done = True
        bot._terminal_gate_time = bot._elapsed_time_s
        bot._terminal_gate_altitude = alt
        bot._terminal_gate_projected_dx = projected_dx
        _capture_terminal_gate_state(bot, passive=passive)
        if not bot._setup_gate_done:
            _finalize_setup_gate_metrics(
                bot,
                passive=passive,
                alt=alt,
                projection=projection,
            )
            bot._debug_setup_print(
                "gate_latch_terminal_fallback "
                f"t={bot._elapsed_time_s:6.2f} "
                f"dx={dx:8.2f} proj_dx={projected_dx:8.2f} "
                f"proj_apex_over_target={bot._setup_gate_projected_apex_over_target:8.2f} "
                f"signed={shortfall_metric:8.2f} "
                f"thrust={thrust_level:5.2f}"
            )

    speed = math.hypot(float(passive.vx), float(passive.vy_up))
    touchdown_dx_limit = max(12.0, cfg.touchdown_phase_dx_ratio * bot._last_target_half)
    in_touchdown_corridor = abs(float(dx)) <= touchdown_dx_limit
    if (
        alt <= cfg.touchdown_phase_altitude
        and speed <= cfg.touchdown_phase_speed
        and in_touchdown_corridor
    ):
        bot._active_phase = "touchdown"
    elif bot._terminal_gate_done or terminal_phase_ready:
        bot._active_phase = "terminal"
    elif bot._setup_gate_done:
        if bot._uphill_transfer:
            bot._active_phase = "setup"
        else:
            bot._active_phase = "coast"
    else:
        bot._active_phase = "setup"

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
            f"ph={bot._active_phase:8s} "
            f"dx={dx:8.2f} proj_dx={projected_dx:8.2f} "
            f"signed={shortfall_metric:8.2f} "
            f"thrust={float(passive.thrust_level):5.2f} "
            f"coast_hold={int(coast_hold)}"
        )


def maybe_start_shape_window(
    bot,
    *,
    passive: Sensors,
    dx: float,
    dy: float,
) -> None:
    if bot._shape_window_started or bot._shape_window_done:
        return
    if bot._launch_takeoff_active:
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
        bot._terminal_gate_done or bot._active_phase in ("terminal", "touchdown")
    ) and not bot._shape_window_done:
        bot._shape_window_done = True
        bot._shape_window_end_time = bot._elapsed_time_s
