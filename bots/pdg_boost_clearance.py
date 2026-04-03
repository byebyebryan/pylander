from __future__ import annotations

import math
from dataclasses import dataclass

from bots.common_math import rate_limit_angle_command
from core.bot import BotAction, Sensors
from core.config import GRAVITY

_GRAVITY_MAG = abs(float(GRAVITY))


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
    if environment is None or getattr(environment, "terrain", None) is None:
        return False
    params = getattr(environment, "scenario_params", None) or {}
    return params.get("hazard_driver") == "progress_clearance"


def _body_clearance(bot) -> float:
    vehicle_info = getattr(bot, "vehicle_info", None)
    if vehicle_info is None:
        return 0.0
    cfg = bot._cfg
    body_margin = max(0.0, float(getattr(cfg, "progress_clearance_body_margin", 0.0)))
    return max(0.0, (0.5 * float(vehicle_info.height)) + body_margin)


def _support_span(bot) -> tuple[float, float] | None:
    params = getattr(getattr(bot, "environment", None), "scenario_params", None) or {}
    support_x0 = params.get("obstacle_support_x0")
    support_x1 = params.get("obstacle_support_x1")
    if not isinstance(support_x0, int | float) or not isinstance(
        support_x1, int | float
    ):
        return None
    x0 = float(support_x0)
    x1 = float(support_x1)
    if x1 <= x0:
        return None
    return x0, x1


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
    support_span = _support_span(bot)
    if support_span is None:
        return BoostClearanceProbe(active=False)
    support_x0, support_x1 = support_span
    release_x = float(bot._cfg.progress_clearance_release_x_margin)
    if float(passive.x) >= (support_x1 + release_x):
        return BoostClearanceProbe(active=False)
    if abs(float(dx)) <= 1e-6:
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
    terrain = bot.environment.terrain
    min_margin = math.inf
    worst_x: float | None = None
    worst_y: float | None = None
    for idx in range(1, sample_count + 1):
        t = horizon_s * (float(idx) / float(sample_count))
        sample_x = float(passive.x) + (float(passive.vx) * t) + (0.5 * accel_x * t * t)
        sample_y = (
            float(passive.y) + (float(passive.vy_up) * t) + (0.5 * accel_y * t * t)
        )
        terrain_y = float(terrain.sample_height(sample_x))
        margin = sample_y - terrain_y - body_clearance
        if margin < min_margin:
            min_margin = margin
            worst_x = float(sample_x)
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
