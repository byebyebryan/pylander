from __future__ import annotations

from dataclasses import dataclass

import core.terrain as _terrain
from core.level import Level
from levels.setup_base import SOURCE_PAD_X, SetupTransferLevel


@dataclass(frozen=True)
class SetupDownhillScenario:
    name: str
    terrain_kind: str
    target_dx: float
    target_dy: float


_SCENARIOS: tuple[SetupDownhillScenario, ...] = (
    SetupDownhillScenario(name="low", terrain_kind="slope", target_dx=400.0, target_dy=-200.0),
    SetupDownhillScenario(name="mid", terrain_kind="slope", target_dx=400.0, target_dy=-400.0),
    SetupDownhillScenario(name="high", terrain_kind="slope", target_dx=400.0, target_dy=-800.0),
)
_SCENARIO_BY_NAME = {item.name: item for item in _SCENARIOS}
_DEFAULT_SCENARIO = "mid"
_SMOKE_BENCHMARK_SCENARIOS: tuple[str, ...] = ("mid",)
_QUICK_BENCHMARK_SCENARIOS: tuple[str, ...] = (
    "low",
    "mid",
    "high",
)


class SetupDownhillLevel(SetupTransferLevel):
    """Pad-to-pad downhill transfer with descending destination profiles."""

    _scenario_by_name = _SCENARIO_BY_NAME
    _default_scenario_name = _DEFAULT_SCENARIO
    _smoke_benchmark_scenarios = _SMOKE_BENCHMARK_SCENARIOS
    _quick_benchmark_scenarios = _QUICK_BENCHMARK_SCENARIOS

    def scenario_has_randomized_fields(self, _name: str | None = None) -> bool:
        return False

    @staticmethod
    def _scenario_slope(scenario: SetupDownhillScenario) -> float:
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
            "terrain_kind": scenario.terrain_kind,
            "slope": slope,
            "dx": scenario.target_dx,
            "dy": scenario.target_dy,
        }

    def update(self, game, dt: float) -> None:
        _ = game, dt


def create_level() -> Level:
    return SetupDownhillLevel()
