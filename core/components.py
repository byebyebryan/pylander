from dataclasses import dataclass, field
from core.maths import Vector2, Transform as MathTransform
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

    def as_transform(self) -> MathTransform:
        """Return a core.maths.Transform for calculation."""
        return MathTransform(self.pos, self.rotation)

@dataclass
class PhysicsState:
    """Component representing physical properties."""
    vel: Vector2 = field(default_factory=lambda: Vector2(0.0, 0.0))
    acc: Vector2 = field(default_factory=lambda: Vector2(0.0, 0.0))
    mass: float = 1.0
    
    # Legacy compatibility properties
    @property
    def vx(self) -> float: return self.vel.x
    @vx.setter
    def vx(self, v: float): self.vel.x = v
    
    @property
    def vy(self) -> float: return self.vel.y
    @vy.setter
    def vy(self, v: float): self.vel.y = v

    @property
    def ax(self) -> float: return self.acc.x
    @ax.setter
    def ax(self, v: float): self.acc.x = v

    @property
    def ay(self) -> float: return self.acc.y
    @ay.setter
    def ay(self, v: float): self.acc.y = v

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
