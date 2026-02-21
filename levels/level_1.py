from __future__ import annotations

import core.terrain as _terrain
from core.components import (
    ActorControlRole,
    ActorProfile,
    FuelTank,
    KinematicMotion,
    LandingSite as LandingSiteComponent,
    LandingSiteEconomy,
    LanderGeometry,
    LanderState,
    PlayerControlled,
    PlayerSelectable,
    PhysicsState,
    ScriptController,
    ScriptFrame,
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


def _compute_lander_spawn_pos(
    terrain,
    x: float,
    geo: LanderGeometry,
    *,
    clearance: float = 80.0,
) -> Vector2:
    """Pick a spawn point safely above local terrain under the hull footprint."""
    half_w = max(geo.width * 0.5, 1.0)
    half_h = max(geo.height * 0.5, 1.0)
    samples = 9
    max_ground = terrain(x)
    for i in range(samples):
        t = i / (samples - 1)
        sx = x - half_w + (2.0 * half_w * t)
        max_ground = max(max_ground, terrain(sx))
    return Vector2(x, max_ground + half_h + clearance)


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

        # Create lander via dynamic loader; default to "classic" when unspecified
        lander_name = getattr(self, "lander_name", "classic")
        player_lander = create_lander(lander_name)
        player_lander.add_component(ActorProfile(kind="lander", name="player"))
        player_lander.add_component(ActorControlRole(role="human"))
        player_lander.add_component(PlayerSelectable(order=0))
        player_lander.add_component(PlayerControlled(active=True))
        player_trans = _require_component(player_lander, Transform)
        player_geo = _require_component(player_lander, LanderGeometry)
        start_pos = _compute_lander_spawn_pos(terrain, 0.0, player_geo)
        player_lander.start_pos = Vector2(start_pos)
        player_trans.pos = Vector2(start_pos)

        bot_spawn_x = start_pos.x + 120.0
        bot_lander = create_lander(lander_name)
        bot_lander.add_component(ActorProfile(kind="lander", name="bot"))
        bot_lander.add_component(ActorControlRole(role="bot"))
        bot_lander.add_component(PlayerSelectable(order=1))
        bot_trans = _require_component(bot_lander, Transform)
        bot_geo = _require_component(bot_lander, LanderGeometry)
        bot_start = _compute_lander_spawn_pos(terrain, bot_spawn_x, bot_geo)
        bot_lander.start_pos = Vector2(bot_start)
        bot_trans.pos = Vector2(bot_start)
        actors = [player_lander, bot_lander]

        # Create physics engine and attach lander body
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
        engine.attach_lander(
            width=bot_geo.width,
            height=bot_geo.height,
            mass=_get_mass(bot_lander),
            uid=bot_lander.uid,
            friction=0.9,
            elasticity=0.0,
            start_pos=bot_start,
            start_angle=bot_trans.rotation,
        )

        carrier_x = 350.0
        carrier_y = terrain(carrier_x) + 80.0
        carrier = Entity(uid="carrier_scripted")
        carrier.add_component(Transform(pos=Vector2(carrier_x, carrier_y)))
        carrier.add_component(KinematicMotion(velocity=Vector2(15.0, 0.0)))
        carrier.add_component(ActorProfile(kind="carrier", name="train_target"))
        carrier.add_component(ActorControlRole(role="script"))
        carrier.add_component(
            ScriptController(
                frames=[
                    ScriptFrame(duration=6.0, velocity=Vector2(15.0, 0.0)),
                    ScriptFrame(duration=6.0, velocity=Vector2(-15.0, 0.0)),
                ],
                loop=True,
            )
        )

        moving_site = Entity(uid="site_scripted_carrier")
        moving_site.add_component(Transform(pos=Vector2(carrier_x, carrier_y)))
        moving_site.add_component(
            LandingSiteComponent(
                size=40.0,
                terrain_mode="elevated_supports",
                terrain_bound=False,
                support_height=20.0,
            )
        )
        moving_site.add_component(LandingSiteEconomy(award=175.0, fuel_price=11.0))
        moving_site.add_component(
            SiteAttachment(parent_uid=carrier.uid, local_offset=Vector2(0.0, 0.0))
        )
        site_entities.append(moving_site)
        initial_views.append(
            to_view(
                uid=moving_site.uid,
                x=carrier_x,
                y=carrier_y,
                size=40.0,
                vel=Vector2(15.0, 0.0),
                award=175.0,
                fuel_price=11.0,
                terrain_mode="elevated_supports",
                terrain_bound=False,
                blend_margin=20.0,
                cut_depth=30.0,
                support_height=20.0,
                visited=False,
            )
        )

        self.world = LevelWorld(
            terrain=terrain,
            sites=site_model,
            actors=actors,
            primary_actor_uid=player_lander.uid,
            site_entities=site_entities,
            lander=player_lander,
            extra_entities=[carrier],
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
