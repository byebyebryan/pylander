from __future__ import annotations

import random
from dataclasses import dataclass

import core.terrain as _terrain
from core.components import (
    ActorControlRole,
    ActorProfile,
    FuelTank,
    LandingSite as LandingSiteComponent,
    LandingSiteEconomy,
    LanderGeometry,
    LanderState,
    PhysicsState,
    PlayerControlled,
    PlayerSelectable,
    Transform,
    Wallet,
)
from core.ecs import Entity
from core.landing_sites import (
    LandingSiteSurfaceModel,
    LandingSiteTerrainModifier,
    to_view,
)
from core.level import Level, LevelWorld
from core.maths import Vector2
from core.physics import PhysicsEngine
from landers import create_lander
from levels.common import compute_score_default, should_end_default


@dataclass(frozen=True)
class EvalScenario:
    name: str
    start_x: float
    target_x: float
    spawn_clearance: float
    terrain_kind: str
    slope: float = 0.0
    terrain_base: float = 0.0
    terrain_amplitude: float = 2200.0
    terrain_frequency: float = 0.00025
    terrain_octaves: int = 5
    target_mode: str = "flush_flatten"
    target_offset_y: float = 0.0
    target_size: float = 100.0


SCENARIOS: dict[str, EvalScenario] = {
    "spawn_above_target": EvalScenario(
        name="spawn_above_target",
        start_x=0.0,
        target_x=0.0,
        spawn_clearance=70.0,
        terrain_kind="flat",
        target_mode="flush_flatten",
        target_offset_y=0.0,
        target_size=110.0,
    ),
    "greater_vertical_distance": EvalScenario(
        name="greater_vertical_distance",
        start_x=0.0,
        target_x=0.0,
        spawn_clearance=220.0,
        terrain_kind="flat",
        target_mode="flush_flatten",
        target_offset_y=0.0,
        target_size=110.0,
    ),
    "horizontal_travel_flat_descend": EvalScenario(
        name="horizontal_travel_flat_descend",
        start_x=0.0,
        target_x=900.0,
        spawn_clearance=110.0,
        terrain_kind="slope",
        slope=-0.03,
        terrain_base=120.0,
        target_mode="flush_flatten",
        target_offset_y=0.0,
        target_size=100.0,
    ),
    "increase_horizontal_distance": EvalScenario(
        name="increase_horizontal_distance",
        start_x=0.0,
        target_x=1800.0,
        spawn_clearance=120.0,
        terrain_kind="flat",
        target_mode="flush_flatten",
        target_offset_y=0.0,
        target_size=105.0,
    ),
    "climb_to_target": EvalScenario(
        name="climb_to_target",
        start_x=0.0,
        target_x=900.0,
        spawn_clearance=70.0,
        terrain_kind="slope",
        slope=0.04,
        terrain_base=-80.0,
        target_mode="elevated_supports",
        target_offset_y=90.0,
        target_size=90.0,
    ),
    "complex_terrain_vertical_features": EvalScenario(
        name="complex_terrain_vertical_features",
        start_x=-150.0,
        target_x=1300.0,
        spawn_clearance=120.0,
        terrain_kind="complex",
        terrain_amplitude=5400.0,
        terrain_frequency=0.00016,
        terrain_octaves=6,
        target_mode="elevated_supports",
        target_offset_y=100.0,
        target_size=85.0,
    ),
}

DEFAULT_SCENARIO = "spawn_above_target"


def list_eval_scenarios() -> list[str]:
    return sorted(SCENARIOS.keys())


def _require_component(entity, component_type):
    comp = entity.get_component(component_type)
    if comp is None:
        raise RuntimeError(f"Entity {entity.uid} missing component {component_type.__name__}")
    return comp


def _get_mass(entity) -> float:
    phys = _require_component(entity, PhysicsState)
    tank = _require_component(entity, FuelTank)
    return phys.mass + tank.fuel * tank.density


def _compute_spawn_pos(
    terrain,
    x: float,
    geo: LanderGeometry,
    *,
    clearance: float,
) -> Vector2:
    half_w = max(geo.width * 0.5, 1.0)
    half_h = max(geo.height * 0.5, 1.0)
    max_ground = terrain(x)
    for i in range(9):
        t = i / 8.0
        sx = x - half_w + (2.0 * half_w * t)
        max_ground = max(max_ground, terrain(sx))
    return Vector2(x, max_ground + half_h + clearance)


def _build_base_terrain(seed: int, scenario: EvalScenario):
    if scenario.terrain_kind == "flat":
        return _terrain.LodGridGenerator(lambda _x: scenario.terrain_base)
    if scenario.terrain_kind == "slope":
        return _terrain.LodGridGenerator(
            lambda x: scenario.terrain_base + scenario.slope * x
        )
    if scenario.terrain_kind == "complex":
        simplex = _terrain.SimplexNoiseGenerator(
            seed=seed,
            octaves=scenario.terrain_octaves,
            amplitude=scenario.terrain_amplitude,
            frequency=scenario.terrain_frequency,
            persistence=0.30,
            lacunarity=3.0,
        )
        return _terrain.LodGridGenerator(simplex, base_resolution=8.0)
    raise ValueError(f"Unsupported terrain kind: {scenario.terrain_kind}")


class BotEvalLevel(Level):
    def setup(self, _game, seed: int) -> None:
        scenario_name = getattr(self, "eval_scenario", DEFAULT_SCENARIO)
        scenario = SCENARIOS.get(scenario_name)
        if scenario is None:
            valid = ", ".join(list_eval_scenarios())
            raise ValueError(f"Unknown eval scenario '{scenario_name}'. Valid: {valid}")

        rng = random.Random(seed)
        base_terrain = _build_base_terrain(seed, scenario)

        target_x = scenario.target_x + rng.uniform(-15.0, 15.0)
        target_ground_y = base_terrain(target_x, lod=0)
        target_y = target_ground_y + scenario.target_offset_y
        target_terrain_bound = scenario.target_mode != "elevated_supports"

        site_uid = "eval_site_primary"
        site_view = to_view(
            uid=site_uid,
            x=target_x,
            y=target_y,
            size=scenario.target_size,
            vel=Vector2(0.0, 0.0),
            award=200.0,
            fuel_price=10.0,
            terrain_mode=scenario.target_mode,
            terrain_bound=target_terrain_bound,
            blend_margin=20.0,
            cut_depth=20.0,
            support_height=max(20.0, target_y - target_ground_y),
            visited=False,
        )
        site_model = LandingSiteSurfaceModel([site_view])
        terrain = _terrain.AddHeightModifier(
            base_terrain,
            LandingSiteTerrainModifier(site_model),
        )

        site_entity = Entity(uid=site_uid)
        site_entity.add_component(Transform(pos=Vector2(target_x, target_y)))
        site_entity.add_component(
            LandingSiteComponent(
                size=scenario.target_size,
                terrain_mode=scenario.target_mode,
                terrain_bound=target_terrain_bound,
                blend_margin=20.0,
                cut_depth=20.0,
                support_height=max(20.0, target_y - target_ground_y),
            )
        )
        site_entity.add_component(
            LandingSiteEconomy(award=200.0, fuel_price=10.0, visited=False)
        )

        lander_name = getattr(self, "lander_name", "classic")
        lander = create_lander(lander_name)
        lander.add_component(ActorProfile(kind="lander", name="player"))
        lander.add_component(ActorControlRole(role="human"))
        lander.add_component(PlayerSelectable(order=0))
        lander.add_component(PlayerControlled(active=True))

        trans = _require_component(lander, Transform)
        geo = _require_component(lander, LanderGeometry)
        start_x = scenario.start_x + rng.uniform(-10.0, 10.0)
        start_pos = _compute_spawn_pos(
            terrain,
            start_x,
            geo,
            clearance=scenario.spawn_clearance,
        )
        lander.start_pos = Vector2(start_pos)
        trans.pos = Vector2(start_pos)

        engine = PhysicsEngine(
            height_sampler=terrain,
            gravity=(0.0, -9.8),
            segment_step=10.0,
            half_width=12000.0,
        )
        if not target_terrain_bound or scenario.target_mode == "elevated_supports":
            engine.set_landing_site_colliders(
                [(target_x, target_y, scenario.target_size)]
            )
        engine.attach_lander(
            width=geo.width,
            height=geo.height,
            mass=_get_mass(lander),
            uid=lander.uid,
            friction=0.9,
            elasticity=0.0,
            start_pos=start_pos,
            start_angle=trans.rotation,
        )

        self.world = LevelWorld(
            terrain=terrain,
            sites=site_model,
            actors=[lander],
            primary_actor_uid=lander.uid,
            site_entities=[site_entity],
            lander=lander,
            extra_entities=[],
        )
        setattr(self, "engine", engine)
        setattr(self, "eval_scenario", scenario.name)

    def should_end(self, game) -> bool:
        return should_end_default(
            game,
            stop_on_crash=getattr(self, "stop_on_crash", False),
            stop_on_first_land=getattr(self, "stop_on_first_land", False),
            stop_on_out_of_fuel=getattr(self, "stop_on_out_of_fuel", False),
            max_time=getattr(self, "max_time", None),
        )

    def end(self, game):
        landing_count = getattr(game, "_landing_count", 0)
        crash_count = getattr(game, "_crash_count", 0)
        score = compute_score_default(
            game,
            landing_count,
            crash_count,
            credits_score=1.0,
            fuel_score=10.0,
            landing_score=100.0,
            crash_penalty=-200.0,
        )
        return {
            "time": getattr(game, "_elapsed_time", 0.0),
            "state": _require_component(game.lander, LanderState).state,
            "landing_count": landing_count,
            "crash_count": crash_count,
            "credits": _require_component(game.lander, Wallet).credits,
            "fuel": _require_component(game.lander, FuelTank).fuel,
            "score": score,
            "scenario": getattr(self, "eval_scenario", DEFAULT_SCENARIO),
        }


def create_level() -> Level:
    return BotEvalLevel()

