"""Typed bot query/request and response payloads for batched sensor evaluation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypeAlias


@dataclass(frozen=True)
class BotQueryRaycast:
    id: str
    dir_angle: float
    max_range: float | None = None


@dataclass(frozen=True)
class BotQueryTerrainProfile:
    id: str
    x_start: float
    x_end: float
    samples: int = 16
    lod: int = 0


@dataclass(frozen=True)
class BotQueryBallistic:
    id: str
    x: float
    y: float
    vx: float
    vy_up: float
    max_distance: float = 3000.0
    segment_length: float = 24.0
    max_points: int = 256
    lod: int = 0
    clearance: float = 0.0


BotQuery: TypeAlias = BotQueryRaycast | BotQueryTerrainProfile | BotQueryBallistic


@dataclass(frozen=True)
class RaycastResult:
    hit: bool
    distance: float | None
    hit_x: float
    hit_y: float


@dataclass(frozen=True)
class TerrainProfileResult:
    points: list[tuple[float, float]]


@dataclass(frozen=True)
class BallisticResult:
    points: list[tuple[float, float]]
    hit: bool
    hit_x: float | None
    hit_y: float | None
    hit_time: float | None
    hit_vx: float | None
    hit_vy_up: float | None
    hit_speed: float | None
    distance: float
    duration: float
    termination: str


BotQueryResult: TypeAlias = RaycastResult | TerrainProfileResult | BallisticResult
BotQueryResults: TypeAlias = dict[str, BotQueryResult]


def clone_ballistic_result(result: BallisticResult) -> BallisticResult:
    # Copy list payloads so callers can mutate without corrupting cache entries.
    return BallisticResult(
        points=list(result.points),
        hit=result.hit,
        hit_x=result.hit_x,
        hit_y=result.hit_y,
        hit_time=result.hit_time,
        hit_vx=result.hit_vx,
        hit_vy_up=result.hit_vy_up,
        hit_speed=result.hit_speed,
        distance=result.distance,
        duration=result.duration,
        termination=result.termination,
    )
