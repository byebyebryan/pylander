from __future__ import annotations

from collections.abc import Iterable

EVAL_GOAL_LANDING = "landing"
EVAL_GOAL_BOOST_CUTOFF = "boost_cutoff"
EVAL_GOAL_BOOST = EVAL_GOAL_BOOST_CUTOFF

KNOWN_EVAL_GOALS: tuple[str, ...] = (
    EVAL_GOAL_LANDING,
    EVAL_GOAL_BOOST_CUTOFF,
)
KNOWN_EVAL_GOAL_SET = set(KNOWN_EVAL_GOALS)


def normalize_eval_goal(goal: str | None) -> str:
    token = str(goal or EVAL_GOAL_LANDING).strip().lower()
    if token not in KNOWN_EVAL_GOAL_SET:
        known = ", ".join(KNOWN_EVAL_GOALS)
        raise ValueError(f"Unknown eval goal '{goal}'. Expected one of: {known}")
    return token


def normalize_eval_goals(goals: Iterable[str] | None) -> tuple[str, ...]:
    if goals is None:
        return (EVAL_GOAL_LANDING,)
    out: list[str] = []
    seen: set[str] = set()
    for raw in goals:
        token = normalize_eval_goal(str(raw))
        if token in seen:
            continue
        seen.add(token)
        out.append(token)
    if not out:
        return (EVAL_GOAL_LANDING,)
    if EVAL_GOAL_LANDING not in seen:
        raise ValueError(
            "Eval-goal support list must include 'landing' (all levels/bots support landing)"
        )
    return tuple(out)
