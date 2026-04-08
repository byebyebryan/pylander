from __future__ import annotations

import math

import pytest

from conftest import FlatTerrain
from core.maths import Vector2
from core.physics import PhysicsEngine


def test_closest_point_uses_vector_origin_signature() -> None:
    engine = PhysicsEngine(height_sampler=FlatTerrain(), gravity=(0.0, -9.8))
    engine.attach_body(width=8.0, height=8.0, mass=10.0, start_pos=Vector2(0.0, 20.0))

    out = engine.closest_point(Vector2(12.0, 30.0), search_radius=100.0)

    assert out.distance >= 0.0
    assert math.isclose(out.y, 0.0, abs_tol=1e-6)


def test_teleport_clears_velocity_when_requested() -> None:
    engine = PhysicsEngine(height_sampler=FlatTerrain(), gravity=(0.0, -9.8))
    engine.attach_body(width=8.0, height=8.0, mass=10.0, start_pos=Vector2(0.0, 50.0))
    engine.step(0.1)

    pre_vel, _ = engine.get_velocity()
    assert pre_vel.y < 0.0  # gravity affected the body

    engine.teleport(Vector2(5.0, 40.0), angle=0.25, clear_velocity=True)
    pose, angle = engine.get_pose()
    vel, ang_vel = engine.get_velocity()

    assert math.isclose(pose.x, 5.0, abs_tol=1e-6)
    assert math.isclose(pose.y, 40.0, abs_tol=1e-6)
    assert math.isclose(angle, 0.25, abs_tol=1e-6)
    assert math.isclose(vel.length(), 0.0, abs_tol=1e-6)
    assert math.isclose(ang_vel, 0.0, abs_tol=1e-6)


def test_engine_tracks_multiple_actor_bodies_by_uid() -> None:
    engine = PhysicsEngine(height_sampler=FlatTerrain(), gravity=(0.0, -9.8))
    engine.attach_body(
        width=8.0, height=8.0, mass=10.0, uid="a", start_pos=Vector2(0.0, 50.0)
    )
    engine.attach_body(
        width=8.0, height=8.0, mass=10.0, uid="b", start_pos=Vector2(20.0, 50.0)
    )

    assert set(engine.get_actor_uids()) == {"a", "b"}

    engine.teleport(Vector2(5.0, 40.0), uid="a")
    pose_a, _ = engine.get_pose(uid="a")
    pose_b, _ = engine.get_pose(uid="b")

    assert math.isclose(pose_a.x, 5.0, abs_tol=1e-6)
    assert math.isclose(pose_a.y, 40.0, abs_tol=1e-6)
    assert math.isclose(pose_b.x, 20.0, abs_tol=1e-6)
    assert math.isclose(pose_b.y, 50.0, abs_tol=1e-6)


def test_landing_site_colliders_are_queryable_by_raycast() -> None:
    engine = PhysicsEngine(height_sampler=FlatTerrain(), gravity=(0.0, -9.8))
    engine.set_landing_site_colliders([(0.0, 40.0, 100.0)])

    hit = engine.raycast(Vector2(0.0, 100.0), -math.pi / 2.0, 120.0)

    assert hit.hit is True
    assert hit.distance is not None
    assert hit.point_y == pytest.approx(40.0, abs=2.0)

    engine.set_landing_site_colliders([])
    assert len(engine._landing_site_handles) == 0


class _WavyTerrain:
    def __call__(self, x: float, lod: int = 0) -> float:
        _ = lod
        return 10.0 * math.sin(x * 0.02) + 2.5 * math.cos(x * 0.11)


def _window_vertices(engine: PhysicsEngine) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []
    segments = engine.terrain_segments
    for seg in segments:
        a, b = seg
        out.append((float(a[0]), float(a[1])))
    if segments:
        last = segments[-1]
        out.append((float(last[1][0]), float(last[1][1])))
    return out


def _is_step_aligned(x: float, step: float, tol: float = 1e-6) -> bool:
    scaled = x / step
    return abs(scaled - round(scaled)) <= tol


def test_terrain_window_rebuild_is_step_anchored_and_stable() -> None:
    step = 7.5
    engine = PhysicsEngine(
        height_sampler=_WavyTerrain(),
        gravity=(0.0, -9.8),
        segment_step=step,
        half_width=120.0,
    )
    engine.attach_body(width=8.0, height=8.0, mass=10.0, start_pos=Vector2(13.0, 80.0))
    verts_a = _window_vertices(engine)

    # Force a second window build around a different center.
    engine._rebuild_window(97.0)
    verts_b = _window_vertices(engine)

    assert verts_a
    assert verts_b
    assert all(_is_step_aligned(x, step) for x, _ in verts_a)
    assert all(_is_step_aligned(x, step) for x, _ in verts_b)

    map_a = {round(x, 6): y for x, y in verts_a}
    map_b = {round(x, 6): y for x, y in verts_b}
    common_xs = sorted(set(map_a.keys()) & set(map_b.keys()))
    assert len(common_xs) > 5
    for x_key in common_xs:
        assert map_a[x_key] == pytest.approx(map_b[x_key])
