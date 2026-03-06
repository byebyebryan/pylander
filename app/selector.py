from __future__ import annotations

from dataclasses import dataclass

from core.eval_goals import KNOWN_EVAL_GOAL_SET, normalize_eval_goal
from core.selector_codec import (
    render_record_selector as _render_record_selector,
    render_selector as _render_selector,
    render_selector_group as _render_selector_group,
)

render_selector = _render_selector
render_selector_group = _render_selector_group
render_record_selector = _render_record_selector


@dataclass(frozen=True)
class ParsedSelector:
    level_name: str
    scenario_name: str | None
    goal: str | None
    seed_token: str | None


def parse_seed_spec(spec: str) -> list[int]:
    values: list[int] = []
    for token in (p.strip() for p in spec.split(",")):
        if not token:
            continue
        if "-" in token:
            left, right = token.split("-", 1)
            start = int(left.strip())
            end = int(right.strip())
            step = 1 if end >= start else -1
            values.extend(range(start, end + step, step))
        else:
            values.append(int(token))

    out: list[int] = []
    seen: set[int] = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def parse_selector(
    raw_selector: str | None,
    *,
    default_level: str | None,
    known_levels: set[str],
) -> ParsedSelector:
    selector = "" if raw_selector is None else str(raw_selector).strip()
    if not selector:
        if default_level is None:
            raise ValueError("Missing selector and no default level is available")
        return ParsedSelector(
            level_name=default_level,
            scenario_name=None,
            goal=None,
            seed_token=None,
        )

    parts = selector.split(":")
    if len(parts) > 4:
        raise ValueError(
            f"Invalid selector '{selector}'. Expected format 'level[:scenario[:goal[:seed]]]'"
        )

    level_name = parts[0].strip()
    if not level_name:
        raise ValueError(
            f"Invalid selector '{selector}'. Level is required in 'level[:scenario[:goal[:seed]]]'"
        )
    if level_name not in known_levels:
        known = ", ".join(sorted(known_levels))
        raise ValueError(f"Unknown level '{level_name}'. Expected one of: {known}")

    scenario_name = None
    if len(parts) >= 2:
        scenario = parts[1].strip()
        scenario_name = scenario if scenario else None

    goal = None
    seed_token = None
    if len(parts) >= 3:
        third = parts[2].strip()
        if len(parts) == 4:
            if not third:
                raise ValueError(
                    f"Invalid selector '{selector}'. Goal is required in "
                    "'level[:scenario[:goal[:seed]]]' when 4 tokens are provided"
                )
            goal = normalize_eval_goal(third)
            seed = parts[3].strip()
            seed_token = seed if seed else None
        else:
            if third:
                lowered = third.lower()
                if lowered in KNOWN_EVAL_GOAL_SET:
                    goal = normalize_eval_goal(lowered)
                else:
                    seed_token = third

    return ParsedSelector(
        level_name=level_name,
        scenario_name=scenario_name,
        goal=goal,
        seed_token=seed_token,
    )
