from __future__ import annotations

from core.bot import BotEvalDecision
from core.eval_goals import EVAL_GOAL_BOOST_CUTOFF

from bots._bot_math import clamp
from bots.pdg.boost import boost_dx_limit


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    sorted_values = sorted(values)
    if len(sorted_values) == 1:
        return sorted_values[0]
    clamped = clamp(float(p), 0.0, 1.0)
    idx = (len(sorted_values) - 1) * clamped
    lo = int(idx)
    hi = min(lo + 1, len(sorted_values) - 1)
    if lo == hi:
        return sorted_values[lo]
    frac = idx - lo
    return (sorted_values[lo] * (1.0 - frac)) + (sorted_values[hi] * frac)


def reset_evaluation_state(
    bot,
    *,
    clear_last_flight_snapshot: bool = False,
) -> None:
    bot._elapsed_time_s = 0.0
    bot._active_phase = "boost"
    bot._active_stage = None
    bot._boost_cutoff_done = False
    bot._boost_cutoff_time = None
    bot._boost_cutoff_altitude = None
    bot._boost_cutoff_projected_dx = None
    bot._boost_cutoff_projected_apex_y = None
    bot._boost_cutoff_projected_apex_over_target = None
    bot._boost_cutoff_has_target_y_solution = None
    bot._boost_cutoff_projected_impact_dx = None
    bot._boost_cutoff_projected_impact_angle_deg = None
    bot._boost_cutoff_burn_duration_s = None
    bot._boost_cutoff_burn_fuel_used = None
    bot._boost_cutoff_burn_avg_thrust_level = None
    bot._boost_cutoff_x = None
    bot._boost_cutoff_y = None
    bot._boost_cutoff_vx = None
    bot._boost_cutoff_vy_up = None
    bot._boost_cutoff_spawn_primed = False
    bot._boost_phase_thrust_integral = 0.0
    bot._boost_phase_fuel_start = None
    bot._boost_burn_started = False
    bot._boost_burn_start_time = None
    bot._boost_burn_idle_since = None
    bot._boost_cut_latched = False
    bot._boost_cut_hold_angle = None
    bot._boost_settle_start_time = None
    bot._boost_quality_verdict = None
    bot._boost_cutoff_quality_pass = None
    bot._boost_cutoff_quality_verdict = None
    bot._terminal_entry_done = False
    bot._terminal_entry_time = None
    bot._terminal_entry_altitude = None
    bot._terminal_entry_projected_dx = None
    bot._terminal_entry_x = None
    bot._terminal_entry_y = None
    bot._terminal_gate_ready_ticks = 0
    bot._terminal_probe_count = 0
    bot._terminal_probe_ms_sum = 0.0
    bot._terminal_probe_ms_samples = []
    bot._terminal_gate_mode = None
    bot._terminal_gate_horizon_s = None
    bot._terminal_gate_terminal_speed = None
    bot._terminal_gate_peak_accel_ratio = None
    bot._terminal_gate_od_excess_s = None
    bot._terminal_gate_latest_safe_margin_s = None
    bot._terminal_gate_required_accel_ratio = None
    bot._last_projection_dx = None
    bot._last_projection_t_fall = None
    bot._last_projection_has_target_y = False
    bot._last_target_y = 0.0
    bot._peak_alt_over_target = 0.0
    bot._lateral_overshoot = 0.0
    bot._hover_time = 0.0
    bot._clearance_margin = 0.0
    bot._clearance_scale = 0.0
    bot._clearance_active = False
    bot._uphill_transfer = False
    bot._reset_shape_window_state()
    bot._debug_boost_last_print_t = -1.0
    bot._debug_boost_post_end_time = None
    if clear_last_flight_snapshot:
        bot._last_flight_snapshot = None


def build_evaluation_snapshot(bot) -> dict[str, float | int | bool | str | None]:
    solve_ms_mean = 0.0
    if bot._solve_count > 0:
        solve_ms_mean = bot._solve_ms_sum / max(1, bot._solve_count)
    probe_ms_mean = 0.0
    if bot._terminal_probe_count > 0:
        probe_ms_mean = bot._terminal_probe_ms_sum / max(1, bot._terminal_probe_count)
    shape_curve_rmse = bot._shape_curve_rmse()
    shape_projected_dx_abs_mean = bot._shape_projected_dx_abs_mean()
    shape_shortfall_ratio = bot._shape_shortfall_ratio()
    shape_apex_error = abs(
        bot._shape_apex_actual_over_target - bot._shape_apex_target_over_target
    )
    return {
        "terminal_entry_done": bot._terminal_entry_done,
        "terminal_entry_time": bot._terminal_entry_time,
        "terminal_entry_altitude": bot._terminal_entry_altitude,
        "terminal_entry_projected_dx": bot._terminal_entry_projected_dx,
        "solve_count": bot._solve_count,
        "solve_ms_mean": solve_ms_mean,
        "solve_ms_p90": percentile(bot._solve_ms_samples, 0.9),
        "terminal_probe_count": bot._terminal_probe_count,
        "terminal_probe_ms_mean": probe_ms_mean,
        "terminal_probe_ms_p90": percentile(bot._terminal_probe_ms_samples, 0.9),
        "terminal_gate_mode": bot._terminal_gate_mode,
        "terminal_gate_horizon_s": bot._terminal_gate_horizon_s,
        "terminal_gate_terminal_speed": bot._terminal_gate_terminal_speed,
        "terminal_gate_peak_accel_ratio": bot._terminal_gate_peak_accel_ratio,
        "terminal_gate_od_excess_s": bot._terminal_gate_od_excess_s,
        "terminal_gate_latest_safe_margin_s": bot._terminal_gate_latest_safe_margin_s,
        "terminal_gate_required_accel_ratio": bot._terminal_gate_required_accel_ratio,
        "fallback_frames": bot._fallback_frames,
        "boost_quality_verdict": bot._boost_cutoff_quality_verdict or bot._boost_quality_verdict,
        "shape_apex_error": shape_apex_error,
        "shape_curve_rmse": shape_curve_rmse,
        "shape_projected_dx_abs_mean": shape_projected_dx_abs_mean,
        "shape_projected_dx_abs_max": bot._shape_projected_dx_abs_max,
        "shape_shortfall_ratio": shape_shortfall_ratio,
    }


def resolve_evaluation_snapshot(bot) -> dict[str, float | int | bool | str | None]:
    snapshot = build_evaluation_snapshot(bot)
    has_live_progress = (
        int(snapshot.get("solve_count") or 0) > 0
        or int(snapshot.get("terminal_probe_count") or 0) > 0
        or bool(snapshot.get("terminal_entry_done"))
        or snapshot.get("shape_curve_rmse") is not None
        or bot._shape_projected_dx_count > 0
    )
    if has_live_progress or bot._last_flight_snapshot is None:
        return snapshot
    return dict(bot._last_flight_snapshot)


def build_evaluation_decision(bot) -> BotEvalDecision | None:
    if bot.get_eval_goal() != EVAL_GOAL_BOOST_CUTOFF:
        return None
    if not bot._boost_cutoff_done:
        return None
    dx_limit = boost_dx_limit(bot)
    has_target_y = bool(bot._boost_cutoff_has_target_y_solution)
    projected_dx = bot._boost_cutoff_projected_dx
    impact_angle = bot._boost_cutoff_projected_impact_angle_deg
    verdict = "pass"
    success = True
    if not has_target_y:
        verdict = "no_target_y_solution"
        success = False
    elif projected_dx is None or abs(float(projected_dx)) > dx_limit:
        verdict = "dx"
        success = False
    elif impact_angle is None:
        verdict = "angle"
        success = False
    elif float(impact_angle) < float(bot._cfg.boost_descent_angle_deg_min):
        verdict = "angle"
        success = False
    bot._boost_cutoff_quality_pass = success
    bot._boost_cutoff_quality_verdict = verdict
    metrics = {"boost_quality_verdict": verdict}
    if success:
        metrics["boost_quality_pass"] = True
        return BotEvalDecision(
            should_end=True,
            success=True,
            failure_mode="none",
            end_reason="goal_reached",
            metrics=metrics,
        )
    return BotEvalDecision(
        should_end=True,
        success=False,
        failure_mode="boost_quality_failed",
        end_reason="boost_quality_failed",
        metrics=metrics,
    )
