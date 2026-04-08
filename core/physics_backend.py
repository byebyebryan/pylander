"""Physics backend protocol and factory."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Protocol, TypeAlias

from core.components import ContactReport

Segment: TypeAlias = tuple[tuple[float, float], tuple[float, float]]


@dataclass(frozen=True)
class BodyState:
    """Immutable snapshot of a body's kinematic state."""

    position: tuple[float, float]
    angle: float
    velocity: tuple[float, float]
    angular_velocity: float


@dataclass(frozen=True)
class RaycastHit:
    """Result of a ray/segment query."""

    hit: bool
    point_x: float = 0.0
    point_y: float = 0.0
    distance: float | None = None


class PhysicsBackend(Protocol):
    """Low-level physics primitives.

    The backend owns the simulation space, bodies, and shapes.
    The engine drives it via this interface.
    """

    def configure(self, gravity: tuple[float, float]) -> None:
        """Set gravity. Called once at creation."""
        ...

    def create_body(
        self,
        uid: str,
        mass: float,
        moment: float,
        polygons: list[list[tuple[float, float]]],
        position: tuple[float, float],
        angle: float,
        friction: float,
        elasticity: float,
    ) -> None:
        """Create a dynamic body with one or more convex polygon shapes."""
        ...

    def remove_body(self, uid: str) -> None:
        """Remove a body and all its shapes."""
        ...

    def set_mass(self, uid: str, mass: float) -> None:
        """Update body mass."""
        ...

    def set_position(self, uid: str, pos: tuple[float, float]) -> None:
        """Teleport body position."""
        ...

    def set_angle(self, uid: str, angle: float) -> None:
        """Set body angle directly."""
        ...

    def set_velocity(self, uid: str, vel: tuple[float, float], angular: float) -> None:
        """Set body velocity directly."""
        ...

    def apply_force(self, uid: str, force: tuple[float, float]) -> None:
        """Apply a force at body center for the next step."""
        ...

    def add_segments(
        self,
        segments: list[tuple[tuple[float, float], tuple[float, float]]],
        friction: float,
        elasticity: float,
        radius: float = 1.0,
    ) -> list[int]:
        """Add static line segments. Returns handle IDs."""
        ...

    def remove_segments(self, handles: list[int]) -> None:
        """Remove segments by handle."""
        ...

    def step(self, dt: float) -> dict[str, ContactReport]:
        """Advance simulation by dt. Returns contact reports keyed by actor UID."""
        ...

    def get_state(self, uid: str) -> BodyState:
        """Read current body state."""
        ...

    def raycast(
        self,
        origin: tuple[float, float],
        endpoint: tuple[float, float],
        ignore_uid: str | None,
    ) -> RaycastHit | None:
        """Segment query. Returns a backend hit or None."""
        ...

    @staticmethod
    def moment_for_poly(mass: float, verts: list[tuple[float, float]]) -> float:
        """Compute rotational inertia for a polygon."""
        ...


def default_backend() -> PhysicsBackend:
    """Select backend based on environment."""
    import sys

    explicit = os.environ.get("PYLANDER_PHYSICS")
    if explicit == "pymunk":
        import core.physics_pymunk

        return core.physics_pymunk.PymunkBackend()
    if explicit == "euler":
        from core.physics_euler import EulerBackend

        return EulerBackend()
    if explicit is not None:
        raise ValueError(f"Unknown PYLANDER_PHYSICS value: {explicit!r}")
    if sys.platform == "emscripten":
        from core.physics_euler import EulerBackend

        return EulerBackend()
    import core.physics_pymunk

    return core.physics_pymunk.PymunkBackend()
