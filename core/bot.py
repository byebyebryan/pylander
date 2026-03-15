"""Bot interface for autonomous lander control."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from core.eval_goals import EVAL_GOAL_LANDING, normalize_eval_goal, normalize_eval_goals
from core.sensor import RadarContact, ProximityContact


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
class Sensors:
    """Sensors snapshot available to the bot each frame."""

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


@dataclass
class BotAction:
    """Explicit action outputs from the bot for this frame (target-based)."""

    target_thrust: float  # 0..vehicle.max_thrust
    target_angle: float  # radians
    refuel: bool
    status: str = ""  # bot status for UI
    message: str = ""  # optional message (not persisted)


@dataclass(frozen=True)
class BotEvalDecision:
    """Optional bot-provided evaluation decision for the current run."""

    should_end: bool = False
    success: bool | None = None
    failure_mode: str | None = None
    end_reason: str | None = None
    metrics: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SetupGateMetrics:
    """Optional shared setup-gate metrics for tuning and evaluation."""

    time_s: float | None = None
    altitude: float | None = None
    x: float | None = None
    y: float | None = None
    vx: float | None = None
    vy_up: float | None = None
    projected_apex_y: float | None = None
    projected_apex_over_target: float | None = None
    has_target_y_solution: bool | None = None
    projected_dx: float | None = None
    projected_impact_dx: float | None = None
    projected_impact_angle_deg: float | None = None
    burn_duration_s: float | None = None
    burn_fuel_used: float | None = None
    burn_avg_thrust_level: float | None = None


@dataclass(frozen=True)
class FlightPhaseSnapshot:
    """Optional generic flight-phase state for runtime consumers."""

    phase: str | None
    milestones: tuple[str, ...] = ()
    setup_gate: SetupGateMetrics | None = None


@dataclass(frozen=True)
class BotDisplayState:
    """Structured bot status for UI and headless presentation."""

    bot_name: str | None = None
    mode: str | None = None
    phase: str | None = None
    summary: str = ""
    detail: str = ""


@dataclass(frozen=True)
class PlotMarker:
    """Optional generic plot marker emitted by a bot."""

    id: str
    name: str
    label: str | None = None
    x: float | None = None
    y: float | None = None
    metadata: dict[str, float | str | None] = field(default_factory=dict)


def resolve_bot_name(bot: "Bot") -> str:
    bot_name = getattr(bot, "_bot_name", None)
    if isinstance(bot_name, str) and bot_name:
        return bot_name
    return bot.__class__.__module__.split(".")[-1]


def resolve_bot_status(bot: "Bot") -> str:
    get_status = getattr(bot, "get_status", None)
    if callable(get_status):
        resolved_status = get_status()
        return resolved_status.strip() if isinstance(resolved_status, str) else ""
    status = getattr(bot, "status", None)
    return status.strip() if isinstance(status, str) else ""


def resolve_bot_display_state(bot: "Bot") -> BotDisplayState | None:
    getter = getattr(bot, "get_display_state", None)
    if not callable(getter):
        return None
    try:
        display = getter()
    except Exception:
        return None
    return display if isinstance(display, BotDisplayState) else None


class Bot(ABC):
    """Abstract base class for lander bots using sensor/action interface."""

    def __init__(self):
        self.status = ""
        self.vehicle_info: VehicleInfo | None = None
        self._pinned_target_uid: str | None = None
        self._eval_goal = EVAL_GOAL_LANDING

    @abstractmethod
    def update(self, dt: float, sensors: Sensors) -> BotAction:
        """Calculate the next action based on sensors.

        Args:
            dt: Delta time in seconds
            sensors: Sensors snapshot for this frame

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

    def supported_eval_goals(self) -> tuple[str, ...]:
        """Return supported evaluation goals for this bot."""
        return (EVAL_GOAL_LANDING,)

    def set_eval_goal(self, goal: str) -> None:
        """Set evaluation goal for this bot.

        Default behavior supports only the end-to-end landing goal.
        """
        key = normalize_eval_goal(goal)
        supported = normalize_eval_goals(self.supported_eval_goals())
        if key not in supported:
            supported_csv = ", ".join(supported)
            raise ValueError(
                f"Bot '{type(self).__name__}' does not support goal '{goal}'. "
                f"Supported goals: {supported_csv}"
            )
        self._eval_goal = key

    def get_eval_goal(self) -> str:
        return self._eval_goal

    def prime_setup_gate(self, setup_gate: SetupGateMetrics) -> None:
        """Optionally seed a setup-gate milestone before the first update."""
        _ = setup_gate

    def get_evaluation_decision(self) -> BotEvalDecision | None:
        """Return optional evaluation decision for run termination/result shaping."""
        return None

    def get_stats_text(self) -> list[str]:
        """Return a list of UI text lines for this bot.

        Default shows only the current status, if any. Bots can override.
        """
        display = resolve_bot_display_state(self)
        if display is not None:
            lines = [""]
            bot_label = display.bot_name or resolve_bot_name(self)
            if display.mode and display.phase:
                lines.append(f"BOT: {bot_label} [{display.mode}/{display.phase}]")
            elif display.phase:
                lines.append(f"BOT: {bot_label} [{display.phase}]")
            else:
                lines.append(f"BOT: {bot_label}")
            if display.summary:
                lines.append(f"BOT SUMMARY: {display.summary}")
            if display.detail:
                lines.append(f"BOT DETAIL: {display.detail}")
            return lines
        s = resolve_bot_status(self)
        if s:
            return ["", f"BOT: {s}"]
        return []

    def get_headless_stats(self) -> str:
        """Return a concise single-line stats string for headless logs.

        Default uses status if available; bots can override to add more.
        """
        display = resolve_bot_display_state(self)
        if display is not None:
            parts: list[str] = []
            bot_label = display.bot_name or resolve_bot_name(self)
            parts.append(f"bot={bot_label}")
            if display.mode:
                parts.append(f"mode={display.mode}")
            if display.phase:
                parts.append(f"phase={display.phase}")
            if display.summary:
                parts.append(display.summary)
            return " ".join(parts)
        s = resolve_bot_status(self)
        return f"bot:{s}" if s else ""

    def get_bot_telemetry(self) -> dict[str, Any]:
        """Return optional bot-owned telemetry for normalized results."""
        return {}

    def get_display_state(self) -> BotDisplayState | None:
        """Return optional structured display state for UI and headless logs."""
        return None

    def get_flight_phase_snapshot(self) -> FlightPhaseSnapshot | None:
        """Return optional generic phase/milestone state for the current frame."""
        return None

    def get_plot_markers(self) -> tuple[PlotMarker, ...]:
        """Return optional generic diagnostic plot markers for the current frame."""
        return ()
