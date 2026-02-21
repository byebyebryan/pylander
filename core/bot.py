"""Bot interface for autonomous lander control."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Protocol, Any, Callable
from core.sensor import RadarContact, ProximityContact


@dataclass(frozen=True)
class VehicleInfo:
    """Static vehicle parameters provided to the bot once at setup."""
    width: float
    height: float
    dry_mass: float
    fuel_density: float
    max_thrust_power: float
    safe_landing_velocity: float
    safe_landing_angle: float
    radar_outer_range: float
    radar_inner_range: float
    proximity_sensor_range: float


@dataclass(frozen=True)
class PassiveSensors:
    """Passive sensors snapshot available to the bot each frame.

    Omits any callable active sensors and economy details.
    """

    # Lander world position (world units)
    x: float
    y: float

    # Local terrain context
    altitude: float  # vertical clearance above terrain under centerline
    terrain_y: float
    terrain_slope: float  # dy/dx under centerline

    # Lander kinematics (world units)
    vx: float  # right +
    vy_up: float  # up +
    angle: float  # radians, 0 = upright
    ax: float  # right +
    ay_up: float  # up +
    mass: float

    # Lander resources/state
    thrust_level: float  # 0..1
    fuel: float  # 0..100
    state: str  # "flying", "landed", "crashed", ...

    # Radar contacts: list of RadarContact
    radar_contacts: list[RadarContact]
    # Proximity sensor: closest terrain contact within range
    proximity: ProximityContact | None = None


class ActiveSensors(Protocol):
    """Active sensor interfaces callable by the bot each frame."""

    def raycast(
        self, dir_angle: float, max_range: float | None = None
    ) -> dict[str, Any]:
        """Cast a ray in world-space direction.

        Returns a dict: {"hit": bool, "distance": float, "hit_x": float, "hit_y": float}
        """
        ...

    def terrain_height(self, world_x: float, lod: int = 0) -> float:
        """Return terrain height y at world x."""
        ...

    def terrain_profile(
        self, x_start: float, x_end: float, samples: int = 16, lod: int = 0
    ) -> list[tuple[float, float]]:
        """Sample terrain between two x-coordinates."""
        ...


@dataclass
class BotAction:
    """Explicit action outputs from the bot for this frame (target-based)."""

    target_thrust: float  # 0..1
    target_angle: float  # radians
    refuel: bool
    status: str = ""  # bot status for UI
    message: str = ""  # optional message (not persisted)


class Bot(ABC):
    """Abstract base class for lander bots using sensor/action interface."""

    def __init__(self):
        self.status = ""
        self.vehicle_info: VehicleInfo | None = None

    @abstractmethod
    def update(
        self, dt: float, passive: PassiveSensors, active: ActiveSensors
    ) -> BotAction:
        """Calculate the next action based on sensors.

        Args:
            dt: Delta time in seconds
            passive: PassiveSensors snapshot for this frame
            active: ActiveSensors callable interfaces for this frame

        Returns:
            BotAction describing control outputs and metadata
        """
        raise NotImplementedError

    def get_status(self) -> str:
        """Get current bot status message for UI/logs."""
        return self.status

    def set_vehicle_info(self, info: "VehicleInfo"):
        """Provide static vehicle parameters (dimensions, masses, performance)."""
        self.vehicle_info = info

    def get_stats_text(self) -> list[str]:
        """Return a list of UI text lines for this bot.

        Default shows only the current status, if any. Bots can override.
        """
        s = self.get_status() if hasattr(self, "get_status") else ""
        if s:
            return ["", f"BOT: {s}"]
        return []

    def get_headless_stats(self) -> str:
        """Return a concise single-line stats string for headless logs.

        Default uses status if available; bots can override to add more.
        """
        s = self.get_status() if hasattr(self, "get_status") else ""
        return f"bot:{s}" if s else ""


class _ActiveSensorImpl:
    """Concrete ActiveSensors implementation backed by an engine adapter."""

    def __init__(
        self,
        origin_fn: Callable[[], Any],
        radar_range_fn: Callable[[], float],
        engine_adapter,
        actor_uid: str | None = None,
        terrain_fn: Callable[[float, int], float] | Callable[[float], float] | None = None,
    ):
        self._origin = origin_fn
        self._range = radar_range_fn
        self._engine = engine_adapter
        self._actor_uid = actor_uid
        self._terrain = terrain_fn

    def raycast(self, dir_angle: float, max_range: float | None = None) -> dict:
        rng = self._range() if max_range is None else max_range
        if self._engine is None:
            return {"hit": False, "hit_x": 0.0, "hit_y": 0.0, "distance": None}
        return self._engine.raycast(self._origin(), dir_angle, rng, uid=self._actor_uid)

    def terrain_height(self, world_x: float, lod: int = 0) -> float:
        if self._terrain is None:
            return 0.0
        try:
            return float(self._terrain(world_x, lod))
        except TypeError:
            return float(self._terrain(world_x))

    def terrain_profile(
        self, x_start: float, x_end: float, samples: int = 16, lod: int = 0
    ) -> list[tuple[float, float]]:
        n = max(2, int(samples))
        out: list[tuple[float, float]] = []
        span = x_end - x_start
        for i in range(n):
            t = i / (n - 1)
            xx = x_start + span * t
            out.append((xx, self.terrain_height(xx, lod=lod)))
        return out
