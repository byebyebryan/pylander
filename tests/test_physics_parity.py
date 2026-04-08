"""Parity tests: Euler backend vs Pymunk backend."""

import math
import pytest
from conftest import FlatTerrain
from core.maths import Vector2
from core.physics import PhysicsEngine
from core.physics_euler import EulerBackend
from core.physics_pymunk import PymunkBackend


def _make_engine(backend):
    return PhysicsEngine(
        height_sampler=FlatTerrain(),
        gravity=(0.0, -9.8),
        backend=backend,
    )


class TestGravityParity:
    """Both backends should produce similar free-fall trajectories."""

    def test_position_after_free_fall_matches_within_tolerance(self):
        dt = 1.0 / 60.0
        steps = 60  # 1 second

        pm_engine = _make_engine(PymunkBackend())
        eu_engine = _make_engine(EulerBackend())

        pm_engine.attach_body(
            width=8.0, height=8.0, mass=100.0, start_pos=Vector2(0.0, 100.0)
        )
        eu_engine.attach_body(
            width=8.0, height=8.0, mass=100.0, start_pos=Vector2(0.0, 100.0)
        )

        for _ in range(steps):
            pm_engine.step(dt)
            eu_engine.step(dt)

        pm_pose, _ = pm_engine.get_pose()
        eu_pose, _ = eu_engine.get_pose()

        assert abs(pm_pose.y - eu_pose.y) < 0.5
        assert abs(pm_pose.x) < 0.1
        assert abs(eu_pose.x) < 0.1

    def test_velocity_after_free_fall_matches_within_tolerance(self):
        dt = 1.0 / 60.0
        steps = 30  # 0.5 seconds

        pm_engine = _make_engine(PymunkBackend())
        eu_engine = _make_engine(EulerBackend())

        pm_engine.attach_body(
            width=8.0, height=8.0, mass=100.0, start_pos=Vector2(0.0, 200.0)
        )
        eu_engine.attach_body(
            width=8.0, height=8.0, mass=100.0, start_pos=Vector2(0.0, 200.0)
        )

        for _ in range(steps):
            pm_engine.step(dt)
            eu_engine.step(dt)

        pm_vel, _ = pm_engine.get_velocity()
        eu_vel, _ = eu_engine.get_velocity()

        assert abs(pm_vel.y - eu_vel.y) < 0.5


class TestThrustParity:
    """Both backends should respond similarly to applied forces."""

    def test_thrust_changes_position_similarly(self):
        dt = 1.0 / 60.0
        steps = 30

        pm_engine = _make_engine(PymunkBackend())
        eu_engine = _make_engine(EulerBackend())

        pm_engine.attach_body(
            width=8.0, height=8.0, mass=100.0, start_pos=Vector2(0.0, 100.0)
        )
        eu_engine.attach_body(
            width=8.0, height=8.0, mass=100.0, start_pos=Vector2(0.0, 100.0)
        )

        for _ in range(steps):
            pm_engine.apply_force(Vector2(0.0, 2000.0))
            eu_engine.apply_force(Vector2(0.0, 2000.0))
            pm_engine.step(dt)
            eu_engine.step(dt)

        pm_pose, _ = pm_engine.get_pose()
        eu_pose, _ = eu_engine.get_pose()

        assert pm_pose.y > 100.0
        assert eu_pose.y > 100.0
        assert abs(pm_pose.y - eu_pose.y) < 1.0


class TestCollisionParity:
    """Both backends should detect terrain collision at similar positions."""

    def test_detects_collision_on_flat_terrain(self):
        dt = 1.0 / 60.0

        pm_engine = _make_engine(PymunkBackend())
        eu_engine = _make_engine(EulerBackend())

        pm_engine.attach_body(
            width=8.0, height=8.0, mass=100.0, start_pos=Vector2(0.0, 15.0)
        )
        eu_engine.attach_body(
            width=8.0, height=8.0, mass=100.0, start_pos=Vector2(0.0, 15.0)
        )

        pm_collided = False
        eu_collided = False

        for _ in range(120):
            pm_engine.step(dt)
            eu_engine.step(dt)

            pm_report = pm_engine.get_contact_report()
            eu_report = eu_engine.get_contact_report()

            if pm_report.colliding:
                pm_collided = True
            if eu_report.colliding:
                eu_collided = True

            if pm_collided and eu_collided:
                break

        assert pm_collided, "Pymunk never detected collision"
        assert eu_collided, "Euler never detected collision"

    def test_collision_normal_points_upward(self):
        dt = 1.0 / 60.0

        eu_engine = _make_engine(EulerBackend())
        eu_engine.attach_body(
            width=8.0, height=8.0, mass=100.0, start_pos=Vector2(0.0, 15.0)
        )

        for _ in range(120):
            eu_engine.step(dt)
            report = eu_engine.get_contact_report()
            if report.colliding and report.normal is not None:
                assert report.normal[1] > 0.5, (
                    f"Normal y={report.normal[1]}, expected upward"
                )
                return

        pytest.fail("Euler backend never detected collision with terrain")


class TestEulerBasic:
    """Tests specific to the Euler backend."""

    def test_teleport_updates_position(self):
        engine = _make_engine(EulerBackend())
        engine.attach_body(
            width=8.0, height=8.0, mass=100.0, start_pos=Vector2(0.0, 50.0)
        )

        engine.teleport(Vector2(10.0, 20.0), angle=0.5)
        pose, angle = engine.get_pose()

        assert math.isclose(pose.x, 10.0, abs_tol=0.01)
        assert math.isclose(pose.y, 20.0, abs_tol=0.01)
        assert math.isclose(angle, 0.5, abs_tol=0.01)

    def test_set_velocity_updates_velocity(self):
        engine = _make_engine(EulerBackend())
        engine.attach_body(
            width=8.0, height=8.0, mass=100.0, start_pos=Vector2(0.0, 50.0)
        )

        engine.set_velocity(Vector2(3.0, -5.0), uid="lander")
        vel, ang_vel = engine.get_velocity()

        assert math.isclose(vel.x, 3.0, abs_tol=0.01)
        assert math.isclose(vel.y, -5.0, abs_tol=0.01)

    def test_no_penetration_through_flat_terrain(self):
        dt = 1.0 / 60.0

        engine = _make_engine(EulerBackend())
        engine.attach_body(
            width=8.0, height=8.0, mass=100.0, start_pos=Vector2(0.0, 5.0)
        )

        for _ in range(300):
            engine.step(dt)

        pose, _ = engine.get_pose()
        assert pose.y >= -0.5, f"Body penetrated terrain: y={pose.y}"

    def test_multiple_actors_tracked_independently(self):
        engine = _make_engine(EulerBackend())
        engine.attach_body(
            width=8.0, height=8.0, mass=100.0, uid="a", start_pos=Vector2(0.0, 50.0)
        )
        engine.attach_body(
            width=8.0, height=8.0, mass=100.0, uid="b", start_pos=Vector2(20.0, 50.0)
        )

        assert set(engine.get_actor_uids()) == {"a", "b"}

        engine.teleport(Vector2(5.0, 40.0), uid="a")
        pose_a, _ = engine.get_pose(uid="a")
        pose_b, _ = engine.get_pose(uid="b")

        assert math.isclose(pose_a.x, 5.0, abs_tol=0.01)
        assert math.isclose(pose_a.y, 40.0, abs_tol=0.01)
        assert math.isclose(pose_b.x, 20.0, abs_tol=0.01)
