"""Shared guidance data types used across bot phases."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GuidanceTargets:
    phase: str
    vertical_mode: str
    vx_sp: float
    vy_sp: float
    dx: float
    alt: float
    burn_altitude: float


__all__ = ["GuidanceTargets"]
