"""Shared radar target-selection helpers."""

from __future__ import annotations

from core.bot import PassiveSensors
from core.sensor import RadarContact


def pick_target(passive: PassiveSensors) -> RadarContact | None:
    """Select the first radar contact (eval levels currently expose one target)."""
    contacts = passive.radar_contacts or []
    if not contacts:
        return None
    return contacts[0]

