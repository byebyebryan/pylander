"""Pymunk-based physics engine and terrain utilities."""

import math
from typing import Any
from .sensor import closest_point_on_terrain as sensor_closest_point_on_terrain

# New engine dependencies
import pymunk as pm
from .maths import Vector2


# World is y-up. Gravity accelerates downward (negative y).
from .config import GRAVITY
# No local closest_point_on_terrain; use sensor.closest_point_on_terrain instead


# -----------------------------
# New Pymunk-based PhysicsEngine
# -----------------------------


def _polygon_area(poly: list[tuple[float, float]]) -> float:
    area = 0.0
    for i in range(len(poly)):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % len(poly)]
        area += x1 * y2 - x2 * y1
    return abs(area) * 0.5


class PhysicsEngine:
    """Pymunk-backed physics with a rolling terrain window.

    - World coordinates are x-right, y-up.
    - Terrain is represented by static Segment shapes generated from a height
      sampler within a centered window.
    - Supports multiple dynamic actor bodies (indexed by uid).
    """

    def __init__(
        self,
        height_sampler: Any,
        gravity: tuple[float, float] = (0.0, GRAVITY),
        segment_step: float = 10.0,
        half_width: float = 12000.0,
    ) -> None:
        self.space = pm.Space()
        self.space.gravity = gravity

        # Collisions: 1 = terrain, 2 = lander
        self._COLL_TERRAIN = 1
        self._COLL_LANDER = 2

        self.height_sampler = height_sampler
        self.segment_step = max(1.0, float(segment_step))
        self.half_width = max(100.0, float(half_width))

        # Terrain window state
        self._terrain_shapes: list[pm.Shape] = []
        self._window_center_x: float | None = None

        # Dynamic actor state, keyed by actor uid
        self._bodies: dict[str, pm.Body] = {}
        self._shapes: dict[str, list[pm.Shape]] = {}
        self._controls: dict[str, tuple[float, float]] = {}  # thrust_force, angle
        self._contacts: dict[str, dict] = {}
        self._overrides: dict[str, float] = {}
        self._pending_forces: dict[str, tuple[float, float]] = {}
        self._shape_to_uid: dict[int, str] = {}
        self._primary_uid: str | None = None

        # Install collision handler for lander vs terrain
        # Register collision callbacks using Space.on_collision (API in this Pymunk build)
        self.space.on_collision(
            self._COLL_LANDER,
            self._COLL_TERRAIN,
            begin=self._on_contact_begin,
            post_solve=self._on_contact_post_solve,
            separate=self._on_contact_separate,
            data=None,
        )

    # ----- Public API -----

    def attach_lander(
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
        """Create the lander dynamic body as a triangle based on width/height.

        Returns actor uid.
        """
        self._remove_actor(uid)
        verts = [
            (0.0, height / 2.0),
            (-width / 2.0, -height / 2.0),
            (width / 2.0, -height / 2.0),
        ]
        moment = pm.moment_for_poly(mass, verts)
        body = pm.Body(mass, moment)
        if start_pos is not None:
            body.position = (start_pos.x, start_pos.y)
        body.angle = start_angle
        shape = pm.Poly(body, verts)
        shape.friction = friction
        shape.elasticity = elasticity
        shape.collision_type = self._COLL_LANDER

        self.space.add(body, shape)
        self._bodies[uid] = body
        self._shapes[uid] = [shape]
        self._shape_to_uid[id(shape)] = uid
        self._controls.setdefault(uid, (0.0, float(start_angle)))
        self._contacts[uid] = self._empty_contact()
        if self._primary_uid is None:
            self._primary_uid = uid

        # Initialize terrain window around start
        cx = body.position.x
        self._ensure_window_centered(cx)

        return uid

    def attach_lander_from_polygons(
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
        """Create the lander dynamic body from one or more convex polygons.

        Polygons are specified in local coordinates (y-up). Mass is distributed
        proportionally to polygon area for inertia calculation.
        """
        self._remove_actor(uid)
        if not polygons:
            return self.attach_lander(
                4.0,
                4.0,
                mass,
                uid=uid,
                start_pos=start_pos,
                start_angle=start_angle,
            )

        # Compute total area and per-poly moments
        total_area = 0.0
        for poly in polygons:
            total_area += _polygon_area(poly)

        if total_area <= 0.0:
            total_area = 1.0

        # Sum moments using mass distributed by area
        moment = 0.0
        for poly in polygons:
            area = _polygon_area(poly)
            poly_mass = mass * (area / total_area)
            moment += pm.moment_for_poly(max(1e-6, poly_mass), poly)

        body = pm.Body(mass, max(moment, 1e-6))
        if start_pos is not None:
            body.position = (start_pos.x, start_pos.y)
        body.angle = start_angle

        shapes: list[pm.Shape] = []
        for poly in polygons:
            shape = pm.Poly(body, poly)
            shape.friction = friction
            shape.elasticity = elasticity
            shape.collision_type = self._COLL_LANDER
            shapes.append(shape)

        self.space.add(body, *shapes)
        self._bodies[uid] = body
        self._shapes[uid] = shapes
        for shape in shapes:
            self._shape_to_uid[id(shape)] = uid
        self._controls.setdefault(uid, (0.0, float(start_angle)))
        self._contacts[uid] = self._empty_contact()
        if self._primary_uid is None:
            self._primary_uid = uid

        cx = body.position.x
        self._ensure_window_centered(cx)

        return uid

    def set_lander_controls(
        self, thrust_force: float, angle_rad: float, uid: str | None = None
    ) -> None:
        """Set the instantaneous thrust force (Newtons) and body angle (radians)."""
        actor_uid = self._resolve_uid(uid)
        if actor_uid is None:
            return
        self._controls[actor_uid] = (max(0.0, float(thrust_force)), float(angle_rad))

    # New explicit control intents
    def override(self, angle: float, uid: str | None = None) -> None:
        """Override body pose angle this step (radians)."""
        actor_uid = self._resolve_uid(uid)
        if actor_uid is None:
            return
        self._overrides[actor_uid] = float(angle)

    def apply_force(
        self, force: Vector2, point: Vector2 | None = None, uid: str | None = None
    ) -> None:
        """Queue a world-space force to apply at the COM or specific point this step."""
        _ = point
        actor_uid = self._resolve_uid(uid)
        if actor_uid is None:
            return
        self._pending_forces[actor_uid] = (force.x, force.y)

    def step(self, dt: float) -> None:
        if not self._bodies:
            return

        # Maintain terrain window around current primary actor x
        anchor_uid = self._resolve_uid(None)
        if anchor_uid is None:
            return
        anchor_body = self._bodies.get(anchor_uid)
        if anchor_body is None:
            return
        cx = float(anchor_body.position.x)
        self._ensure_window_centered(cx)

        for uid, body in self._bodies.items():
            if uid in self._overrides:
                body.angle = self._overrides.pop(uid)

            if uid in self._pending_forces:
                fx, fy = self._pending_forces.pop(uid)
                body.apply_force_at_world_point((fx, fy), body.position)
                continue

            thrust_force, angle = self._controls.get(uid, (0.0, float(body.angle)))
            body.angle = angle
            if thrust_force > 0.0:
                fx = math.sin(angle) * thrust_force
                fy = math.cos(angle) * thrust_force
                body.apply_force_at_world_point((fx, fy), body.position)

        self.space.step(max(1e-4, float(dt)))

    def get_pose(self, uid: str | None = None) -> tuple[Vector2, float]:
        actor_uid = self._resolve_uid(uid)
        if actor_uid is None:
            return Vector2(0.0, 0.0), 0.0
        body = self._bodies.get(actor_uid)
        if body is None:
            return Vector2(0.0, 0.0), 0.0
        p = body.position
        return Vector2(p.x, p.y), float(body.angle)

    def get_velocity(self, uid: str | None = None) -> tuple[Vector2, float]:
        actor_uid = self._resolve_uid(uid)
        if actor_uid is None:
            return Vector2(0.0, 0.0), 0.0
        body = self._bodies.get(actor_uid)
        if body is None:
            return Vector2(0.0, 0.0), 0.0
        v = body.velocity
        return Vector2(v.x, v.y), float(body.angular_velocity)

    def get_contact_report(self, uid: str | None = None) -> dict:
        actor_uid = self._resolve_uid(uid)
        if actor_uid is None:
            return self._empty_contact()
        report = self._contacts.get(actor_uid)
        return dict(report) if report is not None else self._empty_contact()

    def raycast(
        self, origin: Vector2, angle: float, max_distance: float, uid: str | None = None
    ) -> dict:
        dx = math.cos(angle)
        dy = math.sin(angle)
        p1 = pm.Vec2d(origin.x, origin.y)
        p2 = pm.Vec2d(
            origin.x + dx * max_distance, origin.y + dy * max_distance
        )
        ignored_uid = self._resolve_uid(uid)
        infos = self.space.segment_query(p1, p2, 0.0, pm.ShapeFilter())
        hit_info = None
        for info in infos:
            owner_uid = self._shape_to_uid.get(id(info.shape))
            if ignored_uid is not None and owner_uid == ignored_uid:
                continue
            hit_info = info
            break
        if hit_info is None:
            return {"hit": False, "hit_x": 0.0, "hit_y": 0.0, "distance": None}
        return {
            "hit": True,
            "hit_x": float(hit_info.point.x),
            "hit_y": float(hit_info.point.y),
            "distance": float(hit_info.alpha * max_distance),
        }

    def closest_point(self, origin: Vector2, search_radius: float) -> dict:
        cx, cy, dist = sensor_closest_point_on_terrain(
            self.height_sampler, origin, lod=0, search_radius=search_radius
        )
        return {"x": cx, "y": cy, "distance": dist}

    # ----- Internal helpers -----

    def _ensure_window_centered(self, center_x: float) -> None:
        if self._window_center_x is None:
            self._rebuild_window(center_x)
            return
        shift = abs(center_x - self._window_center_x)
        if shift >= (0.25 * self.half_width):
            self._rebuild_window(center_x)

    def _rebuild_window(self, center_x: float) -> None:
        # Remove old terrain shapes
        if self._terrain_shapes:
            self.space.remove(*self._terrain_shapes)
            self._terrain_shapes.clear()

        start_x = center_x - self.half_width
        end_x = center_x + self.half_width
        step = self.segment_step

        prev_x = start_x
        prev_y = float(self.height_sampler(prev_x))
        x = start_x + step
        while x <= end_x + 1e-6:
            y = float(self.height_sampler(x))
            seg = pm.Segment(self.space.static_body, (prev_x, prev_y), (x, y), 1.0)
            seg.friction = 0.8
            seg.elasticity = 0.0
            seg.collision_type = self._COLL_TERRAIN
            self.space.add(seg)
            self._terrain_shapes.append(seg)
            prev_x, prev_y = x, y
            x += step

        self._window_center_x = center_x

    # ----- Collision callbacks -----

    def _on_contact_begin(self, arbiter: pm.Arbiter, _space: pm.Space, _data) -> None:
        uid = self._uid_from_arbiter(arbiter)
        if uid is None:
            return
        # Mark colliding; details populated in post_solve.
        self._contacts[uid] = self._empty_contact(colliding=True)

    def _on_contact_separate(
        self, _arbiter: pm.Arbiter, _space: pm.Space, _data
    ) -> None:
        uid = self._uid_from_arbiter(_arbiter)
        if uid is None:
            return
        self._contacts[uid] = self._empty_contact(colliding=False)

    def _on_contact_post_solve(
        self, arbiter: pm.Arbiter, _space: pm.Space, _data
    ) -> None:
        uid = self._uid_from_arbiter(arbiter)
        if uid is None:
            return
        n = arbiter.normal  # points from second to first shape
        point = None
        cps = arbiter.contact_point_set
        if cps and cps.points:
            # Use world-space point on first shape
            point = (float(cps.points[0].point_a.x), float(cps.points[0].point_a.y))
        rel_speed = 0.0
        body = self._bodies.get(uid)
        if body is not None and n is not None:
            v = body.velocity
            rel_speed = abs(float(v.x * n.x + v.y * n.y))
        self._contacts[uid] = {
            "colliding": True,
            "normal": (float(n.x), float(n.y)) if n is not None else None,
            "rel_speed": rel_speed,
            "point": point,
        }

    # Mass update (for fuel burn effects)
    def set_lander_mass(self, mass: float, uid: str | None = None) -> None:
        actor_uid = self._resolve_uid(uid)
        if actor_uid is None:
            return
        body = self._bodies.get(actor_uid)
        if body is not None:
            body.mass = max(0.001, float(mass))

    def teleport_lander(
        self,
        pos: Vector2,
        angle: float | None = None,
        clear_velocity: bool = True,
        uid: str | None = None,
    ) -> None:
        """Instantly move an actor body to a new pose (used for takeoff bump)."""
        actor_uid = self._resolve_uid(uid)
        if actor_uid is None:
            return
        body = self._bodies.get(actor_uid)
        if body is None:
            return
        body.position = (pos.x, pos.y)
            
        if angle is not None:
            body.angle = float(angle)
        if clear_velocity:
            body.velocity = (0.0, 0.0)
            body.angular_velocity = 0.0

    def set_primary_actor(self, uid: str | None) -> None:
        if uid is None:
            self._primary_uid = None
            return
        if uid in self._bodies:
            self._primary_uid = uid

    def get_actor_uids(self) -> list[str]:
        return list(self._bodies.keys())

    def _uid_from_arbiter(self, arbiter: pm.Arbiter) -> str | None:
        for shape in arbiter.shapes:
            uid = self._shape_to_uid.get(id(shape))
            if uid is not None:
                return uid
        return None

    def _resolve_uid(self, uid: str | None) -> str | None:
        if uid is not None:
            return uid if uid in self._bodies else None
        if self._primary_uid is not None and self._primary_uid in self._bodies:
            return self._primary_uid
        if not self._bodies:
            return None
        return next(iter(self._bodies.keys()))

    def _remove_actor(self, uid: str) -> None:
        shapes = self._shapes.pop(uid, [])
        body = self._bodies.pop(uid, None)
        if body is not None:
            removals: list[Any] = [body, *shapes]
            try:
                self.space.remove(*removals)
            except Exception:
                pass
        for shape in shapes:
            self._shape_to_uid.pop(id(shape), None)
        self._controls.pop(uid, None)
        self._contacts.pop(uid, None)
        self._overrides.pop(uid, None)
        self._pending_forces.pop(uid, None)
        if self._primary_uid == uid:
            self._primary_uid = next(iter(self._bodies.keys()), None)

    @staticmethod
    def _empty_contact(colliding: bool = False) -> dict:
        return {
            "colliding": colliding,
            "normal": None,
            "rel_speed": 0.0,
            "point": None,
        }
