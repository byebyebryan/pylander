"""Bot interface for autonomous lander control."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Protocol, Any
from sensor import RadarContact, ProximityContact


@dataclass
class PassiveSensors:
    """Passive sensors snapshot available to the bot each frame.

    Omits any callable active sensors and economy details.
    """

    # Lander kinematics (world units)
    altitude: float  # absolute world-space y
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
        self.vehicle_info: dict | None = None

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

    def set_vehicle_info(self, info: dict):
        """Provide static vehicle parameters (dimensions, masses, performance)."""
        self.vehicle_info = dict(info) if info is not None else {}

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


"""
Concrete bot classes moved into the `bots/` package.
- `bots.turtle.TurtleBot`
- `bots.hare.HareBot`
- `bots.magpie.MagpieBot`
"""
