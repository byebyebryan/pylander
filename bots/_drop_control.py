"""Shared drop control helpers for angle/thrust allocation."""

from __future__ import annotations

import math
from typing import Protocol

from bots._bot_math import clamp, vehicle_limits
from core.bot import BotAction, PassiveSensors


class DropControlPolicy(Protocol):
    terminal_brake_gain_high_alt: float
    terminal_brake_gain_low_alt: float
    overdrive_soft_cap: float
    allow_overdrive: bool
    overdrive_requires_terminal_burn: bool
    emergency_vy_threshold: float
    emergency_low_alt: float
    emergency_low_alt_vy_threshold: float
    min_fuel_ratio_for_overdrive: float


def rate_limit_angle_command(
    target_angle: float,
    prev_angle: float,
    dt: float,
    *,
    max_rate: float = 2.2,
) -> float:
    max_delta = max_rate * max(dt, 1e-3)
    return clamp(target_angle, prev_angle - max_delta, prev_angle + max_delta)


def horizontal_controller(passive: PassiveSensors, vx_sp: float) -> float:
    vx_err = vx_sp - passive.vx
    return (0.5 * vx_err) - (0.1 * passive.ax)


def vertical_controller(
    policy: DropControlPolicy,
    passive: PassiveSensors,
    vy_sp: float,
    alt: float,
    vertical_mode: str,
    up_acc_max: float,
) -> float:
    if vertical_mode in ("coast", "eco_glide", "speed_dive"):
        return 0.0
    if vertical_mode == "coast_hold":
        vy_err = vy_sp - passive.vy_up
        # Keep correction burns thrust-backed without drifting into hover.
        a_up_cmd = 7.2 + (0.2 * vy_err)
        max_up_cmd = 9.8 if alt < 14.0 else 9.25
        return clamp(a_up_cmd, 4.8, max_up_cmd)
    if vertical_mode == "terminal_burn":
        brake_gain = (
            policy.terminal_brake_gain_high_alt
            if alt > 8.0
            else policy.terminal_brake_gain_low_alt
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


def fuel_ratio(passive: PassiveSensors) -> float:
    max_fuel = max(1e-6, float(passive.max_fuel))
    return clamp(float(passive.fuel) / max_fuel, 0.0, 1.0)


def can_use_overdrive(
    policy: DropControlPolicy,
    passive: PassiveSensors,
    *,
    vertical_mode: str,
    alt: float,
) -> bool:
    if not policy.allow_overdrive:
        return False
    if fuel_ratio(passive) < policy.min_fuel_ratio_for_overdrive:
        return False
    if policy.overdrive_requires_terminal_burn and vertical_mode != "terminal_burn":
        return False
    return (
        passive.vy_up < policy.emergency_vy_threshold
        or (
            alt < policy.emergency_low_alt
            and passive.vy_up < policy.emergency_low_alt_vy_threshold
        )
    )


def allocate_controls(
    policy: DropControlPolicy,
    dt: float,
    passive: PassiveSensors,
    *,
    a_x_sp: float,
    a_up_sp: float,
    alt: float,
    dx: float,
    vertical_mode: str,
    prev_angle_cmd: float,
    max_power: float,
    min_throttle: float,
    max_throttle: float,
) -> tuple[BotAction, float]:
    max_force = max_power * max_throttle
    mass, _ = vehicle_limits(passive, max_force)

    req = clamp((a_x_sp * mass) / max(max_force, 1e-3), -0.95, 0.95)
    angle_cmd = math.asin(req)
    max_tilt = 0.18 if alt < 20.0 else 0.56
    angle_cmd = clamp(angle_cmd, -max_tilt, max_tilt)

    angle_cmd = rate_limit_angle_command(
        angle_cmd,
        prev_angle_cmd,
        dt,
    )
    next_angle_cmd = angle_cmd

    cos_term = max(0.25, abs(math.cos(angle_cmd)))
    thrust = (mass * a_up_sp) / max(max_power * cos_term, 1e-3)
    if alt < 9.0 and abs(dx) <= 10.0:
        angle_cmd = 0.0
    if alt < 2.5 and abs(dx) <= 7.0 and abs(passive.vx) < 0.6 and abs(passive.vy_up) < 0.9:
        thrust = 0.0
        angle_cmd = 0.0

    soft_cap = min(policy.overdrive_soft_cap, max_throttle)
    if thrust > soft_cap and not can_use_overdrive(
        policy,
        passive,
        vertical_mode=vertical_mode,
        alt=alt,
    ):
        thrust = soft_cap

    thrust = clamp(thrust, 0.0, max_throttle)
    if thrust > 0.0:
        thrust = max(min_throttle, thrust)
    return BotAction(target_thrust=thrust, target_angle=angle_cmd, refuel=False), next_angle_cmd

