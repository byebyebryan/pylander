from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any

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
from core.landing_sites import LandingSiteSurfaceModel, LandingSiteTerrainModifier, to_view
from core.level import Level, LevelWorld
from core.maths import Vector2
from core.physics import PhysicsEngine
from landers import create_lander


@dataclass(frozen=True)
class SiteSpec:
    uid: str
    x: float
    size: float
    award: float
    fuel_price: float
    terrain_mode: str = "flush_flatten"
    terrain_bound: bool = True
    y_offset: float = 0.0
    blend_margin: float = 20.0
    cut_depth: float = 30.0
    support_height: float = 40.0


def _require_component(entity, component_type):
    comp = entity.get_component(component_type)
    if comp is None:
        raise RuntimeError(f"Entity {entity.uid} missing component {component_type.__name__}")
    return comp


def _get_focus_actor(game):
    if hasattr(game, "get_active_actor"):
        return game.get_active_actor()
    return game.lander


def _get_mass(entity) -> float:
    phys = _require_component(entity, PhysicsState)
    tank = _require_component(entity, FuelTank)
    return phys.mass + tank.fuel * tank.density


def _compute_lander_spawn_pos(
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


def should_end_default(
    game,
    *,
    stop_on_crash=False,
    stop_on_first_land=False,
    stop_on_out_of_fuel=False,
    max_time=None,
) -> bool:
    actor = _get_focus_actor(game)
    state = _require_component(actor, LanderState).state
    tank = _require_component(actor, FuelTank)
    if stop_on_crash and state == "crashed":
        return True
    if stop_on_first_land and state == "landed":
        return True
    if stop_on_out_of_fuel and tank.fuel <= 0.0:
        return True
    if (
        game.headless
        and max_time is not None
        and getattr(game, "_elapsed_time", 0.0) >= max_time
    ):
        return True
    return False


class PresetLevel(Level):
    site_specs: tuple[SiteSpec, ...] = ()
    spawn_x: float = 0.0
    spawn_clearance: float = 100.0
    spawn_x_jitter: float = 0.0
    site_x_jitter: float = 0.0

    def _build_base_terrain(self, seed: int) -> Any:
        raise NotImplementedError

    def setup(self, _game, seed: int) -> None:
        rng = random.Random(seed)
        base_terrain = self._build_base_terrain(seed)

        initial_views = []
        site_entities: list[Entity] = []
        for spec in self.site_specs:
            x = spec.x + rng.uniform(-self.site_x_jitter, self.site_x_jitter)
            ground_y = base_terrain(x, lod=0)
            y = ground_y + spec.y_offset
            support_height = max(
                20.0,
                spec.support_height if spec.terrain_mode == "elevated_supports" else y - ground_y,
            )

            site_entity = Entity(uid=spec.uid)
            site_entity.add_component(Transform(pos=Vector2(x, y)))
            site_entity.add_component(
                LandingSiteComponent(
                    size=spec.size,
                    terrain_mode=spec.terrain_mode,
                    terrain_bound=spec.terrain_bound,
                    blend_margin=spec.blend_margin,
                    cut_depth=spec.cut_depth,
                    support_height=support_height,
                )
            )
            site_entity.add_component(
                LandingSiteEconomy(
                    award=spec.award,
                    fuel_price=spec.fuel_price,
                    visited=False,
                )
            )
            site_entities.append(site_entity)
            initial_views.append(
                to_view(
                    uid=spec.uid,
                    x=x,
                    y=y,
                    size=spec.size,
                    vel=Vector2(0.0, 0.0),
                    award=spec.award,
                    fuel_price=spec.fuel_price,
                    terrain_mode=spec.terrain_mode,
                    terrain_bound=spec.terrain_bound,
                    blend_margin=spec.blend_margin,
                    cut_depth=spec.cut_depth,
                    support_height=support_height,
                    visited=False,
                )
            )

        site_model = LandingSiteSurfaceModel(initial_views)
        terrain = _terrain.AddHeightModifier(
            base_terrain,
            LandingSiteTerrainModifier(site_model),
        )

        lander_name = getattr(self, "lander_name", "classic")
        player_lander = create_lander(lander_name)
        player_lander.add_component(ActorProfile(kind="lander", name="player"))
        player_lander.add_component(ActorControlRole(role="human"))
        player_lander.add_component(PlayerSelectable(order=0))
        player_lander.add_component(PlayerControlled(active=True))
        player_trans = _require_component(player_lander, Transform)
        player_geo = _require_component(player_lander, LanderGeometry)

        spawn_x = self.spawn_x + rng.uniform(-self.spawn_x_jitter, self.spawn_x_jitter)
        start_pos = _compute_lander_spawn_pos(
            terrain,
            spawn_x,
            player_geo,
            clearance=self.spawn_clearance,
        )
        player_lander.start_pos = Vector2(start_pos)
        player_trans.pos = Vector2(start_pos)

        engine = PhysicsEngine(
            height_sampler=terrain,
            gravity=(0.0, -9.8),
            segment_step=10.0,
            half_width=12000.0,
        )
        engine.attach_lander(
            width=player_geo.width,
            height=player_geo.height,
            mass=_get_mass(player_lander),
            uid=player_lander.uid,
            friction=0.9,
            elasticity=0.0,
            start_pos=start_pos,
            start_angle=player_trans.rotation,
        )

        self.world = LevelWorld(
            terrain=terrain,
            sites=site_model,
            actors=[player_lander],
            primary_actor_uid=player_lander.uid,
            site_entities=site_entities,
            lander=player_lander,
            extra_entities=[],
        )
        setattr(self, "engine", engine)

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
        }


def compute_score_default(
    game,
    landing_count,
    crash_count,
    *,
    credits_score=1.0,
    fuel_score=10.0,
    landing_score=100.0,
    crash_penalty=-200.0,
) -> float:
    actor = _get_focus_actor(game)
    wallet = _require_component(actor, Wallet)
    tank = _require_component(actor, FuelTank)
    return (
        wallet.credits * credits_score
        + tank.fuel * fuel_score
        + landing_count * landing_score
        + crash_count * crash_penalty
    )
