"""Analytic ballistic projection and time helpers for bot planning."""

from __future__ import annotations

import math
from dataclasses import dataclass

from bots._bot_math import coerce_finite
from core.config import GRAVITY
from core.terrain import ballistic_fall_time

_GRAVITY_MAG = abs(float(GRAVITY))


@dataclass(frozen=True)
class BallisticProjection:
    projected_dx: float
    t_fall: float
    target_x: float | None
    impact_x: float | None
    has_target_y_solution: bool = True


@dataclass(frozen=True)
class BallisticApex:
    t_apex: float
    x_apex: float | None
    y_apex: float


def ballistic_apex_from_state(
    *,
    x: float | None,
    y: float,
    vx: float | None,
    vy_up: float | None,
    gravity_mag: float = _GRAVITY_MAG,
) -> BallisticApex:
    """Return ballistic apex time/position relative to current kinematic state."""
    safe_x = coerce_finite(x, float("nan"))
    safe_y = coerce_finite(y, 0.0)
    safe_vx = coerce_finite(vx, 0.0)
    safe_vy = coerce_finite(vy_up, 0.0)
    g = max(0.0, coerce_finite(gravity_mag, _GRAVITY_MAG))

    t_apex = 0.0 if g <= 1e-6 else (safe_vy / g)
    x_apex = (safe_x + (safe_vx * t_apex)) if math.isfinite(safe_x) else None
    y_apex = safe_y + (safe_vy * t_apex) - (0.5 * g * t_apex * t_apex)
    return BallisticApex(t_apex=t_apex, x_apex=x_apex, y_apex=y_apex)


def time_to_target_y_crossing(
    *,
    dy: float,
    vy_up: float,
    gravity_mag: float,
    prefer_descending: bool,
) -> tuple[float | None, bool]:
    """Return ballistic time to y==target_y and whether a real crossing exists."""
    safe_dy = coerce_finite(dy, 0.0)
    safe_vy = coerce_finite(vy_up, 0.0)
    g = max(0.0, coerce_finite(gravity_mag, _GRAVITY_MAG))
    eps = 1e-6

    if g <= eps:
        if abs(safe_vy) <= eps:
            if abs(safe_dy) <= eps:
                return 0.0, True
            return None, False
        t_lin = safe_dy / safe_vy
        if t_lin >= 0.0:
            return t_lin, True
        return None, False

    disc = (safe_vy * safe_vy) - (2.0 * g * safe_dy)
    if disc < -eps:
        return None, False
    disc = max(0.0, disc)
    sqrt_disc = math.sqrt(disc)
    roots = sorted(((safe_vy - sqrt_disc) / g, (safe_vy + sqrt_disc) / g))
    positive = [t for t in roots if t >= 0.0]
    if not positive:
        return None, False

    if prefer_descending and len(positive) >= 2 and safe_dy >= 0.0:
        return positive[-1], True
    future = [t for t in positive if t > 1e-4]
    if future:
        return future[0], True
    return positive[0], True


def estimate_target_y_projection(
    *,
    dx: float,
    dy: float,
    vx: float | None,
    vy_up: float | None,
    x: float | None,
    y: float,
    min_t_fall: float = 0.5,
    gravity_mag: float = _GRAVITY_MAG,
    prefer_descending: bool = True,
) -> BallisticProjection:
    """Estimate projected lateral error at ballistic crossing of target_y.

    If target_y is unreachable ballistically (apex below target), returns
    `has_target_y_solution=False` and projects to ballistic apex time.
    """
    safe_dx = coerce_finite(dx, 0.0)
    safe_dy = coerce_finite(dy, 0.0)
    safe_vx = coerce_finite(vx, 0.0)
    safe_vy = coerce_finite(vy_up, 0.0)
    safe_x = coerce_finite(x, float("nan"))
    safe_y = coerce_finite(y, 0.0)

    target_x: float | None = None
    target_y = safe_y + safe_dy
    if math.isfinite(safe_x):
        target_x = safe_x + safe_dx

    apex = ballistic_apex_from_state(
        x=safe_x,
        y=safe_y,
        vx=safe_vx,
        vy_up=safe_vy,
        gravity_mag=gravity_mag,
    )
    if safe_dy > 0.0 and (apex.t_apex <= 0.0 or apex.y_apex <= target_y):
        return BallisticProjection(
            projected_dx=safe_dx - (safe_vx * apex.t_apex),
            t_fall=max(float(min_t_fall), apex.t_apex),
            target_x=target_x,
            impact_x=apex.x_apex,
            has_target_y_solution=False,
        )

    t_cross, has_solution = time_to_target_y_crossing(
        dy=safe_dy,
        vy_up=safe_vy,
        gravity_mag=gravity_mag,
        prefer_descending=prefer_descending,
    )
    if has_solution and t_cross is not None:
        x_cross = (safe_x + (safe_vx * t_cross)) if math.isfinite(safe_x) else None
        projected_dx = safe_dx - (safe_vx * t_cross)
        return BallisticProjection(
            projected_dx=projected_dx,
            t_fall=max(float(min_t_fall), float(t_cross)),
            target_x=target_x,
            impact_x=x_cross,
            has_target_y_solution=True,
        )

    return BallisticProjection(
        projected_dx=safe_dx - (safe_vx * apex.t_apex),
        t_fall=max(float(min_t_fall), float(apex.t_apex)),
        target_x=target_x,
        impact_x=apex.x_apex,
        has_target_y_solution=False,
    )


def estimate_ground_time_to_impact(
    *,
    altitude: float,
    vy_up: float | None,
    min_t_fall: float = 0.0,
) -> float:
    """Estimate ballistic time-to-ground from current altitude and vertical speed."""
    safe_alt = max(0.0, coerce_finite(altitude, 0.0))
    safe_vy = coerce_finite(vy_up, 0.0)
    return max(float(min_t_fall), ballistic_fall_time(altitude=safe_alt, vy_up=safe_vy))
