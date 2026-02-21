"""Adapter around the physics engine for a stable game-loop API."""

from __future__ import annotations

from utils.protocols import EngineProtocol
from core.maths import Vector2


class EngineAdapter:
    """Thin adapter that normalizes engine access and no-ops when missing."""

    def __init__(self, engine: EngineProtocol | None):
        self._engine = engine
        self._primary_actor_uid: str | None = None

    @property
    def enabled(self) -> bool:
        return self._engine is not None

    def set_lander_mass(self, mass: float) -> None:
        if self._engine is not None:
            try:
                self._engine.set_lander_mass(mass, uid=self._primary_actor_uid)
            except TypeError:
                self._engine.set_lander_mass(mass)

    def set_lander_controls(self, thrust_force: float, angle: float) -> None:
        if self._engine is not None:
            try:
                self._engine.set_lander_controls(
                    thrust_force, angle, uid=self._primary_actor_uid
                )
            except TypeError:
                self._engine.set_lander_controls(thrust_force, angle)

    def set_actor_mass(self, uid: str, mass: float) -> None:
        if self._engine is not None:
            try:
                self._engine.set_lander_mass(mass, uid=uid)
            except TypeError:
                self._engine.set_lander_mass(mass)

    def set_actor_controls(self, uid: str, thrust_force: float, angle: float) -> None:
        if self._engine is not None:
            try:
                self._engine.set_lander_controls(thrust_force, angle, uid=uid)
            except TypeError:
                self._engine.set_lander_controls(thrust_force, angle)

    def override(self, angle: float, uid: str | None = None) -> None:
        if self._engine is not None and hasattr(self._engine, "override"):
            try:
                self._engine.override(
                    angle, uid=uid if uid is not None else self._primary_actor_uid
                )
            except TypeError:
                self._engine.override(angle)

    def override_for(self, uid: str, angle: float) -> None:
        self.override(angle, uid=uid)

    def apply_force(
        self, force: Vector2, point: Vector2 | None = None, uid: str | None = None
    ) -> None:
        if self._engine is not None and hasattr(self._engine, "apply_force"):
            try:
                self._engine.apply_force(
                    force,
                    point,
                    uid=uid if uid is not None else self._primary_actor_uid,
                )
            except TypeError:
                self._engine.apply_force(force, point)

    def apply_force_for(
        self, uid: str, force: Vector2, point: Vector2 | None = None
    ) -> None:
        self.apply_force(force, point=point, uid=uid)

    def step(self, dt: float) -> None:
        if self._engine is not None:
            self._engine.step(dt)

    def get_pose(self, uid: str | None = None) -> tuple[Vector2, float]:
        if self._engine is None:
            return Vector2(0.0, 0.0), 0.0
        try:
            return self._engine.get_pose(
                uid=uid if uid is not None else self._primary_actor_uid
            )
        except TypeError:
            return self._engine.get_pose()

    def get_velocity(self, uid: str | None = None) -> tuple[Vector2, float]:
        if self._engine is None:
            return Vector2(0.0, 0.0), 0.0
        try:
            return self._engine.get_velocity(
                uid=uid if uid is not None else self._primary_actor_uid
            )
        except TypeError:
            return self._engine.get_velocity()

    def get_contact_report(self, uid: str | None = None) -> dict:
        if self._engine is None:
            return {
                "colliding": False,
                "normal": None,
                "rel_speed": 0.0,
                "point": None,
            }
        try:
            return self._engine.get_contact_report(
                uid=uid if uid is not None else self._primary_actor_uid
            )
        except TypeError:
            return self._engine.get_contact_report()

    def teleport_lander(
        self,
        pos: Vector2,
        angle: float | None = None,
        clear_velocity: bool = True,
        uid: str | None = None,
    ) -> None:
        if self._engine is not None:
            try:
                self._engine.teleport_lander(
                    pos,
                    angle=angle,
                    clear_velocity=clear_velocity,
                    uid=uid if uid is not None else self._primary_actor_uid,
                )
            except TypeError:
                self._engine.teleport_lander(
                    pos, angle=angle, clear_velocity=clear_velocity
                )

    def teleport_actor(
        self,
        uid: str,
        pos: Vector2,
        angle: float | None = None,
        clear_velocity: bool = True,
    ) -> None:
        self.teleport_lander(pos, angle=angle, clear_velocity=clear_velocity, uid=uid)

    def raycast(
        self,
        origin: Vector2,
        angle: float,
        max_distance: float,
        uid: str | None = None,
    ) -> dict:
        if self._engine is None:
            return {"hit": False, "hit_x": 0.0, "hit_y": 0.0, "distance": None}
        try:
            return self._engine.raycast(
                origin,
                angle,
                max_distance,
                uid=uid if uid is not None else self._primary_actor_uid,
            )
        except TypeError:
            return self._engine.raycast(origin, angle, max_distance)

    def set_primary_actor(self, uid: str | None) -> None:
        self._primary_actor_uid = uid
        if self._engine is not None and hasattr(self._engine, "set_primary_actor"):
            self._engine.set_primary_actor(uid)

    def get_actor_uids(self) -> set[str]:
        if self._engine is None or not hasattr(self._engine, "get_actor_uids"):
            return set()
        return set(self._engine.get_actor_uids())
