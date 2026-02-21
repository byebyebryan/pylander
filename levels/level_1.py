from __future__ import annotations

import core.terrain as _terrain
from core.components import (
    FuelTank,
    KinematicMotion,
    LandingSite as LandingSiteComponent,
    LandingSiteEconomy,
    LanderGeometry,
    LanderState,
    PhysicsState,
    SiteAttachment,
    Transform,
    Wallet,
)
from core.ecs import Entity
from core.landing_sites import (
    LandingSiteSurfaceModel,
    LandingSiteTerrainModifier,
    build_seeded_sites,
    to_view,
)
from core.maths import Vector2
from landers import create_lander
from core.level import Level, LevelWorld
from levels.common import should_end_default, compute_score_default
from core.physics import PhysicsEngine


def _require_component(entity, component_type):
    comp = entity.get_component(component_type)
    if comp is None:
        raise RuntimeError(f"Entity {entity.uid} missing component {component_type.__name__}")
    return comp


def _get_mass(entity) -> float:
    phys = _require_component(entity, PhysicsState)
    tank = _require_component(entity, FuelTank)
    return phys.mass + tank.fuel * tank.density


class GentleStartLevel(Level):
    """Baseline level: simplex terrain with decoupled landing sites."""

    def setup(self, _game, seed: int) -> None:
        height_func = _terrain.SimplexNoiseGenerator(seed=seed)
        base_terrain = _terrain.LodGridGenerator(height_func)
        site_seeds = build_seeded_sites(lambda x: base_terrain(x, lod=0), seed=seed)
        site_entities: list[Entity] = []
        initial_views = []
        for seed_site in site_seeds:
            site_entity = Entity(uid=seed_site.uid)
            site_entity.add_component(Transform(pos=Vector2(seed_site.x, seed_site.y)))
            site_entity.add_component(
                LandingSiteComponent(
                    size=seed_site.size,
                    terrain_mode=seed_site.terrain_mode,
                    terrain_bound=seed_site.terrain_bound,
                    blend_margin=seed_site.blend_margin,
                    cut_depth=seed_site.cut_depth,
                    support_height=seed_site.support_height,
                )
            )
            site_entity.add_component(
                LandingSiteEconomy(
                    award=seed_site.award,
                    fuel_price=seed_site.fuel_price,
                    visited=False,
                )
            )
            if seed_site.velocity.length_squared() > 0.0:
                site_entity.add_component(KinematicMotion(Vector2(seed_site.velocity)))
            if seed_site.parent_uid is not None:
                site_entity.add_component(
                    SiteAttachment(
                        parent_uid=seed_site.parent_uid,
                        local_offset=Vector2(seed_site.local_offset),
                    )
                )
            site_entities.append(site_entity)
            initial_views.append(
                to_view(
                    uid=seed_site.uid,
                    x=seed_site.x,
                    y=seed_site.y,
                    size=seed_site.size,
                    vel=seed_site.velocity,
                    award=seed_site.award,
                    fuel_price=seed_site.fuel_price,
                    terrain_mode=seed_site.terrain_mode,
                    terrain_bound=seed_site.terrain_bound,
                    blend_margin=seed_site.blend_margin,
                    cut_depth=seed_site.cut_depth,
                    support_height=seed_site.support_height,
                    visited=False,
                )
            )

        site_model = LandingSiteSurfaceModel(initial_views)
        terrain = _terrain.AddHeightModifier(
            base_terrain,
            LandingSiteTerrainModifier(site_model),
        )

        start_pos = Vector2(0.0, terrain(0.0) + 100.0)
        # Create lander via dynamic loader; default to "classic" when unspecified
        lander_name = getattr(self, "lander_name", "classic")
        lander = create_lander(lander_name)
        lander.start_pos = Vector2(start_pos)
        trans = _require_component(lander, Transform)
        geo = _require_component(lander, LanderGeometry)
        trans.pos = Vector2(start_pos)

        # Create physics engine and attach lander body
        engine = PhysicsEngine(
            height_sampler=terrain,
            gravity=(0.0, -9.8),
            segment_step=10.0,
            half_width=12000.0,
        )
        engine.attach_lander(
            width=geo.width,
            height=geo.height,
            mass=_get_mass(lander),
            friction=0.9,
            elasticity=0.0,
            start_pos=start_pos,
            start_angle=trans.rotation,
        )

        self.world = LevelWorld(
            terrain=terrain,
            sites=site_model,
            site_entities=site_entities,
            lander=lander,
        )
        # Expose engine on the level for the game loop
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
        # compute simple stats
        # We derive landings/crashes from game loop counters if present; if not available, approximate from state transitions would be needed.
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

        result = {
            "time": getattr(game, "_elapsed_time", 0.0),
            "state": _require_component(game.lander, LanderState).state,
            "landing_count": landing_count,
            "crash_count": crash_count,
            "credits": _require_component(game.lander, Wallet).credits,
            "fuel": _require_component(game.lander, FuelTank).fuel,
            "score": score,
        }

        # Plotting handled by Plotter in game; any plot artifacts will be merged
        # into the final result by the game loop.

        return result


def create_level() -> Level:
    return GentleStartLevel()
