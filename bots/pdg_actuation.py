from __future__ import annotations

import math

from bots.common_math import clamp, rate_limit_angle_command
from core.bot import BotAction, Sensors
from core.config import GRAVITY

_GRAVITY_MAG = abs(float(GRAVITY))


def _retrograde_angle_target(passive: Sensors) -> float:
    speed = math.hypot(float(passive.vx), float(passive.vy_up))
    if speed <= 1e-3:
        return 0.0
    return math.atan2(-float(passive.vx), -float(passive.vy_up))


def command_passive_coast(
    bot,
    *,
    dt: float,
    passive: Sensors,
) -> BotAction:
    angle_cmd = rate_limit_angle_command(
        _retrograde_angle_target(passive),
        bot._prev_angle_cmd,
        dt,
        max_rate=bot._cfg.angle_rate,
    )
    bot._prev_angle_cmd = angle_cmd
    bot._thrust_enabled = False
    return BotAction(target_thrust=0.0, target_angle=angle_cmd, refuel=False)


def command_zero_thrust_hold_angle(
    bot,
    *,
    dt: float,
    hold_angle: float,
) -> BotAction:
    angle_cmd = rate_limit_angle_command(
        float(hold_angle),
        bot._prev_angle_cmd,
        dt,
        max_rate=bot._cfg.angle_rate,
    )
    bot._prev_angle_cmd = angle_cmd
    bot._thrust_enabled = False
    return BotAction(target_thrust=0.0, target_angle=angle_cmd, refuel=False)


def command_from_plan(
    bot,
    *,
    dt: float,
    passive: Sensors,
    dx: float,
    projected_dx: float | None,
    dy: float,
    alt: float,
    max_power: float,
    min_throttle: float,
    max_throttle: float,
    max_thrust_accel: float,
) -> BotAction:
    cfg = bot._cfg

    if (
        alt <= cfg.touchdown_zero_alt
        and abs(dx) <= bot._last_target_half
        and abs(float(passive.vx)) <= cfg.touchdown_zero_vx
        and abs(float(passive.vy_up)) <= cfg.touchdown_zero_vy
    ):
        angle_cmd = rate_limit_angle_command(
            0.0, bot._prev_angle_cmd, dt, max_rate=cfg.angle_rate
        )
        bot._prev_angle_cmd = angle_cmd
        return BotAction(target_thrust=0.0, target_angle=0.0, refuel=False)

    if bot._plan is None or not bot._plan.feasible:
        vx = float(passive.vx)
        vy = float(passive.vy_up)
        down_speed = max(0.0, -vy)
        a_y = _GRAVITY_MAG + (0.72 * max_thrust_accel)
        if down_speed >= cfg.emergency_vy and alt <= cfg.emergency_alt:
            a_y = _GRAVITY_MAG + max_thrust_accel
        a_y = clamp(a_y, 0.0, _GRAVITY_MAG + max_thrust_accel)
        a_x = clamp((-0.55 * vx) + (0.04 * dx), -7.0, 7.0)
    else:
        runtime_state = bot.state
        idx = bot._plan_index()
        a_x = float(bot._plan.ax[idx])
        a_y = float(bot._plan.ay[idx])
        a_y = clamp(a_y, 0.0, max_thrust_accel)
        max_tilt = bot._resolve_max_tilt(
            alt,
            dx,
            float(passive.vx),
            dy=dy,
            phase=runtime_state._active_phase,
            vy_up=float(passive.vy_up)
            if runtime_state._active_phase == "terminal"
            else None,
            max_thrust_accel=max_thrust_accel
            if runtime_state._active_phase == "terminal"
            else None,
            lateral_dx=projected_dx
            if runtime_state._active_phase == "terminal"
            else None,
        )
        tilt_tan = math.tan(max_tilt)
        a_x = clamp(a_x, -tilt_tan * max(0.2, a_y), tilt_tan * max(0.2, a_y))

    runtime_state = bot.state
    max_tilt_now = bot._resolve_max_tilt(
        alt,
        dx,
        float(passive.vx),
        dy=dy,
        phase=runtime_state._active_phase,
        vy_up=float(passive.vy_up)
        if runtime_state._active_phase == "terminal"
        else None,
        max_thrust_accel=max_thrust_accel
        if runtime_state._active_phase == "terminal"
        else None,
        lateral_dx=projected_dx if runtime_state._active_phase == "terminal" else None,
    )
    angle_target = math.atan2(a_x, max(0.2, a_y))
    angle_target = clamp(angle_target, -max_tilt_now, max_tilt_now)
    angle_cmd = rate_limit_angle_command(
        angle_target,
        bot._prev_angle_cmd,
        dt,
        max_rate=cfg.angle_rate,
    )

    mass = max(0.5, float(passive.mass))
    thrust_acc = math.hypot(a_x, max(0.0, a_y))
    thrust = (mass * thrust_acc) / max(max_power, 1e-3)
    thrust = clamp(thrust, 0.0, max_throttle)

    idle_angle_target: float | None = None
    off_threshold = cfg.throttle_off_threshold_scale * min_throttle
    if bot._thrust_enabled:
        if thrust < off_threshold:
            bot._thrust_enabled = False
    elif thrust >= min_throttle:
        bot._thrust_enabled = True

    if not bot._thrust_enabled:
        thrust = 0.0
        if alt > cfg.touchdown_zero_alt and abs(float(passive.vx)) > 0.5:
            idle_angle_target = clamp(
                math.copysign(max_tilt_now, -float(passive.vx)),
                -max_tilt_now,
                max_tilt_now,
            )
    elif thrust > 0.0:
        thrust = max(min_throttle, thrust)
    if idle_angle_target is not None:
        angle_cmd = rate_limit_angle_command(
            idle_angle_target,
            bot._prev_angle_cmd,
            dt,
            max_rate=cfg.angle_rate,
        )

    down_speed = max(0.0, -float(passive.vy_up))
    rescue_limit = bot._braking_speed_limit(alt, max_thrust_accel, max_tilt_now)
    if alt <= cfg.touchdown_rescue_altitude and down_speed > (
        cfg.touchdown_rescue_vy_ratio * rescue_limit
    ):
        rescue_angle_target = 0.0
        if abs(float(passive.vx)) > cfg.touchdown_zero_vx:
            rescue_angle_target = math.copysign(
                cfg.touchdown_rescue_tilt, -float(passive.vx)
            )
        rescue_angle_target = clamp(
            rescue_angle_target,
            -cfg.touchdown_rescue_tilt,
            cfg.touchdown_rescue_tilt,
        )
        angle_cmd = rate_limit_angle_command(
            rescue_angle_target,
            bot._prev_angle_cmd,
            dt,
            max_rate=cfg.angle_rate,
        )

        alt_eff = max(cfg.touchdown_rescue_alt_floor, alt - cfg.touchdown_zero_alt)
        v_excess = max(0.0, down_speed - cfg.vy_touch_cap)
        required_net_brake = (v_excess * v_excess) / (2.0 * alt_eff)
        required_ay = _GRAVITY_MAG + required_net_brake
        required_accel = required_ay / max(0.2, math.cos(angle_cmd))
        required_thrust = (mass * required_accel) / max(max_power, 1e-3)
        thrust = max(thrust, clamp(required_thrust, 0.0, max_throttle))
        if thrust >= min_throttle:
            bot._thrust_enabled = True
    bot._prev_angle_cmd = angle_cmd

    return BotAction(target_thrust=thrust, target_angle=angle_cmd, refuel=False)
