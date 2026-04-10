"""Pymunk-based physics backend implementation."""

from __future__ import annotations

import pymunk as pm
from typing import Any

from game.core.components import ContactReport
from game.core.physics_backend import BodyState, RaycastHit


class PymunkBackend:
    """Pymunk implementation of PhysicsBackend."""

    _collision_type_lander: int = 2
    _collision_type_terrain: int = 1

    def __init__(self) -> None:
        self._space: pm.Space | None = None
        self._bodies: dict[str, pm.Body] = {}
        self._shapes: dict[str, list[pm.Shape]] = {}
        self._shape_to_uid: dict[int, str] = {}
        self._contact_reports: dict[str, ContactReport] = {}
        self._segments: dict[int, pm.Segment] = {}
        self._next_handle: int = 0

    def configure(self, gravity: tuple[float, float]) -> None:
        self._space = pm.Space()
        self._space.gravity = gravity
        self._space.on_collision(
            self._collision_type_lander,
            self._collision_type_terrain,
            begin=self._on_contact_begin,
            post_solve=self._on_contact_post_solve,
            separate=self._on_contact_separate,
            data=None,
        )

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
        if self._space is None:
            return
        body = pm.Body(mass, moment)
        body.position = position
        body.angle = angle

        shapes: list[pm.Shape] = []
        for poly in polygons:
            shape = pm.Poly(body, poly)
            shape.friction = friction
            shape.elasticity = elasticity
            shape.collision_type = self._collision_type_lander
            shapes.append(shape)

        self._space.add(body, *shapes)
        self._bodies[uid] = body
        self._shapes[uid] = shapes
        for shape in shapes:
            self._shape_to_uid[id(shape)] = uid

    def remove_body(self, uid: str) -> None:
        if self._space is None:
            return
        shapes = self._shapes.pop(uid, [])
        body = self._bodies.pop(uid, None)
        if body is not None:
            removals: list[Any] = [body, *shapes]
            try:
                self._space.remove(*removals)
            except AssertionError:
                pass
        for shape in shapes:
            self._shape_to_uid.pop(id(shape), None)

    def set_mass(self, uid: str, mass: float) -> None:
        body = self._bodies.get(uid)
        if body is not None:
            body.mass = max(0.001, float(mass))

    def set_position(self, uid: str, pos: tuple[float, float]) -> None:
        body = self._bodies.get(uid)
        if body is not None:
            body.position = pos

    def set_angle(self, uid: str, angle: float) -> None:
        body = self._bodies.get(uid)
        if body is not None:
            body.angle = angle

    def set_velocity(self, uid: str, vel: tuple[float, float], angular: float) -> None:
        body = self._bodies.get(uid)
        if body is not None:
            body.velocity = vel
            body.angular_velocity = angular

    def apply_force(self, uid: str, force: tuple[float, float]) -> None:
        body = self._bodies.get(uid)
        if body is not None:
            body.apply_force_at_world_point(force, body.position)

    def add_segments(
        self,
        segments: list[tuple[tuple[float, float], tuple[float, float]]],
        friction: float,
        elasticity: float,
        radius: float = 1.0,
    ) -> list[int]:
        if self._space is None:
            return []
        handles: list[int] = []
        for a, b in segments:
            seg = pm.Segment(
                self._space.static_body,
                a,
                b,
                radius,
            )
            seg.friction = friction
            seg.elasticity = elasticity
            seg.collision_type = self._collision_type_terrain
            self._space.add(seg)
            handle = self._next_handle
            self._next_handle += 1
            self._segments[handle] = seg
            handles.append(handle)
        return handles

    def remove_segments(self, handles: list[int]) -> None:
        if self._space is None:
            return
        for handle in handles:
            seg = self._segments.pop(handle, None)
            if seg is not None:
                try:
                    self._space.remove(seg)
                except AssertionError:
                    pass

    def step(self, dt: float) -> dict[str, ContactReport]:
        if self._space is None:
            return {}
        self._contact_reports.clear()
        self._space.step(max(1e-4, float(dt)))
        result = dict(self._contact_reports)
        return result

    def get_state(self, uid: str) -> BodyState:
        body = self._bodies.get(uid)
        if body is None:
            return BodyState((0.0, 0.0), 0.0, (0.0, 0.0), 0.0)
        return BodyState(
            position=(float(body.position.x), float(body.position.y)),
            angle=float(body.angle),
            velocity=(float(body.velocity.x), float(body.velocity.y)),
            angular_velocity=float(body.angular_velocity),
        )

    def raycast(
        self,
        origin: tuple[float, float],
        endpoint: tuple[float, float],
        ignore_uid: str | None,
    ) -> RaycastHit | None:
        if self._space is None:
            return None
        p1 = pm.Vec2d(origin[0], origin[1])
        p2 = pm.Vec2d(endpoint[0], endpoint[1])
        segment_length = (p2 - p1).length
        infos = self._space.segment_query(p1, p2, 0.0, pm.ShapeFilter())
        for info in infos:
            owner_uid = self._shape_to_uid.get(id(info.shape))
            if ignore_uid is not None and owner_uid == ignore_uid:
                continue
            return RaycastHit(
                hit=True,
                point_x=float(info.point.x),
                point_y=float(info.point.y),
                distance=float(info.alpha * segment_length),
            )
        return None

    @staticmethod
    def moment_for_poly(mass: float, verts: list[tuple[float, float]]) -> float:
        return pm.moment_for_poly(mass, verts)

    def _uid_from_arbiter(self, arbiter: pm.Arbiter) -> str | None:
        for shape in arbiter.shapes:
            uid = self._shape_to_uid.get(id(shape))
            if uid is not None:
                return uid
        return None

    def _on_contact_begin(self, arbiter: pm.Arbiter, _space: pm.Space, _data) -> None:
        uid = self._uid_from_arbiter(arbiter)
        if uid is None:
            return
        self._contact_reports[uid] = ContactReport(colliding=True)

    def _on_contact_separate(
        self, _arbiter: pm.Arbiter, _space: pm.Space, _data
    ) -> None:
        uid = self._uid_from_arbiter(_arbiter)
        if uid is None:
            return
        self._contact_reports[uid] = ContactReport(colliding=False)

    def _on_contact_post_solve(
        self, arbiter: pm.Arbiter, _space: pm.Space, _data
    ) -> None:
        uid = self._uid_from_arbiter(arbiter)
        if uid is None:
            return
        n = arbiter.normal
        point = None
        cps = arbiter.contact_point_set
        if cps and cps.points:
            point = (float(cps.points[0].point_a.x), float(cps.points[0].point_a.y))
        rel_speed = 0.0
        body = self._bodies.get(uid)
        if body is not None and n is not None:
            v = body.velocity
            rel_speed = abs(float(v.x * n.x + v.y * n.y))
        self._contact_reports[uid] = ContactReport(
            colliding=True,
            normal=(float(n.x), float(n.y)) if n is not None else None,
            rel_speed=rel_speed,
            point=point,
        )
