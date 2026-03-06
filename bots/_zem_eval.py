from __future__ import annotations

from core.bot import BotEvalDecision
from core.eval_goals import EVAL_GOAL_SETUP

from bots._bot_math import clamp


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
    bot._active_phase = "setup"
    bot._setup_gate_done = False
    bot._setup_gate_time = None
    bot._setup_gate_altitude = None
    bot._setup_gate_projected_dx = None
    bot._setup_gate_projected_apex_y = None
    bot._setup_gate_projected_apex_over_target = None
    bot._setup_burn_started = False
    bot._setup_burn_idle_since = None
    bot._terminal_gate_done = False
    bot._terminal_gate_time = None
    bot._terminal_gate_altitude = None
    bot._terminal_gate_projected_dx = None
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
    bot._debug_setup_last_print_t = -1.0
    bot._debug_setup_post_end_time = None
    if clear_last_flight_snapshot:
        bot._last_flight_snapshot = None


def build_evaluation_snapshot(bot) -> dict[str, float | int | bool | str | None]:
    solve_ms_mean = 0.0
    if bot._solve_count > 0:
        solve_ms_mean = bot._solve_ms_sum / max(1, bot._solve_count)
    shape_curve_rmse = bot._shape_curve_rmse()
    shape_projected_dx_abs_mean = bot._shape_projected_dx_abs_mean()
    shape_shortfall_ratio = bot._shape_shortfall_ratio()
    shape_apex_error = abs(
        bot._shape_apex_actual_over_target - bot._shape_apex_target_over_target
    )
    return {
        "kind": "zem_zev",
        "phase": bot._active_phase,
        "projected_dx": bot._last_projection_dx,
        "t_fall": bot._last_projection_t_fall,
        "projection_has_target_y_solution": bot._last_projection_has_target_y,
        "setup_gate_done": bot._setup_gate_done,
        "setup_gate_time": bot._setup_gate_time,
        "setup_gate_altitude": bot._setup_gate_altitude,
        "setup_gate_projected_dx": bot._setup_gate_projected_dx,
        "setup_gate_projected_apex_y": bot._setup_gate_projected_apex_y,
        "setup_gate_projected_apex_over_target": bot._setup_gate_projected_apex_over_target,
        "terminal_gate_done": bot._terminal_gate_done,
        "terminal_gate_time": bot._terminal_gate_time,
        "terminal_gate_altitude": bot._terminal_gate_altitude,
        "terminal_gate_projected_dx": bot._terminal_gate_projected_dx,
        "solve_count": bot._solve_count,
        "solve_ms_mean": solve_ms_mean,
        "solve_ms_p90": percentile(bot._solve_ms_samples, 0.9),
        "fallback_frames": bot._fallback_frames,
        "peak_alt_over_target": bot._peak_alt_over_target,
        "lateral_overshoot": bot._lateral_overshoot,
        "hover_time": bot._hover_time,
        "clearance_margin": bot._clearance_margin,
        "clearance_scale": bot._clearance_scale,
        "clearance_active": bot._clearance_active,
        "shape_window_started": bot._shape_window_started,
        "shape_window_done": bot._shape_window_done,
        "shape_window_start_time": bot._shape_window_start_time,
        "shape_window_end_time": bot._shape_window_end_time,
        "shape_apex_target_over_target": bot._shape_apex_target_over_target,
        "shape_apex_actual_over_target": bot._shape_apex_actual_over_target,
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
        or bool(snapshot.get("setup_gate_done"))
        or bool(snapshot.get("terminal_gate_done"))
        or bool(snapshot.get("shape_window_started"))
    )
    if has_live_progress or bot._last_flight_snapshot is None:
        return snapshot
    return dict(bot._last_flight_snapshot)


def build_evaluation_decision(bot) -> BotEvalDecision | None:
    if bot.get_eval_goal() != EVAL_GOAL_SETUP:
        return None
    if not bot._setup_gate_done:
        return None
    return BotEvalDecision(
        should_end=True,
        success=True,
        failure_mode="none",
        end_reason="goal_reached",
        metrics={
            "zem_goal_setup_done": True,
            "zem_goal_setup_time": bot._setup_gate_time,
            "zem_goal_setup_altitude": bot._setup_gate_altitude,
            "zem_goal_setup_projected_dx": bot._setup_gate_projected_dx,
        },
    )
