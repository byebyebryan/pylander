from __future__ import annotations

from typing import Any, Mapping

from game.core.eval_goals import EVAL_GOAL_LANDING, normalize_eval_goal


def render_selector(
    *,
    level_name: str,
    scenario_name: str | None,
    goal: str | None,
    seed_token: str | int | None,
) -> str:
    level = str(level_name or "").strip() or "unknown"
    scenario = str(scenario_name or "").strip() or None
    seed = str(seed_token).strip() if seed_token is not None else None
    goal_token = normalize_eval_goal(goal)
    parts: list[str] = [level]
    if scenario:
        parts.extend(token for token in scenario.split(":") if token)
    if goal_token != EVAL_GOAL_LANDING:
        parts.append(goal_token)
    if seed:
        parts.append(seed)
    return ":".join(parts)


def render_selector_group(
    *,
    level_name: str,
    scenario_name: str | None,
    goal: str | None,
) -> str:
    return render_selector(
        level_name=level_name,
        scenario_name=scenario_name,
        goal=goal,
        seed_token=None,
    )


def _record_level_name(record: Mapping[str, Any]) -> str:
    return str(record.get("level") or "").strip() or "unknown"


def _record_scenario_name(record: Mapping[str, Any]) -> str | None:
    scenario = str(record.get("scenario") or "").strip()
    if not scenario:
        return None
    level_name = _record_level_name(record)
    return None if scenario == level_name else scenario


def _record_seed_token(record: Mapping[str, Any]) -> str | None:
    seed = record.get("seed")
    if seed is None:
        return None
    try:
        return str(int(seed))
    except (TypeError, ValueError):
        return str(seed).strip() or None


def render_record_selector(
    record: Mapping[str, Any],
    *,
    include_seed: bool = True,
) -> str:
    return render_selector(
        level_name=_record_level_name(record),
        scenario_name=_record_scenario_name(record),
        goal=record.get("eval_goal"),
        seed_token=_record_seed_token(record) if include_seed else None,
    )
