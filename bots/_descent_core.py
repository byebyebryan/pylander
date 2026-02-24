"""Shared descent guidance/control core for strategy variants."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Mapping, TypeVar

from core.bot import ActiveSensors, Bot, BotAction, PassiveSensors, VehicleInfo
from core.sensor import RadarContact
from core.terrain import ballistic_fall_time

_BehaviorT = TypeVar("_BehaviorT")


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def normalize_behavior_key(behavior: str) -> str:
    return str(behavior).strip().lower().replace("-", "_")


def resolve_behavior(
    behavior: str,
    behaviors: Mapping[str, _BehaviorT],
    *,
    context: str,
) -> tuple[str, _BehaviorT]:
    key = normalize_behavior_key(behavior)
    if key not in behaviors:
        known = ", ".join(sorted(behaviors))
        raise ValueError(
            f"Unknown {context} behavior '{behavior}'. Expected one of: {known}"
        )
    return key, behaviors[key]


def rate_limit_angle_command(
    target_angle: float,
    prev_angle: float,
    dt: float,
    *,
    max_rate: float = 2.2,
) -> float:
    max_delta = max_rate * max(dt, 1e-3)
    return clamp(target_angle, prev_angle - max_delta, prev_angle + max_delta)


def stable(value: float, digits: int = 1) -> float:
    epsilon = 0.5 * (10.0 ** (-digits))
    return 0.0 if abs(value) < epsilon else value


def pick_target(passive: PassiveSensors) -> RadarContact | None:
    contacts = passive.radar_contacts or []
    if not contacts:
        return None
    inner = [c for c in contacts if c.is_inner_lock]
    candidates = inner if inner else contacts
    return min(candidates, key=lambda c: c.distance)


def finite_altitude(passive: PassiveSensors) -> float:
    if math.isfinite(passive.altitude):
        return passive.altitude
    return 1e9


def vehicle_limits(passive: PassiveSensors, max_force: float) -> tuple[float, float]:
    mass = max(0.5, passive.mass)
    up_acc_max = max(0.1, (max_force / mass) - 9.8)
    return mass, up_acc_max


def ballistic_time_to_impact(
    passive: PassiveSensors,
    active: ActiveSensors | None,
) -> tuple[float, str]:
    """Estimate time-to-impact using sensor hit-time when available."""
    alt = max(0.0, finite_altitude(passive))
    vy_up = passive.vy_up if math.isfinite(passive.vy_up) else 0.0
    fallback = ballistic_fall_time(altitude=alt, vy_up=vy_up)
    if active is None:
        return fallback, "analytic"

    distance_budget = max(
        900.0,
        abs(float(passive.vx)) * max(2.0, fallback) + (0.5 * alt) + 500.0,
    )
    try:
        traj = active.ballistic_trajectory(
            x=passive.x,
            y=passive.y,
            vx=passive.vx,
            vy_up=passive.vy_up,
            max_distance=min(5000.0, distance_budget),
            segment_length=20.0,
            max_points=192,
            lod=0,
            clearance=0.0,
        )
    except Exception:
        return fallback, "analytic"
    if not isinstance(traj, dict) or not bool(traj.get("hit")):
        return fallback, "analytic"

    hit_time = traj.get("hit_time")
    if isinstance(hit_time, (int, float)) and math.isfinite(float(hit_time)):
        return max(0.0, float(hit_time)), "sensor"
    duration = traj.get("duration")
    if isinstance(duration, (int, float)) and math.isfinite(float(duration)):
        return max(0.0, float(duration)), "sensor"
    return fallback, "analytic"


def engine_profile(vehicle_info: VehicleInfo | None) -> tuple[float, float, float, float]:
    if vehicle_info is None:
        # Keep fallback aligned with Engine defaults in SI-like units.
        return 230000.0, 0.25, 1.6, 1.1
    max_power = max(1e-3, float(vehicle_info.max_thrust_power))
    max_throttle = max(0.0, float(vehicle_info.max_thrust))
    min_throttle = max(0.0, min(float(vehicle_info.min_thrust), max_throttle))
    ramp_up = max(0.1, float(vehicle_info.thrust_increase_rate))
    return max_power, min_throttle, max_throttle, ramp_up


@dataclass(frozen=True)
class GuidanceTargets:
    phase: str
    vertical_mode: str
    vx_sp: float
    vy_sp: float
    dx: float
    alt: float
    burn_altitude: float


@dataclass(frozen=True)
class DescentPolicy:
    status_prefix: str
    lateral_gain: float = 1.0
    descent_rate_scale: float = 1.0
    burn_margin_scale: float = 1.0
    time_to_brake_buffer: float = 0.2
    coast_horiz_deadband: float = 14.0
    terminal_brake_gain_high_alt: float = 0.94
    terminal_brake_gain_low_alt: float = 0.82
    overdrive_soft_cap: float = 1.0
    allow_overdrive: bool = True
    overdrive_requires_terminal_burn: bool = True
    emergency_vy_threshold: float = -6.0
    emergency_low_alt: float = 12.0
    emergency_low_alt_vy_threshold: float = -3.5
    min_fuel_ratio_for_overdrive: float = 0.16
    enable_gravity_glide: bool = False
    glide_altitude_min: float = 120.0
    glide_upward_vy_min: float = 1.0
    enable_speed_dive: bool = False
    speed_dive_altitude_min: float = 180.0
    speed_dive_downspeed_max: float = 8.0
    speed_dive_target_vy: float = -9.0


BALANCED_POLICY = DescentPolicy(status_prefix="descent")
SPEED_POLICY = DescentPolicy(
    status_prefix="descent_speed",
    lateral_gain=1.0,
    descent_rate_scale=1.28,
    burn_margin_scale=0.82,
    time_to_brake_buffer=0.05,
    coast_horiz_deadband=14.0,
    terminal_brake_gain_high_alt=1.08,
    terminal_brake_gain_low_alt=0.98,
    overdrive_soft_cap=1.6,
    overdrive_requires_terminal_burn=False,
    min_fuel_ratio_for_overdrive=0.03,
    enable_speed_dive=True,
    speed_dive_altitude_min=160.0,
    speed_dive_downspeed_max=10.0,
    speed_dive_target_vy=-11.0,
)
ECON_POLICY = DescentPolicy(
    status_prefix="descent_econ",
    lateral_gain=1.0,
    descent_rate_scale=0.78,
    burn_margin_scale=1.35,
    time_to_brake_buffer=0.45,
    coast_horiz_deadband=14.0,
    terminal_brake_gain_high_alt=0.8,
    terminal_brake_gain_low_alt=0.68,
    overdrive_soft_cap=0.9,
    min_fuel_ratio_for_overdrive=0.45,
    emergency_vy_threshold=-7.0,
    emergency_low_alt_vy_threshold=-4.5,
    enable_gravity_glide=True,
    glide_altitude_min=80.0,
    glide_upward_vy_min=0.6,
)
class StrategyDescentBot(Bot):
    def __init__(self, policy: DescentPolicy) -> None:
        super().__init__()
        self._policy = policy
        self._prev_angle_cmd = 0.0
        self._ballistic_debug_summary = ""

    def _engine_profile(self) -> tuple[float, float, float, float]:
        return engine_profile(self.vehicle_info)

    def _fuel_ratio(self, passive: PassiveSensors) -> float:
        max_fuel = max(1e-6, float(passive.max_fuel))
        return clamp(float(passive.fuel) / max_fuel, 0.0, 1.0)

    def _terminal_brake_altitude(
        self,
        passive: PassiveSensors,
        *,
        alt: float,
        dx: float,
        burn_altitude: float,
        spool_time: float,
        max_force: float,
    ) -> float:
        _ = passive, alt, dx, spool_time, max_force
        return burn_altitude

    def _guidance(
        self,
        passive: PassiveSensors,
        target: RadarContact,
        *,
        max_force: float,
        max_throttle: float,
        ramp_up: float,
        active: ActiveSensors | None = None,
    ) -> GuidanceTargets:
        alt = finite_altitude(passive)
        dx = target.x - passive.x
        abs_dx = abs(dx)
        _, up_acc_max = vehicle_limits(passive, max_force)

        align_band = 10.0
        vx_cap = clamp(2.2 + (0.03 * alt), 2.2, 8.0)
        vx_sp = clamp(dx * 0.09 * self._policy.lateral_gain, -vx_cap, vx_cap)

        down_speed = max(0.0, -passive.vy_up)
        nominal_throttle = min(1.0, max_throttle)
        spool_time = max(0.0, nominal_throttle - max(0.0, passive.thrust_level)) / ramp_up
        spool_distance = (down_speed * spool_time) + (4.9 * spool_time * spool_time)
        flare_speed = clamp(0.45 + (0.11 * alt), 0.7, 2.5)
        speed_to_kill = max(0.0, down_speed - flare_speed)
        stop_distance = (speed_to_kill * speed_to_kill) / (2.0 * max(up_acc_max, 1e-3))
        burn_margin = (2.1 + (0.12 * max(0.0, abs_dx - align_band))) * self._policy.burn_margin_scale
        burn_altitude = stop_distance + spool_distance + burn_margin
        burn_altitude = self._terminal_brake_altitude(
            passive,
            alt=alt,
            dx=dx,
            burn_altitude=burn_altitude,
            spool_time=spool_time,
            max_force=max_force,
        )

        time_to_impact, impact_source = ballistic_time_to_impact(passive, active)
        time_to_brake = spool_time + (speed_to_kill / max(up_acc_max, 1e-3))
        burn_now = bool(
            down_speed > 0.6
            and (
                alt <= burn_altitude
                or time_to_impact <= (time_to_brake + self._policy.time_to_brake_buffer)
            )
        )
        self._ballistic_debug_summary = (
            f"ball tti:{stable(time_to_impact, 1):4.1f} "
            f"src:{'s' if impact_source == 'sensor' else 'a'} "
            f"burn:{int(burn_now)}"
        )

        gravity_glide = (
            self._policy.enable_gravity_glide
            and alt >= self._policy.glide_altitude_min
            and passive.vy_up >= self._policy.glide_upward_vy_min
        )
        speed_dive = (
            self._policy.enable_speed_dive
            and alt >= self._policy.speed_dive_altitude_min
            and down_speed <= self._policy.speed_dive_downspeed_max
            and not burn_now
        )

        if gravity_glide:
            vertical_mode = "eco_glide"
            vy_sp = -0.2
            vx_sp = 0.0
        elif speed_dive:
            vertical_mode = "speed_dive"
            vy_sp = self._policy.speed_dive_target_vy
            vx_sp = clamp(vx_sp, -1.8, 1.8)
        elif burn_now:
            vertical_mode = "terminal_burn"
            vy_sp = -clamp(0.45 + (0.11 * alt), 0.55, 2.2)
            vy_sp *= self._policy.descent_rate_scale
            vx_sp = clamp(vx_sp, -1.2, 1.2)
        elif alt < 7.0 and abs_dx <= 10.0:
            vertical_mode = "flare"
            vy_sp = -clamp(0.35 + (0.09 * alt), 0.45, 1.0)
            vy_sp *= self._policy.descent_rate_scale
            vx_sp = clamp(vx_sp, -0.8, 0.8)
        elif abs_dx > align_band and alt < 45.0:
            vertical_mode = "coast"
            vy_sp = -clamp(1.1 + (0.18 * math.sqrt(max(0.0, alt))), 1.2, 3.0)
            vy_sp *= self._policy.descent_rate_scale
            vx_sp = clamp(dx * 0.13 * self._policy.lateral_gain, -7.5, 7.5)
        else:
            vertical_mode = "coast"
            vy_sp = -clamp(1.2 + (0.3 * math.sqrt(max(0.0, alt))), 1.4, 6.0)
            vy_sp *= self._policy.descent_rate_scale

        if alt < 4.2 and abs_dx <= 8.0:
            phase = "touchdown"
            vertical_mode = "flare"
            vy_sp = -clamp(0.3 + (0.07 * alt), 0.4, 0.75)
            vy_sp *= self._policy.descent_rate_scale
        elif gravity_glide:
            phase = "eco_glide"
        elif speed_dive:
            phase = "speed_dive"
        elif burn_now:
            phase = "terminal_burn"
        elif vertical_mode == "flare":
            phase = "flare"
        elif abs_dx > align_band and alt < 45.0:
            phase = "align"
        else:
            phase = "coast"

        return GuidanceTargets(
            phase=phase,
            vertical_mode=vertical_mode,
            vx_sp=vx_sp,
            vy_sp=vy_sp,
            dx=dx,
            alt=alt,
            burn_altitude=burn_altitude,
        )

    def _horizontal_controller(
        self,
        passive: PassiveSensors,
        vx_sp: float,
    ) -> float:
        vx_err = vx_sp - passive.vx
        return (0.5 * vx_err) - (0.1 * passive.ax)

    def _vertical_controller(
        self,
        passive: PassiveSensors,
        vy_sp: float,
        alt: float,
        vertical_mode: str,
        up_acc_max: float,
    ) -> float:
        if vertical_mode == "coast":
            return 0.0
        if vertical_mode == "eco_glide":
            return 0.0
        if vertical_mode == "speed_dive":
            return 0.0
        if vertical_mode == "drift_coast":
            vy_err = vy_sp - passive.vy_up
            # Keep correction burns thrust-backed without drifting into hover.
            a_up_cmd = 7.2 + (0.2 * vy_err)
            max_up_cmd = 9.8 if alt < 14.0 else 9.25
            return clamp(a_up_cmd, 4.8, max_up_cmd)
        if vertical_mode == "terminal_burn":
            brake_gain = (
                self._policy.terminal_brake_gain_high_alt
                if alt > 8.0
                else self._policy.terminal_brake_gain_low_alt
            )
            a_up_cmd = 9.8 + (brake_gain * up_acc_max)
            if passive.vy_up > -0.7:
                a_up_cmd = min(a_up_cmd, 9.8 + (0.45 * up_acc_max))
            return a_up_cmd

        vy_err = vy_sp - passive.vy_up
        a_up_cmd = 9.8 + (0.38 * vy_err)
        if alt < 7.0:
            a_up_cmd += 0.08
        if alt < 3.0 and passive.vy_up > -0.45:
            a_up_cmd -= 0.12
        return a_up_cmd

    def _can_use_overdrive(
        self,
        passive: PassiveSensors,
        *,
        vertical_mode: str,
        alt: float,
    ) -> bool:
        if not self._policy.allow_overdrive:
            return False
        fuel_ratio = self._fuel_ratio(passive)
        if fuel_ratio < self._policy.min_fuel_ratio_for_overdrive:
            return False
        if self._policy.overdrive_requires_terminal_burn and vertical_mode != "terminal_burn":
            return False
        return (
            passive.vy_up < self._policy.emergency_vy_threshold
            or (
                alt < self._policy.emergency_low_alt
                and passive.vy_up < self._policy.emergency_low_alt_vy_threshold
            )
        )

    def _allocate_controls(
        self,
        dt: float,
        passive: PassiveSensors,
        *,
        a_x_sp: float,
        a_up_sp: float,
        alt: float,
        dx: float,
        vertical_mode: str,
    ) -> BotAction:
        max_power, min_throttle, max_throttle, _ = self._engine_profile()
        max_force = max_power * max_throttle
        mass, _ = vehicle_limits(passive, max_force)

        req = clamp((a_x_sp * mass) / max(max_force, 1e-3), -0.95, 0.95)
        angle_cmd = math.asin(req)
        max_tilt = 0.18 if alt < 20.0 else 0.56
        angle_cmd = clamp(angle_cmd, -max_tilt, max_tilt)

        angle_cmd = rate_limit_angle_command(
            angle_cmd,
            self._prev_angle_cmd,
            dt,
        )
        self._prev_angle_cmd = angle_cmd

        cos_term = max(0.25, abs(math.cos(angle_cmd)))
        thrust = (mass * a_up_sp) / max(max_power * cos_term, 1e-3)
        if alt < 9.0 and abs(dx) <= 10.0:
            angle_cmd = 0.0
        if alt < 2.5 and abs(dx) <= 7.0 and abs(passive.vx) < 0.6 and abs(passive.vy_up) < 0.9:
            thrust = 0.0
            angle_cmd = 0.0

        soft_cap = min(self._policy.overdrive_soft_cap, max_throttle)
        if thrust > soft_cap and not self._can_use_overdrive(
            passive,
            vertical_mode=vertical_mode,
            alt=alt,
        ):
            thrust = soft_cap

        thrust = clamp(thrust, 0.0, max_throttle)
        if thrust > 0.0:
            thrust = max(min_throttle, thrust)
        return BotAction(target_thrust=thrust, target_angle=angle_cmd, refuel=False)

    def update(
        self,
        dt: float,
        passive: PassiveSensors,
        active: ActiveSensors,
    ) -> BotAction:
        if passive.state in ("landed", "crashed", "out_of_fuel"):
            self._ballistic_debug_summary = ""
            action = BotAction(
                0.0,
                passive.angle,
                False,
                status=f"{self._policy.status_prefix}:{passive.state}",
            )
            self.status = action.status
            return action

        max_power, _, max_throttle, ramp_up = self._engine_profile()
        max_force = max_power * max_throttle
        _, up_acc_max = vehicle_limits(passive, max_force)

        target = pick_target(passive)
        if target is None:
            t_impact, impact_source = ballistic_time_to_impact(passive, active)
            self._ballistic_debug_summary = (
                f"ball tti:{stable(t_impact, 1):4.1f} "
                f"src:{'s' if impact_source == 'sensor' else 'a'} "
                "burn:0"
            )
            a_x_sp = self._horizontal_controller(passive, vx_sp=0.0)
            a_up_sp = self._vertical_controller(
                passive,
                vy_sp=-1.0,
                alt=finite_altitude(passive),
                vertical_mode="flare",
                up_acc_max=up_acc_max,
            )
            action = self._allocate_controls(
                dt,
                passive,
                a_x_sp=a_x_sp,
                a_up_sp=a_up_sp,
                dx=0.0,
                alt=finite_altitude(passive),
                vertical_mode="flare",
            )
            action.status = f"{self._policy.status_prefix}:search"
            self.status = action.status
            return action

        guidance = self._guidance(
            passive,
            target,
            max_force=max_force,
            max_throttle=max_throttle,
            ramp_up=ramp_up,
            active=active,
        )
        if guidance.vertical_mode in ("coast", "drift_coast") and abs(
            guidance.dx
        ) <= self._policy.coast_horiz_deadband:
            if self._policy.status_prefix == "drift":
                deadband = max(1e-3, self._policy.coast_horiz_deadband)
                deadband_ratio = clamp(abs(guidance.dx) / deadband, 0.0, 1.0)
                softened_vx_sp = guidance.vx_sp * deadband_ratio
                a_x_sp = self._horizontal_controller(passive, softened_vx_sp)
            else:
                a_x_sp = 0.0
        else:
            a_x_sp = self._horizontal_controller(passive, guidance.vx_sp)
        a_up_sp = self._vertical_controller(
            passive,
            guidance.vy_sp,
            guidance.alt,
            guidance.vertical_mode,
            up_acc_max,
        )
        action = self._allocate_controls(
            dt,
            passive,
            a_x_sp=a_x_sp,
            a_up_sp=a_up_sp,
            dx=guidance.dx,
            alt=guidance.alt,
            vertical_mode=guidance.vertical_mode,
        )

        action.status = (
            f"{self._policy.status_prefix}:{guidance.phase} dx:{stable(guidance.dx, 1):6.1f} "
            f"vx:{stable(passive.vx, 1):5.1f} vy:{stable(passive.vy_up, 1):5.1f} "
            f"vys:{stable(guidance.vy_sp, 1):5.1f} "
            f"balt:{stable(guidance.burn_altitude, 1):5.1f}"
        )
        self.status = action.status
        return action

    def get_headless_stats(self) -> str:
        base = super().get_headless_stats()
        if not self._ballistic_debug_summary:
            return base
        if not base:
            return self._ballistic_debug_summary
        return f"{base} {self._ballistic_debug_summary}"


__all__ = [
    "BALANCED_POLICY",
    "ECON_POLICY",
    "GuidanceTargets",
    "DescentPolicy",
    "SPEED_POLICY",
    "StrategyDescentBot",
    "clamp",
    "ballistic_time_to_impact",
    "engine_profile",
    "finite_altitude",
    "normalize_behavior_key",
    "pick_target",
    "rate_limit_angle_command",
    "resolve_behavior",
    "stable",
    "vehicle_limits",
]
