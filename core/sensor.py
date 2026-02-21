from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any
from collections import OrderedDict
from .maths import Range1D, Vector2


def closest_point_on_terrain(
    height_at: Any,
    pos: Vector2,
    lod: int = 0,
    search_radius: float = 200.0,
) -> tuple[float, float, float]:
    """Find the closest point on the terrain polyline to (x,y).

    Samples the height function at a step derived from the terrain resolution
    (via get_resolution when available), builds local segments, and projects
    the query point onto each segment to find the closest point.
    Returns (closest_x, closest_y, euclidean_distance).
    """

    def _get_res(obj, level: int) -> float:
        try:
            return max(1e-6, float(obj.get_resolution(level)))
        except Exception:
            return 2.0

    def _sample(obj, xx: float, level: int) -> float:
        try:
            return float(obj(xx, level))
        except TypeError:
            return float(obj(xx))
        except Exception:
            return float("nan")

    x, y = pos.x, pos.y

    step = _get_res(height_at, lod)
    min_x = x - search_radius
    max_x = x + search_radius

    points: list[tuple[float, float]] = []
    sx = min_x
    while sx <= max_x:
        points.append((sx, _sample(height_at, sx, lod)))
        sx += step
    if points and points[-1][0] < max_x:
        points.append((max_x, _sample(height_at, max_x, lod)))

    def _closest_on_segment(
        ax: float, ay: float, bx: float, by: float, px: float, py: float
    ) -> tuple[float, float]:
        abx, aby = bx - ax, by - ay
        apx, apy = px - ax, py - ay
        ab2 = abx * abx + aby * aby
        if ab2 == 0:
            return ax, ay
        t = (apx * abx + apy * aby) / ab2
        t = max(0.0, min(1.0, t))
        return ax + abx * t, ay + aby * t

    best_dx2 = float("inf")
    best = (x, _sample(height_at, x, lod))
    for i in range(1, len(points)):
        cx, cy = _closest_on_segment(
            points[i - 1][0], points[i - 1][1], points[i][0], points[i][1], x, y
        )
        dx = cx - x
        dy = cy - y
        d2 = dx * dx + dy * dy
        if d2 < best_dx2:
            best_dx2 = d2
            best = (cx, cy)
    return best[0], best[1], math.sqrt(best_dx2)


@dataclass
class RadarContact:
    x: float | None
    y: float | None
    size: float | None
    angle: float
    distance: float | None
    info: dict | None


def get_radar_contacts(
    pos: Vector2,
    sites,
    inner_range: float = 1000.0,
    outer_range: float = 2000.0,
) -> list[RadarContact]:
    x, y = pos.x, pos.y
    tgts = sites.get_sites(Range1D.from_center(x, outer_range))
    contacts: list[RadarContact] = []
    for t in tgts:
        dx = t.x - x
        dy = t.y - y
        dist = math.hypot(dx, dy)
        if dist <= outer_range:
            angle = math.atan2(dy, dx)
            tx = t.x if dist <= inner_range else None
            ty = t.y if dist <= inner_range else None
            ts = t.size if dist <= inner_range else None
            td = dist if dist <= inner_range else None
            ti = t.info if dist <= inner_range else None
            contacts.append(RadarContact(tx, ty, ts, angle, td, ti))

    # Sort by distance (unknown last)
    def _sort_key(c: RadarContact):
        return c.distance if c.distance is not None else float("inf")

    contacts.sort(key=_sort_key)
    return contacts


@dataclass
class ProximityCache:
    capacity: int = 256
    quantize: float = 1.0
    store: OrderedDict[tuple[float, float, float], tuple[float, float, float]] = field(
        default_factory=OrderedDict
    )


# Module-level proximity cache (transparent to callers)
_PROX_CACHE = ProximityCache()


@dataclass
class ProximityContact:
    x: float
    y: float
    angle: float
    distance: float


def get_proximity_contact(
    pos: Vector2,
    terrain,
    range: float = 500.0,
) -> ProximityContact | None:
    x, y = pos.x, pos.y
        
    # Cache check (LRU keyed by quantized x,y,range)
    cache = _PROX_CACHE
    q = max(1e-6, float(cache.quantize))
    key = (round(x / q) * q, round(y / q) * q, round(range / q) * q)
    if key in cache.store:
        result = cache.store.pop(key)
        cache.store[key] = result  # mark as most-recent
        cx, cy, dist = result
        # Respect range on cache hits
        if not math.isfinite(dist) or dist > range:
            return None
        angle = math.atan2(cy - y, cx - x)
        return ProximityContact(cx, cy, angle, dist)

    cx, cy, dist = closest_point_on_terrain(terrain, pos, search_radius=range)

    # If no point is within range, return None and do not cache
    if not math.isfinite(dist) or dist > range:
        return None

    # Update cache
    # insert/update and enforce capacity (LRU eviction)
    if key in cache.store:
        cache.store.pop(key)
    cache.store[key] = (cx, cy, dist)
    while len(cache.store) > max(1, int(cache.capacity)):
        cache.store.popitem(last=False)

    angle = math.atan2(cy - y, cx - x)
    return ProximityContact(cx, cy, angle, dist)
