"""Shared radar target-selection helpers."""

from __future__ import annotations

import math

from core.bot import PassiveSensors
from core.sensor import RadarContact


def pick_target(passive: PassiveSensors) -> RadarContact | None:
    """Select the first radar contact (eval levels currently expose one target)."""
    contacts = passive.radar_contacts or []
    if not contacts:
        return None
    return contacts[0]


def target_half_width(target_size: float | None) -> float:
    """Return a safe half-width for target-center tolerance checks."""
    if target_size is None:
        return 55.0
    try:
        numeric = abs(float(target_size))
    except (TypeError, ValueError):
        return 55.0
    if not math.isfinite(numeric):
        return 55.0
    return max(6.0, 0.5 * numeric)

