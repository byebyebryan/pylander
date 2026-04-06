"""Shared numeric and behavior-selection helpers for bots."""

from __future__ import annotations

import math
from typing import Mapping, TypeVar

from core.bot import Sensors, VehicleInfo
from core.config import GRAVITY_MAG

_BehaviorT = TypeVar("_BehaviorT")
_GRAVITY_MAG = GRAVITY_MAG


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def stable(value: float, digits: int = 1) -> float:
    epsilon = 0.5 * (10.0 ** (-digits))
    return 0.0 if abs(value) < epsilon else value


def coerce_finite(value: float | None, default: float = 0.0) -> float:
    if value is None:
        return default
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(numeric):
        return default
    return numeric


def finite_altitude(passive: Sensors) -> float:
    if math.isfinite(passive.altitude):
        return passive.altitude
    return 1e9


def normalize_behavior_key(behavior: str) -> str:
    return str(behavior).strip().lower().replace("-", "_")


def resolve_behavior(
    behavior: str,
    behaviors: Mapping[str, _BehaviorT],
    *,
    context: str,
) -> tuple[str, _BehaviorT]:
    key = normalize_behavior_key(behavior)
    if key not in behaviors:
        known = ", ".join(sorted(behaviors))
        raise ValueError(
            f"Unknown {context} behavior '{behavior}'. Expected one of: {known}"
        )
    return key, behaviors[key]


def vehicle_limits(passive: Sensors, max_force: float) -> tuple[float, float]:
    mass = max(0.5, passive.mass)
    up_acc_max = max(0.1, (max_force / mass) - _GRAVITY_MAG)
    return mass, up_acc_max


def engine_profile(
    vehicle_info: VehicleInfo | None,
) -> tuple[float, float, float, float]:
    if vehicle_info is None:
        # Keep fallback aligned with Engine defaults in SI-like units.
        return 240000.0, 0.25, 1.6, 1.1
    max_power = max(1e-3, float(vehicle_info.max_thrust_power))
    max_throttle = max(0.0, float(vehicle_info.max_thrust))
    min_throttle = max(0.0, min(float(vehicle_info.min_thrust), max_throttle))
    ramp_up = max(0.1, float(vehicle_info.thrust_increase_rate))
    return max_power, min_throttle, max_throttle, ramp_up


def rate_limit_angle_command(
    target_angle: float,
    prev_angle: float,
    dt: float,
    *,
    max_rate: float = 2.2,
) -> float:
    max_delta = max_rate * max(dt, 1e-3)
    delta = (target_angle - prev_angle + math.pi) % (2.0 * math.pi) - math.pi
    limited_delta = clamp(delta, -max_delta, max_delta)
    limited = prev_angle + limited_delta
    return (limited + math.pi) % (2.0 * math.pi) - math.pi


def retrograde_angle_target(*, vx: float, vy_up: float) -> float:
    speed = math.hypot(float(vx), float(vy_up))
    if speed <= 1e-3:
        return 0.0
    return math.atan2(-float(vx), -float(vy_up))
