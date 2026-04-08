from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING
from core.maths import Vector2, RigidTransform2
import math

if TYPE_CHECKING:
    from core.sensor import ProximityContact, RadarContact


class FlightState(StrEnum):
    FLYING = "flying"
    LANDED = "landed"
    CRASHED = "crashed"
    OUT_OF_FUEL = "out_of_fuel"


@dataclass
class Transform:
    """Component representing position, rotation, and scale."""

    pos: Vector2 = field(default_factory=lambda: Vector2(0.0, 0.0))
    rotation: float = 0.0  # Radians, 0 = upright
    scale: float = 1.0

    @property
    def x(self) -> float:
        return self.pos.x

    @x.setter
    def x(self, value: float):
        self.pos.x = value

    @property
    def y(self) -> float:
        return self.pos.y

    @y.setter
    def y(self, value: float):
        self.pos.y = value

    def as_transform(self) -> RigidTransform2:
        """Return a core.maths.RigidTransform2 for calculation."""
        return RigidTransform2(self.pos, self.rotation)


@dataclass
class PhysicsState:
    """Component representing physical properties."""

    vel: Vector2 = field(default_factory=lambda: Vector2(0.0, 0.0))
    acc: Vector2 = field(default_factory=lambda: Vector2(0.0, 0.0))
    mass: float = 7200.0  # Dry mass (kg), includes hull + installed systems


@dataclass
class FuelTank:
    """Component representing fuel storage."""

    fuel: float = 140.0
    max_fuel: float = 140.0
    density: float = 45.0  # Mass per fuel unit (kg/unit)


@dataclass
class CargoHold:
    """Component representing carried cargo mass constraints."""

    cargo_mass: float = 1800.0
    max_cargo_mass: float = 6000.0

    @property
    def effective_mass(self) -> float:
        return max(0.0, min(float(self.cargo_mass), float(self.max_cargo_mass)))


@dataclass
class Engine:
    """Component representing propulsion capabilities."""

    thrust_level: float = 0.0  # Current output (0..max_thrust)
    target_thrust: float = 0.0  # Desired output (0..max_thrust, 0=off)
    min_thrust: float = 0.25  # Ignited minimum throttle floor
    max_thrust: float = 1.6  # Allows overdrive above nominal 1.0
    max_power: float = 240000.0  # Force at nominal thrust=1.0 (N)
    base_burn_rate: float = 1.10  # Fuel units/sec at nominal thrust=1.0
    overdrive_burn_multiplier: float = 8.0  # Extra burn slope above nominal

    # Control characteristics
    increase_rate: float = 1.1  # Throttle units/sec
    decrease_rate: float = 1.8  # Throttle units/sec

    # Rotation control
    target_angle: float = 0.0
    max_rotation_rate: float = math.radians(90.0)


@dataclass
class LanderGeometry:
    """Component representing physical shape dimensions."""

    width: float = 8.0
    height: float = 8.0
    polygon_points: list[Vector2] | None = None  # Local space cache


@dataclass
class Radar:
    """Component representing radar capabilities."""

    inner_range: float = 2000.0
    outer_range: float = 5000.0
    active: bool = True


@dataclass
class LanderState:
    """Component representing the lander's flight/contact state."""

    state: FlightState = FlightState.FLYING
    safe_landing_velocity: float = 10.0
    safe_landing_angle: float = 0.2618  # math.radians(15)


@dataclass
class Wallet:
    """Component representing the lander's credits balance."""

    credits: float = 0.0


@dataclass
class ActorProfile:
    """Generic actor metadata shared by controllable and scripted entities."""

    kind: str = "lander"
    name: str | None = None
    tags: list[str] = field(default_factory=list)


@dataclass
class ActorControlRole:
    """Who drives this actor: human, bot, script, or none."""

    role: str = "none"


@dataclass
class PlayerSelectable:
    """Marker component for actors eligible for player focus switching."""

    order: int = 0


@dataclass
class PlayerControlled:
    """Marker component for the currently player-controlled actor."""

    active: bool = True


@dataclass
class ControlIntent:
    """Per-frame control input selected by the game loop."""

    target_thrust: float | None = None
    target_angle: float | None = None
    refuel_requested: bool = False


@dataclass
class ScriptFrame:
    """Deterministic scripted action for a finite duration."""

    duration: float = 1.0
    target_thrust: float | None = None
    target_angle: float | None = None
    refuel: bool = False
    velocity: Vector2 | None = None


@dataclass
class ScriptController:
    """Stateful timeline controller for scripted actors."""

    frames: list[ScriptFrame] = field(default_factory=list)
    loop: bool = True
    enabled: bool = True
    frame_index: int = 0
    frame_elapsed: float = 0.0


@dataclass
class RefuelConfig:
    """Economic and short-range interaction configuration."""

    refuel_rate: float = 1.0
    proximity_sensor_range: float = 500.0


@dataclass
class SensorReadings:
    """Cached sensor outputs produced by SensorUpdateSystem."""

    radar_contacts: list["RadarContact"] = field(default_factory=list)
    proximity: "ProximityContact | None" = None


@dataclass
class LandingSite:
    """Landing-site shape and terrain interaction config."""

    size: float = 80.0
    terrain_mode: str = "flush_flatten"  # flush_flatten, cut_in, elevated_supports
    terrain_bound: bool = True
    blend_margin: float = 20.0
    cut_depth: float = 30.0
    support_height: float = 40.0


@dataclass
class LandingSiteEconomy:
    """Economy state associated with a landing site."""

    award: float = 0.0
    fuel_price: float = 10.0
    visited: bool = False


@dataclass
class KinematicMotion:
    """Kinematic velocity used by non-physics entities."""

    velocity: Vector2 = field(default_factory=lambda: Vector2(0.0, 0.0))


@dataclass
class SiteAttachment:
    """Attach a site to another entity using a local offset."""

    parent_uid: str | None = None
    local_offset: Vector2 = field(default_factory=lambda: Vector2(0.0, 0.0))


@dataclass
class ContactReport:
    """Typed contact report replacing untyped dict."""

    colliding: bool = False
    normal: tuple[float, float] | None = None
    rel_speed: float = 0.0
    point: tuple[float, float] | None = None
