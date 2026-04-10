"""Bot-scenario catalog mixin and related types.

This module was moved from game/shared/common_scenarios.py as it is
bot-scenario-specific infrastructure.
"""

from __future__ import annotations

from typing import Generic, Mapping, TypeVar

from game.core.level_capabilities import (
    BenchmarkLevelPolicy,
    BenchmarkScenarioSets,
    LevelBenchmarkProfile,
)

ScenarioT = TypeVar("ScenarioT")


class ScenarioCatalogMixin(Generic[ScenarioT]):
    """Shared scenario catalog plumbing for named scenario levels."""

    _scenario_by_name: Mapping[str, ScenarioT] = {}
    _default_scenario_name: str = ""
    _smoke_benchmark_scenarios: tuple[str, ...] = ()
    _quick_benchmark_scenarios: tuple[str, ...] = ()
    _benchmark_policy: BenchmarkLevelPolicy = "normal"
    _supported_eval_goals: tuple[str, ...] = ("landing",)

    def _init_scenario_catalog(self) -> None:
        default_name = str(type(self)._default_scenario_name).strip()
        if not default_name:
            raise ValueError(
                f"{type(self).__name__} must define _default_scenario_name"
            )
        self._eval_scenario_name = default_name

    @classmethod
    def _scenario_catalog_name(cls) -> str:
        type_name = cls.__name__
        if type_name.endswith("Level"):
            type_name = type_name[:-5]
        return type_name.lower() or "level"

    def _scenario_names(self) -> tuple[str, ...]:
        return tuple(str(name) for name in type(self)._scenario_by_name)

    def _active_scenario(self) -> ScenarioT:
        return type(self)._scenario_by_name[self._eval_scenario_name]

    def supported_eval_goals(self) -> tuple[str, ...]:
        return tuple(str(goal) for goal in type(self)._supported_eval_goals)

    def list_batch_scenarios(self) -> list[str]:
        return list(self._scenario_names())

    def list_quick_benchmark_scenarios(self) -> list[str]:
        scenario_by_name = type(self)._scenario_by_name
        return [
            name
            for name in type(self)._quick_benchmark_scenarios
            if name in scenario_by_name
        ]

    def benchmark_profile(self) -> LevelBenchmarkProfile:
        scenario_by_name = type(self)._scenario_by_name
        full = self._scenario_names()
        quick = tuple(
            name
            for name in type(self)._quick_benchmark_scenarios
            if name in scenario_by_name
        )
        smoke = tuple(
            name
            for name in type(self)._smoke_benchmark_scenarios
            if name in scenario_by_name
        )
        return LevelBenchmarkProfile(
            policy=type(self)._benchmark_policy,
            scenarios=BenchmarkScenarioSets(smoke=smoke, quick=quick, full=full),
        )

    def set_eval_scenario(self, name: str) -> None:
        key = str(name).strip().lower()
        scenario_by_name = type(self)._scenario_by_name
        if key not in scenario_by_name:
            known = ", ".join(sorted(scenario_by_name))
            label = type(self)._scenario_catalog_name()
            raise ValueError(
                f"Unknown {label} scenario '{name}'. Expected one of: {known}"
            )
        self._eval_scenario_name = key
