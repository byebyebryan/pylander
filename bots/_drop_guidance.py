"""Shared drop-phase guidance primitives."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable

from bots._ballistics import ballistic_time_to_impact, estimate_ballistic_projection
from bots._bot_math import clamp, finite_altitude, stable, vehicle_limits
from bots._guidance_types import GuidanceTargets
from core.bot import ActiveSensors, PassiveSensors
from core.sensor import RadarContact


@dataclass(frozen=True)
class DropPolicy:
    status_prefix: str
    use_projected_lateral_error: bool = True
    lateral_gain: float = 1.0
    lateral_track_gain: float = 0.09
    align_band: float = 10.0
    vx_cap_base: float = 2.2
    vx_cap_alt_gain: float = 0.03
    vx_cap_min: float = 2.2
    vx_cap_max: float = 8.0
    align_lateral_gain: float = 0.13
    align_vx_cap: float = 7.5
    align_low_altitude: float = 45.0
    flare_altitude: float = 7.0
    flare_track_band: float = 10.0
    touchdown_altitude: float = 4.2
    touchdown_track_band: float = 8.0
    descent_rate_scale: float = 1.0
    burn_margin_scale: float = 1.0
    time_to_brake_buffer: float = 0.2
    sensor_time_to_brake_buffer_scale: float = 0.75
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


BASE_DROP_POLICY = DropPolicy(status_prefix="plunge")


def lateral_velocity_targets(policy: DropPolicy, *, alt: float, track_dx: float) -> tuple[float, float]:
    vx_cap = clamp(
        policy.vx_cap_base + (policy.vx_cap_alt_gain * alt),
        policy.vx_cap_min,
        policy.vx_cap_max,
    )
    vx_sp = clamp(
        track_dx * policy.lateral_track_gain * policy.lateral_gain,
        -vx_cap,
        vx_cap,
    )
    return vx_cap, vx_sp


def resolve_drop_phase(
    policy: DropPolicy,
    *,
    alt: float,
    track_dx: float,
    burn_now: bool,
    vertical_mode: str,
) -> str:
    if alt < policy.touchdown_altitude and abs(track_dx) <= policy.touchdown_track_band:
        return "touchdown"
    if burn_now:
        return "terminal_burn"
    if vertical_mode == "flare":
        return "flare"
    if abs(track_dx) > policy.align_band and alt < policy.align_low_altitude:
        return "align"
    return "coast"


TerminalBrakeAltitudeFn = Callable[
    [PassiveSensors, float, float, float, float, float],
    float,
]


def _identity_terminal_brake_altitude(
    passive: PassiveSensors,
    alt: float,
    dx: float,
    burn_altitude: float,
    spool_time: float,
    max_force: float,
) -> float:
    _ = passive, alt, dx, spool_time, max_force
    return burn_altitude


def compute_drop_guidance(
    policy: DropPolicy,
    passive: PassiveSensors,
    target: RadarContact,
    *,
    max_force: float,
    max_throttle: float,
    ramp_up: float,
    active: ActiveSensors | None = None,
    terminal_brake_altitude_fn: TerminalBrakeAltitudeFn | None = None,
) -> tuple[GuidanceTargets, str]:
    alt = finite_altitude(passive)
    dx = target.x - passive.x
    if policy.use_projected_lateral_error:
        projection = estimate_ballistic_projection(
            dx=dx,
            alt=alt,
            vx=passive.vx,
            vy_up=passive.vy_up,
            x=passive.x,
            y=passive.y,
            active=active,
            clearance=0.0,
            segment_length=20.0,
            max_points=192,
            min_t_fall=0.0,
        )
        track_dx = projection.projected_dx
    else:
        track_dx = dx
    abs_track_dx = abs(track_dx)
    _, up_acc_max = vehicle_limits(passive, max_force)

    _, vx_sp = lateral_velocity_targets(policy, alt=alt, track_dx=track_dx)

    down_speed = max(0.0, -passive.vy_up)
    nominal_throttle = min(1.0, max_throttle)
    spool_time = max(0.0, nominal_throttle - max(0.0, passive.thrust_level)) / ramp_up
    spool_distance = (down_speed * spool_time) + (4.9 * spool_time * spool_time)
    flare_speed = clamp(0.45 + (0.11 * alt), 0.7, 2.5)
    speed_to_kill = max(0.0, down_speed - flare_speed)
    stop_distance = (speed_to_kill * speed_to_kill) / (2.0 * max(up_acc_max, 1e-3))
    burn_margin = (
        2.1 + (0.12 * max(0.0, abs_track_dx - policy.align_band))
    ) * policy.burn_margin_scale
    burn_altitude = stop_distance + spool_distance + burn_margin
    terminal_brake_altitude = terminal_brake_altitude_fn or _identity_terminal_brake_altitude
    burn_altitude = terminal_brake_altitude(
        passive,
        alt,
        track_dx,
        burn_altitude,
        spool_time,
        max_force,
    )

    time_to_impact, impact_source = ballistic_time_to_impact(passive, active)
    time_to_brake = spool_time + (speed_to_kill / max(up_acc_max, 1e-3))
    time_to_brake_buffer = policy.time_to_brake_buffer
    if impact_source == "sensor":
        time_to_brake_buffer *= policy.sensor_time_to_brake_buffer_scale
    burn_now = bool(
        down_speed > 0.6
        and (
            alt <= burn_altitude
            or time_to_impact <= (time_to_brake + time_to_brake_buffer)
        )
    )
    ballistic_debug_summary = (
        f"ball tti:{stable(time_to_impact, 1):4.1f} "
        f"src:{'s' if impact_source == 'sensor' else 'a'} "
        f"pdx:{stable(track_dx, 1):5.1f} "
        f"burn:{int(burn_now)}"
    )

    if burn_now:
        vertical_mode = "terminal_burn"
        vy_sp = -clamp(0.45 + (0.11 * alt), 0.55, 2.2)
        vy_sp *= policy.descent_rate_scale
        vx_sp = clamp(vx_sp, -1.2, 1.2)
    elif alt < policy.flare_altitude and abs_track_dx <= policy.flare_track_band:
        vertical_mode = "flare"
        vy_sp = -clamp(0.35 + (0.09 * alt), 0.45, 1.0)
        vy_sp *= policy.descent_rate_scale
        vx_sp = clamp(vx_sp, -0.8, 0.8)
    elif abs_track_dx > policy.align_band and alt < policy.align_low_altitude:
        vertical_mode = "coast"
        vy_sp = -clamp(1.1 + (0.18 * math.sqrt(max(0.0, alt))), 1.2, 3.0)
        vy_sp *= policy.descent_rate_scale
        vx_sp = clamp(
            track_dx * policy.align_lateral_gain * policy.lateral_gain,
            -policy.align_vx_cap,
            policy.align_vx_cap,
        )
    else:
        vertical_mode = "coast"
        vy_sp = -clamp(1.2 + (0.3 * math.sqrt(max(0.0, alt))), 1.4, 6.0)
        vy_sp *= policy.descent_rate_scale

    phase = resolve_drop_phase(
        policy,
        alt=alt,
        track_dx=track_dx,
        burn_now=burn_now,
        vertical_mode=vertical_mode,
    )
    if phase == "touchdown":
        vertical_mode = "flare"
        vy_sp = -clamp(0.3 + (0.07 * alt), 0.4, 0.75)
        vy_sp *= policy.descent_rate_scale

    return GuidanceTargets(
        phase=phase,
        vertical_mode=vertical_mode,
        vx_sp=vx_sp,
        vy_sp=vy_sp,
        dx=dx,
        alt=alt,
        burn_altitude=burn_altitude,
    ), ballistic_debug_summary


__all__ = [
    "BASE_DROP_POLICY",
    "DropPolicy",
    "TerminalBrakeAltitudeFn",
    "compute_drop_guidance",
    "lateral_velocity_targets",
    "resolve_drop_phase",
]
