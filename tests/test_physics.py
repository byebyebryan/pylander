from __future__ import annotations

import math

from core.physics import PhysicsEngine


class _FlatTerrain:
    def __call__(self, _x: float, lod: int = 0) -> float:
        return 0.0

    def get_resolution(self, _lod: int) -> float:
        return 1.0


def test_closest_point_uses_origin_tuple_signature() -> None:
    engine = PhysicsEngine(height_sampler=_FlatTerrain(), gravity=(0.0, -9.8))
    engine.attach_lander(width=8.0, height=8.0, mass=10.0, start_x=0.0, start_y=20.0)

    out = engine.closest_point((12.0, 30.0), search_radius=100.0)

    assert isinstance(out, dict)
    assert out["distance"] >= 0.0
    assert math.isclose(out["y"], 0.0, abs_tol=1e-6)


def test_teleport_lander_clears_velocity_when_requested() -> None:
    engine = PhysicsEngine(height_sampler=_FlatTerrain(), gravity=(0.0, -9.8))
    engine.attach_lander(width=8.0, height=8.0, mass=10.0, start_x=0.0, start_y=50.0)
    engine.step(0.1)

    pre_vel, _ = engine.get_velocity()
    assert pre_vel.y < 0.0  # gravity affected the body

    engine.teleport_lander((5.0, 40.0), angle=0.25, clear_velocity=True)
    pose, angle = engine.get_pose()
    vel, ang_vel = engine.get_velocity()

    assert math.isclose(pose.x, 5.0, abs_tol=1e-6)
    assert math.isclose(pose.y, 40.0, abs_tol=1e-6)
    assert math.isclose(angle, 0.25, abs_tol=1e-6)
    assert math.isclose(vel.length(), 0.0, abs_tol=1e-6)
    assert math.isclose(ang_vel, 0.0, abs_tol=1e-6)
