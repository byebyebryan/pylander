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
    uid: str | None
    x: float
    y: float
    size: float
    angle: float
    distance: float
    rel_x: float
    rel_y: float
    is_inner_lock: bool
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
            contacts.append(
                RadarContact(
                    uid=getattr(t, "uid", None),
                    x=float(t.x),
                    y=float(t.y),
                    size=float(t.size),
                    angle=angle,
                    distance=dist,
                    rel_x=dx,
                    rel_y=dy,
                    is_inner_lock=dist <= inner_range,
                    info=getattr(t, "info", None),
                )
            )

    # Sort by distance (unknown last)
    def _sort_key(c: RadarContact):
        return c.distance

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
    normal_x: float
    normal_y: float
    terrain_slope: float


def get_proximity_contact(
    pos: Vector2,
    terrain,
    range: float = 500.0,
) -> ProximityContact | None:
    def _sample_terrain(obj, xx: float, lod: int = 0) -> float:
        try:
            return float(obj(xx, lod))
        except TypeError:
            return float(obj(xx))

    def _terrain_resolution(obj, lod: int = 0) -> float:
        get_resolution = getattr(obj, "get_resolution", None)
        if callable(get_resolution):
            try:
                return max(0.5, float(get_resolution(lod)))
            except Exception:
                return 2.0
        return 2.0

    def _surface_metrics(obj, xx: float) -> tuple[float, float, float]:
        step = _terrain_resolution(obj, lod=0)
        y0 = _sample_terrain(obj, xx - step, lod=0)
        y1 = _sample_terrain(obj, xx + step, lod=0)
        slope = (y1 - y0) / (2.0 * step)
        nx, ny = -slope, 1.0
        nlen = math.hypot(nx, ny)
        if nlen <= 1e-9:
            return 0.0, 1.0, slope
        return nx / nlen, ny / nlen, slope

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
        nx, ny, slope = _surface_metrics(terrain, cx)
        return ProximityContact(cx, cy, angle, dist, nx, ny, slope)

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
    nx, ny, slope = _surface_metrics(terrain, cx)
    return ProximityContact(cx, cy, angle, dist, nx, ny, slope)
