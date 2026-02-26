"""Shared ballistic projection and time-to-impact helpers."""

from __future__ import annotations

import math
from dataclasses import dataclass

from bots._bot_math import coerce_finite, finite_altitude
from core.bot import ActiveSensors, PassiveSensors
from core.terrain import ballistic_fall_time


@dataclass(frozen=True)
class BallisticProjection:
    projected_dx: float
    t_fall: float
    target_x: float | None
    impact_x: float | None
    used_sensor: bool


def estimate_ballistic_projection(
    *,
    dx: float,
    alt: float,
    vx: float | None,
    vy_up: float | None,
    x: float | None,
    y: float | None,
    active: ActiveSensors | None,
    clearance: float,
    segment_length: float = 22.0,
    max_points: int = 192,
    max_distance_cap: float = 7000.0,
    distance_floor: float = 600.0,
    distance_time_horizon: float = 2.0,
    distance_margin: float = 300.0,
    min_t_fall: float = 0.5,
) -> BallisticProjection:
    safe_alt = max(0.0, coerce_finite(alt, 0.0))
    safe_vx = coerce_finite(vx, 0.0)
    safe_vy = coerce_finite(vy_up, 0.0)
    safe_dx = coerce_finite(dx, 0.0)
    fallback_t_fall = ballistic_fall_time(altitude=safe_alt, vy_up=safe_vy)
    fallback_projected_dx = safe_dx - (safe_vx * fallback_t_fall)

    safe_x = coerce_finite(x, float("nan"))
    safe_y = coerce_finite(y, float("nan"))
    target_x: float | None = None
    fallback_impact_x: float | None = None
    if math.isfinite(safe_x):
        target_x = safe_x + safe_dx
        fallback_impact_x = safe_x + (safe_vx * fallback_t_fall)
    fallback = BallisticProjection(
        projected_dx=fallback_projected_dx,
        t_fall=max(float(min_t_fall), fallback_t_fall),
        target_x=target_x,
        impact_x=fallback_impact_x,
        used_sensor=False,
    )
    if active is None or not (math.isfinite(safe_x) and math.isfinite(safe_y)):
        return fallback

    distance_budget = max(
        distance_floor,
        abs(safe_dx) + (abs(safe_vx) * max(distance_time_horizon, fallback_t_fall)) + distance_margin,
    )
    try:
        traj = active.ballistic_trajectory(
            x=safe_x,
            y=safe_y,
            vx=safe_vx,
            vy_up=safe_vy,
            max_distance=min(max_distance_cap, distance_budget),
            segment_length=segment_length,
            max_points=max_points,
            lod=0,
            clearance=max(0.0, float(clearance)),
        )
    except Exception:
        return fallback
    if not isinstance(traj, dict) or not bool(traj.get("hit")):
        return fallback
    hit_x_raw = traj.get("hit_x")
    if not isinstance(hit_x_raw, (int, float)) or not math.isfinite(float(hit_x_raw)):
        return fallback

    target_x = safe_x + safe_dx
    sensor_projected_dx = target_x - float(hit_x_raw)
    hit_time = traj.get("hit_time")
    duration = traj.get("duration")
    sensor_t_fall = coerce_finite(hit_time, coerce_finite(duration, fallback_t_fall))
    return BallisticProjection(
        projected_dx=sensor_projected_dx,
        t_fall=max(float(min_t_fall), sensor_t_fall),
        target_x=target_x,
        impact_x=float(hit_x_raw),
        used_sensor=True,
    )


def ballistic_time_to_impact(
    passive: PassiveSensors,
    active: ActiveSensors | None,
) -> tuple[float, str]:
    """Estimate time-to-impact using sensor hit-time when available."""
    alt = max(0.0, finite_altitude(passive))
    vy_up = passive.vy_up if math.isfinite(passive.vy_up) else 0.0
    fallback = ballistic_fall_time(altitude=alt, vy_up=vy_up)
    if active is None:
        return fallback, "analytic"

    distance_budget = max(
        900.0,
        abs(float(passive.vx)) * max(2.0, fallback) + (0.5 * alt) + 500.0,
    )
    try:
        traj = active.ballistic_trajectory(
            x=passive.x,
            y=passive.y,
            vx=passive.vx,
            vy_up=passive.vy_up,
            max_distance=min(7000.0, distance_budget),
            segment_length=20.0,
            max_points=192,
            lod=0,
            clearance=0.0,
        )
    except Exception:
        return fallback, "analytic"
    if not isinstance(traj, dict) or not bool(traj.get("hit")):
        return fallback, "analytic"

    hit_time = traj.get("hit_time")
    if isinstance(hit_time, (int, float)) and math.isfinite(float(hit_time)):
        return max(0.0, float(hit_time)), "sensor"
    duration = traj.get("duration")
    if isinstance(duration, (int, float)) and math.isfinite(float(duration)):
        return max(0.0, float(duration)), "sensor"
    return fallback, "analytic"

