from __future__ import annotations

from dataclasses import dataclass

from bot_framework.scenarios.boost_transfer import BOOST_WEIGHT_TIERS
from game.shared.common_scenarios import SampleRange


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


def terrain_scenario_name(avoidance_band: str, public_case: str) -> str:
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
    seed_case: str | None = None,
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
        seed_key=f"{family}:{route.route_tier}:{seed_case or obstacle_case}",
        reactive_contract="execution_guardrail",
        hazard_driver=hazard_driver,
        reactive_trigger="execution_drift",
        resume_without_replan=True,
        primary_navigation_owner="boost",
        nominal_route_must_clear=True,
    )


def _backstop_scenario(
    public_case: str,
    *,
    obstacle_case: str,
    top_width: float,
    shoulder_width: float,
    height_offset: float,
    target_offset: float,
) -> TerrainScenario:
    return _build_reactive_scenario(
        public_case,
        "flat",
        "far",
        obstacle_case,
        seed_case="backstop",
        weight_tier="half",
        obstacle=TerrainObstacle(
            kind="backstop",
            placement="target",
            x_fraction=0.0,
            top_width=top_width,
            shoulder_width=shoulder_width,
            height_offset=height_offset,
            target_offset=target_offset,
        ),
        hazard_driver="containment_backstop",
    )


def _clip_scenario(
    public_case: str,
    *,
    obstacle_case: str,
    top_width: float,
    height_offset: float,
    target_offset: float,
) -> TerrainScenario:
    return _build_reactive_scenario(
        public_case,
        "downhill",
        "mid",
        obstacle_case,
        seed_case="clip",
        weight_tier="half",
        obstacle=TerrainObstacle(
            kind="shoulder",
            placement="terminal",
            x_fraction=0.0,
            top_width=top_width,
            shoulder_width=0.0,
            height_offset=height_offset,
            target_offset=target_offset,
        ),
        hazard_driver="descent_clip",
    )


def _boost_clearance_scenario(
    public_case: str,
    *,
    obstacle_case: str,
    height_offset: float,
    anchor_points: tuple[tuple[float, float], ...],
) -> TerrainScenario:
    return _build_reactive_scenario(
        public_case,
        "flat",
        "mid",
        obstacle_case,
        seed_case="source_rise",
        weight_tier="full",
        obstacle=TerrainObstacle(
            kind="source_rise",
            placement="route",
            x_fraction=0.0,
            top_width=0.0,
            shoulder_width=0.0,
            height_offset=height_offset,
            anchor_points=anchor_points,
        ),
        hazard_driver="progress_clearance",
    )


TERRAIN_SCENARIOS: tuple[TerrainScenario, ...] = (
    _backstop_scenario(
        "terminal_backstop",
        obstacle_case="backstop",
        top_width=120.0,
        shoulder_width=25.0,
        height_offset=260.0,
        target_offset=75.0,
    ),
    _backstop_scenario(
        "terminal_backstop_close",
        obstacle_case="backstop_close",
        top_width=100.0,
        shoulder_width=15.0,
        height_offset=220.0,
        target_offset=75.0,
    ),
    _backstop_scenario(
        "terminal_backstop_tall",
        obstacle_case="backstop_tall",
        top_width=120.0,
        shoulder_width=25.0,
        height_offset=340.0,
        target_offset=75.0,
    ),
    _clip_scenario(
        "terminal_clip",
        obstacle_case="clip",
        top_width=80.0,
        height_offset=180.0,
        target_offset=100.0,
    ),
    _clip_scenario(
        "terminal_clip_brow",
        obstacle_case="clip_brow",
        top_width=60.0,
        height_offset=130.0,
        target_offset=90.0,
    ),
    _clip_scenario(
        "terminal_clip_wide",
        obstacle_case="clip_wide",
        top_width=120.0,
        height_offset=200.0,
        target_offset=115.0,
    ),
    _boost_clearance_scenario(
        "boost_clearance",
        obstacle_case="source_rise",
        height_offset=80.0,
        anchor_points=(
            (0.10, 0.00),
            (0.14, 1.00),
            (0.20, 0.95),
            (0.28, 0.20),
            (0.34, 0.00),
        ),
    ),
    _boost_clearance_scenario(
        "boost_clearance_shelf",
        obstacle_case="source_shelf",
        height_offset=88.0,
        anchor_points=(
            (0.10, 0.00),
            (0.14, 0.96),
            (0.22, 1.00),
            (0.30, 0.95),
            (0.38, 0.30),
            (0.44, 0.00),
        ),
    ),
    _boost_clearance_scenario(
        "boost_clearance_late_rise",
        obstacle_case="source_rise_late",
        height_offset=80.0,
        anchor_points=(
            (0.15, 0.00),
            (0.20, 1.00),
            (0.26, 0.92),
            (0.34, 0.18),
            (0.40, 0.00),
        ),
    ),
)

TERRAIN_SCENARIO_BY_NAME = {scenario.name: scenario for scenario in TERRAIN_SCENARIOS}
TERRAIN_DEFAULT_SCENARIO = terrain_scenario_name("reactive", "terminal_backstop")
TERRAIN_SMOKE_SCENARIOS: tuple[str, ...] = (
    terrain_scenario_name("reactive", "terminal_backstop"),
    terrain_scenario_name("reactive", "terminal_clip"),
    terrain_scenario_name("reactive", "boost_clearance"),
)
TERRAIN_QUICK_SCENARIOS: tuple[str, ...] = (
    terrain_scenario_name("reactive", "terminal_backstop"),
    terrain_scenario_name("reactive", "terminal_backstop_close"),
    terrain_scenario_name("reactive", "terminal_clip"),
    terrain_scenario_name("reactive", "terminal_clip_brow"),
    terrain_scenario_name("reactive", "boost_clearance"),
    terrain_scenario_name("reactive", "boost_clearance_shelf"),
)
