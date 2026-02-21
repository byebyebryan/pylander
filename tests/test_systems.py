from __future__ import annotations

import math
from dataclasses import dataclass, field

from core.components import (
    ControlIntent,
    Engine,
    FuelTank,
    KinematicMotion,
    LandingSite,
    LandingSiteEconomy,
    LanderGeometry,
    LanderState,
    PhysicsState,
    Radar,
    RefuelConfig,
    SensorReadings,
    Transform,
    Wallet,
)
from core.ecs import Entity, World
from core.landing_sites import LandingSiteSurfaceModel
from core.lander import Lander
from core.maths import Range1D, Vector2
from core.systems.contact import ContactSystem
from core.systems.control_routing import ControlRoutingSystem
from core.systems.force_application import ForceApplicationSystem
from core.systems.landing_site_motion import LandingSiteMotionSystem
from core.systems.landing_site_projection import LandingSiteProjectionSystem
from core.systems.physics_sync import PhysicsSyncSystem
from core.systems.propulsion import PropulsionSystem
from core.systems.refuel import RefuelSystem
from core.systems.sensor_update import SensorUpdateSystem
from core.systems.state_transition import StateTransitionSystem


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


def test_control_routing_updates_intent_and_engine_targets() -> None:
    entity = Entity()
    intent = ControlIntent()
    engine = Engine(target_thrust=0.0, target_angle=0.0)
    entity.add_component(intent)
    entity.add_component(engine)

    world = World()
    world.add_entity(entity)

    system = ControlRoutingSystem()
    system.world = world
    system.set_controls((0.75, 0.25, True))
    system.update(1.0 / 60.0)

    assert math.isclose(engine.target_thrust, 0.75, abs_tol=1e-6)
    assert math.isclose(engine.target_angle, 0.25, abs_tol=1e-6)
    assert intent.refuel_requested is True


def test_state_transition_takes_off_when_landed_and_thrust_requested() -> None:
    entity = Entity()
    entity.add_component(LanderState(state="landed"))
    entity.add_component(Engine(target_thrust=0.2))
    entity.add_component(Transform(pos=Vector2(0.0, 10.0)))
    entity.add_component(FuelTank(fuel=10.0))

    world = World()
    world.add_entity(entity)
    system = StateTransitionSystem()
    system.world = world

    system.update(1.0 / 60.0)

    ls = entity.get_component(LanderState)
    trans = entity.get_component(Transform)
    assert ls is not None
    assert trans is not None
    assert ls.state == "flying"
    assert math.isclose(trans.pos.y, 11.0, abs_tol=1e-6)


@dataclass
class _Target:
    x: float
    y: float
    size: float
    fuel_price: float = 10.0
    award: float = 0.0
    vel: Vector2 = field(default_factory=lambda: Vector2(0.0, 0.0))

    @property
    def info(self) -> dict:
        return {"fuel_price": self.fuel_price, "award": self.award}


class _Targets:
    def __init__(self, target):
        self.target = target

    def get_sites(self, _span):
        return [self.target]


class _FlatTerrain:
    def __call__(self, _x: float, lod: int = 0) -> float:
        _ = lod
        return 0.0

    def get_resolution(self, _lod: int) -> float:
        return 1.0


class _FakeContactAdapter:
    enabled = False

    def get_contact_report(self) -> dict:
        return {"colliding": False, "normal": None, "rel_speed": 0.0, "point": None}

    def teleport_lander(self, _pos, angle=None, clear_velocity=True) -> None:
        _ = angle, clear_velocity


def test_refuel_system_transfers_fuel_and_spends_credits() -> None:
    entity = Entity()
    entity.add_component(LanderState(state="landed"))
    entity.add_component(FuelTank(fuel=10.0, max_fuel=20.0))
    entity.add_component(Wallet(credits=50.0))
    entity.add_component(Transform(pos=Vector2(0.0, 5.0)))
    entity.add_component(LanderGeometry(width=8.0, height=8.0))
    entity.add_component(RefuelConfig(refuel_rate=5.0))
    entity.add_component(ControlIntent(refuel_requested=True))
    sites = _Targets(_Target(x=0.0, y=0.0, size=20.0, fuel_price=2.0))

    world = World()
    world.add_entity(entity)
    system = RefuelSystem(sites)
    system.world = world

    system.update(1.0)

    tank = entity.get_component(FuelTank)
    wallet = entity.get_component(Wallet)
    assert tank is not None
    assert wallet is not None
    assert math.isclose(tank.fuel, 15.0, abs_tol=1e-6)
    assert math.isclose(wallet.credits, 40.0, abs_tol=1e-6)


def test_sensor_update_system_populates_cached_readings() -> None:
    entity = Entity()
    entity.add_component(Transform(pos=Vector2(0.0, 100.0)))
    entity.add_component(Radar(inner_range=2000.0, outer_range=5000.0))
    entity.add_component(RefuelConfig(proximity_sensor_range=500.0))
    readings = SensorReadings()
    entity.add_component(readings)
    sites = _Targets(_Target(x=50.0, y=0.0, size=20.0))

    world = World()
    world.add_entity(entity)
    system = SensorUpdateSystem(_FlatTerrain(), sites)
    system.world = world

    system.update(1.0 / 10.0)

    assert len(readings.radar_contacts) >= 1
    assert readings.proximity is not None
    assert readings.proximity.distance >= 0.0


def test_landing_site_motion_and_projection_update_model() -> None:
    world = World()
    site = Entity(uid="site_a")
    site.add_component(Transform(pos=Vector2(0.0, 0.0)))
    site.add_component(LandingSite(size=30.0, terrain_mode="elevated_supports", terrain_bound=False))
    site.add_component(LandingSiteEconomy(award=200.0, fuel_price=9.0))
    site.add_component(KinematicMotion(velocity=Vector2(3.0, 0.0)))
    world.add_entity(site)

    model = LandingSiteSurfaceModel()
    motion = LandingSiteMotionSystem()
    projection = LandingSiteProjectionSystem(model)
    motion.world = world
    projection.world = world

    motion.update(2.0)
    projection.update(2.0)

    out = model.get_sites(Range1D(-10.0, 10.0))
    assert out
    assert math.isclose(out[0].x, 6.0, abs_tol=1e-6)
    assert math.isclose(out[0].fuel_price, 9.0, abs_tol=1e-6)


def test_contact_system_lands_using_relative_site_velocity() -> None:
    world = World()

    lander = Entity(uid="lander")
    lander.add_component(LanderState(state="flying"))
    lander.add_component(PhysicsState(vel=Vector2(8.0, -1.0)))
    lander.add_component(Transform(pos=Vector2(0.0, 4.0), rotation=0.0))
    lander.add_component(FuelTank())
    lander.add_component(LanderGeometry(width=8.0, height=8.0))
    lander.add_component(Wallet(credits=0.0))
    lander.add_component(Engine())
    world.add_entity(lander)

    site = Entity(uid="site_landing")
    site.add_component(Transform(pos=Vector2(0.0, 0.0)))
    site.add_component(LandingSite(size=30.0, terrain_mode="elevated_supports", terrain_bound=False))
    site.add_component(LandingSiteEconomy(award=150.0, fuel_price=10.0))
    site.add_component(KinematicMotion(velocity=Vector2(7.0, 0.0)))
    world.add_entity(site)

    model = LandingSiteSurfaceModel()
    projection = LandingSiteProjectionSystem(model)
    projection.world = world
    projection.update(1.0 / 60.0)

    system = ContactSystem(_FakeContactAdapter(), model)
    system.world = world
    system.update(1.0 / 60.0)

    ls = lander.get_component(LanderState)
    wallet = lander.get_component(Wallet)
    assert ls is not None
    assert wallet is not None
    assert ls.state == "landed"
    assert math.isclose(wallet.credits, 150.0, abs_tol=1e-6)


def test_lander_behavior_api_is_removed() -> None:
    lander = Lander(start_pos=Vector2(0.0, 0.0))
    assert not hasattr(lander, "apply_controls")
    assert not hasattr(lander, "update_sensors")
    assert not hasattr(lander, "get_stats_text")
