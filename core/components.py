from dataclasses import dataclass, field
from typing import Any
from core.maths import Vector2, RigidTransform2
import math

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
    mass: float = 1.0

@dataclass
class FuelTank:
    """Component representing fuel storage."""
    fuel: float = 100.0
    max_fuel: float = 100.0
    burn_rate: float = 1.0  # Units per second at max thrust
    density: float = 0.01   # Mass per unit of fuel

@dataclass
class Engine:
    """Component representing propulsion capabilities."""
    thrust_level: float = 0.0       # Current output (0..1)
    target_thrust: float = 0.0      # Desired output (0..1)
    max_power: float = 50.0         # Max force in Newtons
    
    # Control characteristics
    increase_rate: float = 2.0      # Per second
    decrease_rate: float = 4.0      # Per second
    
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
    state: str = "flying"               # "flying", "landed", "crashed", "out_of_fuel"
    safe_landing_velocity: float = 10.0
    safe_landing_angle: float = 0.2618  # math.radians(15)

@dataclass
class Wallet:
    """Component representing the lander's credits balance."""
    credits: float = 0.0


@dataclass
class ControlIntent:
    """Per-frame control input selected by the game loop."""
    target_thrust: float | None = None
    target_angle: float | None = None
    refuel_requested: bool = False


@dataclass
class RefuelConfig:
    """Economic and short-range interaction configuration."""
    refuel_rate: float = 1.0
    proximity_sensor_range: float = 500.0


@dataclass
class SensorReadings:
    """Cached sensor outputs produced by SensorUpdateSystem."""
    radar_contacts: list[Any] = field(default_factory=list)
    proximity: Any | None = None
