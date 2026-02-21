"""Typing protocols for engine and control interfaces."""

from __future__ import annotations

from typing import Protocol, TYPE_CHECKING

if TYPE_CHECKING:
    from core.maths import Vector2


ControlTuple = tuple[float | None, float | None, bool]


class EngineProtocol(Protocol):
    def set_lander_mass(self, mass: float, uid: str | None = None) -> None: ...

    def set_lander_controls(
        self, thrust_force: float, angle: float, uid: str | None = None
    ) -> None: ...

    def override(self, angle: float, uid: str | None = None) -> None: ...

    def apply_force(
        self,
        force: Vector2,
        point: Vector2 | None = None,
        uid: str | None = None,
    ) -> None: ...

    def step(self, dt: float) -> None: ...

    def get_pose(self, uid: str | None = None) -> tuple[Vector2, float]: ...

    def get_velocity(self, uid: str | None = None) -> tuple[Vector2, float]: ...

    def get_contact_report(self, uid: str | None = None) -> dict: ...

    def teleport_lander(
        self,
        pos: Vector2,
        angle: float | None = None,
        clear_velocity: bool = True,
        uid: str | None = None,
    ) -> None: ...

    def raycast(
        self,
        origin: Vector2,
        angle: float,
        max_distance: float,
        uid: str | None = None,
    ) -> dict: ...
