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
    target_offset: float = 0.0
    anchor_points: tuple[tuple[float, float], ...] = ()


@dataclass(frozen=True)
class TerrainScenario:
    name: str
    public_case: str
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
    seed_key: str
    reactive_contract: str
    hazard_driver: str
    reactive_trigger: str
    resume_without_replan: bool
    primary_navigation_owner: str
    nominal_route_must_clear: bool


@dataclass(frozen=True)
class _TerrainRoute:
    family: str
    route_tier: str
    route_dx: TerrainDistance
    route_dy: float


def terrain_scenario_name(
    avoidance_band: str, public_case: str
) -> str:
    return f"{avoidance_band}:{public_case}"


_WEIGHT_BY_KEY = {weight.key: weight for weight in BOOST_WEIGHT_TIERS}

_EXECUTION_GUARDRAIL_ROUTES: dict[tuple[str, str], _TerrainRoute] = {
    ("flat", "mid"): _TerrainRoute(
        family="flat",
        route_tier="mid",
        route_dx=SampleRange(700.0, 900.0),
        route_dy=0.0,
    ),
    ("flat", "far"): _TerrainRoute(
        family="flat",
        route_tier="far",
        route_dx=SampleRange(1200.0, 2000.0),
        route_dy=0.0,
    ),
    ("downhill", "mid"): _TerrainRoute(
        family="downhill",
        route_tier="mid",
        route_dx=SampleRange(360.0, 400.0),
        route_dy=-400.0,
    ),
}


def _build_reactive_scenario(
    public_case: str,
    family: str,
    route_tier: str,
    obstacle_case: str,
    *,
    weight_tier: str,
    obstacle: TerrainObstacle,
    hazard_driver: str,
) -> TerrainScenario:
    route = _EXECUTION_GUARDRAIL_ROUTES[(family, route_tier)]
    weight = _WEIGHT_BY_KEY[weight_tier]
    return TerrainScenario(
        name=terrain_scenario_name("reactive", public_case),
        public_case=public_case,
        family=family,
        route_tier=route.route_tier,
        obstacle_case=obstacle_case,
        avoidance_band="reactive",
        weight_tier=weight.key,
        cargo_mass=float(weight.cargo_mass),
        cargo_fraction=float(weight.cargo_fraction),
        route_dx=route.route_dx,
        route_dy=float(route.route_dy),
        obstacle=obstacle,
        seed_key=f"{family}:{route.route_tier}:{obstacle_case}",
        reactive_contract="execution_guardrail",
        hazard_driver=hazard_driver,
        reactive_trigger="execution_drift",
        resume_without_replan=True,
        primary_navigation_owner="boost",
        nominal_route_must_clear=True,
    )


TERRAIN_SCENARIOS: tuple[TerrainScenario, ...] = (
    _build_reactive_scenario(
        "terminal_backstop",
        "flat",
        "far",
        "backstop",
        weight_tier="half",
        obstacle=TerrainObstacle(
            kind="backstop",
            placement="target",
            x_fraction=0.0,
            top_width=120.0,
            shoulder_width=25.0,
            height_offset=260.0,
            target_offset=75.0,
        ),
        hazard_driver="containment_backstop",
    ),
    _build_reactive_scenario(
        "terminal_clip",
        "downhill",
        "mid",
        "clip",
        weight_tier="half",
        obstacle=TerrainObstacle(
            kind="shoulder",
            placement="terminal",
            x_fraction=0.0,
            top_width=80.0,
            shoulder_width=0.0,
            height_offset=180.0,
            target_offset=100.0,
        ),
        hazard_driver="descent_clip",
    ),
    _build_reactive_scenario(
        "boost_clearance",
        "flat",
        "mid",
        "source_rise",
        weight_tier="full",
        obstacle=TerrainObstacle(
            kind="source_rise",
            placement="route",
            x_fraction=0.0,
            top_width=0.0,
            shoulder_width=0.0,
            height_offset=80.0,
            anchor_points=(
                (0.10, 0.00),
                (0.14, 1.00),
                (0.20, 0.95),
                (0.28, 0.20),
                (0.34, 0.00),
            ),
        ),
        hazard_driver="progress_clearance",
    ),
)

TERRAIN_SCENARIO_BY_NAME = {scenario.name: scenario for scenario in TERRAIN_SCENARIOS}
TERRAIN_DEFAULT_SCENARIO = terrain_scenario_name("reactive", "terminal_backstop")
TERRAIN_SMOKE_SCENARIOS: tuple[str, ...] = (
    terrain_scenario_name("reactive", "terminal_backstop"),
)
TERRAIN_QUICK_SCENARIOS: tuple[str, ...] = (
    terrain_scenario_name("reactive", "terminal_backstop"),
    terrain_scenario_name("reactive", "terminal_clip"),
    terrain_scenario_name("reactive", "boost_clearance"),
)
