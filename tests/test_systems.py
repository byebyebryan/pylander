from __future__ import annotations

import math

from core.components import Engine, FuelTank, LanderState, PhysicsState, Transform
from core.ecs import Entity, World
from core.maths import Vector2
from core.systems.force_application import ForceApplicationSystem
from core.systems.physics_sync import PhysicsSyncSystem
from core.systems.propulsion import PropulsionSystem


class _FakeEngineAdapter:
    def __init__(self):
        self.forces: list[tuple[float, float]] = []
        self.overrides: list[float] = []
        self.pose = (Vector2(10.0, 20.0), 0.0)
        self.velocity = (Vector2(1.0, -2.0), 0.0)

    def apply_force(self, force, _point=None) -> None:
        self.forces.append((force.x, force.y))

    def override(self, angle: float) -> None:
        self.overrides.append(angle)

    def get_pose(self):
        return self.pose

    def get_velocity(self):
        return self.velocity


def test_propulsion_system_slews_controls_and_burns_fuel() -> None:
    entity = Entity()
    engine = Engine(
        thrust_level=0.0,
        target_thrust=1.0,
        increase_rate=2.0,
        decrease_rate=4.0,
        target_angle=math.pi / 2.0,
        max_rotation_rate=math.pi,
    )
    tank = FuelTank(fuel=10.0, burn_rate=1.0)
    trans = Transform(rotation=0.0)
    entity.add_component(engine)
    entity.add_component(tank)
    entity.add_component(trans)

    world = World()
    world.add_entity(entity)

    system = PropulsionSystem()
    system.world = world
    system.update(0.5)

    assert math.isclose(engine.thrust_level, 1.0, abs_tol=1e-6)
    assert math.isclose(tank.fuel, 9.5, abs_tol=1e-6)
    assert math.isclose(trans.rotation, math.pi / 2.0, abs_tol=1e-6)


def test_force_application_system_applies_thrust_and_override() -> None:
    entity = Entity()
    entity.add_component(Engine(thrust_level=0.5, max_power=100.0))
    entity.add_component(Transform(rotation=0.0))

    world = World()
    world.add_entity(entity)

    adapter = _FakeEngineAdapter()
    system = ForceApplicationSystem(adapter)
    system.world = world
    system.update(1.0)

    assert adapter.forces == [(0.0, 50.0)]
    assert adapter.overrides == [0.0]


def test_physics_sync_updates_single_lander_entity() -> None:
    adapter = _FakeEngineAdapter()
    system = PhysicsSyncSystem(adapter)

    lander = Entity()
    lander.add_component(Transform(pos=Vector2(0.0, 0.0)))
    lander.add_component(PhysicsState(vel=Vector2(0.0, 0.0)))
    lander.add_component(LanderState())

    non_lander = Entity()
    non_lander_transform = Transform(pos=Vector2(99.0, 99.0))
    non_lander_physics = PhysicsState(vel=Vector2(9.0, 9.0))
    non_lander.add_component(non_lander_transform)
    non_lander.add_component(non_lander_physics)

    world = World()
    world.add_entity(lander)
    world.add_entity(non_lander)
    system.world = world

    system.update(1.0 / 60.0)

    lander_trans = lander.get_component(Transform)
    lander_phys = lander.get_component(PhysicsState)
    assert lander_trans is not None
    assert lander_phys is not None
    assert lander_trans.pos == Vector2(10.0, 20.0)
    assert lander_phys.vel == Vector2(1.0, -2.0)

    assert non_lander_transform.pos == Vector2(99.0, 99.0)
    assert non_lander_physics.vel == Vector2(9.0, 9.0)
