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


BotQuery: TypeAlias = BotQueryRaycast | BotQueryTerrainProfile


@dataclass(frozen=True)
class RaycastResult:
    hit: bool
    distance: float | None
    hit_x: float
    hit_y: float


@dataclass(frozen=True)
class TerrainProfileResult:
    points: list[tuple[float, float]]


BotQueryResult: TypeAlias = RaycastResult | TerrainProfileResult
BotQueryResults: TypeAlias = dict[str, BotQueryResult]
