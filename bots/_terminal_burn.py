"""Shared terminal-burn timing model helpers."""

from __future__ import annotations

from dataclasses import dataclass

from bots._bot_math import clamp


@dataclass(frozen=True)
class TerminalBurnModel:
    spool_quadratic_accel: float = 4.9
    flare_speed_base: float = 0.45
    flare_speed_alt_gain: float = 0.11
    flare_speed_min: float = 0.7
    flare_speed_max: float = 2.5
    burn_margin_base: float = 2.1
    burn_margin_dx_gain: float = 0.12
    burn_margin_dx_deadband: float = 8.0
    burn_activation_down_speed_min: float = 0.6


@dataclass(frozen=True)
class TerminalBurnEstimate:
    down_speed: float
    spool_time: float
    spool_distance: float
    flare_speed: float
    speed_to_kill: float
    stop_distance: float
    burn_margin: float
    burn_altitude: float
    time_to_brake: float
    raw_burn_now: bool


def compute_terminal_burn_estimate(
    *,
    alt: float,
    track_dx: float,
    vy_up: float,
    thrust_level: float,
    up_acc_max: float,
    max_throttle: float,
    ramp_up: float,
    time_to_impact: float,
    burn_enter_time_margin: float,
    model: TerminalBurnModel,
) -> TerminalBurnEstimate:
    safe_alt = max(0.0, float(alt))
    down_speed = max(0.0, -float(vy_up))
    nominal_throttle = min(1.0, float(max_throttle))
    spool_time = max(0.0, nominal_throttle - max(0.0, float(thrust_level))) / max(
        1e-3,
        float(ramp_up),
    )
    spool_distance = (down_speed * spool_time) + (
        float(model.spool_quadratic_accel) * spool_time * spool_time
    )
    flare_speed = clamp(
        float(model.flare_speed_base) + (float(model.flare_speed_alt_gain) * safe_alt),
        float(model.flare_speed_min),
        float(model.flare_speed_max),
    )
    speed_to_kill = max(0.0, down_speed - flare_speed)
    stop_distance = (speed_to_kill * speed_to_kill) / (2.0 * max(1e-3, float(up_acc_max)))
    burn_margin = float(model.burn_margin_base) + (
        float(model.burn_margin_dx_gain)
        * max(0.0, abs(float(track_dx)) - float(model.burn_margin_dx_deadband))
    )
    burn_altitude = stop_distance + spool_distance + burn_margin
    time_to_brake = spool_time + (speed_to_kill / max(1e-3, float(up_acc_max)))
    raw_burn_now = bool(
        down_speed > float(model.burn_activation_down_speed_min)
        and (
            safe_alt <= burn_altitude
            or float(time_to_impact) <= (time_to_brake + float(burn_enter_time_margin))
        )
    )
    return TerminalBurnEstimate(
        down_speed=down_speed,
        spool_time=spool_time,
        spool_distance=spool_distance,
        flare_speed=flare_speed,
        speed_to_kill=speed_to_kill,
        stop_distance=stop_distance,
        burn_margin=burn_margin,
        burn_altitude=burn_altitude,
        time_to_brake=time_to_brake,
        raw_burn_now=raw_burn_now,
    )


__all__ = ["TerminalBurnEstimate", "TerminalBurnModel", "compute_terminal_burn_estimate"]
