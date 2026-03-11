from __future__ import annotations

from typing import Any

from core.bot import Bot, BotEvalDecision, FlightPhaseSnapshot, SetupGateMetrics
from core.eval_goals import EVAL_GOAL_LANDING, EVAL_GOAL_SETUP

_SETUP_GATE_RESULT_TO_ATTR: tuple[tuple[str, str], ...] = (
    ("setup_gate_time", "time_s"),
    ("setup_gate_altitude", "altitude"),
    ("setup_gate_projected_apex_y", "projected_apex_y"),
    ("setup_gate_projected_apex_over_target", "projected_apex_over_target"),
    ("setup_gate_has_target_y_solution", "has_target_y_solution"),
    ("setup_gate_projected_dx", "projected_impact_dx"),
    ("setup_gate_projected_impact_angle_deg", "projected_impact_angle_deg"),
    ("setup_gate_burn_duration_s", "burn_duration_s"),
    ("setup_gate_burn_fuel_used", "burn_fuel_used"),
    ("setup_gate_burn_avg_thrust_level", "burn_avg_thrust_level"),
)

_SETUP_GATE_TO_SETUP_GOAL_FIELDS: tuple[tuple[str, str], ...] = (
    ("setup_goal_time", "setup_gate_time"),
    ("setup_goal_altitude", "setup_gate_altitude"),
    ("setup_goal_projected_apex_y", "setup_gate_projected_apex_y"),
    ("setup_goal_projected_apex_over_target", "setup_gate_projected_apex_over_target"),
    ("setup_goal_has_target_y_solution", "setup_gate_has_target_y_solution"),
    ("setup_goal_projected_dx", "setup_gate_projected_dx"),
    ("setup_goal_projected_impact_angle_deg", "setup_gate_projected_impact_angle_deg"),
    ("setup_goal_fuel_consumed", "setup_gate_burn_fuel_used"),
    ("setup_goal_burn_avg_thrust_level", "setup_gate_burn_avg_thrust_level"),
)


def _safe_bot_telemetry(bot: Any) -> dict[str, Any]:
    getter = getattr(bot, "get_bot_telemetry", None)
    if not callable(getter):
        return {}
    try:
        snapshot = getter()
    except Exception:
        return {}
    return dict(snapshot) if isinstance(snapshot, dict) else {}


def _bot_metric_prefix(bot: Bot) -> str:
    raw_name = getattr(bot, "_bot_name", None)
    if not isinstance(raw_name, str) or not raw_name.strip():
        raw_name = type(bot).__name__
    token = str(raw_name).strip().lower().replace("-", "_").replace(" ", "_")
    return f"bot_{token}_"


def _safe_phase_snapshot(bot: Any) -> FlightPhaseSnapshot | None:
    getter = getattr(bot, "get_flight_phase_snapshot", None)
    if not callable(getter):
        return None
    try:
        snapshot = getter()
    except Exception:
        return None
    return snapshot if isinstance(snapshot, FlightPhaseSnapshot) else None


def _merge_setup_gate_snapshot_into_result(
    *,
    result: dict[str, Any],
    phase_snapshot: FlightPhaseSnapshot,
) -> None:
    has_setup_gate = "setup_gate" in phase_snapshot.milestones or phase_snapshot.setup_gate is not None
    if not has_setup_gate:
        return
    result.setdefault("setup_gate_done", True)
    setup_gate = phase_snapshot.setup_gate
    if not isinstance(setup_gate, SetupGateMetrics):
        return
    for result_key, attr_name in _SETUP_GATE_RESULT_TO_ATTR:
        result.setdefault(result_key, getattr(setup_gate, attr_name))


def _copy_setup_gate_result_to_setup_goal(result: dict[str, Any]) -> None:
    if not bool(result.get("setup_gate_done")):
        return
    result.setdefault("setup_goal_done", True)
    for setup_goal_key, setup_gate_key in _SETUP_GATE_TO_SETUP_GOAL_FIELDS:
        result.setdefault(setup_goal_key, result.get(setup_gate_key))


def merge_bot_snapshots_into_result(
    *,
    actor_bots: dict[str, Bot],
    result: dict[str, Any],
) -> None:
    for bot in actor_bots.values():
        phase_snapshot = _safe_phase_snapshot(bot)
        if phase_snapshot is not None:
            _merge_setup_gate_snapshot_into_result(
                result=result,
                phase_snapshot=phase_snapshot,
            )
        bot_prefix = _bot_metric_prefix(bot)
        for key, value in _safe_bot_telemetry(bot).items():
            if not isinstance(key, str):
                continue
            out_key = key if key.startswith("bot_") else f"{bot_prefix}{key}"
            result.setdefault(out_key, value)


def resolve_headless_bot_eval_decision(
    *,
    headless: bool,
    bot: Bot | None,
) -> BotEvalDecision | None:
    if not headless or bot is None:
        return None
    getter = getattr(bot, "get_evaluation_decision", None)
    if not callable(getter):
        return None
    try:
        decision = getter()
    except Exception:
        return None
    if isinstance(decision, BotEvalDecision):
        return decision
    return None


def apply_bot_eval_to_result(
    *,
    result: dict[str, Any],
    eval_goal: str,
    decision: BotEvalDecision | None,
) -> None:
    result["eval_goal"] = eval_goal
    result["eval_early_end"] = bool(decision.should_end) if decision else False
    if decision is not None:
        if decision.end_reason:
            result["eval_end_reason"] = str(decision.end_reason)
        for key, value in (decision.metrics or {}).items():
            if not isinstance(key, str):
                continue
            result[str(key)] = value
    if eval_goal == EVAL_GOAL_SETUP and bool(result.get("setup_gate_done")):
        _copy_setup_gate_result_to_setup_goal(result)

    if eval_goal != EVAL_GOAL_LANDING:
        if decision is not None and decision.success is True:
            result["success"] = True
            result["failure_mode"] = "none"
        else:
            result["success"] = False
            if decision is not None and decision.failure_mode is not None:
                result["failure_mode"] = str(decision.failure_mode)
            else:
                result["failure_mode"] = "goal_not_reached"
            result.setdefault("eval_end_reason", "goal_not_reached")
        return

    if decision is None:
        return
    if decision.success is not None:
        result["success"] = bool(decision.success)
    if decision.failure_mode is not None:
        result["failure_mode"] = str(decision.failure_mode)
