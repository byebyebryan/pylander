from __future__ import annotations

from dataclasses import dataclass

from game.core.eval_goals import (
    EVAL_GOAL_BOOST_CUTOFF,
    KNOWN_EVAL_GOAL_SET,
    normalize_eval_goal,
)
from game.levels.registry import list_public_levels
from game.levels.benchmark_catalog import selector_path_looks_like_seed
from game.core.selector_codec import (
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
    scenario_path: tuple[str, ...]
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
            scenario_path=(),
            goal=None,
            seed_token=None,
        )

    parts = [part.strip().lower() for part in selector.split(":")]
    if any(not part for part in parts):
        raise ValueError(
            f"Invalid selector '{selector}'. Empty selector tokens are not supported"
        )

    tokens = list(parts)
    if not tokens:
        raise ValueError(f"Invalid selector '{selector}'. Level is required")

    goal = None
    seed_token = None
    if len(tokens) >= 2 and selector_path_looks_like_seed(tokens[-1]):
        seed_token = tokens.pop()
    if len(tokens) >= 2 and tokens[-1] in KNOWN_EVAL_GOAL_SET:
        goal = normalize_eval_goal(tokens.pop())

    if not tokens:
        raise ValueError(
            f"Invalid selector '{selector}'. Level is required before goal/seed tokens"
        )

    level_name = tokens[0]
    if level_name not in known_levels:
        legacy_hint = _legacy_selector_hint(selector, known_levels=known_levels)
        if legacy_hint is not None:
            raise ValueError(
                f"Invalid selector '{selector}'. Old selector forms are no longer supported; "
                f"use '{legacy_hint}'"
            )
        known = ", ".join(sorted(known_levels))
        raise ValueError(f"Unknown level '{level_name}'. Expected one of: {known}")

    if (
        goal is None
        and len(tokens) >= 2
        and tokens[-1] == "boost"
        and level_name == "boost"
    ):
        replacement_tokens = [*tokens[:-1], EVAL_GOAL_BOOST_CUTOFF]
        if seed_token is not None:
            replacement_tokens.append(seed_token)
        replacement = ":".join(replacement_tokens)
        raise ValueError(
            f"Invalid selector '{selector}'. Eval goal 'boost' was renamed to "
            f"'{EVAL_GOAL_BOOST_CUTOFF}'; use '{replacement}'"
        )

    scenario_path = tuple(tokens[1:])
    scenario_name = ":".join(scenario_path) if scenario_path else None

    return ParsedSelector(
        level_name=level_name,
        scenario_name=scenario_name,
        scenario_path=scenario_path,
        goal=goal,
        seed_token=seed_token,
    )


def _legacy_selector_hint(
    raw_selector: str,
    *,
    known_levels: set[str],
) -> str | None:
    parts = [
        part.strip().lower()
        for part in str(raw_selector or "").split(":")
        if part.strip()
    ]
    if not parts:
        return None

    legacy_level = parts[0]
    known_public_levels = {
        level for level in list_public_levels() if level in known_levels
    }
    if legacy_level in known_public_levels:
        return None

    goal = None
    seed = None
    tokens = list(parts)
    if len(tokens) >= 2 and selector_path_looks_like_seed(tokens[-1]):
        seed = tokens.pop()
    if len(tokens) >= 2 and tokens[-1] in KNOWN_EVAL_GOAL_SET:
        goal = tokens.pop()
    elif len(tokens) >= 2 and tokens[-1] == "boost":
        goal = EVAL_GOAL_BOOST_CUTOFF
        tokens.pop()
    if not tokens:
        return None

    scenario = tokens[1] if len(tokens) >= 2 else None
    path_tokens: list[str] | None = None

    if legacy_level == "boost_flat":
        path_tokens = ["boost", "flat"]
    elif legacy_level == "boost_downhill":
        path_tokens = ["boost", "downhill"]
    elif legacy_level == "boost_climb":
        path_tokens = ["boost", "climb"]
    elif legacy_level == "terminal_normal":
        path_tokens = ["terminal", "normal"]
    elif legacy_level == "terminal_error":
        path_tokens = ["terminal", "error"]
    elif legacy_level == "plunge":
        path_tokens = ["plunge"]
    else:
        return None

    if scenario:
        path_tokens.extend(_legacy_scenario_tokens(legacy_level, scenario))

    rendered = ":".join(path_tokens)
    if goal and goal != "landing":
        rendered = f"{rendered}:{goal}"
    if seed:
        rendered = f"{rendered}:{seed}"
    return rendered


def _legacy_scenario_tokens(level_name: str, scenario_name: str) -> list[str]:
    scenario = str(scenario_name or "").strip().lower()
    if not scenario:
        return []
    if level_name in {"boost_flat", "boost_downhill", "boost_climb"}:
        left, right = _split_legacy_token_pair(level_name, scenario)
        return [left, right]
    if level_name == "terminal_error":
        left, right = _split_legacy_token_pair(level_name, scenario)
        return [left, right]
    if level_name == "terminal_normal":
        return [scenario]
    if level_name == "plunge":
        altitude, weight = _split_legacy_token_pair(level_name, scenario)
        plunge_weight = {
            "light": "empty",
            "normal": "half",
            "heavy": "full",
            "empty": "empty",
            "half": "half",
            "full": "full",
        }.get(weight, weight)
        return [altitude, plunge_weight]
    return [scenario]


def _split_legacy_token_pair(level_name: str, scenario_name: str) -> tuple[str, str]:
    if "_" not in scenario_name:
        raise ValueError(
            f"Legacy selector '{level_name}:{scenario_name}' is ambiguous. "
            "Expected an underscore-delimited scenario token"
        )
    left, right = scenario_name.split("_", 1)
    return left, right
