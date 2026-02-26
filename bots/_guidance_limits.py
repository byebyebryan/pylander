"""Shared guidance safety/limit helpers."""

from __future__ import annotations

from typing import Protocol

from bots._bot_math import clamp


class LowAltitudeAngleLimitConfig(Protocol):
    low_altitude_angle_limit_alt: float
    low_altitude_angle_limit_dx: float
    low_altitude_angle_cap: float


def cap_low_altitude_angle(
    target_angle: float,
    *,
    alt: float,
    dx: float,
    cfg: LowAltitudeAngleLimitConfig,
) -> float:
    if alt <= cfg.low_altitude_angle_limit_alt and abs(dx) <= cfg.low_altitude_angle_limit_dx:
        cap = cfg.low_altitude_angle_cap
        return clamp(target_angle, -cap, cap)
    return target_angle


__all__ = ["LowAltitudeAngleLimitConfig", "cap_low_altitude_angle"]
