"""Bot interface for autonomous lander control."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Protocol, Any, Callable

from core.bot_queries import (
    BotQuery,
    BotQueryResults,
)
from core.sensor import RadarContact, ProximityContact
from core.terrain import sample_ballistic_trajectory


@dataclass(frozen=True)
class VehicleInfo:
    """Static vehicle parameters provided to the bot once at setup."""
    width: float
    height: float
    dry_mass: float
    cargo_mass: float
    max_cargo_mass: float
    fuel_density: float
    max_fuel: float
    max_thrust_power: float
    min_thrust: float
    max_thrust: float
    thrust_increase_rate: float
    thrust_decrease_rate: float
    base_burn_rate: float
    overdrive_burn_multiplier: float
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
    thrust_level: float  # 0..vehicle.max_thrust
    fuel: float  # 0..100
    max_fuel: float
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

    def ballistic_trajectory(
        self,
        x: float,
        y: float,
        vx: float,
        vy_up: float,
        *,
        max_distance: float = 3000.0,
        segment_length: float = 24.0,
        max_points: int = 256,
        lod: int = 0,
        clearance: float = 0.0,
    ) -> dict[str, Any]:
        """Predict engine-off trajectory against terrain.

        Returns keys:
        - points, hit, hit_x, hit_y, hit_time
        - hit_vx, hit_vy_up, hit_speed
        - distance, duration, termination
        """
        ...


@dataclass
class BotAction:
    """Explicit action outputs from the bot for this frame (target-based)."""

    target_thrust: float  # 0..vehicle.max_thrust
    target_angle: float  # radians
    refuel: bool
    status: str = ""  # bot status for UI
    message: str = ""  # optional message (not persisted)


class Bot(ABC):
    """Abstract base class for lander bots using sensor/action interface."""

    def __init__(self):
        self.status = ""
        self.vehicle_info: VehicleInfo | None = None
        self._pinned_target_uid: str | None = None

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

    @property
    def pinned_target_uid(self) -> str | None:
        """Optional radar contact UID to force as the active target."""
        return self._pinned_target_uid

    def set_pinned_target_uid(self, target_uid: str | None) -> None:
        """Pin target selection to a specific radar contact UID."""
        if target_uid is None:
            self._pinned_target_uid = None
            return
        normalized = str(target_uid).strip()
        self._pinned_target_uid = normalized if normalized else None

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

    def get_evaluation_snapshot(self) -> dict[str, Any] | None:
        """Return optional structured evaluation state for the current frame."""
        return None


class QueryBot(Bot, ABC):
    """Optional two-stage bot API for batched active sensor queries."""

    @abstractmethod
    def plan(self, dt: float, passive: PassiveSensors) -> list[BotQuery]:
        """Declare active sensor queries required for this tick."""
        raise NotImplementedError

    @abstractmethod
    def act(
        self,
        dt: float,
        passive: PassiveSensors,
        results: BotQueryResults,
    ) -> BotAction:
        """Produce action from passive sensors plus evaluated query results."""
        raise NotImplementedError

    def update(
        self, dt: float, passive: PassiveSensors, active: ActiveSensors
    ) -> BotAction:
        _ = dt, passive, active
        raise RuntimeError(
            "QueryBot.update() should not be called directly; "
            "use plan()/act() via the game query loop."
        )


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
        # _ActiveSensorImpl instances are built once per bot step, so this is
        # effectively a per-step cache for repeated ballistic queries.
        self._ballistic_cache: dict[tuple[Any, ...], dict[str, Any]] = {}

    @staticmethod
    def _copy_ballistic_payload(payload: dict[str, Any]) -> dict[str, Any]:
        out = dict(payload)
        points = payload.get("points")
        if isinstance(points, list):
            out["points"] = list(points)
        return out

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

    def ballistic_trajectory(
        self,
        x: float,
        y: float,
        vx: float,
        vy_up: float,
        *,
        max_distance: float = 3000.0,
        segment_length: float = 24.0,
        max_points: int = 256,
        lod: int = 0,
        clearance: float = 0.0,
    ) -> dict[str, Any]:
        key = (
            float(x),
            float(y),
            float(vx),
            float(vy_up),
            float(max_distance),
            float(segment_length),
            int(max_points),
            int(lod),
            float(clearance),
        )
        cached = self._ballistic_cache.get(key)
        if cached is not None:
            return self._copy_ballistic_payload(cached)
        if self._terrain is None:
            payload = {
                "points": [(float(x), float(y))],
                "hit": False,
                "hit_x": None,
                "hit_y": None,
                "hit_time": None,
                "hit_vx": None,
                "hit_vy_up": None,
                "hit_speed": None,
                "distance": 0.0,
                "duration": 0.0,
                "termination": "no_terrain",
            }
            self._ballistic_cache[key] = payload
            return self._copy_ballistic_payload(payload)
        result = sample_ballistic_trajectory(
            self._terrain,
            x=x,
            y=y,
            vx=vx,
            vy_up=vy_up,
            max_distance=max_distance,
            segment_length=segment_length,
            max_points=max_points,
            lod=lod,
            clearance=clearance,
        )
        payload = {
            "points": result.points,
            "hit": result.hit,
            "hit_x": result.hit_x,
            "hit_y": result.hit_y,
            "hit_time": result.hit_time,
            "hit_vx": result.hit_vx,
            "hit_vy_up": result.hit_vy_up,
            "hit_speed": result.hit_speed,
            "distance": result.distance,
            "duration": result.duration,
            "termination": result.termination,
        }
        self._ballistic_cache[key] = payload
        return self._copy_ballistic_payload(payload)
