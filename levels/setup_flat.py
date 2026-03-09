from __future__ import annotations

from dataclasses import dataclass

import core.terrain as _terrain
from core.level import Level
from levels.setup_base import SOURCE_PAD_X, SetupTransferLevel
from levels.scenario_common import (
    SampleRange,
    has_randomized_values,
    resolve_sample_value,
)

_SOURCE_PAD_X = SOURCE_PAD_X


@dataclass(frozen=True)
class SetupFlatScenario:
    name: str
    dx: float | SampleRange


_SCENARIOS: tuple[SetupFlatScenario, ...] = (
    SetupFlatScenario(name="near", dx=SampleRange(150.0, 250.0)),
    SetupFlatScenario(name="mid", dx=SampleRange(300.0, 500.0)),
    SetupFlatScenario(name="far", dx=SampleRange(600.0, 1000.0)),
)
_SCENARIO_BY_NAME = {item.name: item for item in _SCENARIOS}
_DEFAULT_SCENARIO = "mid"
_SMOKE_BENCHMARK_SCENARIOS: tuple[str, ...] = ("mid",)
_QUICK_BENCHMARK_SCENARIOS: tuple[str, ...] = ("mid",)


class SetupFlatLevel(SetupTransferLevel):
    """Pad-to-pad flat transfer setup for setup-phase tuning."""

    _scenario_by_name = _SCENARIO_BY_NAME
    _default_scenario_name = _DEFAULT_SCENARIO
    _smoke_benchmark_scenarios = _SMOKE_BENCHMARK_SCENARIOS
    _quick_benchmark_scenarios = _QUICK_BENCHMARK_SCENARIOS

    def scenario_has_randomized_fields(self, _name: str | None = None) -> bool:
        scenario = _SCENARIO_BY_NAME[self._eval_scenario_name]
        return has_randomized_values((scenario.dx,))

    def _build_base_terrain(self, _seed: int):
        return _terrain.LodGridGenerator(lambda _x: 0.0)

    def _resolve_dest_x(self, scenario, rng) -> float:
        dest_dx = resolve_sample_value(
            scenario.dx,
            mode="median" if self._benchmark_random_mode == "median" else "sample",
            rng=rng,
        )
        return _SOURCE_PAD_X + dest_dx

    def _build_scenario_params(self, scenario, dest_x: float) -> dict:
        return {"dx": dest_x - _SOURCE_PAD_X}


def create_level() -> Level:
    return SetupFlatLevel()
