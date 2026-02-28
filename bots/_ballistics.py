"""Shared ballistic projection and time-to-impact helpers."""

from __future__ import annotations

import math
from dataclasses import dataclass

from bots._bot_math import coerce_finite, finite_altitude
from core.bot import ActiveSensors, PassiveSensors
from core.bot_queries import BallisticResult, BotQueryBallistic, BotQueryResult
from core.terrain import ballistic_fall_time


@dataclass(frozen=True)
class BallisticProjection:
    projected_dx: float
    t_fall: float
    target_x: float | None
    impact_x: float | None
    used_sensor: bool


def _projection_fallback(
    *,
    dx: float,
    alt: float,
    vx: float | None,
    vy_up: float | None,
    x: float | None,
    min_t_fall: float,
) -> tuple[BallisticProjection, float, float, float, float, float]:
    safe_alt = max(0.0, coerce_finite(alt, 0.0))
    safe_vx = coerce_finite(vx, 0.0)
    safe_vy = coerce_finite(vy_up, 0.0)
    safe_dx = coerce_finite(dx, 0.0)
    fallback_t_fall = ballistic_fall_time(altitude=safe_alt, vy_up=safe_vy)
    fallback_projected_dx = safe_dx - (safe_vx * fallback_t_fall)

    safe_x = coerce_finite(x, float("nan"))
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
    return fallback, safe_alt, safe_vx, safe_vy, safe_dx, fallback_t_fall


def build_projection_query(
    *,
    query_id: str,
    dx: float,
    alt: float,
    vx: float | None,
    vy_up: float | None,
    x: float | None,
    y: float | None,
    clearance: float,
    segment_length: float = 22.0,
    max_points: int = 192,
    max_distance_cap: float = 7000.0,
    distance_floor: float = 600.0,
    distance_time_horizon: float = 2.0,
    distance_margin: float = 300.0,
) -> BotQueryBallistic | None:
    _fallback, _safe_alt, safe_vx, _safe_vy, safe_dx, fallback_t_fall = _projection_fallback(
        dx=dx,
        alt=alt,
        vx=vx,
        vy_up=vy_up,
        x=x,
        min_t_fall=0.0,
    )
    safe_x = coerce_finite(x, float("nan"))
    safe_y = coerce_finite(y, float("nan"))
    if not (math.isfinite(safe_x) and math.isfinite(safe_y)):
        return None

    distance_budget = max(
        distance_floor,
        abs(safe_dx) + (abs(safe_vx) * max(distance_time_horizon, fallback_t_fall)) + distance_margin,
    )
    return BotQueryBallistic(
        id=str(query_id),
        x=safe_x,
        y=safe_y,
        vx=safe_vx,
        vy_up=coerce_finite(vy_up, 0.0),
        max_distance=min(max_distance_cap, distance_budget),
        segment_length=segment_length,
        max_points=max_points,
        lod=0,
        clearance=max(0.0, float(clearance)),
    )


def _extract_hit_metrics(result: BotQueryResult | dict | None) -> tuple[bool, float | None, float | None]:
    if isinstance(result, BallisticResult):
        return bool(result.hit), result.hit_x, result.hit_time if result.hit_time is not None else result.duration
    if not isinstance(result, dict):
        return False, None, None

    hit = bool(result.get("hit"))
    hit_x_raw = result.get("hit_x")
    hit_x = float(hit_x_raw) if isinstance(hit_x_raw, (int, float)) else None
    hit_time_raw = result.get("hit_time")
    if isinstance(hit_time_raw, (int, float)) and math.isfinite(float(hit_time_raw)):
        return hit, hit_x, float(hit_time_raw)
    duration_raw = result.get("duration")
    if isinstance(duration_raw, (int, float)) and math.isfinite(float(duration_raw)):
        return hit, hit_x, float(duration_raw)
    return hit, hit_x, None


def estimate_ballistic_projection_from_result(
    *,
    dx: float,
    alt: float,
    vx: float | None,
    vy_up: float | None,
    x: float | None,
    result: BotQueryResult | dict | None,
    min_t_fall: float = 0.5,
) -> BallisticProjection:
    fallback, _safe_alt, _safe_vx, _safe_vy, safe_dx, fallback_t_fall = _projection_fallback(
        dx=dx,
        alt=alt,
        vx=vx,
        vy_up=vy_up,
        x=x,
        min_t_fall=min_t_fall,
    )
    safe_x = coerce_finite(x, float("nan"))
    if not math.isfinite(safe_x):
        return fallback

    hit, hit_x, hit_time_or_duration = _extract_hit_metrics(result)
    if not hit or hit_x is None or not math.isfinite(float(hit_x)):
        return fallback

    target_x = safe_x + safe_dx
    sensor_projected_dx = target_x - float(hit_x)
    sensor_t_fall = coerce_finite(hit_time_or_duration, fallback_t_fall)
    return BallisticProjection(
        projected_dx=sensor_projected_dx,
        t_fall=max(float(min_t_fall), sensor_t_fall),
        target_x=target_x,
        impact_x=float(hit_x),
        used_sensor=True,
    )


def build_time_to_impact_query(
    passive: PassiveSensors,
    *,
    query_id: str,
    max_distance_cap: float = 7000.0,
    segment_length: float = 20.0,
    max_points: int = 192,
) -> BotQueryBallistic:
    alt = max(0.0, finite_altitude(passive))
    vy_up = passive.vy_up if math.isfinite(passive.vy_up) else 0.0
    fallback = ballistic_fall_time(altitude=alt, vy_up=vy_up)
    distance_budget = max(
        900.0,
        abs(float(passive.vx)) * max(2.0, fallback) + (0.5 * alt) + 500.0,
    )
    return BotQueryBallistic(
        id=str(query_id),
        x=float(passive.x),
        y=float(passive.y),
        vx=float(passive.vx),
        vy_up=float(passive.vy_up),
        max_distance=min(max_distance_cap, distance_budget),
        segment_length=segment_length,
        max_points=max_points,
        lod=0,
        clearance=0.0,
    )


def ballistic_time_to_impact_from_result(
    passive: PassiveSensors,
    result: BotQueryResult | dict | None,
) -> tuple[float, str]:
    alt = max(0.0, finite_altitude(passive))
    vy_up = passive.vy_up if math.isfinite(passive.vy_up) else 0.0
    fallback = ballistic_fall_time(altitude=alt, vy_up=vy_up)

    hit, _hit_x, hit_time_or_duration = _extract_hit_metrics(result)
    if not hit:
        return fallback, "analytic"
    if isinstance(hit_time_or_duration, (int, float)) and math.isfinite(float(hit_time_or_duration)):
        return max(0.0, float(hit_time_or_duration)), "sensor"
    return fallback, "analytic"


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
    query = build_projection_query(
        query_id="legacy_projection",
        dx=dx,
        alt=alt,
        vx=vx,
        vy_up=vy_up,
        x=x,
        y=y,
        clearance=clearance,
        segment_length=segment_length,
        max_points=max_points,
        max_distance_cap=max_distance_cap,
        distance_floor=distance_floor,
        distance_time_horizon=distance_time_horizon,
        distance_margin=distance_margin,
    )
    if active is None or query is None:
        return estimate_ballistic_projection_from_result(
            dx=dx,
            alt=alt,
            vx=vx,
            vy_up=vy_up,
            x=x,
            result=None,
            min_t_fall=min_t_fall,
        )
    try:
        traj = active.ballistic_trajectory(
            x=query.x,
            y=query.y,
            vx=query.vx,
            vy_up=query.vy_up,
            max_distance=query.max_distance,
            segment_length=query.segment_length,
            max_points=query.max_points,
            lod=query.lod,
            clearance=query.clearance,
        )
    except Exception:
        traj = None
    return estimate_ballistic_projection_from_result(
        dx=dx,
        alt=alt,
        vx=vx,
        vy_up=vy_up,
        x=x,
        result=traj,
        min_t_fall=min_t_fall,
    )


def ballistic_time_to_impact(
    passive: PassiveSensors,
    active: ActiveSensors | None,
) -> tuple[float, str]:
    """Estimate time-to-impact using sensor hit-time when available."""
    query = build_time_to_impact_query(passive, query_id="legacy_tti")
    if active is None:
        return ballistic_time_to_impact_from_result(passive, None)
    try:
        traj = active.ballistic_trajectory(
            x=query.x,
            y=query.y,
            vx=query.vx,
            vy_up=query.vy_up,
            max_distance=query.max_distance,
            segment_length=query.segment_length,
            max_points=query.max_points,
            lod=query.lod,
            clearance=query.clearance,
        )
    except Exception:
        traj = None
    return ballistic_time_to_impact_from_result(passive, traj)
