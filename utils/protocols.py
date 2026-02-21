"""Typing protocols for engine and control interfaces."""

from __future__ import annotations

from typing import Protocol, TYPE_CHECKING

if TYPE_CHECKING:
    from core.maths import Vector2


ControlTuple = tuple[float | None, float | None, bool]


class EngineProtocol(Protocol):
    def set_lander_mass(self, mass: float) -> None: ...

    def set_lander_controls(self, thrust_force: float, angle: float) -> None: ...

    def override(self, angle: float) -> None: ...

    def apply_force(
        self,
        force: Vector2 | tuple[float, float],
        point: Vector2 | tuple[float, float] | None = None,
    ) -> None: ...

    def step(self, dt: float) -> None: ...

    def get_pose(self) -> tuple[Vector2, float]: ...

    def get_velocity(self) -> tuple[Vector2, float]: ...

    def get_contact_report(self) -> dict: ...

    def teleport_lander(
        self,
        pos: Vector2 | tuple[float, float],
        angle: float | None = None,
        clear_velocity: bool = True,
    ) -> None: ...

    def raycast(
        self,
        origin: Vector2 | tuple[float, float],
        angle: float,
        max_distance: float,
    ) -> dict: ...
