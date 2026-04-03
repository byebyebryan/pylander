from __future__ import annotations

from dataclasses import dataclass

from levels.boost_transfer import BOOST_WEIGHT_TIERS
from levels.common_scenarios import SampleRange


BoostDistance = float | SampleRange


@dataclass(frozen=True)
class BoostScenario:
    name: str
    family: str
    route_tier: str
    weight_tier: str
    cargo_mass: float
    cargo_fraction: float
    route_dx: BoostDistance
    route_dy: float
    seed_key: str

    @property
    def terrain_kind(self) -> str:
        return "flat" if self.family == "flat" else "slope"


@dataclass(frozen=True)
class _BoostGeometry:
    family: str
    route_tier: str
    route_dx: BoostDistance
    route_dy: float


def boost_scenario_name(family: str, route_tier: str, weight_tier: str) -> str:
    return f"{family}:{route_tier}:{weight_tier}"


_BOOST_GEOMETRIES: tuple[_BoostGeometry, ...] = (
    _BoostGeometry(
        family="flat",
        route_tier="near",
        route_dx=SampleRange(300.0, 500.0),
        route_dy=0.0,
    ),
    _BoostGeometry(
        family="flat",
        route_tier="mid",
        route_dx=SampleRange(600.0, 1000.0),
        route_dy=0.0,
    ),
    _BoostGeometry(
        family="flat",
        route_tier="far",
        route_dx=SampleRange(1200.0, 2000.0),
        route_dy=0.0,
    ),
    _BoostGeometry(
        family="downhill",
        route_tier="low",
        route_dx=SampleRange(300.0, 500.0),
        route_dy=-200.0,
    ),
    _BoostGeometry(
        family="downhill",
        route_tier="mid",
        route_dx=SampleRange(300.0, 500.0),
        route_dy=-400.0,
    ),
    _BoostGeometry(
        family="downhill",
        route_tier="mid_long",
        route_dx=SampleRange(600.0, 1000.0),
        route_dy=-400.0,
    ),
    _BoostGeometry(
        family="downhill",
        route_tier="high",
        route_dx=SampleRange(300.0, 500.0),
        route_dy=-800.0,
    ),
    _BoostGeometry(
        family="climb",
        route_tier="low",
        route_dx=SampleRange(300.0, 500.0),
        route_dy=200.0,
    ),
    _BoostGeometry(
        family="climb",
        route_tier="mid",
        route_dx=SampleRange(300.0, 500.0),
        route_dy=400.0,
    ),
    _BoostGeometry(
        family="climb",
        route_tier="mid_long",
        route_dx=SampleRange(600.0, 1000.0),
        route_dy=400.0,
    ),
    _BoostGeometry(
        family="climb",
        route_tier="high",
        route_dx=SampleRange(300.0, 500.0),
        route_dy=800.0,
    ),
)


BOOST_SCENARIOS: tuple[BoostScenario, ...] = tuple(
    BoostScenario(
        name=boost_scenario_name(geometry.family, geometry.route_tier, weight.key),
        family=geometry.family,
        route_tier=geometry.route_tier,
        weight_tier=weight.key,
        cargo_mass=float(weight.cargo_mass),
        cargo_fraction=float(weight.cargo_fraction),
        route_dx=geometry.route_dx,
        route_dy=float(geometry.route_dy),
        seed_key=f"{geometry.family}:{geometry.route_tier}",
    )
    for geometry in _BOOST_GEOMETRIES
    for weight in BOOST_WEIGHT_TIERS
)

BOOST_SCENARIO_BY_NAME = {scenario.name: scenario for scenario in BOOST_SCENARIOS}
BOOST_DEFAULT_SCENARIO = boost_scenario_name("flat", "mid", "half")
BOOST_SMOKE_SCENARIOS: tuple[str, ...] = (
    boost_scenario_name("flat", "mid", "half"),
    boost_scenario_name("downhill", "mid", "half"),
    boost_scenario_name("climb", "mid", "half"),
)
BOOST_QUICK_SCENARIOS: tuple[str, ...] = (
    boost_scenario_name("flat", "mid", "half"),
    boost_scenario_name("downhill", "low", "half"),
    boost_scenario_name("downhill", "mid", "half"),
    boost_scenario_name("downhill", "high", "half"),
    boost_scenario_name("climb", "low", "half"),
    boost_scenario_name("climb", "mid", "half"),
    boost_scenario_name("climb", "high", "half"),
)
