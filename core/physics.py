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


class PhysicsEngine:
    """Pymunk-backed physics with a rolling terrain window.

    - World coordinates are x-right, y-up.
    - Terrain is represented by static Segment shapes generated from a height
      sampler within a centered window.
    - Supports a single lander body for now.
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

        # Lander state
        self._lander_body: pm.Body | None = None
        self._lander_shape: pm.Shape | None = None
        self._lander_controls: tuple[float, float] = (0.0, 0.0)  # thrust_force, angle
        self._lander_contact: dict | None = None

        # Pending control intents (set by game each frame)
        self._override_angle: float | None = None
        self._pending_force: tuple[float, float] | None = None

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
        *,
        friction: float = 0.9,
        elasticity: float = 0.0,
        start_x: float | None = None,
        start_y: float | None = None,
        start_angle: float = 0.0,
    ) -> str:
        """Create the lander dynamic body as a triangle based on width/height.

        Returns a handle string (currently a constant 'lander').
        """
        verts = [
            (0.0, height / 2.0),
            (-width / 2.0, -height / 2.0),
            (width / 2.0, -height / 2.0),
        ]
        moment = pm.moment_for_poly(mass, verts)
        body = pm.Body(mass, moment)
        if start_x is not None and start_y is not None:
            body.position = (start_x, start_y)
        body.angle = start_angle
        shape = pm.Poly(body, verts)
        shape.friction = friction
        shape.elasticity = elasticity
        shape.collision_type = self._COLL_LANDER

        self.space.add(body, shape)
        self._lander_body = body
        self._lander_shape = shape

        # Initialize terrain window around start
        cx = body.position.x if start_x is None else start_x
        self._ensure_window_centered(cx)

        return "lander"

    def attach_lander_from_polygons(
        self,
        polygons: list[list[tuple[float, float]]],
        mass: float,
        *,
        friction: float = 0.9,
        elasticity: float = 0.0,
        start_x: float | None = None,
        start_y: float | None = None,
        start_angle: float = 0.0,
    ) -> str:
        """Create the lander dynamic body from one or more convex polygons.

        Polygons are specified in local coordinates (y-up). Mass is distributed
        proportionally to polygon area for inertia calculation.
        """
        if not polygons:
            return self.attach_lander(4.0, 4.0, mass, start_x=start_x, start_y=start_y, start_angle=start_angle)

        # Compute total area and per-poly moments
        total_area = 0.0
        for poly in polygons:
            # polygon area via shoelace (absolute)
            area = 0.0
            for i in range(len(poly)):
                x1, y1 = poly[i]
                x2, y2 = poly[(i + 1) % len(poly)]
                area += x1 * y2 - x2 * y1
            total_area += abs(area) * 0.5

        if total_area <= 0.0:
            total_area = 1.0

        # Sum moments using mass distributed by area
        moment = 0.0
        for poly in polygons:
            area = 0.0
            for i in range(len(poly)):
                x1, y1 = poly[i]
                x2, y2 = poly[(i + 1) % len(poly)]
                area += x1 * y2 - x2 * y1
            area = abs(area) * 0.5
            poly_mass = mass * (area / total_area)
            moment += pm.moment_for_poly(max(1e-6, poly_mass), poly)

        body = pm.Body(mass, max(moment, 1e-6))
        if start_x is not None and start_y is not None:
            body.position = (start_x, start_y)
        body.angle = start_angle

        shapes: list[pm.Shape] = []
        for poly in polygons:
            shape = pm.Poly(body, poly)
            shape.friction = friction
            shape.elasticity = elasticity
            shape.collision_type = self._COLL_LANDER
            shapes.append(shape)

        self.space.add(body, *shapes)
        self._lander_body = body
        # keep a reference to the first shape for type/filters; list not needed elsewhere
        self._lander_shape = shapes[0] if shapes else None

        cx = body.position.x if start_x is None else start_x
        self._ensure_window_centered(cx)

        return "lander"

    def set_lander_controls(self, thrust_force: float, angle_rad: float) -> None:
        """Set the instantaneous thrust force (Newtons) and body angle (radians)."""
        self._lander_controls = (max(0.0, float(thrust_force)), float(angle_rad))

    # New explicit control intents
    def override(self, angle: float) -> None:
        """Override body pose angle this step (radians)."""
        self._override_angle = float(angle)

    def apply_force(self, force: Vector2 | tuple[float, float], point: Vector2 | tuple[float, float] | None = None) -> None:
        """Queue a world-space force to apply at the COM or specific point this step."""
        if isinstance(force, Vector2):
            fx, fy = force.x, force.y
        else:
            fx, fy = force[0], force[1]
            
        self._pending_force = (fx, fy)

    def step(self, dt: float) -> None:
        if self._lander_body is None:
            return

        # Maintain terrain window around current lander x
        cx = float(self._lander_body.position.x)
        self._ensure_window_centered(cx)

        # Apply explicit override/apply_force first if provided
        if self._override_angle is not None:
            self._lander_body.angle = self._override_angle
            self._override_angle = None

        if self._pending_force is not None:
            fx, fy = self._pending_force
            self._lander_body.apply_force_at_world_point(
                (fx, fy), self._lander_body.position
            )
            self._pending_force = None
        else:
            # Fallback to legacy thrust/angle path
            thrust_force, angle = self._lander_controls
            self._lander_body.angle = angle
            if thrust_force > 0.0:
                fx = math.sin(angle) * thrust_force
                fy = math.cos(angle) * thrust_force
                self._lander_body.apply_force_at_world_point(
                    (fx, fy), self._lander_body.position
                )

        self.space.step(max(1e-4, float(dt)))

    def get_pose(self) -> tuple[Vector2, float]:
        if self._lander_body is None:
            return Vector2(0.0, 0.0), 0.0
        p = self._lander_body.position
        return Vector2(p.x, p.y), float(self._lander_body.angle)

    def get_velocity(self) -> tuple[Vector2, float]:
        if self._lander_body is None:
            return Vector2(0.0, 0.0), 0.0
        v = self._lander_body.velocity
        return Vector2(v.x, v.y), float(self._lander_body.angular_velocity)

    def get_contact_report(self) -> dict:
        return (
            dict(self._lander_contact)
            if self._lander_contact
            else {
                "colliding": False,
                "normal": None,
                "rel_speed": 0.0,
                "point": None,
            }
        )

    def raycast(
        self, origin: Vector2 | tuple[float, float], angle: float, max_distance: float
    ) -> dict:
        dx = math.cos(angle)
        dy = math.sin(angle)
        
        if isinstance(origin, Vector2):
            ox, oy = origin.x, origin.y
        else:
            ox, oy = origin[0], origin[1]
            
        p1 = pm.Vec2d(ox, oy)
        p2 = pm.Vec2d(
            ox + dx * max_distance, oy + dy * max_distance
        )
        info = self.space.segment_query_first(p1, p2, 0.0, pm.ShapeFilter())
        if info is None:
            return {"hit": False, "hit_x": 0.0, "hit_y": 0.0, "distance": None}
        return {
            "hit": True,
            "hit_x": float(info.point.x),
            "hit_y": float(info.point.y),
            "distance": float(info.alpha * max_distance),
        }

    def closest_point(
        self, origin: Vector2 | tuple[float, float], search_radius: float
    ) -> dict:
        if isinstance(origin, Vector2):
            x0, y0 = origin.x, origin.y
        else:
            x0, y0 = float(origin[0]), float(origin[1])
        cx, cy, dist = sensor_closest_point_on_terrain(
            self.height_sampler, x0, y0, lod=0, search_radius=search_radius
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
        # Mark colliding; details populated in post_solve
        self._lander_contact = {
            "colliding": True,
            "normal": None,
            "rel_speed": 0.0,
            "point": None,
        }

    def _on_contact_separate(
        self, _arbiter: pm.Arbiter, _space: pm.Space, _data
    ) -> None:
        self._lander_contact = {
            "colliding": False,
            "normal": None,
            "rel_speed": 0.0,
            "point": None,
        }

    def _on_contact_post_solve(
        self, arbiter: pm.Arbiter, _space: pm.Space, _data
    ) -> None:
        n = arbiter.normal  # points from second to first shape
        point = None
        cps = arbiter.contact_point_set
        if cps and cps.points:
            # Use world-space point on first shape
            point = (float(cps.points[0].point_a.x), float(cps.points[0].point_a.y))
        rel_speed = 0.0
        if self._lander_body is not None and n is not None:
            v = self._lander_body.velocity
            rel_speed = abs(float(v.x * n.x + v.y * n.y))
        self._lander_contact = {
            "colliding": True,
            "normal": (float(n.x), float(n.y)) if n is not None else None,
            "rel_speed": rel_speed,
            "point": point,
        }

    # Mass update (for fuel burn effects)
    def set_lander_mass(self, mass: float) -> None:
        if self._lander_body is not None:
            self._lander_body.mass = max(0.001, float(mass))

    def teleport_lander(
        self,
        pos: Vector2 | tuple[float, float],
        angle: float | None = None,
        clear_velocity: bool = True,
    ) -> None:
        """Instantly move the lander to a new pose (used for takeoff bump)."""
        if self._lander_body is None:
            return
            
        if isinstance(pos, Vector2):
            self._lander_body.position = (pos.x, pos.y)
        else:
            self._lander_body.position = (float(pos[0]), float(pos[1]))
            
        if angle is not None:
            self._lander_body.angle = float(angle)
        if clear_velocity:
            self._lander_body.velocity = (0.0, 0.0)
            self._lander_body.angular_velocity = 0.0
