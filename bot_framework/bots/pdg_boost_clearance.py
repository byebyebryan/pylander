from __future__ import annotations

import math
from dataclasses import dataclass

from .common_math import _GRAVITY_MAG, rate_limit_angle_command
from core.bot import BotAction, Sensors


@dataclass(frozen=True)
class BoostClearanceProbe:
    active: bool
    min_margin: float | None = None
    worst_x: float | None = None
    worst_y: float | None = None
    horizon_s: float = 0.0
    sample_count: int = 0
    angle_cap: float | None = None


def _progress_clearance_enabled(bot) -> bool:
    cfg = getattr(bot, "_cfg", None)
    if cfg is None or not bool(getattr(cfg, "terrain_awareness_enable", False)):
        return False
    if not bool(getattr(cfg, "progress_clearance_enable", False)):
        return False
    environment = getattr(bot, "environment", None)
    if environment is None:
        return False
    return (
        getattr(environment, "terrain", None) is not None
        and getattr(environment, "target", None) is not None
    )


def _body_clearance(bot) -> float:
    vehicle_info = getattr(bot, "vehicle_info", None)
    if vehicle_info is None:
        return 0.0
    cfg = bot._cfg
    body_margin = max(0.0, float(getattr(cfg, "progress_clearance_body_margin", 0.0)))
    return max(0.0, (0.5 * float(vehicle_info.height)) + body_margin)


def _targetward_half_width(bot) -> float:
    vehicle_info = getattr(bot, "vehicle_info", None)
    if vehicle_info is None:
        return 0.0
    width = float(
        getattr(vehicle_info, "width", getattr(vehicle_info, "height", 0.0)) or 0.0
    )
    return max(0.0, 0.5 * width)


def _targetward_terrain_height(
    terrain,
    *,
    sample_x: float,
    direction: float,
    half_width: float,
) -> tuple[float, float]:
    worst_x = float(sample_x)
    worst_y = float(terrain.sample_height(sample_x))
    if abs(float(direction)) <= 1e-6 or half_width <= 1e-6:
        return worst_y, worst_x

    resolution = 0.5
    resolution_fn = getattr(terrain, "resolution", None)
    if callable(resolution_fn):
        resolution = max(0.5, float(resolution_fn(lod=0)))
    sample_count = max(1, int(math.ceil(half_width / resolution)))
    for idx in range(1, sample_count + 1):
        probe_x = float(sample_x) + (
            float(direction) * half_width * (float(idx) / float(sample_count))
        )
        probe_y = float(terrain.sample_height(probe_x))
        if probe_y > worst_y:
            worst_y = probe_y
            worst_x = probe_x
    return worst_y, worst_x


def evaluate_boost_clearance_probe(
    bot,
    *,
    passive: Sensors,
    dx: float,
    action: BotAction,
    max_power: float,
    currently_active: bool = False,
) -> BoostClearanceProbe:
    if not _progress_clearance_enabled(bot):
        return BoostClearanceProbe(active=False)
    if abs(float(dx)) <= 1e-6:
        return BoostClearanceProbe(active=False)

    environment = bot.environment
    assert environment is not None
    target = environment.target
    assert target is not None
    target_x = float(target.x)
    direction = 1.0 if float(dx) > 0.0 else -1.0
    distance_to_target = max(0.0, direction * (target_x - float(passive.x)))
    release_x = float(bot._cfg.progress_clearance_release_x_margin)
    if distance_to_target <= release_x:
        return BoostClearanceProbe(active=False)

    mass = max(0.5, float(passive.mass))
    thrust_accel = max(0.0, float(action.target_thrust) * float(max_power) / mass)
    angle = float(action.target_angle)
    accel_x = thrust_accel * math.sin(angle)
    accel_y = (thrust_accel * math.cos(angle)) - _GRAVITY_MAG

    cfg = bot._cfg
    horizon_s = float(cfg.progress_clearance_horizon_s)
    sample_count = max(1, int(cfg.progress_clearance_samples))
    body_clearance = _body_clearance(bot)
    half_width = _targetward_half_width(bot)
    vx_toward = max(0.0, direction * float(passive.vx))
    if vx_toward > 1.0:
        horizon_s = min(horizon_s, distance_to_target / vx_toward)
    if horizon_s <= 0.0:
        return BoostClearanceProbe(active=False)
    terrain = environment.terrain
    min_margin = math.inf
    worst_x: float | None = None
    worst_y: float | None = None
    for idx in range(1, sample_count + 1):
        t = horizon_s * (float(idx) / float(sample_count))
        sample_x = float(passive.x) + (float(passive.vx) * t) + (0.5 * accel_x * t * t)
        if direction * (sample_x - target_x) > 0.0:
            sample_x = target_x
        sample_y = (
            float(passive.y) + (float(passive.vy_up) * t) + (0.5 * accel_y * t * t)
        )
        terrain_y, terrain_x = _targetward_terrain_height(
            terrain,
            sample_x=sample_x,
            direction=direction,
            half_width=half_width,
        )
        margin = sample_y - terrain_y - body_clearance
        if margin < min_margin:
            min_margin = margin
            worst_x = float(terrain_x)
            worst_y = float(terrain_y)

    threshold = (
        float(cfg.progress_clearance_release_margin)
        if currently_active
        else float(cfg.progress_clearance_trigger_margin)
    )
    if not math.isfinite(min_margin) or min_margin >= threshold:
        return BoostClearanceProbe(
            active=False,
            min_margin=(None if not math.isfinite(min_margin) else float(min_margin)),
            worst_x=worst_x,
            worst_y=worst_y,
            horizon_s=horizon_s,
            sample_count=sample_count,
        )

    deficit = max(0.0, threshold - float(min_margin))
    angle_cap = max(
        float(cfg.progress_clearance_targetward_cap_min),
        float(cfg.progress_clearance_targetward_cap)
        - (float(cfg.progress_clearance_targetward_cap_gain) * deficit),
    )
    return BoostClearanceProbe(
        active=True,
        min_margin=float(min_margin),
        worst_x=worst_x,
        worst_y=worst_y,
        horizon_s=horizon_s,
        sample_count=sample_count,
        angle_cap=float(angle_cap),
    )


def apply_boost_clearance_guard(
    bot,
    *,
    passive: Sensors,
    dx: float,
    action: BotAction,
    dt: float,
    prev_angle_cmd: float,
    max_power: float,
    max_throttle: float,
    currently_active: bool = False,
) -> tuple[BotAction, BoostClearanceProbe]:
    probe = evaluate_boost_clearance_probe(
        bot,
        passive=passive,
        dx=dx,
        action=action,
        max_power=max_power,
        currently_active=currently_active,
    )
    if not probe.active:
        return action, probe

    target_sign = 1.0 if float(dx) > 0.0 else -1.0
    angle_cmd = float(action.target_angle)
    angle_cap = float(probe.angle_cap or 0.0)
    if target_sign > 0.0 and angle_cmd > angle_cap:
        angle_cmd = rate_limit_angle_command(
            angle_cap,
            prev_angle_cmd,
            dt,
            max_rate=bot._cfg.angle_rate,
        )
    elif target_sign < 0.0 and angle_cmd < -angle_cap:
        angle_cmd = rate_limit_angle_command(
            -angle_cap,
            prev_angle_cmd,
            dt,
            max_rate=bot._cfg.angle_rate,
        )

    thrust_floor = float(bot._cfg.progress_clearance_thrust_floor_ratio) * float(
        max_throttle
    )
    thrust_cmd = max(float(action.target_thrust), thrust_floor)
    if angle_cmd != float(action.target_angle):
        bot._prev_angle_cmd = angle_cmd
    bot._thrust_enabled = True
    return (
        BotAction(
            target_thrust=thrust_cmd,
            target_angle=angle_cmd,
            refuel=bool(action.refuel),
            status=str(action.status),
            message=str(action.message),
        ),
        probe,
    )


__all__ = [
    "BoostClearanceProbe",
    "apply_boost_clearance_guard",
    "evaluate_boost_clearance_probe",
]
