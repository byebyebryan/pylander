"""Shared sideburn shaping helpers."""

from __future__ import annotations

from bots._bot_math import clamp


def resolve_sideburn_target_angle(
    *,
    projected_dx: float,
    cone_limit: float,
    vy_up: float,
    base_angle: float,
    min_angle: float,
    max_angle: float,
    upward_vy_target: float,
    upward_angle_gain: float,
) -> float:
    """Compute sideburn angle magnitude with optional climb bias."""
    low = min(min_angle, max_angle)
    high = max(min_angle, max_angle)
    base = clamp(base_angle, low, high)
    if high - low <= 1e-6:
        return base

    miss_ratio = clamp(abs(projected_dx) / max(1.0, cone_limit), 0.0, 2.0)
    center_bias = 0.16 * clamp(1.0 - miss_ratio, 0.0, 1.0)
    climb_target = max(0.0, upward_vy_target)
    climb_gap = max(0.0, climb_target - float(vy_up))
    climb_bias = upward_angle_gain * (climb_gap / max(1.0, climb_target))
    angle_mag = base - center_bias - clamp(climb_bias, 0.0, 0.28)
    return clamp(angle_mag, low, high)


__all__ = ["resolve_sideburn_target_angle"]
