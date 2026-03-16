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


@dataclass(frozen=True)
class _SetupClimbGeometry:
    key: str
    terrain_kind: str
    target_dx: float
    target_dy: float


@dataclass(frozen=True)
class SetupClimbScenario:
    name: str
    route_tier: str
    weight_tier: str
    cargo_mass: float
    cargo_fraction: float
    terrain_kind: str
    target_dx: float
    target_dy: float


_GEOMETRY_TIERS: tuple[_SetupClimbGeometry, ...] = (
    _SetupClimbGeometry(
        key="low", terrain_kind="slope", target_dx=400.0, target_dy=200.0
    ),
    _SetupClimbGeometry(
        key="mid", terrain_kind="slope", target_dx=400.0, target_dy=400.0
    ),
    _SetupClimbGeometry(
        key="high", terrain_kind="slope", target_dx=400.0, target_dy=800.0
    ),
)


def _scenario_name(route_tier: str, weight_tier: str) -> str:
    return f"{route_tier}_{weight_tier}"


_SCENARIOS: tuple[SetupClimbScenario, ...] = tuple(
    SetupClimbScenario(
        name=_scenario_name(geometry.key, weight.key),
        route_tier=geometry.key,
        weight_tier=weight.key,
        cargo_mass=float(weight.cargo_mass),
        cargo_fraction=float(weight.cargo_fraction),
        terrain_kind=geometry.terrain_kind,
        target_dx=float(geometry.target_dx),
        target_dy=float(geometry.target_dy),
    )
    for geometry in _GEOMETRY_TIERS
    for weight in SETUP_WEIGHT_TIERS
)
_SCENARIO_BY_NAME = {item.name: item for item in _SCENARIOS}
_DEFAULT_SCENARIO = _scenario_name("mid", "half")
_SMOKE_BENCHMARK_SCENARIOS: tuple[str, ...] = (_DEFAULT_SCENARIO,)
_QUICK_BENCHMARK_SCENARIOS: tuple[str, ...] = (
    _scenario_name("low", "half"),
    _scenario_name("mid", "half"),
    _scenario_name("high", "half"),
)


class SetupClimbLevel(SetupTransferLevel):
    """Pad-to-pad climb transfer with uphill destination profiles and no obstacles."""

    _scenario_by_name = _SCENARIO_BY_NAME
    _default_scenario_name = _DEFAULT_SCENARIO
    _smoke_benchmark_scenarios = _SMOKE_BENCHMARK_SCENARIOS
    _quick_benchmark_scenarios = _QUICK_BENCHMARK_SCENARIOS

    def scenario_has_randomized_fields(self, _name: str | None = None) -> bool:
        return False

    @staticmethod
    def _scenario_slope(scenario: SetupClimbScenario) -> float:
        if scenario.terrain_kind != "slope":
            return 0.0
        return float(scenario.target_dy) / max(1e-6, float(scenario.target_dx))

    def _build_base_terrain(self, _seed: int):
        scenario = self._active_scenario()
        slope = self._scenario_slope(scenario)
        return _terrain.LodGridGenerator(lambda x: slope * x)

    def _resolve_dest_x(self, scenario, rng) -> float:
        return SOURCE_PAD_X + float(scenario.target_dx)

    def _build_scenario_params(self, scenario, dest_x: float) -> dict:
        slope = self._scenario_slope(scenario)
        return {
            "route_tier": scenario.route_tier,
            "terrain_kind": scenario.terrain_kind,
            "slope": slope,
            "dx": scenario.target_dx,
            "dy": scenario.target_dy,
            **build_setup_weight_params(scenario),
        }

    def update(self, game, dt: float) -> None:
        _ = game, dt


def create_level() -> Level:
    return SetupClimbLevel()
