from __future__ import annotations

import math
from dataclasses import dataclass, field

from bots.turtle import TurtleBot
from core.bot import PassiveSensors, VehicleInfo
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
from core.sensor import ProximityContact, RadarContact
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
        self.pose_by_uid: dict[str, tuple[Vector2, float]] = {}
        self.velocity_by_uid: dict[str, tuple[Vector2, float]] = {}
        self.actor_uids: set[str] = set()

    def apply_force(self, force, _point=None, uid=None) -> None:
        self.forces.append((force.x, force.y))
        if uid is not None:
            self.actor_uids.add(uid)

    def apply_force_for(self, uid, force, _point=None) -> None:
        self.apply_force(force, _point, uid=uid)

    def override(self, angle: float, uid=None) -> None:
        self.overrides.append(angle)
        if uid is not None:
            self.actor_uids.add(uid)

    def override_for(self, uid, angle: float) -> None:
        self.override(angle, uid=uid)

    def get_pose(self, uid=None):
        if uid is not None and uid in self.pose_by_uid:
            return self.pose_by_uid[uid]
        return self.pose

    def get_velocity(self, uid=None):
        if uid is not None and uid in self.velocity_by_uid:
            return self.velocity_by_uid[uid]
        return self.velocity

    def get_actor_uids(self):
        return set(self.actor_uids)


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


def test_propulsion_system_forces_thrust_off_when_crashed() -> None:
    entity = Entity()
    engine = Engine(thrust_level=0.8, target_thrust=1.0, target_angle=0.5)
    tank = FuelTank(fuel=10.0, burn_rate=1.0)
    trans = Transform(rotation=0.0)
    state = LanderState(state="crashed")
    entity.add_component(engine)
    entity.add_component(tank)
    entity.add_component(trans)
    entity.add_component(state)

    world = World()
    world.add_entity(entity)

    system = PropulsionSystem()
    system.world = world
    system.update(0.5)

    assert math.isclose(engine.thrust_level, 0.0, abs_tol=1e-6)
    assert math.isclose(engine.target_thrust, 0.0, abs_tol=1e-6)
    # Fuel should not burn while crashed.
    assert math.isclose(tank.fuel, 10.0, abs_tol=1e-6)


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


def test_control_routing_accepts_per_actor_control_map() -> None:
    a = Entity(uid="a")
    b = Entity(uid="b")
    a_intent = ControlIntent()
    b_intent = ControlIntent()
    a_engine = Engine(target_thrust=0.0, target_angle=0.0)
    b_engine = Engine(target_thrust=0.5, target_angle=0.2)
    a.add_component(a_intent)
    a.add_component(a_engine)
    b.add_component(b_intent)
    b.add_component(b_engine)

    world = World()
    world.add_entity(a)
    world.add_entity(b)

    system = ControlRoutingSystem()
    system.world = world
    system.set_controls_map({"a": (0.8, 0.4, True)})
    system.update(1.0 / 60.0)

    assert math.isclose(a_engine.target_thrust, 0.8, abs_tol=1e-6)
    assert math.isclose(a_engine.target_angle, 0.4, abs_tol=1e-6)
    assert a_intent.refuel_requested is True

    # b gets no explicit controls this frame (only refuel resets)
    assert math.isclose(b_engine.target_thrust, 0.5, abs_tol=1e-6)
    assert math.isclose(b_engine.target_angle, 0.2, abs_tol=1e-6)
    assert b_intent.refuel_requested is False


def test_physics_sync_updates_multiple_entities_with_actor_uids() -> None:
    adapter = _FakeEngineAdapter()
    adapter.actor_uids = {"a", "b"}
    adapter.pose_by_uid = {
        "a": (Vector2(1.0, 2.0), 0.0),
        "b": (Vector2(3.0, 4.0), 0.0),
    }
    adapter.velocity_by_uid = {
        "a": (Vector2(5.0, 6.0), 0.0),
        "b": (Vector2(7.0, 8.0), 0.0),
    }
    system = PhysicsSyncSystem(adapter)

    a = Entity(uid="a")
    a.add_component(Transform(pos=Vector2(0.0, 0.0)))
    a.add_component(PhysicsState(vel=Vector2(0.0, 0.0)))
    b = Entity(uid="b")
    b.add_component(Transform(pos=Vector2(0.0, 0.0)))
    b.add_component(PhysicsState(vel=Vector2(0.0, 0.0)))

    world = World()
    world.add_entity(a)
    world.add_entity(b)
    system.world = world
    system.update(1.0 / 60.0)

    a_trans = a.get_component(Transform)
    a_phys = a.get_component(PhysicsState)
    b_trans = b.get_component(Transform)
    b_phys = b.get_component(PhysicsState)
    assert a_trans is not None and a_phys is not None
    assert b_trans is not None and b_phys is not None
    assert a_trans.pos == Vector2(1.0, 2.0)
    assert a_phys.vel == Vector2(5.0, 6.0)
    assert b_trans.pos == Vector2(3.0, 4.0)
    assert b_phys.vel == Vector2(7.0, 8.0)


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
    uid: str = "site_test"
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


class _FakeCollidingContactAdapter:
    enabled = False

    def get_contact_report(self) -> dict:
        return {"colliding": True, "normal": (0.0, 1.0), "rel_speed": 1.0, "point": (0.0, 0.0)}

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
    c0 = readings.radar_contacts[0]
    assert c0.distance >= 0.0
    assert isinstance(c0.is_inner_lock, bool)
    assert c0.x == 50.0
    assert c0.y == 0.0
    assert readings.proximity is not None
    assert readings.proximity.distance >= 0.0
    assert math.isfinite(readings.proximity.normal_x)
    assert math.isfinite(readings.proximity.normal_y)


class _BotActiveSensors:
    def __init__(self, hill_x: float, hill_width: float, hill_height: float):
        self.hill_x = hill_x
        self.hill_width = hill_width
        self.hill_height = hill_height

    def _terrain(self, x: float) -> float:
        dx = abs(x - self.hill_x)
        if dx >= self.hill_width:
            return 0.0
        t = 1.0 - (dx / self.hill_width)
        return self.hill_height * t

    def raycast(self, _dir_angle: float, max_range: float | None = None) -> dict:
        _ = max_range
        return {"hit": False, "hit_x": 0.0, "hit_y": 0.0, "distance": None}

    def terrain_height(self, world_x: float, lod: int = 0) -> float:
        _ = lod
        return self._terrain(world_x)

    def terrain_profile(
        self, x_start: float, x_end: float, samples: int = 16, lod: int = 0
    ) -> list[tuple[float, float]]:
        _ = lod
        n = max(2, int(samples))
        span = x_end - x_start
        out = []
        for i in range(n):
            t = i / (n - 1)
            xx = x_start + span * t
            out.append((xx, self._terrain(xx)))
        return out


def test_turtle_bot_enters_climb_mode_for_above_blocked_target() -> None:
    bot = TurtleBot()
    bot.set_vehicle_info(
        VehicleInfo(
            width=8.0,
            height=8.0,
            dry_mass=1.0,
            fuel_density=0.01,
            max_thrust_power=50.0,
            safe_landing_velocity=10.0,
            safe_landing_angle=math.radians(15.0),
            radar_outer_range=5000.0,
            radar_inner_range=2000.0,
            proximity_sensor_range=500.0,
        )
    )

    passive = PassiveSensors(
        x=0.0,
        y=40.0,
        altitude=36.0,
        terrain_y=0.0,
        terrain_slope=0.0,
        vx=0.0,
        vy_up=0.0,
        angle=0.0,
        ax=0.0,
        ay_up=0.0,
        mass=2.0,
        thrust_level=0.0,
        fuel=100.0,
        state="flying",
        radar_contacts=[
            RadarContact(
                uid="site_above",
                x=220.0,
                y=120.0,
                size=70.0,
                angle=math.atan2(80.0, 220.0),
                distance=math.hypot(220.0, 80.0),
                rel_x=220.0,
                rel_y=80.0,
                is_inner_lock=True,
                info={"award": 250.0},
            )
        ],
        proximity=ProximityContact(
            x=0.0,
            y=0.0,
            angle=-math.pi / 2.0,
            distance=40.0,
            normal_x=0.0,
            normal_y=1.0,
            terrain_slope=0.0,
        ),
    )

    sensors = _BotActiveSensors(hill_x=100.0, hill_width=60.0, hill_height=90.0)
    action = bot.update(1.0 / 60.0, passive, sensors)

    assert "CLB" in action.status
    assert action.target_thrust > 0.0


def test_turtle_bot_keeps_climbing_when_under_elevated_target() -> None:
    bot = TurtleBot()
    bot.set_vehicle_info(
        VehicleInfo(
            width=8.0,
            height=8.0,
            dry_mass=1.0,
            fuel_density=0.01,
            max_thrust_power=50.0,
            safe_landing_velocity=10.0,
            safe_landing_angle=math.radians(15.0),
            radar_outer_range=5000.0,
            radar_inner_range=2000.0,
            proximity_sensor_range=500.0,
        )
    )

    passive = PassiveSensors(
        x=190.0,
        y=40.0,
        altitude=36.0,
        terrain_y=0.0,
        terrain_slope=0.0,
        vx=0.0,
        vy_up=0.0,
        angle=0.0,
        ax=0.0,
        ay_up=0.0,
        mass=2.0,
        thrust_level=0.0,
        fuel=100.0,
        state="flying",
        radar_contacts=[
            RadarContact(
                uid="site_above_close_x",
                x=220.0,
                y=120.0,
                size=70.0,
                angle=math.atan2(80.0, 30.0),
                distance=math.hypot(30.0, 80.0),
                rel_x=30.0,
                rel_y=80.0,
                is_inner_lock=True,
                info={"award": 250.0},
            )
        ],
        proximity=ProximityContact(
            x=190.0,
            y=0.0,
            angle=-math.pi / 2.0,
            distance=40.0,
            normal_x=0.0,
            normal_y=1.0,
            terrain_slope=0.0,
        ),
    )

    sensors = _BotActiveSensors(hill_x=1000.0, hill_width=10.0, hill_height=1.0)
    action = bot.update(1.0 / 60.0, passive, sensors)

    assert "CLB" in action.status
    assert action.target_thrust > 0.0


def test_turtle_bot_does_not_reselect_blacklisted_contact_on_fallback() -> None:
    bot = TurtleBot()
    bot.set_vehicle_info(
        VehicleInfo(
            width=8.0,
            height=8.0,
            dry_mass=1.0,
            fuel_density=0.01,
            max_thrust_power=50.0,
            safe_landing_velocity=10.0,
            safe_landing_angle=math.radians(15.0),
            radar_outer_range=5000.0,
            radar_inner_range=2000.0,
            proximity_sensor_range=500.0,
        )
    )
    bot._target_uid_blacklist.add("blocked_site")

    passive = PassiveSensors(
        x=100.0,
        y=40.0,
        altitude=20.0,
        terrain_y=16.0,
        terrain_slope=0.0,
        vx=0.0,
        vy_up=0.0,
        angle=0.0,
        ax=0.0,
        ay_up=0.0,
        mass=2.0,
        thrust_level=0.0,
        fuel=100.0,
        state="flying",
        radar_contacts=[
            RadarContact(
                uid="blocked_site",
                x=104.0,
                y=36.0,
                size=80.0,
                angle=math.atan2(-4.0, 4.0),
                distance=math.hypot(4.0, -4.0),
                rel_x=4.0,
                rel_y=-4.0,
                is_inner_lock=True,
                info={"award": 250.0},
            )
        ],
        proximity=ProximityContact(
            x=100.0,
            y=16.0,
            angle=-math.pi / 2.0,
            distance=24.0,
            normal_x=0.0,
            normal_y=1.0,
            terrain_slope=0.0,
        ),
    )

    sensors = _BotActiveSensors(hill_x=1000.0, hill_width=10.0, hill_height=1.0)
    _ = bot.update(1.0, passive, sensors)

    # If fallback reselected the blacklisted target, hover-stuck timer would increase.
    assert bot._target_hover_stuck_s == 0.0


def test_turtle_bot_falls_back_to_outer_contacts_when_inner_are_blacklisted() -> None:
    bot = TurtleBot()
    bot.set_vehicle_info(
        VehicleInfo(
            width=8.0,
            height=8.0,
            dry_mass=1.0,
            fuel_density=0.01,
            max_thrust_power=50.0,
            safe_landing_velocity=10.0,
            safe_landing_angle=math.radians(15.0),
            radar_outer_range=5000.0,
            radar_inner_range=2000.0,
            proximity_sensor_range=500.0,
        )
    )
    bot._target_uid_blacklist.add("inner_blocked")

    passive = PassiveSensors(
        x=0.0,
        y=30.0,
        altitude=26.0,
        terrain_y=0.0,
        terrain_slope=0.0,
        vx=0.0,
        vy_up=0.0,
        angle=0.0,
        ax=0.0,
        ay_up=0.0,
        mass=2.0,
        thrust_level=0.0,
        fuel=100.0,
        state="flying",
        radar_contacts=[
            RadarContact(
                uid="inner_blocked",
                x=-120.0,
                y=30.0,
                size=80.0,
                angle=math.atan2(0.0, -120.0),
                distance=120.0,
                rel_x=-120.0,
                rel_y=0.0,
                is_inner_lock=True,
                info={"award": 250.0},
            ),
            RadarContact(
                uid="outer_available",
                x=180.0,
                y=10.0,
                size=80.0,
                angle=math.atan2(-20.0, 180.0),
                distance=math.hypot(180.0, -20.0),
                rel_x=180.0,
                rel_y=-20.0,
                is_inner_lock=False,
                info={"award": 250.0},
            ),
        ],
        proximity=ProximityContact(
            x=0.0,
            y=0.0,
            angle=-math.pi / 2.0,
            distance=30.0,
            normal_x=0.0,
            normal_y=1.0,
            terrain_slope=0.0,
        ),
    )

    sensors = _BotActiveSensors(hill_x=1000.0, hill_width=10.0, hill_height=1.0)
    action = bot.update(1.0 / 60.0, passive, sensors)

    # With the inner contact blacklisted, the bot should still track the outer
    # right-side contact instead of running targetless.
    assert action.target_angle > 0.0


def test_turtle_bot_penalizes_moving_named_outer_contacts() -> None:
    bot = TurtleBot()
    bot.set_vehicle_info(
        VehicleInfo(
            width=8.0,
            height=8.0,
            dry_mass=1.0,
            fuel_density=0.01,
            max_thrust_power=50.0,
            safe_landing_velocity=10.0,
            safe_landing_angle=math.radians(15.0),
            radar_outer_range=5000.0,
            radar_inner_range=2000.0,
            proximity_sensor_range=500.0,
        )
    )

    passive = PassiveSensors(
        x=0.0,
        y=30.0,
        altitude=26.0,
        terrain_y=0.0,
        terrain_slope=0.0,
        vx=0.0,
        vy_up=0.0,
        angle=0.0,
        ax=0.0,
        ay_up=0.0,
        mass=2.0,
        thrust_level=0.0,
        fuel=100.0,
        state="flying",
        radar_contacts=[
            RadarContact(
                uid="moving_outer_right",
                x=120.0,
                y=30.0,
                size=80.0,
                angle=math.atan2(0.0, 120.0),
                distance=120.0,
                rel_x=120.0,
                rel_y=0.0,
                is_inner_lock=False,
                info={"award": 250.0},
            ),
            RadarContact(
                uid="stable_outer_left",
                x=-160.0,
                y=30.0,
                size=80.0,
                angle=math.atan2(0.0, -160.0),
                distance=160.0,
                rel_x=-160.0,
                rel_y=0.0,
                is_inner_lock=False,
                info={"award": 250.0},
            ),
        ],
        proximity=ProximityContact(
            x=0.0,
            y=0.0,
            angle=-math.pi / 2.0,
            distance=30.0,
            normal_x=0.0,
            normal_y=1.0,
            terrain_slope=0.0,
        ),
    )

    sensors = _BotActiveSensors(hill_x=1000.0, hill_width=10.0, hill_height=1.0)
    action = bot.update(1.0 / 60.0, passive, sensors)

    # The closer right-side target is marked moving by uid and should be
    # penalized, so the stable left-side target is preferred.
    assert action.target_angle < 0.0


def test_turtle_bot_filters_high_outer_contacts_by_vertical_offset() -> None:
    bot = TurtleBot()
    bot.set_vehicle_info(
        VehicleInfo(
            width=8.0,
            height=8.0,
            dry_mass=1.0,
            fuel_density=0.01,
            max_thrust_power=50.0,
            safe_landing_velocity=10.0,
            safe_landing_angle=math.radians(15.0),
            radar_outer_range=5000.0,
            radar_inner_range=2000.0,
            proximity_sensor_range=500.0,
        )
    )

    passive = PassiveSensors(
        x=0.0,
        y=30.0,
        altitude=26.0,
        terrain_y=0.0,
        terrain_slope=0.0,
        vx=0.0,
        vy_up=0.0,
        angle=0.0,
        ax=0.0,
        ay_up=0.0,
        mass=2.0,
        thrust_level=0.0,
        fuel=100.0,
        state="flying",
        radar_contacts=[
            RadarContact(
                uid="outer_high_right",
                x=140.0,
                y=250.0,
                size=80.0,
                angle=math.atan2(220.0, 140.0),
                distance=math.hypot(140.0, 220.0),
                rel_x=140.0,
                rel_y=220.0,
                is_inner_lock=False,
                info={"award": 250.0},
            ),
            RadarContact(
                uid="outer_level_left",
                x=-190.0,
                y=30.0,
                size=80.0,
                angle=math.atan2(0.0, -190.0),
                distance=190.0,
                rel_x=-190.0,
                rel_y=0.0,
                is_inner_lock=False,
                info={"award": 250.0},
            ),
        ],
        proximity=ProximityContact(
            x=0.0,
            y=0.0,
            angle=-math.pi / 2.0,
            distance=30.0,
            normal_x=0.0,
            normal_y=1.0,
            terrain_slope=0.0,
        ),
    )

    sensors = _BotActiveSensors(hill_x=1000.0, hill_width=10.0, hill_height=1.0)
    action = bot.update(1.0 / 60.0, passive, sensors)

    # The high-above outer contact should be filtered by dy > 120, leaving the
    # level left-side outer contact as the preferred candidate.
    assert action.target_angle < 0.0


def test_turtle_bot_prefers_inner_lock_contacts_for_scoring() -> None:
    bot = TurtleBot()
    bot.set_vehicle_info(
        VehicleInfo(
            width=8.0,
            height=8.0,
            dry_mass=1.0,
            fuel_density=0.01,
            max_thrust_power=50.0,
            safe_landing_velocity=10.0,
            safe_landing_angle=math.radians(15.0),
            radar_outer_range=5000.0,
            radar_inner_range=2000.0,
            proximity_sensor_range=500.0,
        )
    )

    passive = PassiveSensors(
        x=0.0,
        y=30.0,
        altitude=26.0,
        terrain_y=0.0,
        terrain_slope=0.0,
        vx=0.0,
        vy_up=0.0,
        angle=0.0,
        ax=0.0,
        ay_up=0.0,
        mass=2.0,
        thrust_level=0.0,
        fuel=100.0,
        state="flying",
        radar_contacts=[
            RadarContact(
                uid="inner_left",
                x=-220.0,
                y=30.0,
                size=80.0,
                angle=math.atan2(0.0, -220.0),
                distance=220.0,
                rel_x=-220.0,
                rel_y=0.0,
                is_inner_lock=True,
                info={"award": 250.0},
            ),
            RadarContact(
                uid="outer_right",
                x=160.0,
                y=-150.0,
                size=80.0,
                angle=math.atan2(-180.0, 160.0),
                distance=math.hypot(160.0, -180.0),
                rel_x=160.0,
                rel_y=-180.0,
                is_inner_lock=False,
                info={"award": 250.0},
            ),
        ],
        proximity=ProximityContact(
            x=0.0,
            y=0.0,
            angle=-math.pi / 2.0,
            distance=30.0,
            normal_x=0.0,
            normal_y=1.0,
            terrain_slope=0.0,
        ),
    )

    sensors = _BotActiveSensors(hill_x=1000.0, hill_width=10.0, hill_height=1.0)
    action = bot.update(1.0 / 60.0, passive, sensors)

    # Inner lock is on the left; if outer-range contact were scored equally,
    # this setup tends to pull the command to the right.
    assert action.target_angle < 0.0


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


def test_contact_system_marks_zero_award_site_visited() -> None:
    world = World()

    lander = Entity(uid="lander")
    lander.add_component(LanderState(state="flying"))
    lander.add_component(PhysicsState(vel=Vector2(0.0, -1.0)))
    lander.add_component(Transform(pos=Vector2(0.0, 4.0), rotation=0.0))
    lander.add_component(FuelTank())
    lander.add_component(LanderGeometry(width=8.0, height=8.0))
    lander.add_component(Wallet(credits=42.0))
    lander.add_component(Engine())
    world.add_entity(lander)

    site = Entity(uid="site_zero_award")
    site.add_component(Transform(pos=Vector2(0.0, 0.0)))
    site.add_component(
        LandingSite(size=30.0, terrain_mode="elevated_supports", terrain_bound=False)
    )
    site.add_component(LandingSiteEconomy(award=0.0, fuel_price=10.0))
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
    econ = site.get_component(LandingSiteEconomy)
    assert ls is not None
    assert wallet is not None
    assert econ is not None
    assert ls.state == "landed"
    assert math.isclose(wallet.credits, 42.0, abs_tol=1e-6)
    assert econ.visited is True


def test_contact_system_does_not_snap_land_when_far_below_site() -> None:
    world = World()

    lander = Entity(uid="lander")
    lander.add_component(LanderState(state="flying"))
    lander.add_component(PhysicsState(vel=Vector2(0.0, -1.0)))
    # Lander is near in x, but far below pad y.
    lander.add_component(Transform(pos=Vector2(0.0, 20.0), rotation=0.0))
    lander.add_component(FuelTank())
    lander.add_component(LanderGeometry(width=8.0, height=8.0))
    lander.add_component(Wallet(credits=0.0))
    lander.add_component(Engine())
    world.add_entity(lander)

    site = Entity(uid="site_high")
    site.add_component(Transform(pos=Vector2(0.0, 120.0)))
    site.add_component(LandingSite(size=30.0, terrain_mode="elevated_supports", terrain_bound=False))
    site.add_component(LandingSiteEconomy(award=100.0, fuel_price=10.0))
    world.add_entity(site)

    model = LandingSiteSurfaceModel()
    projection = LandingSiteProjectionSystem(model)
    projection.world = world
    projection.update(1.0 / 60.0)

    system = ContactSystem(_FakeCollidingContactAdapter(), model)
    system.world = world
    system.update(1.0 / 60.0)

    ls = lander.get_component(LanderState)
    assert ls is not None
    assert ls.state == "crashed"


def test_contact_system_crashes_on_high_speed_site_plane_cross_without_contact() -> None:
    world = World()

    lander = Entity(uid="lander")
    lander.add_component(LanderState(state="flying"))
    # Unsafe downward speed; current pose is already below the site plane.
    lander.add_component(PhysicsState(vel=Vector2(0.0, -80.0)))
    lander.add_component(Transform(pos=Vector2(0.0, -2.0), rotation=0.0))
    lander.add_component(FuelTank())
    lander.add_component(LanderGeometry(width=8.0, height=8.0))
    lander.add_component(Wallet(credits=0.0))
    lander.add_component(Engine())
    world.add_entity(lander)

    site = Entity(uid="site_plane")
    site.add_component(Transform(pos=Vector2(0.0, 0.0)))
    site.add_component(
        LandingSite(size=40.0, terrain_mode="elevated_supports", terrain_bound=False)
    )
    site.add_component(LandingSiteEconomy(award=100.0, fuel_price=10.0))
    world.add_entity(site)

    model = LandingSiteSurfaceModel()
    projection = LandingSiteProjectionSystem(model)
    projection.world = world
    dt = 0.2
    projection.update(dt)

    # No engine collision report this frame; crossing fallback should still crash.
    system = ContactSystem(_FakeContactAdapter(), model)
    system.world = world
    system.update(dt)

    ls = lander.get_component(LanderState)
    assert ls is not None
    assert ls.state == "crashed"


def test_lander_behavior_api_is_removed() -> None:
    lander = Lander(start_pos=Vector2(0.0, 0.0))
    assert not hasattr(lander, "apply_controls")
    assert not hasattr(lander, "update_sensors")
    assert not hasattr(lander, "get_stats_text")
