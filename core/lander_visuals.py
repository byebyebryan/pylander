"""Visual data types for lander rendering."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Thrust:
    """Thrust flame descriptor for rendering."""
    x: float
    y: float
    angle: float
    width: float
    length: float
    power: float
