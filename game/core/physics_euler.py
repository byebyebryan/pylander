"""Pure-Python Euler physics backend implementing the PhysicsBackend protocol."""

from __future__ import annotations

import bisect
import math

# Angular velocity damping coefficient (rad/s per rad/s per second).
# Controls how quickly the tumble settles after a crash.
_ANGULAR_DAMPING = 1.5
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from game.core.components import ContactReport

from game.core.physics_backend import BodyState, RaycastHit


@dataclass
class _Body:
    uid: str
    mass: float
    moment: float
    polygons: list[list[tuple[float, float]]]
    px: float
    py: float
    angle: float
    vx: float = 0.0
    vy: float = 0.0
    angular_velocity: float = 0.0
    fx: float = 0.0
    fy: float = 0.0
    friction: float = 0.9
    elasticity: float = 0.0


@dataclass
class _Segment:
    x1: float
    y1: float
    x2: float
    y2: float
    nx: float
    ny: float
    friction: float
    elasticity: float


class EulerBackend:
    def __init__(self) -> None:
        self._gravity: tuple[float, float] = (0.0, 0.0)
        self._bodies: dict[str, _Body] = {}
        self._segments: dict[int, _Segment] = {}
        self._next_handle: int = 0
        self._prev_colliding: dict[str, bool] = {}
        self._frozen: set[str] = set()
        # Spatial index: sorted list of (min_x, handle) for fast x-range lookup
        self._seg_index: list[tuple[float, int]] = []
        self._index_dirty: bool = False

    def freeze_body(self, uid: str) -> None:
        """Freeze linear motion; angular velocity is preserved for tumble."""
        self._frozen.add(uid)
        body = self._bodies.get(uid)
        if body is not None:
            body.vx = 0.0
            body.vy = 0.0
            body.fx = 0.0
            body.fy = 0.0

    def unfreeze_body(self, uid: str) -> None:
        """Restore normal physics integration for a body."""
        self._frozen.discard(uid)

    def configure(self, gravity: tuple[float, float]) -> None:
        self._gravity = gravity

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
        body = _Body(
            uid=uid,
            mass=mass,
            moment=moment,
            polygons=polygons,
            px=position[0],
            py=position[1],
            angle=angle,
            friction=friction,
            elasticity=elasticity,
        )
        self._bodies[uid] = body

    def remove_body(self, uid: str) -> None:
        self._bodies.pop(uid, None)

    def set_mass(self, uid: str, mass: float) -> None:
        body = self._bodies.get(uid)
        if body is not None:
            body.mass = max(0.001, mass)

    def set_position(self, uid: str, pos: tuple[float, float]) -> None:
        body = self._bodies.get(uid)
        if body is not None:
            body.px = pos[0]
            body.py = pos[1]

    def set_angle(self, uid: str, angle: float) -> None:
        body = self._bodies.get(uid)
        if body is not None:
            body.angle = angle

    def set_velocity(self, uid: str, vel: tuple[float, float], angular: float) -> None:
        body = self._bodies.get(uid)
        if body is not None:
            body.vx = vel[0]
            body.vy = vel[1]
            body.angular_velocity = angular

    def apply_force(self, uid: str, force: tuple[float, float]) -> None:
        body = self._bodies.get(uid)
        if body is not None:
            body.fx += force[0]
            body.fy += force[1]

    def add_segments(
        self,
        segments: list[tuple[tuple[float, float], tuple[float, float]]],
        friction: float,
        elasticity: float,
        radius: float = 1.0,
    ) -> list[int]:
        _ = radius
        handles: list[int] = []
        for (x1, y1), (x2, y2) in segments:
            dx = x2 - x1
            dy = y2 - y1
            length = math.sqrt(dx * dx + dy * dy)
            if length < 1e-12:
                continue
            nx = -dy / length
            ny = dx / length
            if ny < 0:
                nx, ny = -nx, -ny
            seg = _Segment(
                x1=x1,
                y1=y1,
                x2=x2,
                y2=y2,
                nx=nx,
                ny=ny,
                friction=friction,
                elasticity=elasticity,
            )
            handle = self._next_handle
            self._next_handle += 1
            self._segments[handle] = seg
            self._seg_index.append((min(x1, x2), handle))
            handles.append(handle)
        if handles:
            self._index_dirty = True
        return handles

    def remove_segments(self, handles: list[int]) -> None:
        if not handles:
            return
        handle_set = set(handles)
        for handle in handles:
            self._segments.pop(handle, None)
        self._seg_index = [
            entry for entry in self._seg_index if entry[1] not in handle_set
        ]
        # Already sorted if we filtered from a sorted list
        # But removal may break ordering if index wasn't sorted yet — mark dirty
        self._index_dirty = True

    def step(self, dt: float) -> dict[str, "ContactReport"]:
        from game.core.components import ContactReport

        contact_reports: dict[str, ContactReport] = {}
        gravity_x, gravity_y = self._gravity

        damping_factor = max(0.0, 1.0 - _ANGULAR_DAMPING * dt)

        for uid, body in self._bodies.items():
            if uid in self._frozen:
                body.fx = 0.0
                body.fy = 0.0
                # Linear is frozen, but angular still integrates (tumble after crash)
                body.angle += body.angular_velocity * dt
                body.angular_velocity *= damping_factor
                continue

            body.vx += gravity_x * dt
            body.vy += gravity_y * dt

            body.vx += (body.fx / body.mass) * dt
            body.vy += (body.fy / body.mass) * dt

            body.fx = 0.0
            body.fy = 0.0

            body.px += body.vx * dt
            body.py += body.vy * dt

            body.angle += body.angular_velocity * dt
            body.angular_velocity *= damping_factor

        for uid, body in self._bodies.items():
            if uid in self._frozen:
                if self._prev_colliding.get(uid, False):
                    contact_reports[uid] = ContactReport(colliding=False)
                self._prev_colliding[uid] = False
                continue

            colliding, normal, point, penetration = self._detect_collisions(body)

            if colliding:
                impact_speed = 0.0
                if normal is not None and penetration > 0:
                    body.px += normal[0] * penetration
                    body.py += normal[1] * penetration

                    v_dot_n = body.vx * normal[0] + body.vy * normal[1]
                    if v_dot_n < 0:
                        # Capture impact speed BEFORE zeroing the normal velocity
                        impact_speed = abs(v_dot_n)
                        body.vx -= v_dot_n * normal[0]
                        body.vy -= v_dot_n * normal[1]

                        # Angular impulse from off-centre contact point
                        if point is not None and body.moment > 0:
                            rx = point[0] - body.px
                            ry = point[1] - body.py
                            # J = -mass * v_dot_n (linear impulse magnitude)
                            jx = -body.mass * v_dot_n * normal[0]
                            jy = -body.mass * v_dot_n * normal[1]
                            # 2D cross product: r × J
                            tau = rx * jy - ry * jx
                            body.angular_velocity += tau / body.moment

                contact_reports[uid] = ContactReport(
                    colliding=True,
                    normal=normal,
                    rel_speed=impact_speed,
                    point=point,
                )
                self._prev_colliding[uid] = True
            else:
                if self._prev_colliding.get(uid, False):
                    contact_reports[uid] = ContactReport(colliding=False)
                self._prev_colliding[uid] = False

        return contact_reports

    def _ensure_index(self) -> None:
        if self._index_dirty:
            self._seg_index.sort()
            self._index_dirty = False

    def _segments_near_x(self, x: float, margin: float = 20.0) -> list[_Segment]:
        """Return segments whose x-range overlaps [x - margin, x + margin]."""
        self._ensure_index()
        index = self._seg_index
        if not index:
            return []

        lo = x - margin
        hi = x + margin

        # Binary search for first entry with min_x >= lo
        start = bisect.bisect_left(index, (lo,))

        result: list[_Segment] = []
        for i in range(max(0, start - 1), len(index)):
            seg_min_x, handle = index[i]
            if seg_min_x > hi:
                break
            seg = self._segments.get(handle)
            if seg is None:
                continue
            seg_max_x = max(seg.x1, seg.x2)
            if seg_max_x >= lo:
                result.append(seg)
        return result

    def _detect_collisions(
        self, body: _Body
    ) -> tuple[bool, tuple[float, float] | None, tuple[float, float] | None, float]:
        cos_a = math.cos(body.angle)
        sin_a = math.sin(body.angle)

        world_verts: list[tuple[float, float]] = []
        for poly in body.polygons:
            for lx, ly in poly:
                wx = body.px + lx * cos_a - ly * sin_a
                wy = body.py + lx * sin_a + ly * cos_a
                world_verts.append((wx, wy))

        # Find the body's x-range to query nearby segments
        if not world_verts:
            return False, None, None, 0.0
        min_wx = min(wx for wx, _ in world_verts)
        max_wx = max(wx for wx, _ in world_verts)
        margin = max(5.0, (max_wx - min_wx) * 0.5 + 2.0)
        nearby = self._segments_near_x((min_wx + max_wx) * 0.5, margin)
        if not nearby:
            return False, None, None, 0.0

        deepest_pen = 0.0
        best_normal: tuple[float, float] | None = None
        best_point: tuple[float, float] | None = None

        for wx, wy in world_verts:
            for seg in nearby:
                seg_lo = min(seg.x1, seg.x2) - 0.5
                seg_hi = max(seg.x1, seg.x2) + 0.5
                if wx < seg_lo or wx > seg_hi:
                    continue

                d = (wx - seg.x1) * seg.nx + (wy - seg.y1) * seg.ny
                if d < 0 and abs(d) > abs(deepest_pen):
                    deepest_pen = d
                    best_normal = (seg.nx, seg.ny)
                    best_point = (wx, wy)

        if deepest_pen < 0 and best_normal is not None:
            return True, best_normal, best_point, abs(deepest_pen)
        return False, None, None, 0.0

    def get_state(self, uid: str) -> BodyState:
        body = self._bodies.get(uid)
        if body is None:
            return BodyState((0.0, 0.0), 0.0, (0.0, 0.0), 0.0)
        return BodyState(
            position=(body.px, body.py),
            angle=body.angle,
            velocity=(body.vx, body.vy),
            angular_velocity=body.angular_velocity,
        )

    def raycast(
        self,
        origin: tuple[float, float],
        endpoint: tuple[float, float],
        ignore_uid: str | None,
    ) -> RaycastHit | None:
        _ = ignore_uid

        ox, oy = origin
        dx = endpoint[0] - ox
        dy = endpoint[1] - oy

        # Use spatial index to only check segments along the ray's x-range
        lo_x = min(ox, endpoint[0])
        hi_x = max(ox, endpoint[0])
        margin = max(5.0, abs(dx) * 0.5 + 2.0)
        nearby = self._segments_near_x((lo_x + hi_x) * 0.5, margin)

        best_t = float("inf")
        best_x = 0.0
        best_y = 0.0

        for seg in nearby:
            hit, t, u = self._segments_intersect(
                ox, oy, endpoint[0], endpoint[1], seg.x1, seg.y1, seg.x2, seg.y2
            )
            if hit and t < best_t:
                best_t = t
                best_x = ox + t * dx
                best_y = oy + t * dy

        if best_t == float("inf"):
            return None

        segment_length = math.sqrt(dx * dx + dy * dy)
        distance = best_t * segment_length
        return RaycastHit(
            hit=True,
            point_x=best_x,
            point_y=best_y,
            distance=distance,
        )

    @staticmethod
    def _segments_intersect(
        ax: float,
        ay: float,
        bx: float,
        by: float,
        cx: float,
        cy: float,
        dx: float,
        dy: float,
    ) -> tuple[bool, float, float]:
        denom = (bx - ax) * (dy - cy) - (by - ay) * (dx - cx)
        if abs(denom) < 1e-12:
            return False, 0.0, 0.0
        t = ((cx - ax) * (dy - cy) - (cy - ay) * (dx - cx)) / denom
        u = ((cx - ax) * (by - ay) - (cy - ay) * (bx - ax)) / denom
        if 0.0 <= t <= 1.0 and 0.0 <= u <= 1.0:
            return True, t, u
        return False, 0.0, 0.0

    @staticmethod
    def moment_for_poly(mass: float, verts: list[tuple[float, float]]) -> float:
        n = len(verts)
        if n < 3:
            return 0.0
        numerator = 0.0
        denominator = 0.0
        for i in range(n):
            x0, y0 = verts[i]
            x1, y1 = verts[(i + 1) % n]
            cross = abs(x0 * y1 - x1 * y0)
            numerator += cross * (
                (x0 * x0 + x0 * x1 + x1 * x1) + (y0 * y0 + y0 * y1 + y1 * y1)
            )
            denominator += cross
        if denominator < 1e-12:
            return 0.0
        return (mass * numerator) / (6.0 * denominator)
