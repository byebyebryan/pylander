from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable

from core.eval_goals import EVAL_GOAL_LANDING, normalize_eval_goal, normalize_eval_goals


@runtime_checkable
class SupportsEvalScenario(Protocol):
    def set_eval_scenario(self, name: str) -> None: ...


@runtime_checkable
class SupportsEvalGoal(Protocol):
    def set_eval_goal(self, goal: str) -> None: ...


@runtime_checkable
class SupportsBenchmarkMode(Protocol):
    def set_benchmark_mode(self, mode: str) -> None: ...


@runtime_checkable
class SupportsBatchScenarioListing(Protocol):
    def list_batch_scenarios(self) -> list[str]: ...


@runtime_checkable
class SupportsScenarioRandomizedFields(Protocol):
    def scenario_has_randomized_fields(self, name: str | None = None) -> bool: ...


@runtime_checkable
class SupportsEvalGoalListing(Protocol):
    def supported_eval_goals(self) -> tuple[str, ...]: ...


BenchmarkLevelPolicy = Literal["normal", "observe_only", "excluded"]


@dataclass(frozen=True)
class BenchmarkScenarioSets:
    smoke: tuple[str, ...]
    quick: tuple[str, ...]
    full: tuple[str, ...]


@dataclass(frozen=True)
class LevelBenchmarkProfile:
    policy: BenchmarkLevelPolicy
    scenarios: BenchmarkScenarioSets


@runtime_checkable
class SupportsBenchmarkProfile(Protocol):
    def benchmark_profile(self) -> LevelBenchmarkProfile: ...


def resolve_default_bot_name(level) -> str | None:
    default_bot = getattr(level, "default_bot_name", None)
    if not isinstance(default_bot, str):
        return None
    normalized = default_bot.strip()
    return normalized if normalized else None


def set_eval_scenario_checked(level, name: str | None) -> None:
    if name is None:
        return
    if not isinstance(level, SupportsEvalScenario):
        level_type_name = type(level).__name__
        raise ValueError(f"Level '{level_type_name}' does not support scenario selection")
    level.set_eval_scenario(name)


def resolve_level_eval_goals(level) -> tuple[str, ...]:
    getter = getattr(level, "supported_eval_goals", None)
    if not callable(getter):
        return (EVAL_GOAL_LANDING,)
    raw = getter()
    try:
        return normalize_eval_goals(raw)
    except Exception as exc:
        level_type_name = type(level).__name__
        raise ValueError(
            f"Level '{level_type_name}' returned invalid supported_eval_goals(): {exc}"
        ) from exc


def set_eval_goal_checked(level, goal: str | None) -> str:
    key = normalize_eval_goal(goal)
    supported = resolve_level_eval_goals(level)
    if key not in supported:
        level_type_name = type(level).__name__
        supported_csv = ", ".join(supported)
        raise ValueError(
            f"Level '{level_type_name}' does not support eval goal '{key}'. "
            f"Supported goals: {supported_csv}"
        )
    if isinstance(level, SupportsEvalGoal):
        level.set_eval_goal(key)
    return key


def set_benchmark_mode_checked(level, benchmark_mode: str | None) -> None:
    if benchmark_mode is None or not isinstance(level, SupportsBenchmarkMode):
        return
    level.set_benchmark_mode(benchmark_mode)


def list_batch_scenarios_safe(level) -> list[str]:
    if not isinstance(level, SupportsBatchScenarioListing):
        return []
    out = [str(name).strip() for name in level.list_batch_scenarios()]
    return [name for name in out if name]


def scenario_has_randomized_fields_safe(level, scenario_name: str | None) -> bool:
    if not isinstance(level, SupportsScenarioRandomizedFields):
        return False
    try:
        return bool(level.scenario_has_randomized_fields(scenario_name))
    except TypeError:
        return bool(level.scenario_has_randomized_fields())


def _normalize_policy(value: object, *, level_name: str) -> BenchmarkLevelPolicy:
    token = str(value or "").strip().lower()
    if token not in {"normal", "observe_only", "excluded"}:
        raise ValueError(
            f"Level '{level_name}' has invalid benchmark policy {value!r}. "
            "Expected one of: normal, observe_only, excluded"
        )
    return token  # type: ignore[return-value]


def _normalize_scenario_names(
    value: object,
    *,
    level_name: str,
    field_name: str,
) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        raise ValueError(
            f"Level '{level_name}' benchmark profile field '{field_name}' "
            f"must be a list/tuple of scenario names, got {type(value).__name__}"
        )
    out: list[str] = []
    seen: set[str] = set()
    for raw in value:
        name = str(raw or "").strip()
        if not name:
            raise ValueError(
                f"Level '{level_name}' benchmark profile field '{field_name}' "
                "contains an empty scenario name"
            )
        if name in seen:
            raise ValueError(
                f"Level '{level_name}' benchmark profile field '{field_name}' "
                f"contains duplicate scenario '{name}'"
            )
        seen.add(name)
        out.append(name)
    return tuple(out)


def resolve_level_benchmark_profile(level, level_name: str | None = None) -> LevelBenchmarkProfile:
    resolved_level_name = str(level_name or type(level).__name__).strip() or type(level).__name__
    if not isinstance(level, SupportsBenchmarkProfile):
        raise ValueError(
            f"Level '{resolved_level_name}' does not implement benchmark_profile()"
        )
    raw = level.benchmark_profile()
    if not isinstance(raw, LevelBenchmarkProfile):
        raise ValueError(
            f"Level '{resolved_level_name}' benchmark_profile() must return "
            f"LevelBenchmarkProfile, got {type(raw).__name__}"
        )

    policy = _normalize_policy(raw.policy, level_name=resolved_level_name)
    smoke = _normalize_scenario_names(
        raw.scenarios.smoke,
        level_name=resolved_level_name,
        field_name="smoke",
    )
    quick = _normalize_scenario_names(
        raw.scenarios.quick,
        level_name=resolved_level_name,
        field_name="quick",
    )
    full = _normalize_scenario_names(
        raw.scenarios.full,
        level_name=resolved_level_name,
        field_name="full",
    )

    if policy != "excluded":
        if not smoke or not quick or not full:
            raise ValueError(
                f"Level '{resolved_level_name}' benchmark profile for policy '{policy}' "
                "must provide non-empty smoke/quick/full scenario sets"
            )

    smoke_set = set(smoke)
    quick_set = set(quick)
    full_set = set(full)
    if not smoke_set.issubset(quick_set):
        missing = sorted(smoke_set - quick_set)
        raise ValueError(
            f"Level '{resolved_level_name}' benchmark profile invalid: "
            f"smoke scenarios missing from quick: {missing}"
        )
    if not quick_set.issubset(full_set):
        missing = sorted(quick_set - full_set)
        raise ValueError(
            f"Level '{resolved_level_name}' benchmark profile invalid: "
            f"quick scenarios missing from full: {missing}"
        )

    return LevelBenchmarkProfile(
        policy=policy,
        scenarios=BenchmarkScenarioSets(smoke=smoke, quick=quick, full=full),
    )


def level_trace_enabled(level, *, default: bool = False) -> bool:
    raw = getattr(level, "trace_enabled", default)
    return bool(raw)


def level_trace_sample_period_s(level, *, default: float = 0.25) -> float:
    raw = getattr(level, "trace_sample_period_s", default)
    try:
        value = float(raw)
    except (TypeError, ValueError):
        value = float(default)
    return max(0.05, value)


def level_name_tag(level) -> str:
    raw = getattr(level, "_level_name", type(level).__module__.split(".")[-1])
    name = str(raw or "").strip()
    return name if name else "level"


def level_scenario_tag(level) -> str:
    raw = getattr(level, "_public_scenario_name", getattr(level, "scenario_name", ""))
    return str(raw or "").strip()
