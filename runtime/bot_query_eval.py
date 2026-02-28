from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.bot_queries import (
    BallisticResult,
    BotQuery,
    BotQueryBallistic,
    BotQueryRaycast,
    BotQueryResults,
    BotQueryTerrainProfile,
    RaycastResult,
    TerrainProfileResult,
    clone_ballistic_result,
)
from core.components import Radar, Transform
from core.ecs import require_component
from core.maths import Vector2
from core.terrain import sample_ballistic_trajectory, sample_terrain_height


@dataclass
class QueryBatchStats:
    total: int = 0
    raycast: int = 0
    terrain_profile: int = 0
    ballistic: int = 0


def _normalize_query_id(raw_id: str) -> str:
    query_id = str(raw_id).strip()
    if not query_id:
        raise ValueError("Bot query id must be non-empty")
    return query_id


def _terrain_height(terrain: Any, world_x: float, lod: int = 0) -> float:
    if terrain is None:
        return 0.0
    return sample_terrain_height(terrain, world_x, lod=lod)


def _evaluate_raycast(actor, engine_adapter, query: BotQueryRaycast) -> RaycastResult:
    trans = require_component(actor, Transform)
    radar = actor.get_component(Radar)
    max_range = query.max_range
    if max_range is None:
        max_range = float(radar.inner_range) if radar is not None else 0.0

    payload = engine_adapter.raycast(
        Vector2(trans.pos),
        float(query.dir_angle),
        float(max_range),
        uid=actor.uid,
    )
    return RaycastResult(
        hit=bool(payload.get("hit", False)),
        distance=(
            float(payload["distance"]) if isinstance(payload.get("distance"), (int, float)) else None
        ),
        hit_x=float(payload.get("hit_x", 0.0) or 0.0),
        hit_y=float(payload.get("hit_y", 0.0) or 0.0),
    )


def _evaluate_terrain_profile(terrain, query: BotQueryTerrainProfile) -> TerrainProfileResult:
    n = max(2, int(query.samples))
    lod = int(query.lod)
    x_start = float(query.x_start)
    x_end = float(query.x_end)
    span = x_end - x_start
    points: list[tuple[float, float]] = []
    for i in range(n):
        t = i / (n - 1)
        xx = x_start + span * t
        yy = _terrain_height(terrain, xx, lod=lod)
        points.append((xx, yy))
    return TerrainProfileResult(points=points)


def _ballistic_cache_key(query: BotQueryBallistic) -> tuple[Any, ...]:
    return (
        float(query.x),
        float(query.y),
        float(query.vx),
        float(query.vy_up),
        float(query.max_distance),
        float(query.segment_length),
        int(query.max_points),
        int(query.lod),
        float(query.clearance),
    )


def _evaluate_ballistic(terrain, query: BotQueryBallistic) -> BallisticResult:
    if terrain is None:
        return BallisticResult(
            points=[(float(query.x), float(query.y))],
            hit=False,
            hit_x=None,
            hit_y=None,
            hit_time=None,
            hit_vx=None,
            hit_vy_up=None,
            hit_speed=None,
            distance=0.0,
            duration=0.0,
            termination="no_terrain",
        )

    result = sample_ballistic_trajectory(
        terrain,
        x=float(query.x),
        y=float(query.y),
        vx=float(query.vx),
        vy_up=float(query.vy_up),
        max_distance=float(query.max_distance),
        segment_length=float(query.segment_length),
        max_points=int(query.max_points),
        lod=int(query.lod),
        clearance=float(query.clearance),
    )
    return BallisticResult(
        points=list(result.points),
        hit=bool(result.hit),
        hit_x=result.hit_x,
        hit_y=result.hit_y,
        hit_time=result.hit_time,
        hit_vx=result.hit_vx,
        hit_vy_up=result.hit_vy_up,
        hit_speed=result.hit_speed,
        distance=float(result.distance),
        duration=float(result.duration),
        termination=str(result.termination),
    )


def evaluate_bot_queries(
    actor,
    engine_adapter,
    terrain,
    queries: list[BotQuery],
) -> tuple[BotQueryResults, QueryBatchStats]:
    seen_ids: set[str] = set()
    out: BotQueryResults = {}
    stats = QueryBatchStats()
    ballistic_cache: dict[tuple[Any, ...], BallisticResult] = {}

    for query in queries:
        query_id = _normalize_query_id(getattr(query, "id", ""))
        if query_id in seen_ids:
            raise ValueError(f"Duplicate bot query id '{query_id}'")
        seen_ids.add(query_id)
        stats.total += 1

        if isinstance(query, BotQueryRaycast):
            stats.raycast += 1
            out[query_id] = _evaluate_raycast(actor, engine_adapter, query)
            continue

        if isinstance(query, BotQueryTerrainProfile):
            stats.terrain_profile += 1
            out[query_id] = _evaluate_terrain_profile(terrain, query)
            continue

        if isinstance(query, BotQueryBallistic):
            stats.ballistic += 1
            key = _ballistic_cache_key(query)
            cached = ballistic_cache.get(key)
            if cached is None:
                cached = _evaluate_ballistic(terrain, query)
                ballistic_cache[key] = cached
            out[query_id] = clone_ballistic_result(cached)
            continue

        raise ValueError(f"Unsupported bot query type: {type(query).__name__}")

    return out, stats
