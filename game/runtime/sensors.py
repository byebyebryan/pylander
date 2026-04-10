from __future__ import annotations

from typing import Any, Iterable, cast

from game.core.bot import BotTarget, Sensors, VehicleInfo
from game.core.components import (
    CargoHold,
    Engine,
    FuelTank,
    LanderGeometry,
    LanderState,
    PhysicsState,
    Radar,
    RefuelConfig,
    SensorReadings,
    Transform,
)
from game.core.ecs import require_component
from game.core.level import Level, get_entity_mass
from game.core.maths import Range1D, Vector2, clearance_above_terrain
from game.core.terrain import estimate_terrain_slope, sample_terrain_height


def _nearest_target_site(sites: Any, target_pos: Vector2) -> Any | None:
    get_sites = getattr(sites, "get_sites", None)
    if not callable(get_sites):
        return None
    try:
        site_iterable = cast(
            Iterable[Any],
            get_sites(Range1D.from_center(float(target_pos.x), 1000.0)),
        )
        nearby_sites = list(site_iterable)
    except (TypeError, ValueError, AttributeError):
        return None
    if not nearby_sites:
        return None
    return min(
        nearby_sites,
        key=lambda site: (
            (float(site.x) - float(target_pos.x)) ** 2
            + (float(site.y) - float(target_pos.y)) ** 2
        ),
    )


def resolve_eval_target_pos(level: Level, sites: Any, start_pos: Any) -> Any | None:
    runtime_context = level.ensure_runtime_context()
    explicit = (
        runtime_context.eval_target_pos
        if runtime_context.eval_target_pos is not None
        else None
    )
    if isinstance(explicit, Vector2):
        return Vector2(explicit)
    if isinstance(explicit, (tuple, list)) and len(explicit) >= 2:
        try:
            return Vector2(float(explicit[0]), float(explicit[1]))
        except (TypeError, ValueError):
            return None

    get_sites = getattr(sites, "get_sites", None)
    if not callable(get_sites):
        return None
    try:
        site_iterable = cast(
            Iterable[Any], get_sites(Range1D.from_center(start_pos.x, 1_000_000.0))
        )
        all_sites = list(site_iterable)
    except (TypeError, ValueError, AttributeError):
        return None
    if not all_sites:
        return None
    nearest = min(
        all_sites,
        key=lambda site: (site.x - start_pos.x) ** 2 + (site.y - start_pos.y) ** 2,
    )
    return Vector2(nearest.x, nearest.y)


def resolve_eval_target(level: Level, sites: Any, start_pos: Any) -> BotTarget | None:
    target_pos = resolve_eval_target_pos(level, sites, start_pos)
    if target_pos is None:
        return None
    nearest_site = _nearest_target_site(sites, Vector2(target_pos))
    target_uid = (
        getattr(nearest_site, "uid", None) if nearest_site is not None else None
    )
    target_size = (
        float(getattr(nearest_site, "size", 0.0) or 0.0)
        if nearest_site is not None
        else None
    )
    return BotTarget(
        uid=str(target_uid) if target_uid is not None else None,
        x=float(target_pos.x),
        y=float(target_pos.y),
        size=target_size,
        label="landing target",
    )


def build_vehicle_info(entity) -> VehicleInfo:
    geo = require_component(entity, LanderGeometry)
    phys = require_component(entity, PhysicsState)
    tank = require_component(entity, FuelTank)
    eng = require_component(entity, Engine)
    cargo = entity.get_component(CargoHold)
    ls = require_component(entity, LanderState)
    radar = require_component(entity, Radar)
    refuel = require_component(entity, RefuelConfig)
    cargo_mass = 0.0
    cargo_limit = 0.0
    if cargo is not None:
        cargo_mass = cargo.effective_mass
        cargo_limit = max(0.0, float(cargo.max_cargo_mass))
    return VehicleInfo(
        width=geo.width,
        height=geo.height,
        dry_mass=phys.mass,
        cargo_mass=cargo_mass,
        max_cargo_mass=cargo_limit,
        fuel_density=tank.density,
        max_fuel=tank.max_fuel,
        max_thrust_power=eng.max_power,
        min_thrust=eng.min_thrust,
        max_thrust=eng.max_thrust,
        thrust_increase_rate=eng.increase_rate,
        thrust_decrease_rate=eng.decrease_rate,
        base_burn_rate=eng.base_burn_rate,
        overdrive_burn_multiplier=eng.overdrive_burn_multiplier,
        safe_landing_velocity=ls.safe_landing_velocity,
        safe_landing_angle=ls.safe_landing_angle,
        radar_outer_range=radar.outer_range,
        radar_inner_range=radar.inner_range,
        proximity_sensor_range=refuel.proximity_sensor_range,
    )


def build_sensors(entity, terrain) -> Sensors:
    trans = require_component(entity, Transform)
    phys = require_component(entity, PhysicsState)
    tank = require_component(entity, FuelTank)
    eng = require_component(entity, Engine)
    ls = require_component(entity, LanderState)
    geo = require_component(entity, LanderGeometry)
    readings = require_component(entity, SensorReadings)
    terrain_y = sample_terrain_height(terrain, trans.pos.x, lod=0)
    terrain_slope = estimate_terrain_slope(terrain, trans.pos.x, lod=0)
    altitude = clearance_above_terrain(
        trans.pos.y,
        terrain_y,
        body_height=geo.height,
    )
    return Sensors(
        x=trans.pos.x,
        y=trans.pos.y,
        altitude=altitude,
        terrain_y=terrain_y,
        terrain_slope=terrain_slope,
        vx=phys.vel.x,
        vy_up=phys.vel.y,
        angle=trans.rotation,
        ax=phys.acc.x,
        ay_up=phys.acc.y,
        mass=get_entity_mass(entity),
        thrust_level=eng.thrust_level,
        fuel=tank.fuel,
        max_fuel=tank.max_fuel,
        state=ls.state,
        radar_contacts=readings.radar_contacts,
        proximity=readings.proximity,
    )
