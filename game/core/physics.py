"""Physics engine with pluggable backend and terrain utilities."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

from game.core.components import ContactReport
from game.core.maths import Vector2
from game.core.physics_backend import PhysicsBackend, RaycastHit, default_backend
from game.core.sensor import closest_point_on_terrain as sensor_closest_point_on_terrain

from game.core.config import GRAVITY

if TYPE_CHECKING:
    from game.core.terrain import Terrain

Segment = tuple[tuple[float, float], tuple[float, float]]


def _polygon_area(poly: list[tuple[float, float]]) -> float:
    area = 0.0
    for i in range(len(poly)):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % len(poly)]
        area += x1 * y2 - x2 * y1
    return abs(area) * 0.5


@dataclass(frozen=True)
class ClosestPointResult:
    """Result of a closest-point-on-terrain query."""

    x: float
    y: float
    distance: float


class PhysicsEngine:
    """Backend-driven physics with a rolling terrain window.

    - World coordinates are x-right, y-up.
    - Terrain is represented by static segments generated from a height
      sampler within a centered window.
    - Supports multiple dynamic bodies (indexed by uid).
    """

    def __init__(
        self,
        height_sampler: Terrain,
        gravity: tuple[float, float] = (0.0, GRAVITY),
        segment_step: float = 10.0,
        half_width: float = 12000.0,
        backend: PhysicsBackend | None = None,
    ) -> None:
        self._backend = backend if backend is not None else default_backend()
        self._backend.configure(gravity)

        self.height_sampler: Terrain = height_sampler
        self.segment_step = max(1.0, float(segment_step))
        self.half_width = max(100.0, float(half_width))

        self._terrain_handles: list[int] = []
        self._terrain_segments: list[Segment] = []
        self._landing_site_handles: list[int] = []
        self._window_center_x: float | None = None

        self._actor_uids: set[str] = set()
        self._contacts: dict[str, ContactReport] = {}
        self._overrides: dict[str, float] = {}
        self._pending_forces: dict[str, tuple[float, float]] = {}
        self._primary_uid: str | None = None

    def attach_body(
        self,
        width: float,
        height: float,
        mass: float,
        uid: str = "lander",
        *,
        friction: float = 0.9,
        elasticity: float = 0.0,
        start_pos: Vector2 | None = None,
        start_angle: float = 0.0,
    ) -> str:
        """Create a dynamic body as a triangle based on width/height.

        Returns actor uid.
        """
        self._remove_actor(uid)
        verts = [
            (0.0, height / 2.0),
            (-width / 2.0, -height / 2.0),
            (width / 2.0, -height / 2.0),
        ]
        moment = self._backend.moment_for_poly(mass, verts)
        position = (start_pos.x, start_pos.y) if start_pos is not None else (0.0, 0.0)
        self._backend.create_body(
            uid, mass, moment, [verts], position, start_angle, friction, elasticity
        )
        self._actor_uids.add(uid)
        self._contacts[uid] = self._empty_contact()
        if self._primary_uid is None:
            self._primary_uid = uid

        state = self._backend.get_state(uid)
        cx = state.position[0]
        self._ensure_window_centered(cx)

        return uid

    def attach_body_from_polygons(
        self,
        polygons: list[list[tuple[float, float]]],
        mass: float,
        uid: str = "lander",
        *,
        friction: float = 0.9,
        elasticity: float = 0.0,
        start_pos: Vector2 | None = None,
        start_angle: float = 0.0,
    ) -> str:
        """Create a dynamic body from one or more convex polygons.

        Polygons are specified in local coordinates (y-up). Mass is distributed
        proportionally to polygon area for inertia calculation.
        """
        self._remove_actor(uid)
        if not polygons:
            return self.attach_body(
                4.0,
                4.0,
                mass,
                uid=uid,
                start_pos=start_pos,
                start_angle=start_angle,
            )

        total_area = 0.0
        for poly in polygons:
            total_area += _polygon_area(poly)

        if total_area <= 0.0:
            total_area = 1.0

        moment = 0.0
        for poly in polygons:
            area = _polygon_area(poly)
            poly_mass = mass * (area / total_area)
            moment += self._backend.moment_for_poly(max(1e-6, poly_mass), poly)

        position = (start_pos.x, start_pos.y) if start_pos is not None else (0.0, 0.0)
        self._backend.create_body(
            uid,
            mass,
            max(moment, 1e-6),
            polygons,
            position,
            start_angle,
            friction,
            elasticity,
        )
        self._actor_uids.add(uid)
        self._contacts[uid] = self._empty_contact()
        if self._primary_uid is None:
            self._primary_uid = uid

        state = self._backend.get_state(uid)
        cx = state.position[0]
        self._ensure_window_centered(cx)

        return uid

    def override(self, angle: float, uid: str | None = None) -> None:
        """Override body pose angle this step (radians)."""
        actor_uid = self._resolve_uid(uid)
        if actor_uid is None:
            return
        self._overrides[actor_uid] = float(angle)

    def apply_force(self, force: Vector2, uid: str | None = None) -> None:
        """Apply a world-space force at the center of mass this step."""
        actor_uid = self._resolve_uid(uid)
        if actor_uid is None:
            return
        self._pending_forces[actor_uid] = (force.x, force.y)

    def step(self, dt: float) -> None:
        if not self._actor_uids:
            return

        anchor_uid = self._resolve_uid(None)
        if anchor_uid is None:
            return
        state = self._backend.get_state(anchor_uid)
        cx = state.position[0]
        self._ensure_window_centered(cx)

        for uid in list(self._actor_uids):
            if uid in self._overrides:
                angle = self._overrides.pop(uid)
                self._backend.set_angle(uid, angle)

            if uid in self._pending_forces:
                fx, fy = self._pending_forces.pop(uid)
                self._backend.apply_force(uid, (fx, fy))

        contact_reports = self._backend.step(dt)
        for uid, report in contact_reports.items():
            self._contacts[uid] = report

    def get_pose(self, uid: str | None = None) -> tuple[Vector2, float]:
        actor_uid = self._resolve_uid(uid)
        if actor_uid is None:
            return Vector2(0.0, 0.0), 0.0
        state = self._backend.get_state(actor_uid)
        if state is None:
            return Vector2(0.0, 0.0), 0.0
        return Vector2(state.position[0], state.position[1]), float(state.angle)

    def get_velocity(self, uid: str | None = None) -> tuple[Vector2, float]:
        actor_uid = self._resolve_uid(uid)
        if actor_uid is None:
            return Vector2(0.0, 0.0), 0.0
        state = self._backend.get_state(actor_uid)
        if state is None:
            return Vector2(0.0, 0.0), 0.0
        return Vector2(state.velocity[0], state.velocity[1]), float(
            state.angular_velocity
        )

    def get_contact_report(self, uid: str | None = None) -> ContactReport:
        actor_uid = self._resolve_uid(uid)
        if actor_uid is None:
            return self._empty_contact()
        report = self._contacts.get(actor_uid)
        if report is None:
            return self._empty_contact()
        return report

    def raycast(
        self, origin: Vector2, angle: float, max_distance: float, uid: str | None = None
    ) -> RaycastHit:
        dx = math.cos(angle)
        dy = math.sin(angle)
        endpoint = (
            origin.x + dx * max_distance,
            origin.y + dy * max_distance,
        )
        ignored_uid = self._resolve_uid(uid)
        result: RaycastHit | None = self._backend.raycast(
            (origin.x, origin.y), endpoint, ignored_uid
        )
        if result is None:
            return RaycastHit(hit=False)
        return result

    def closest_point(
        self, origin: Vector2, search_radius: float
    ) -> ClosestPointResult:
        cx, cy, dist = sensor_closest_point_on_terrain(
            self.height_sampler, origin, lod=0, search_radius=search_radius
        )
        return ClosestPointResult(x=cx, y=cy, distance=dist)

    def set_landing_site_colliders(
        self,
        sites: list[tuple[float, float, float]],
        *,
        radius: float = 1.5,
        friction: float = 0.9,
        elasticity: float = 0.0,
    ) -> None:
        if self._landing_site_handles:
            self._backend.remove_segments(self._landing_site_handles)
            self._landing_site_handles.clear()

        segments: list[tuple[tuple[float, float], tuple[float, float]]] = []
        for cx, y, size in sites:
            half = max(0.5, float(size) * 0.5)
            segments.append(
                ((float(cx) - half, float(y)), (float(cx) + half, float(y)))
            )
        handles = self._backend.add_segments(
            segments, friction, elasticity, max(0.1, float(radius))
        )
        self._landing_site_handles.extend(handles)

    def set_mass(self, mass: float, uid: str | None = None) -> None:
        actor_uid = self._resolve_uid(uid)
        if actor_uid is None:
            return
        self._backend.set_mass(actor_uid, mass)

    def set_velocity(
        self,
        velocity: Vector2,
        angular_velocity: float = 0.0,
        uid: str | None = None,
    ) -> None:
        actor_uid = self._resolve_uid(uid)
        if actor_uid is None:
            return
        self._backend.set_velocity(
            actor_uid, (float(velocity.x), float(velocity.y)), float(angular_velocity)
        )

    def teleport(
        self,
        pos: Vector2,
        angle: float | None = None,
        clear_velocity: bool = True,
        uid: str | None = None,
    ) -> None:
        """Instantly move an actor body to a new pose."""
        actor_uid = self._resolve_uid(uid)
        if actor_uid is None:
            return
        self._backend.set_position(actor_uid, (pos.x, pos.y))
        if angle is not None:
            self._backend.set_angle(actor_uid, float(angle))
        if clear_velocity:
            self._backend.set_velocity(actor_uid, (0.0, 0.0), 0.0)

    def set_primary_actor(self, uid: str | None) -> None:
        if uid is None:
            self._primary_uid = None
            return
        if uid in self._actor_uids:
            self._primary_uid = uid

    def get_actor_uids(self) -> list[str]:
        return list(self._actor_uids)

    def _ensure_window_centered(self, center_x: float) -> None:
        if self._window_center_x is None:
            self._rebuild_window(center_x)
            return
        shift = abs(center_x - self._window_center_x)
        if shift >= (0.25 * self.half_width):
            self._rebuild_window(center_x)

    def _rebuild_window(self, center_x: float) -> None:
        if self._terrain_handles:
            self._backend.remove_segments(self._terrain_handles)
            self._terrain_handles.clear()
            self._terrain_segments.clear()

        step = self.segment_step
        start_x = math.floor((center_x - self.half_width) / step) * step
        end_x = math.ceil((center_x + self.half_width) / step) * step

        prev_x = start_x
        prev_y = float(self.height_sampler(prev_x))
        x = start_x + step

        segments: list[tuple[tuple[float, float], tuple[float, float]]] = []
        while x <= end_x + 1e-6:
            y = float(self.height_sampler(x))
            segments.append(((prev_x, prev_y), (x, y)))
            prev_x, prev_y = x, y
            x += step

        self._terrain_segments.extend(segments)
        handles = self._backend.add_segments(segments, 0.8, 0.0)
        self._terrain_handles.extend(handles)
        self._window_center_x = center_x

    @property
    def terrain_segments(self) -> list[Segment]:
        """Read-only view of current terrain segments for tests/debugging."""
        return list(self._terrain_segments)

    def _resolve_uid(self, uid: str | None) -> str | None:
        if uid is not None:
            return uid if uid in self._actor_uids else None
        if self._primary_uid is not None and self._primary_uid in self._actor_uids:
            return self._primary_uid
        if not self._actor_uids:
            return None
        return next(iter(self._actor_uids))

    def _remove_actor(self, uid: str) -> None:
        self._backend.remove_body(uid)
        self._actor_uids.discard(uid)
        self._contacts.pop(uid, None)
        self._overrides.pop(uid, None)
        self._pending_forces.pop(uid, None)
        if self._primary_uid == uid:
            self._primary_uid = next(iter(self._actor_uids), None)

    @staticmethod
    def _empty_contact() -> ContactReport:
        return ContactReport(colliding=False)
