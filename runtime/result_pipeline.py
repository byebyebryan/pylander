from __future__ import annotations

from typing import Any

from core.bot import Bot, BotEvalDecision
from core.eval_goals import EVAL_GOAL_LANDING


def _zem_snapshot(snapshot: Any) -> dict[str, Any] | None:
    if not isinstance(snapshot, dict):
        return None
    if str(snapshot.get("kind", "")).strip().lower() != "zem_zev":
        return None
    return snapshot


def merge_bot_snapshots_into_result(
    *,
    actor_bots: dict[str, Bot],
    result: dict[str, Any],
) -> None:
    for bot in actor_bots.values():
        get_snapshot = getattr(bot, "get_evaluation_snapshot", None)
        if not callable(get_snapshot):
            continue
        try:
            snapshot = _zem_snapshot(get_snapshot())
        except Exception:
            continue
        if snapshot is None:
            continue
        for key, value in snapshot.items():
            if key == "kind":
                continue
            out_key = key if str(key).startswith("zem_") else f"zem_{key}"
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

    if eval_goal != EVAL_GOAL_LANDING:
        if decision is not None and decision.success is True:
            result["success"] = True
            result["failure_mode"] = "none"
        else:
            result["success"] = False
            result["failure_mode"] = "goal_not_reached"
            result.setdefault("eval_end_reason", "goal_not_reached")
        return

    if decision is None:
        return
    if decision.success is not None:
        result["success"] = bool(decision.success)
    if decision.failure_mode is not None:
        result["failure_mode"] = str(decision.failure_mode)
