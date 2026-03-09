from __future__ import annotations

import math
from typing import Any

from core.bot import Sensors, VehicleInfo
from core.components import (
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
from core.ecs import require_component
from core.level import Level
from core.maths import Range1D, Vector2, clearance_above_terrain
from core.terrain import estimate_terrain_slope, sample_terrain_height
from levels.common import get_mass


def resolve_eval_target_pos(level: Level, sites: Any, start_pos: Vector2) -> Vector2 | None:
    explicit = getattr(level, "eval_target_pos", None)
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
        all_sites = list(get_sites(Range1D.from_center(start_pos.x, 1_000_000.0)))
    except (TypeError, ValueError, AttributeError):
        return None
    if not all_sites:
        return None
    nearest = min(
        all_sites,
        key=lambda site: (site.x - start_pos.x) ** 2 + (site.y - start_pos.y) ** 2,
    )
    return Vector2(nearest.x, nearest.y)


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
        mass=get_mass(entity),
        thrust_level=eng.thrust_level,
        fuel=tank.fuel,
        max_fuel=tank.max_fuel,
        state=ls.state,
        radar_contacts=readings.radar_contacts,
        proximity=readings.proximity,
    )


def build_headless_stats(entity, terrain) -> str:
    trans = require_component(entity, Transform)
    phys = require_component(entity, PhysicsState)
    eng = require_component(entity, Engine)
    tank = require_component(entity, FuelTank)
    _ = terrain
    angle_deg = math.degrees(trans.rotation)
    thrust_pct = eng.thrust_level * 100.0
    fuel_pct = 100.0 * tank.fuel / max(1e-6, tank.max_fuel)
    return (
        "ship "
        f"x={trans.pos.x:6.1f} "
        f"y={trans.pos.y:6.1f} "
        f"vx={phys.vel.x:6.2f} "
        f"vy={phys.vel.y:6.2f} "
        f"ang={angle_deg:5.1f} "
        f"thr={thrust_pct:3.0f}% "
        f"fuel={fuel_pct:5.1f}%"
    )
