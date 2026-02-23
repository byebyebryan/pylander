from __future__ import annotations

import random
from dataclasses import dataclass

import core.terrain as _terrain
from core.components import (
    ActorControlRole,
    ActorProfile,
    CargoHold,
    Engine,
    FuelTank,
    LandingSite as LandingSiteComponent,
    LandingSiteEconomy,
    LanderGeometry,
    PhysicsState,
    PlayerControlled,
    PlayerSelectable,
    Transform,
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
from core.ecs import require_component
from levels.common import (
    build_end_result_default,
    compute_score_default,
    compute_spawn_pos,
    get_mass,
    should_end_default,
)


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
    cargo_mass: float | None = None


def validate_scenario_recoverability(
    actor,
    *,
    scenario_name: str,
    spawn_clearance: float,
    initial_vy_up: float,
) -> None:
    """Fail fast for scenarios that cannot physically arrest descent in time."""
    phys = require_component(actor, PhysicsState)
    tank = require_component(actor, FuelTank)
    engine = require_component(actor, Engine)
    cargo = actor.get_component(CargoHold)

    cargo_mass = 0.0
    if cargo is not None:
        cargo_mass = max(0.0, min(float(cargo.cargo_mass), float(cargo.max_cargo_mass)))
    total_mass = max(
        0.5,
        float(phys.mass) + float(tank.fuel) * float(tank.density) + cargo_mass,
    )
    max_up_acc = (float(engine.max_power) * float(engine.max_thrust) / total_mass) - 9.8
    if max_up_acc <= 1e-6:
        raise ValueError(
            f"Scenario '{scenario_name}' is unrecoverable: no upward acceleration"
        )

    downward_speed = max(0.0, -float(initial_vy_up))
    stop_distance = (downward_speed * downward_speed) / (2.0 * max_up_acc)
    safety_margin = max(8.0, float(spawn_clearance) * 0.18)
    usable_altitude = max(0.0, float(spawn_clearance) - safety_margin)

    if stop_distance > usable_altitude:
        raise ValueError(
            f"Scenario '{scenario_name}' is unrecoverable: "
            f"stop_distance={stop_distance:.2f} usable_altitude={usable_altitude:.2f}"
        )


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
        if spec.cargo_mass is not None:
            cargo = lander.get_component(CargoHold)
            if cargo is not None:
                cargo.cargo_mass = max(
                    0.0,
                    min(float(spec.cargo_mass), float(cargo.max_cargo_mass)),
                )
        lander.add_component(ActorProfile(kind="lander", name="player"))
        lander.add_component(ActorControlRole(role="human"))
        lander.add_component(PlayerSelectable(order=0))
        lander.add_component(PlayerControlled(active=True))

        trans = require_component(lander, Transform)
        geo = require_component(lander, LanderGeometry)
        start_x = spec.start_x
        if spec.start_x_jitter > 0.0:
            start_x += rng.uniform(-spec.start_x_jitter, spec.start_x_jitter)
        start_pos = compute_spawn_pos(
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
            mass=get_mass(lander),
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
        setattr(self, "eval_target_pos", Vector2(target_x, target_y))

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
        result = build_end_result_default(
            game,
            landing_count=landing_count,
            crash_count=crash_count,
            score=score,
        )
        result["scenario"] = getattr(self, "scenario_name", type(self).__name__)
        return result

