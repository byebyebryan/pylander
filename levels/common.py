from __future__ import annotations

import math
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
    Radar,
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


def _sample_terrain_height(terrain, x: float) -> float:
    try:
        return float(terrain(x, lod=0))
    except TypeError:
        return float(terrain(x))


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
    dynamic_site_enabled: bool = True
    dynamic_site_lead_distance: float = 2000.0
    dynamic_cluster_size_min: int = 3
    dynamic_cluster_size_max: int = 5
    dynamic_cluster_spacing_min: float = 360.0
    dynamic_cluster_spacing_max: float = 760.0
    dynamic_corridor_length_min: float = 10000.0
    dynamic_corridor_length_max: float = 22000.0
    dynamic_corridor_refuel_stops_min: int = 0
    dynamic_corridor_refuel_stops_max: int = 1
    dynamic_site_elevated_chance: float = 0.25
    dynamic_refuel_price_min: float = 5.5
    dynamic_refuel_price_max: float = 8.5
    dynamic_radar_spacing_ratio: float = 0.9
    dynamic_min_radar_outer_range: float = 5000.0

    def _build_base_terrain(self, seed: int) -> Any:
        raise NotImplementedError

    def _dynamic_guidance_spacing(self, actor) -> float:
        radar = actor.get_component(Radar) if actor is not None else None
        outer_range = 5000.0
        if radar is not None:
            outer_range = max(1200.0, float(radar.outer_range))
        ratio = max(0.3, min(0.95, float(self.dynamic_radar_spacing_ratio)))
        return max(700.0, outer_range * ratio)

    def _seed_dynamic_cluster_state(self, direction: int) -> None:
        rng = getattr(self, "_dynamic_site_rng", None)
        if rng is None:
            return

        state = self._dynamic_state_by_direction[direction]
        min_sites = max(1, int(self.dynamic_cluster_size_min))
        max_sites = max(min_sites, int(self.dynamic_cluster_size_max))
        state["phase"] = "cluster"
        state["cluster_remaining"] = rng.randint(min_sites, max_sites)
        state["corridor_remaining"] = 0

    def _start_dynamic_corridor(self, direction: int, guidance_spacing: float) -> None:
        rng = getattr(self, "_dynamic_site_rng", None)
        if rng is None:
            return

        state = self._dynamic_state_by_direction[direction]
        min_length = max(1000.0, float(self.dynamic_corridor_length_min))
        max_length = max(min_length, float(self.dynamic_corridor_length_max))
        corridor_length = rng.uniform(min_length, max_length)

        min_stops = max(1, int(self.dynamic_corridor_refuel_stops_min))
        max_stops = max(min_stops, int(self.dynamic_corridor_refuel_stops_max))
        desired_stops = rng.randint(min_stops, max_stops)
        required_stops = max(
            0,
            math.ceil(corridor_length / max(400.0, guidance_spacing)) - 1,
        )
        stop_count = max(desired_stops, required_stops)
        interval_count = stop_count + 1

        state["phase"] = "corridor"
        state["cluster_remaining"] = 0
        state["corridor_remaining"] = stop_count
        state["corridor_step"] = corridor_length / max(1, interval_count)

    def _corridor_spacing(self, direction: int, guidance_spacing: float) -> float:
        rng = getattr(self, "_dynamic_site_rng", None)
        if rng is None:
            return min(guidance_spacing, 1400.0)

        state = self._dynamic_state_by_direction[direction]
        base_step = max(350.0, float(state.get("corridor_step", 1400.0)))
        spacing = base_step * rng.uniform(0.87, 1.13)
        return min(guidance_spacing, max(350.0, spacing))

    def _next_dynamic_spawn_plan(self, game, *, direction: int) -> tuple[str, float]:
        rng = getattr(self, "_dynamic_site_rng", None)
        if rng is None:
            return "cluster", 1200.0

        actor = _get_focus_actor(game)
        guidance_spacing = self._dynamic_guidance_spacing(actor)
        state = self._dynamic_state_by_direction[direction]
        phase = state.get("phase", "cluster")

        if phase == "cluster":
            remaining = int(state.get("cluster_remaining", 0))
            if remaining <= 0:
                self._seed_dynamic_cluster_state(direction)
                remaining = int(state.get("cluster_remaining", 1))

            state["cluster_remaining"] = remaining - 1
            if state["cluster_remaining"] > 0:
                spacing_min = max(250.0, float(self.dynamic_cluster_spacing_min))
                spacing_max = max(spacing_min, float(self.dynamic_cluster_spacing_max))
                next_spacing = min(guidance_spacing, rng.uniform(spacing_min, spacing_max))
            else:
                self._start_dynamic_corridor(direction, guidance_spacing)
                next_spacing = self._corridor_spacing(direction, guidance_spacing)
            return "cluster", next_spacing

        remaining = int(state.get("corridor_remaining", 0))
        if remaining <= 0:
            self._seed_dynamic_cluster_state(direction)
            spacing_min = max(250.0, float(self.dynamic_cluster_spacing_min))
            spacing_max = max(spacing_min, float(self.dynamic_cluster_spacing_max))
            return "cluster", min(guidance_spacing, rng.uniform(spacing_min, spacing_max))

        state["corridor_remaining"] = remaining - 1
        next_spacing = self._corridor_spacing(direction, guidance_spacing)
        if state["corridor_remaining"] <= 0:
            self._seed_dynamic_cluster_state(direction)
        return "refuel_bridge", next_spacing

    def _spawn_dynamic_site(self, game, *, direction: int) -> None:
        if self.world is None:
            return

        rng = getattr(self, "_dynamic_site_rng", None)
        base_terrain = getattr(self, "_dynamic_base_terrain", None)
        if rng is None or base_terrain is None:
            return

        site_kind, next_spacing = self._next_dynamic_spawn_plan(game, direction=direction)
        if direction >= 0:
            x = float(self._dynamic_next_site_x_right)
            self._dynamic_next_site_x_right = x + next_spacing
            self._dynamic_site_max_x = max(self._dynamic_site_max_x, x)
        else:
            x = float(self._dynamic_next_site_x_left)
            self._dynamic_next_site_x_left = x - next_spacing
            self._dynamic_site_min_x = min(self._dynamic_site_min_x, x)

        ground_y = _sample_terrain_height(base_terrain, x)
        distance = abs(x)
        if site_kind == "refuel_bridge":
            terrain_mode = "flush_flatten"
            terrain_bound = True
            y_offset = rng.uniform(-18.0, 22.0)
            size = rng.uniform(96.0, 132.0)
            blend_margin = rng.uniform(18.0, 30.0)
            cut_depth = rng.uniform(20.0, 30.0)
            award = 40.0 + rng.uniform(0.0, 85.0) + min(120.0, distance * 0.01)
            pmin = max(2.0, float(self.dynamic_refuel_price_min))
            pmax = max(pmin, float(self.dynamic_refuel_price_max))
            fuel_price = round(rng.uniform(pmin, pmax) * 2.0) / 2.0
        else:
            elevated = rng.random() < max(0.0, min(1.0, self.dynamic_site_elevated_chance))
            if elevated:
                terrain_mode = "elevated_supports"
                terrain_bound = False
                y_offset = rng.uniform(70.0, 180.0)
            else:
                terrain_mode = "flush_flatten"
                terrain_bound = True
                y_offset = rng.uniform(-25.0, 35.0)
            size = rng.uniform(74.0, 120.0)
            blend_margin = rng.uniform(16.0, 28.0)
            cut_depth = rng.uniform(22.0, 34.0)
            award = 120.0 + rng.uniform(0.0, 240.0) + min(320.0, distance * 0.03)
            fuel_price = round(
                (
                    8.0
                    + rng.uniform(0.0, 3.5)
                    + min(2.0, distance / 7000.0)
                )
                * 2.0
            ) / 2.0

        y = ground_y + y_offset
        support_height = max(20.0, y - ground_y)

        uid = f"auto_site_{self._dynamic_site_uid_index}"
        self._dynamic_site_uid_index += 1

        site_entity = Entity(uid=uid)
        site_entity.add_component(Transform(pos=Vector2(x, y)))
        site_entity.add_component(
            LandingSiteComponent(
                size=size,
                terrain_mode=terrain_mode,
                terrain_bound=terrain_bound,
                blend_margin=blend_margin,
                cut_depth=cut_depth,
                support_height=support_height,
            )
        )
        site_entity.add_component(
            LandingSiteEconomy(
                award=award,
                fuel_price=fuel_price,
                visited=False,
            )
        )
        self.world.site_entities.append(site_entity)
        game.ecs_world.add_entity(site_entity)

        if (not terrain_bound) or terrain_mode == "elevated_supports":
            self._dynamic_elevated_sites.append((x, y, size))
            engine = getattr(self, "engine", None)
            if engine is not None:
                engine.set_landing_site_colliders(self._dynamic_elevated_sites)

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
        player_radar = _require_component(player_lander, Radar)

        min_outer = max(1000.0, float(self.dynamic_min_radar_outer_range))
        if player_radar.outer_range < min_outer:
            player_radar.outer_range = min_outer
        if player_radar.inner_range > player_radar.outer_range:
            player_radar.inner_range = player_radar.outer_range * 0.7

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
        elevated_sites: list[tuple[float, float, float]] = []
        for site_entity in site_entities:
            site_trans = site_entity.get_component(Transform)
            site_shape = site_entity.get_component(LandingSiteComponent)
            if site_trans is None or site_shape is None:
                continue
            if site_shape.terrain_bound and site_shape.terrain_mode != "elevated_supports":
                continue
            elevated_sites.append((site_trans.pos.x, site_trans.pos.y, site_shape.size))
        if elevated_sites:
            engine.set_landing_site_colliders(elevated_sites)
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
        self._dynamic_base_terrain = base_terrain
        self._dynamic_site_rng = random.Random(seed ^ 0x9E3779B9)
        self._dynamic_site_uid_index = 0
        if site_entities:
            site_xs = [
                _require_component(site_entity, Transform).pos.x
                for site_entity in site_entities
            ]
            self._dynamic_site_min_x = min(site_xs)
            self._dynamic_site_max_x = max(site_xs)
        else:
            self._dynamic_site_min_x = spawn_x
            self._dynamic_site_max_x = spawn_x
        self._dynamic_state_by_direction = {
            1: {
                "phase": "cluster",
                "cluster_remaining": 0,
                "corridor_remaining": 0,
                "corridor_step": 1400.0,
            },
            -1: {
                "phase": "cluster",
                "cluster_remaining": 0,
                "corridor_remaining": 0,
                "corridor_step": 1400.0,
            },
        }
        self._seed_dynamic_cluster_state(1)
        self._seed_dynamic_cluster_state(-1)
        guidance_spacing = self._dynamic_guidance_spacing(player_lander)
        cluster_spacing_min = max(250.0, float(self.dynamic_cluster_spacing_min))
        cluster_spacing_max = max(cluster_spacing_min, float(self.dynamic_cluster_spacing_max))
        initial_right_spacing = min(
            guidance_spacing,
            self._dynamic_site_rng.uniform(cluster_spacing_min, cluster_spacing_max),
        )
        initial_left_spacing = min(
            guidance_spacing,
            self._dynamic_site_rng.uniform(cluster_spacing_min, cluster_spacing_max),
        )
        self._dynamic_next_site_x_right = self._dynamic_site_max_x + initial_right_spacing
        self._dynamic_next_site_x_left = self._dynamic_site_min_x - initial_left_spacing
        self._dynamic_elevated_sites = list(elevated_sites)

    def update(self, game, dt: float) -> None:
        _ = dt
        if not self.dynamic_site_enabled:
            return
        if self.world is None:
            return
        if not hasattr(self, "_dynamic_site_min_x") or not hasattr(
            self, "_dynamic_site_max_x"
        ):
            return

        actor = _get_focus_actor(game)
        trans = actor.get_component(Transform)
        if trans is None:
            return

        lead = max(200.0, float(self.dynamic_site_lead_distance))
        max_spawns_per_side = 64
        right_spawns = 0
        while trans.pos.x + lead > self._dynamic_site_max_x:
            self._spawn_dynamic_site(game, direction=1)
            right_spawns += 1
            if right_spawns >= max_spawns_per_side:
                break

        left_spawns = 0
        while trans.pos.x - lead < self._dynamic_site_min_x:
            self._spawn_dynamic_site(game, direction=-1)
            left_spawns += 1
            if left_spawns >= max_spawns_per_side:
                break

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
