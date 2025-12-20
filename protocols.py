"""Typing protocols for engine and control interfaces."""

from __future__ import annotations

from typing import Protocol


ControlTuple = tuple[float | None, float | None, bool]


class EngineProtocol(Protocol):
    def set_lander_mass(self, mass: float) -> None: ...

    def set_lander_controls(self, thrust_force: float, angle: float) -> None: ...

    def override(self, angle: float) -> None: ...

    def apply_force(
        self,
        fx: float,
        fy: float,
        angle: float | None = None,
        power: float | None = None,
    ) -> None: ...

    def step(self, dt: float) -> None: ...

    def get_pose(self) -> tuple[float, float, float]: ...

    def get_velocity(self) -> tuple[float, float, float]: ...

    def get_contact_report(self) -> dict: ...

    def teleport_lander(
        self,
        x: float,
        y: float,
        angle: float | None = None,
        clear_velocity: bool = True,
    ) -> None: ...

    def raycast(
        self, origin_xy: tuple[float, float], angle: float, max_distance: float
    ) -> dict: ...
