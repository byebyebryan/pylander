"""Adapter around the physics engine for a stable game-loop API."""

from __future__ import annotations

from utils.protocols import EngineProtocol
from core.components import ContactReport
from core.maths import Vector2


class EngineAdapter:
    """Thin adapter that normalizes engine access and no-ops when missing."""

    def __init__(self, engine: EngineProtocol | None):
        self._engine = engine
        self._primary_actor_uid: str | None = None
        self._uid_supported: bool | None = None  # probed once on first call

    @property
    def enabled(self) -> bool:
        return self._engine is not None

    def _resolve_uid(self, uid: str | None) -> str | None:
        return self._primary_actor_uid if uid is None else uid

    def _call_engine(
        self,
        method_name: str,
        *args,
        uid: str | None = None,
        default=None,
        **kwargs,
    ):
        if self._engine is None:
            return default
        method = getattr(self._engine, method_name, None)
        if not callable(method):
            return default
        resolved_uid = self._resolve_uid(uid)
        if resolved_uid is not None and self._uid_supported is not False:
            try:
                result = method(*args, uid=resolved_uid, **kwargs)
                if self._uid_supported is None:
                    self._uid_supported = True
                return result
            except TypeError:
                self._uid_supported = False
        return method(*args, **kwargs)

    def set_lander_mass(self, mass: float) -> None:
        self._call_engine("set_lander_mass", mass)

    def set_lander_controls(self, thrust_force: float, angle: float) -> None:
        self._call_engine("set_lander_controls", thrust_force, angle)

    def set_actor_mass(self, uid: str, mass: float) -> None:
        self._call_engine("set_lander_mass", mass, uid=uid)

    def set_actor_controls(self, uid: str, thrust_force: float, angle: float) -> None:
        self._call_engine("set_lander_controls", thrust_force, angle, uid=uid)

    def set_lander_velocity(
        self,
        velocity: Vector2,
        angular_velocity: float = 0.0,
        uid: str | None = None,
    ) -> None:
        self._call_engine(
            "set_lander_velocity",
            velocity,
            angular_velocity=angular_velocity,
            uid=uid,
        )

    def set_actor_velocity(
        self,
        uid: str,
        velocity: Vector2,
        angular_velocity: float = 0.0,
    ) -> None:
        self.set_lander_velocity(velocity, angular_velocity=angular_velocity, uid=uid)

    def override(self, angle: float, uid: str | None = None) -> None:
        self._call_engine("override", angle, uid=uid)

    def override_for(self, uid: str, angle: float) -> None:
        self.override(angle, uid=uid)

    def apply_force(
        self, force: Vector2, point: Vector2 | None = None, uid: str | None = None
    ) -> None:
        self._call_engine("apply_force", force, point, uid=uid)

    def apply_force_for(
        self, uid: str, force: Vector2, point: Vector2 | None = None
    ) -> None:
        self.apply_force(force, point=point, uid=uid)

    def step(self, dt: float) -> None:
        if self._engine is not None:
            self._engine.step(dt)

    def get_pose(self, uid: str | None = None) -> tuple[Vector2, float]:
        return self._call_engine("get_pose", uid=uid, default=(Vector2(0.0, 0.0), 0.0))

    def get_velocity(self, uid: str | None = None) -> tuple[Vector2, float]:
        return self._call_engine(
            "get_velocity",
            uid=uid,
            default=(Vector2(0.0, 0.0), 0.0),
        )

    def get_contact_report(self, uid: str | None = None) -> ContactReport:
        return self._call_engine(
            "get_contact_report",
            uid=uid,
            default=ContactReport(),
        )

    def teleport_lander(
        self,
        pos: Vector2,
        angle: float | None = None,
        clear_velocity: bool = True,
        uid: str | None = None,
    ) -> None:
        self._call_engine(
            "teleport_lander",
            pos,
            angle=angle,
            clear_velocity=clear_velocity,
            uid=uid,
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
        return self._call_engine(
            "raycast",
            origin,
            angle,
            max_distance,
            uid=uid,
            default={"hit": False, "hit_x": 0.0, "hit_y": 0.0, "distance": None},
        )

    def set_primary_actor(self, uid: str | None) -> None:
        self._primary_actor_uid = uid
        if self._engine is not None and hasattr(self._engine, "set_primary_actor"):
            self._engine.set_primary_actor(uid)

    def get_actor_uids(self) -> set[str]:
        if self._engine is None or not hasattr(self._engine, "get_actor_uids"):
            return set()
        return set(self._engine.get_actor_uids())
