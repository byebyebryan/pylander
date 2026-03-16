from __future__ import annotations

from dataclasses import dataclass

import core.terrain as _terrain
from core.level import Level
from levels.boost_base import (
    SOURCE_PAD_X,
    SETUP_WEIGHT_TIERS,
    SetupTransferLevel,
    build_setup_weight_params,
)
from levels.scenario_common import (
    SampleRange,
    has_randomized_values,
    resolve_sample_value,
)

_SOURCE_PAD_X = SOURCE_PAD_X


@dataclass(frozen=True)
class _SetupFlatGeometry:
    key: str
    dx: float | SampleRange


@dataclass(frozen=True)
class SetupFlatScenario:
    name: str
    route_tier: str
    weight_tier: str
    cargo_mass: float
    cargo_fraction: float
    sample_key: str
    dx: float | SampleRange


_GEOMETRY_TIERS: tuple[_SetupFlatGeometry, ...] = (
    _SetupFlatGeometry(key="near", dx=SampleRange(150.0, 250.0)),
    _SetupFlatGeometry(key="mid", dx=SampleRange(300.0, 500.0)),
    _SetupFlatGeometry(key="far", dx=SampleRange(600.0, 1000.0)),
)


def _scenario_name(route_tier: str, weight_tier: str) -> str:
    return f"{route_tier}_{weight_tier}"


_SCENARIOS: tuple[SetupFlatScenario, ...] = tuple(
    SetupFlatScenario(
        name=_scenario_name(geometry.key, weight.key),
        route_tier=geometry.key,
        weight_tier=weight.key,
        cargo_mass=float(weight.cargo_mass),
        cargo_fraction=float(weight.cargo_fraction),
        sample_key=geometry.key,
        dx=geometry.dx,
    )
    for geometry in _GEOMETRY_TIERS
    for weight in SETUP_WEIGHT_TIERS
)
_SCENARIO_BY_NAME = {item.name: item for item in _SCENARIOS}
_DEFAULT_SCENARIO = _scenario_name("mid", "half")
_SMOKE_BENCHMARK_SCENARIOS: tuple[str, ...] = (_DEFAULT_SCENARIO,)
_QUICK_BENCHMARK_SCENARIOS: tuple[str, ...] = (_DEFAULT_SCENARIO,)


class SetupFlatLevel(SetupTransferLevel):
    """Pad-to-pad flat transfer benchmark for boost-phase tuning."""

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
        return {
            "route_tier": scenario.route_tier,
            "dx": dest_x - _SOURCE_PAD_X,
            **build_setup_weight_params(scenario),
        }


def create_level() -> Level:
    return SetupFlatLevel()
