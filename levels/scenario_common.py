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
class ScenarioLevelSpec:
    name: str
    start_x: float
    target_x: float
    spawn_clearance: float
    terrain_kind: str
    start_x_jitter: float = 0.0
    target_x_jitter: float = 0.0
    slope: float = 0.0
    terrain_base: float = 0.0
    terrain_amplitude: float = 2200.0
    terrain_frequency: float = 0.00025
    terrain_octaves: int = 5
    target_mode: str = "flush_flatten"
    target_offset_y: float = 0.0
    target_size: float = 100.0


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


def _build_base_terrain(seed: int, spec: ScenarioLevelSpec):
    if spec.terrain_kind == "flat":
        return _terrain.LodGridGenerator(lambda _x: spec.terrain_base)
    if spec.terrain_kind == "slope":
        return _terrain.LodGridGenerator(
            lambda x: spec.terrain_base + spec.slope * x
        )
    if spec.terrain_kind == "complex":
        simplex = _terrain.SimplexNoiseGenerator(
            seed=seed,
            octaves=spec.terrain_octaves,
            amplitude=spec.terrain_amplitude,
            frequency=spec.terrain_frequency,
            persistence=0.30,
            lacunarity=3.0,
        )
        return _terrain.LodGridGenerator(simplex, base_resolution=8.0)
    raise ValueError(f"Unsupported terrain kind: {spec.terrain_kind}")


class ScenarioLevel(Level):
    """Single-scenario level with deterministic setup and optional default bot."""

    scenario: ScenarioLevelSpec | None = None
    default_bot_name: str | None = None

    def setup(self, _game, seed: int) -> None:
        spec = self.scenario
        if spec is None:
            raise ValueError(f"{type(self).__name__} must define `scenario`")

        rng = random.Random(seed)
        base_terrain = _build_base_terrain(seed, spec)

        target_x = spec.target_x
        if spec.target_x_jitter > 0.0:
            target_x += rng.uniform(-spec.target_x_jitter, spec.target_x_jitter)
        target_ground_y = base_terrain(target_x, lod=0)
        target_y = target_ground_y + spec.target_offset_y
        target_terrain_bound = spec.target_mode != "elevated_supports"

        site_uid = "eval_site_primary"
        site_view = to_view(
            uid=site_uid,
            x=target_x,
            y=target_y,
            size=spec.target_size,
            vel=Vector2(0.0, 0.0),
            award=200.0,
            fuel_price=10.0,
            terrain_mode=spec.target_mode,
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
                size=spec.target_size,
                terrain_mode=spec.target_mode,
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
        start_x = spec.start_x
        if spec.start_x_jitter > 0.0:
            start_x += rng.uniform(-spec.start_x_jitter, spec.start_x_jitter)
        start_pos = _compute_spawn_pos(
            terrain,
            start_x,
            geo,
            clearance=spec.spawn_clearance,
        )
        lander.start_pos = Vector2(start_pos)
        trans.pos = Vector2(start_pos)

        engine = PhysicsEngine(
            height_sampler=terrain,
            gravity=(0.0, -9.8),
            segment_step=10.0,
            half_width=12000.0,
        )
        if not target_terrain_bound or spec.target_mode == "elevated_supports":
            engine.set_landing_site_colliders([(target_x, target_y, spec.target_size)])
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
        setattr(self, "scenario_name", spec.name)

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
            "scenario": getattr(self, "scenario_name", type(self).__name__),
        }

