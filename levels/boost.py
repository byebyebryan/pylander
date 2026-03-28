from __future__ import annotations

import core.terrain as _terrain
from core.level import Level
from levels.boost_catalog import (
    BOOST_DEFAULT_SCENARIO,
    BOOST_QUICK_SCENARIOS,
    BOOST_SCENARIO_BY_NAME,
    BOOST_SMOKE_SCENARIOS,
)
from levels.boost_transfer import (
    SOURCE_PAD_X,
    BoostTransferLevel,
    build_boost_weight_params,
)
from levels.common_scenarios import (
    has_randomized_values,
    is_ranged_value,
    resolve_sample_value,
)


class BoostLevel(BoostTransferLevel):
    """Pad-to-pad boost-transfer benchmark across flat, downhill, and climb routes."""

    _scenario_by_name = BOOST_SCENARIO_BY_NAME
    _default_scenario_name = BOOST_DEFAULT_SCENARIO
    _smoke_benchmark_scenarios = BOOST_SMOKE_SCENARIOS
    _quick_benchmark_scenarios = BOOST_QUICK_SCENARIOS

    def scenario_has_randomized_fields(self, _name: str | None = None) -> bool:
        scenario = self._active_scenario()
        return has_randomized_values((scenario.route_dx,))

    @staticmethod
    def _scenario_dx(scenario, *, dest_x: float | None = None) -> float:  # noqa: ANN001
        if dest_x is not None:
            return max(1e-6, float(dest_x) - float(SOURCE_PAD_X))
        route_dx = scenario.route_dx
        if is_ranged_value(route_dx):
            return max(1e-6, route_dx.median())
        return max(1e-6, float(route_dx))

    @classmethod
    def _scenario_slope(cls, scenario, *, dest_x: float | None = None) -> float:  # noqa: ANN001
        if scenario.family == "flat":
            return 0.0
        return float(scenario.route_dy) / cls._scenario_dx(scenario, dest_x=dest_x)

    def _build_base_terrain(self, seed: int):
        _ = seed
        scenario = self._active_scenario()
        dest_x = getattr(self, "_sampled_dest_x", None)
        slope = self._scenario_slope(scenario, dest_x=dest_x)
        return _terrain.LodGridGenerator(lambda x: slope * x)

    def _resolve_dest_x(self, scenario, rng) -> float:  # noqa: ANN001
        dest_dx = resolve_sample_value(
            scenario.route_dx,
            mode="median" if self._benchmark_random_mode == "median" else "sample",
            rng=rng,
        )
        return SOURCE_PAD_X + dest_dx

    def _build_scenario_params(self, scenario, dest_x: float) -> dict:  # noqa: ANN001
        slope = self._scenario_slope(scenario, dest_x=dest_x)
        return {
            "family": scenario.family,
            "route_tier": scenario.route_tier,
            "terrain_kind": scenario.terrain_kind,
            "slope": slope,
            "dx": float(dest_x) - float(SOURCE_PAD_X),
            "dy": float(scenario.route_dy),
            **build_boost_weight_params(scenario),
        }


def create_level() -> Level:
    return BoostLevel()
