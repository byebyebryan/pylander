from __future__ import annotations

from dataclasses import dataclass

from levels.boost_transfer import BOOST_WEIGHT_TIERS
from levels.common_scenarios import SampleRange


TerrainDistance = float | SampleRange


@dataclass(frozen=True)
class TerrainObstacle:
    kind: str
    placement: str
    x_fraction: float
    top_width: float
    shoulder_width: float
    height_offset: float
    left_shoulder_width: float | None = None
    right_shoulder_width: float | None = None


@dataclass(frozen=True)
class TerrainScenario:
    name: str
    family: str
    route_tier: str
    obstacle_case: str
    avoidance_band: str
    weight_tier: str
    cargo_mass: float
    cargo_fraction: float
    route_dx: TerrainDistance
    route_dy: float
    obstacle: TerrainObstacle
    sample_key: str


@dataclass(frozen=True)
class _TerrainRoute:
    family: str
    route_tier: str
    route_dx: TerrainDistance
    route_dy: float


def terrain_scenario_name(
    family: str, route_tier: str, obstacle_case: str, weight_tier: str
) -> str:
    return f"{family}:{route_tier}:{obstacle_case}:{weight_tier}"


_HALF_WEIGHT = next(weight for weight in BOOST_WEIGHT_TIERS if weight.key == "half")

_MID_ROUTES: dict[str, _TerrainRoute] = {
    "flat": _TerrainRoute(
        family="flat",
        route_tier="mid",
        route_dx=SampleRange(600.0, 1000.0),
        route_dy=0.0,
    ),
    "downhill": _TerrainRoute(
        family="downhill",
        route_tier="mid",
        route_dx=SampleRange(300.0, 500.0),
        route_dy=-400.0,
    ),
    "climb": _TerrainRoute(
        family="climb",
        route_tier="mid",
        route_dx=SampleRange(300.0, 500.0),
        route_dy=400.0,
    ),
}


def _build_reactive_scenario(
    family: str,
    obstacle_case: str,
    *,
    obstacle: TerrainObstacle,
) -> TerrainScenario:
    route = _MID_ROUTES[family]
    return TerrainScenario(
        name=terrain_scenario_name(
            family, route.route_tier, obstacle_case, _HALF_WEIGHT.key
        ),
        family=family,
        route_tier=route.route_tier,
        obstacle_case=obstacle_case,
        avoidance_band="reactive",
        weight_tier=_HALF_WEIGHT.key,
        cargo_mass=float(_HALF_WEIGHT.cargo_mass),
        cargo_fraction=float(_HALF_WEIGHT.cargo_fraction),
        route_dx=route.route_dx,
        route_dy=float(route.route_dy),
        obstacle=obstacle,
        sample_key=f"{family}:{route.route_tier}:{obstacle_case}",
    )


TERRAIN_SCENARIOS: tuple[TerrainScenario, ...] = (
    _build_reactive_scenario(
        "flat",
        "boost_table",
        obstacle=TerrainObstacle(
            kind="table",
            placement="boost",
            x_fraction=0.28,
            top_width=120.0,
            shoulder_width=55.0,
            height_offset=120.0,
        ),
    ),
    _build_reactive_scenario(
        "flat",
        "mid_table",
        obstacle=TerrainObstacle(
            kind="table",
            placement="mid",
            x_fraction=0.50,
            top_width=140.0,
            shoulder_width=60.0,
            height_offset=150.0,
        ),
    ),
    _build_reactive_scenario(
        "flat",
        "terminal_table",
        obstacle=TerrainObstacle(
            kind="table",
            placement="terminal",
            x_fraction=0.78,
            top_width=90.0,
            shoulder_width=40.0,
            height_offset=180.0,
        ),
    ),
    _build_reactive_scenario(
        "downhill",
        "boost_shoulder",
        obstacle=TerrainObstacle(
            kind="shoulder",
            placement="boost",
            x_fraction=0.28,
            top_width=90.0,
            shoulder_width=0.0,
            height_offset=0.0,
        ),
    ),
    _build_reactive_scenario(
        "downhill",
        "terminal_shoulder",
        obstacle=TerrainObstacle(
            kind="shoulder",
            placement="terminal",
            x_fraction=0.78,
            top_width=90.0,
            shoulder_width=0.0,
            height_offset=180.0,
        ),
    ),
    _build_reactive_scenario(
        "climb",
        "boost_shoulder",
        obstacle=TerrainObstacle(
            kind="shoulder",
            placement="boost",
            x_fraction=0.34,
            top_width=90.0,
            shoulder_width=55.0,
            height_offset=220.0,
        ),
    ),
    _build_reactive_scenario(
        "climb",
        "terminal_shoulder",
        obstacle=TerrainObstacle(
            kind="shoulder",
            placement="terminal",
            x_fraction=0.78,
            top_width=80.0,
            shoulder_width=45.0,
            height_offset=260.0,
        ),
    ),
)

TERRAIN_SCENARIO_BY_NAME = {scenario.name: scenario for scenario in TERRAIN_SCENARIOS}
TERRAIN_DEFAULT_SCENARIO = terrain_scenario_name("flat", "mid", "boost_table", "half")
TERRAIN_SMOKE_SCENARIOS: tuple[str, ...] = (
    terrain_scenario_name("flat", "mid", "mid_table", "half"),
)
TERRAIN_QUICK_SCENARIOS: tuple[str, ...] = (
    terrain_scenario_name("flat", "mid", "mid_table", "half"),
    terrain_scenario_name("downhill", "mid", "terminal_shoulder", "half"),
    terrain_scenario_name("climb", "mid", "terminal_shoulder", "half"),
)
