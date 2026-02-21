"""Adapter around the physics engine for a stable game-loop API."""

from __future__ import annotations

from utils.protocols import EngineProtocol
from core.maths import Vector2


class EngineAdapter:
    """Thin adapter that normalizes engine access and no-ops when missing."""

    def __init__(self, engine: EngineProtocol | None):
        self._engine = engine

    @property
    def enabled(self) -> bool:
        return self._engine is not None

    def set_lander_mass(self, mass: float) -> None:
        if self._engine is not None:
            self._engine.set_lander_mass(mass)

    def set_lander_controls(self, thrust_force: float, angle: float) -> None:
        if self._engine is not None:
            self._engine.set_lander_controls(thrust_force, angle)

    def override(self, angle: float) -> None:
        if self._engine is not None and hasattr(self._engine, "override"):
            self._engine.override(angle)

    def apply_force(
        self, force: Vector2, point: Vector2 | None = None
    ) -> None:
        if self._engine is not None and hasattr(self._engine, "apply_force"):
            self._engine.apply_force(force, point)

    def step(self, dt: float) -> None:
        if self._engine is not None:
            self._engine.step(dt)

    def get_pose(self) -> tuple[Vector2, float]:
        if self._engine is None:
            return Vector2(0.0, 0.0), 0.0
        return self._engine.get_pose()

    def get_velocity(self) -> tuple[Vector2, float]:
        if self._engine is None:
            return Vector2(0.0, 0.0), 0.0
        return self._engine.get_velocity()

    def get_contact_report(self) -> dict:
        if self._engine is None:
            return {
                "colliding": False,
                "normal": None,
                "rel_speed": 0.0,
                "point": None,
            }
        return self._engine.get_contact_report()

    def teleport_lander(
        self,
        pos: Vector2,
        angle: float | None = None,
        clear_velocity: bool = True,
    ) -> None:
        if self._engine is not None:
            self._engine.teleport_lander(pos, angle=angle, clear_velocity=clear_velocity)

    def raycast(self, origin: Vector2, angle: float, max_distance: float) -> dict:
        if self._engine is None:
            return {"hit": False, "hit_x": 0.0, "hit_y": 0.0, "distance": None}
        return self._engine.raycast(origin, angle, max_distance)
