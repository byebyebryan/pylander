from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class SupportsEvalScenario(Protocol):
    def set_eval_scenario(self, name: str) -> None: ...


@runtime_checkable
class SupportsEvalMode(Protocol):
    def set_eval_mode(self, name: str) -> None: ...


@runtime_checkable
class SupportsBenchmarkMode(Protocol):
    def set_benchmark_mode(self, mode: str) -> None: ...


@runtime_checkable
class SupportsBatchScenarioListing(Protocol):
    def list_batch_scenarios(self) -> list[str]: ...


@runtime_checkable
class SupportsScenarioRandomizedFields(Protocol):
    def scenario_has_randomized_fields(self, name: str | None = None) -> bool: ...


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


def set_eval_mode_checked(level, eval_mode: str) -> None:
    if isinstance(level, SupportsEvalMode):
        level.set_eval_mode(eval_mode)
        return
    if eval_mode != "auto":
        level_type_name = type(level).__name__
        raise ValueError(
            f"Level '{level_type_name}' does not support --eval-mode {eval_mode!r}"
        )


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


def level_plot_mode(level, *, default: str = "none") -> str:
    raw = getattr(level, "plot_mode", default)
    mode = str(raw or "").strip()
    return mode if mode else default


def level_name_tag(level) -> str:
    raw = getattr(level, "_level_name", type(level).__module__.split(".")[-1])
    name = str(raw or "").strip()
    return name if name else "level"


def level_scenario_tag(level) -> str:
    raw = getattr(level, "scenario_name", "")
    return str(raw or "").strip()
