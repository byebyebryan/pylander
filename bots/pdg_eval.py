from __future__ import annotations

from core.bot import BotEvalDecision
from core.eval_goals import EVAL_GOAL_BOOST_CUTOFF

from bots.common_math import clamp
from bots.pdg_boost import boost_dx_limit


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
    state = bot.state
    state._elapsed_time_s = 0.0
    state._active_phase = "boost"
    state._active_stage = None
    state._boost_cutoff_done = False
    state._boost_cutoff_time = None
    state._boost_cutoff_altitude = None
    state._boost_cutoff_projected_dx = None
    state._boost_cutoff_projected_apex_y = None
    state._boost_cutoff_projected_apex_over_target = None
    state._boost_cutoff_has_target_y_solution = None
    state._boost_cutoff_projected_impact_dx = None
    state._boost_cutoff_projected_impact_angle_deg = None
    state._boost_cutoff_burn_duration_s = None
    state._boost_cutoff_burn_fuel_used = None
    state._boost_cutoff_burn_avg_thrust_level = None
    state._boost_cutoff_x = None
    state._boost_cutoff_y = None
    state._boost_cutoff_vx = None
    state._boost_cutoff_vy_up = None
    state._boost_cutoff_spawn_primed = False
    state._boost_phase_thrust_integral = 0.0
    state._boost_phase_fuel_start = None
    state._boost_burn_started = False
    state._boost_burn_start_time = None
    state._boost_burn_idle_since = None
    state._boost_cut_latched = False
    state._boost_cut_hold_angle = None
    state._boost_settle_start_time = None
    state._boost_quality_verdict = None
    state._boost_cutoff_quality_pass = None
    state._boost_cutoff_quality_verdict = None
    state._terminal_entry_done = False
    state._terminal_entry_time = None
    state._terminal_entry_altitude = None
    state._terminal_entry_projected_dx = None
    state._terminal_entry_x = None
    state._terminal_entry_y = None
    state._terminal_gate_ready_ticks = 0
    state._terminal_probe_count = 0
    state._terminal_probe_ms_sum = 0.0
    state._terminal_probe_ms_samples = []
    state._terminal_gate_mode = None
    state._terminal_gate_horizon_s = None
    state._terminal_gate_terminal_speed = None
    state._terminal_gate_peak_accel_ratio = None
    state._terminal_gate_od_excess_s = None
    state._terminal_gate_latest_safe_margin_s = None
    state._terminal_gate_required_accel_ratio = None
    state._last_projection_dx = None
    state._last_projection_t_fall = None
    state._last_projection_has_target_y = False
    state._last_target_y = 0.0
    state._peak_alt_over_target = 0.0
    state._lateral_overshoot = 0.0
    state._hover_time = 0.0
    state._clearance_margin = 0.0
    state._clearance_scale = 0.0
    state._clearance_active = False
    state._uphill_transfer = False
    bot._reset_shape_window_state()
    state._debug_boost_last_print_t = -1.0
    state._debug_boost_post_end_time = None
    if clear_last_flight_snapshot:
        bot._last_flight_snapshot = None


def build_evaluation_snapshot(bot) -> dict[str, float | int | bool | str | None]:
    state = bot.state
    solve_ms_mean = 0.0
    if bot._solve_count > 0:
        solve_ms_mean = bot._solve_ms_sum / max(1, bot._solve_count)
    probe_ms_mean = 0.0
    if state._terminal_probe_count > 0:
        probe_ms_mean = state._terminal_probe_ms_sum / max(
            1, state._terminal_probe_count
        )
    shape_curve_rmse = bot._shape_curve_rmse()
    shape_projected_dx_abs_mean = bot._shape_projected_dx_abs_mean()
    shape_shortfall_ratio = bot._shape_shortfall_ratio()
    shape_apex_error = abs(
        state._shape_apex_actual_over_target - state._shape_apex_target_over_target
    )
    return {
        "terminal_entry_done": state._terminal_entry_done,
        "terminal_entry_time": state._terminal_entry_time,
        "terminal_entry_altitude": state._terminal_entry_altitude,
        "terminal_entry_projected_dx": state._terminal_entry_projected_dx,
        "solve_count": bot._solve_count,
        "solve_ms_mean": solve_ms_mean,
        "solve_ms_p90": percentile(bot._solve_ms_samples, 0.9),
        "terminal_probe_count": state._terminal_probe_count,
        "terminal_probe_ms_mean": probe_ms_mean,
        "terminal_probe_ms_p90": percentile(state._terminal_probe_ms_samples, 0.9),
        "terminal_gate_mode": state._terminal_gate_mode,
        "terminal_gate_horizon_s": state._terminal_gate_horizon_s,
        "terminal_gate_terminal_speed": state._terminal_gate_terminal_speed,
        "terminal_gate_peak_accel_ratio": state._terminal_gate_peak_accel_ratio,
        "terminal_gate_od_excess_s": state._terminal_gate_od_excess_s,
        "terminal_gate_latest_safe_margin_s": state._terminal_gate_latest_safe_margin_s,
        "terminal_gate_required_accel_ratio": state._terminal_gate_required_accel_ratio,
        "fallback_frames": bot._fallback_frames,
        "boost_quality_verdict": state._boost_cutoff_quality_verdict
        or state._boost_quality_verdict,
        "shape_apex_error": shape_apex_error,
        "shape_curve_rmse": shape_curve_rmse,
        "shape_projected_dx_abs_mean": shape_projected_dx_abs_mean,
        "shape_projected_dx_abs_max": state._shape_projected_dx_abs_max,
        "shape_shortfall_ratio": shape_shortfall_ratio,
    }


def resolve_evaluation_snapshot(bot) -> dict[str, float | int | bool | str | None]:
    state = bot.state
    snapshot = build_evaluation_snapshot(bot)
    has_live_progress = (
        int(snapshot.get("solve_count") or 0) > 0
        or int(snapshot.get("terminal_probe_count") or 0) > 0
        or bool(snapshot.get("terminal_entry_done"))
        or snapshot.get("shape_curve_rmse") is not None
        or state._shape_projected_dx_count > 0
    )
    if has_live_progress or bot._last_flight_snapshot is None:
        return snapshot
    return dict(bot._last_flight_snapshot)


def build_evaluation_decision(bot) -> BotEvalDecision | None:
    state = bot.state
    if bot.get_eval_goal() != EVAL_GOAL_BOOST_CUTOFF:
        return None
    if not state._boost_cutoff_done:
        return None
    dx_limit = boost_dx_limit(bot)
    has_target_y = bool(state._boost_cutoff_has_target_y_solution)
    projected_dx = state._boost_cutoff_projected_dx
    impact_angle = state._boost_cutoff_projected_impact_angle_deg
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
    state._boost_cutoff_quality_pass = success
    state._boost_cutoff_quality_verdict = verdict
    metrics: dict[str, str | bool] = {"boost_quality_verdict": verdict}
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
