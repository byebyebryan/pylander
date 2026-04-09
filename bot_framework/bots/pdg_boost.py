from __future__ import annotations

import math
from dataclasses import dataclass
from types import SimpleNamespace
from typing import cast

from .common_ballistics import (
    ballistic_apex_from_state,
    estimate_target_y_projection,
)
from .common_math import _GRAVITY_MAG, engine_profile, retrograde_angle_target
from core.bot import Sensors

_SETTLE_ROTATION_RATE = math.radians(90.0)
_SETTLE_THRUST_EFFECT_SCALE = 1.0
_SETTLE_STEP_S = 0.05


@dataclass(frozen=True)
class BoostQualityStatus:
    verdict: str
    passed: bool
    apex_target: float
    apex_tolerance: float
    dx_limit: float
    impact_angle_deg: float | None
    projected_dx: float | None
    projected_apex_over_target: float
    ratio_min: float
    ratio_max: float


@dataclass(frozen=True)
class BoostObjectiveGeometry:
    has_target_y_solution: bool
    dx_limit: float
    projected_dx: float
    impact_angle_deg: float | None
    no_away_ax_sign: float
    angle_scale: float


def _direction_sign(bot, *, dx: float) -> float:
    state = bot.state
    if state._shape_window_started:
        delta = float(state._shape_target_x) - float(state._shape_start_x)
        if abs(delta) > 1e-6:
            return math.copysign(1.0, delta)
    if abs(float(dx)) > 1e-6:
        return math.copysign(1.0, float(dx))
    return 1.0


def apex_target_and_tolerance(
    bot,
    *,
    dx_anchor_abs: float,
    dy: float = 0.0,
) -> tuple[float, float]:
    transfer_dy = transfer_dy_for_boost(bot, dy=dy)
    apex_target = (
        bot._shape_apex_target(float(dx_anchor_abs))
        + max(
            0.0,
            transfer_dy * float(bot._cfg.boost_apex_height_per_uphill_dy),
        )
        + max(0.0, -transfer_dy)
    )
    cfg = bot._cfg
    apex_tolerance = max(
        float(cfg.boost_cutoff_apex_tol_abs),
        float(cfg.boost_cutoff_apex_tol_ratio) * apex_target,
    )
    return apex_target, apex_tolerance


def transfer_dy_for_boost(bot, *, dy: float) -> float:
    state = bot.state
    transfer_dy = float(dy)
    if bool(state._shape_window_started):
        transfer_dy = float(state._shape_target_y) - float(state._shape_start_y)
    return transfer_dy


def boost_dx_limit(bot) -> float:
    cfg = bot._cfg
    return max(
        float(cfg.boost_cutoff_projected_dx_abs),
        float(cfg.boost_cutoff_projected_dx_target_ratio)
        * float(bot._last_target_half),
    )


def descent_angle_ratio_bounds(bot) -> tuple[float, float]:
    cfg = bot._cfg
    angle_min = max(1.0, float(cfg.boost_descent_angle_deg_min))
    angle_max = max(angle_min + 1.0, float(cfg.boost_descent_angle_deg_max))
    ratio_min = 2.0 / max(1e-3, math.tan(math.radians(angle_max)))
    ratio_max = 2.0 / max(1e-3, math.tan(math.radians(angle_min)))
    return ratio_min, ratio_max


def descent_angle_slope_bounds(bot) -> tuple[float, float]:
    cfg = bot._cfg
    angle_min = max(1.0, float(cfg.boost_descent_angle_deg_min))
    angle_max = max(angle_min + 1.0, float(cfg.boost_descent_angle_deg_max))
    slope_min = math.tan(math.radians(angle_min))
    slope_max = math.tan(math.radians(angle_max))
    return slope_min, slope_max


def select_reference_times(
    bot,
    *,
    passive: Sensors,
    dx: float,
    dy: float,
    plan,
) -> tuple[float, float, float]:
    state = bot.state
    ref_x = float(passive.x)
    ref_y = float(passive.y)
    ref_vx = float(passive.vx)
    ref_vy = float(passive.vy_up)
    _ = plan

    dx_anchor_abs = (
        state._shape_anchor_dx_abs if state._shape_window_started else abs(float(dx))
    )
    apex_target, _ = apex_target_and_tolerance(bot, dx_anchor_abs=dx_anchor_abs, dy=dy)

    apex = ballistic_apex_from_state(
        x=ref_x,
        y=ref_y,
        vx=ref_vx,
        vy_up=ref_vy,
        gravity_mag=_GRAVITY_MAG,
    )
    t_apex_ref = max(0.0, float(apex.t_apex))
    projection = estimate_target_y_projection(
        dx=(float(passive.x) + float(dx)) - ref_x,
        dy=(float(passive.y) + float(dy)) - ref_y,
        vx=ref_vx,
        vy_up=ref_vy,
        x=ref_x,
        y=ref_y,
        min_t_fall=0.0,
        gravity_mag=_GRAVITY_MAG,
    )
    if bool(projection.has_target_y_solution) and float(projection.t_fall) > t_apex_ref:
        t_cross_ref = float(projection.t_fall)
    else:
        t_desc = math.sqrt(max(0.0, (2.0 * apex_target) / max(1e-6, _GRAVITY_MAG)))
        t_cross_ref = max(t_apex_ref + t_desc, t_apex_ref + 0.5)
    return dx_anchor_abs, t_apex_ref, t_cross_ref


def projected_impact_angle_deg(*, vx: float, vy_up: float, t_fall: float) -> float:
    vy_down = abs(float(vy_up) - (_GRAVITY_MAG * max(0.0, float(t_fall))))
    return math.degrees(math.atan2(vy_down, abs(float(vx))))


def _angle_diff(current: float, target: float) -> float:
    return (float(target) - float(current) + math.pi) % (2.0 * math.pi) - math.pi


def boost_objective_geometry(
    bot,
    *,
    passive: Sensors,
    dx: float,
    projection,
    boost_t_cross_ref: float,
) -> BoostObjectiveGeometry:
    dx_limit = boost_dx_limit(bot)
    has_solution = bool(getattr(projection, "has_target_y_solution", True))
    if has_solution and getattr(projection, "projected_dx", None) is not None:
        projected_dx = float(projection.projected_dx)
    else:
        projected_dx = float(dx) - (
            float(passive.vx) * max(0.0, float(boost_t_cross_ref))
        )

    impact_angle = None
    if has_solution:
        impact_angle = projected_impact_angle_deg(
            vx=float(passive.vx),
            vy_up=float(passive.vy_up),
            t_fall=float(projection.t_fall),
        )

    no_away_ax_sign = 0.0
    if abs(float(dx)) > dx_limit and abs(float(dx)) > 1e-6:
        no_away_ax_sign = _direction_sign(bot, dx=dx)

    angle_scale = 0.0
    if has_solution and impact_angle is not None:
        angle_scale = (
            1.0
            if impact_angle < float(bot._cfg.boost_descent_angle_deg_target)
            else 0.0
        )

    return BoostObjectiveGeometry(
        has_target_y_solution=has_solution,
        dx_limit=dx_limit,
        projected_dx=projected_dx,
        impact_angle_deg=impact_angle,
        no_away_ax_sign=no_away_ax_sign,
        angle_scale=angle_scale,
    )


def evaluate_boost_quality(
    bot,
    *,
    passive: Sensors,
    dx: float,
    dy: float,
    projection,
    dx_anchor_abs: float,
) -> BoostQualityStatus:
    cfg = bot._cfg
    apex_target, apex_tolerance = apex_target_and_tolerance(
        bot,
        dx_anchor_abs=dx_anchor_abs,
        dy=dy,
    )
    dx_limit = boost_dx_limit(bot)
    ratio_min, ratio_max = descent_angle_ratio_bounds(bot)

    target_y = float(bot.state._last_target_y)
    apex = ballistic_apex_from_state(
        x=float(passive.x),
        y=float(passive.y),
        vx=float(passive.vx),
        vy_up=float(passive.vy_up),
        gravity_mag=_GRAVITY_MAG,
    )
    projected_apex_over_target = float(apex.y_apex) - target_y
    has_solution = bool(getattr(projection, "has_target_y_solution", True))
    projected_dx = float(projection.projected_dx) if has_solution else None
    impact_angle = None
    if has_solution:
        impact_angle = projected_impact_angle_deg(
            vx=float(passive.vx),
            vy_up=float(passive.vy_up),
            t_fall=float(projection.t_fall),
        )

    verdict = "pass"
    passed = True
    if not has_solution:
        verdict = "no_target_y_solution"
        passed = False
    elif projected_dx is None or abs(projected_dx) > dx_limit:
        verdict = "dx"
        passed = False
    elif impact_angle is None:
        verdict = "angle"
        passed = False
    elif impact_angle < float(cfg.boost_descent_angle_deg_min):
        verdict = "angle"
        passed = False

    return BoostQualityStatus(
        verdict=verdict,
        passed=passed,
        apex_target=apex_target,
        apex_tolerance=apex_tolerance,
        dx_limit=dx_limit,
        impact_angle_deg=impact_angle,
        projected_dx=projected_dx,
        projected_apex_over_target=projected_apex_over_target,
        ratio_min=ratio_min,
        ratio_max=ratio_max,
    )


def evaluate_boost_quality_after_settle(
    bot,
    *,
    passive: Sensors,
    dx: float,
    dy: float,
    settle_s: float,
    dx_anchor_abs: float,
    settle_angle_target: float | None = None,
) -> BoostQualityStatus:
    settle_dt = max(0.0, float(settle_s))
    max_power, _min_throttle, _max_throttle, _ramp_up = engine_profile(
        getattr(bot, "vehicle_info", None)
    )
    thrust_down_rate = 1.8
    vehicle_info = getattr(bot, "vehicle_info", None)
    if vehicle_info is not None:
        thrust_down_rate = max(0.0, float(vehicle_info.thrust_decrease_rate))
    target_x = float(passive.x) + float(dx)
    target_y = float(passive.y) + float(dy)
    x_settle = float(passive.x)
    y_settle = float(passive.y)
    vx_settle = float(passive.vx)
    vy_settle = float(passive.vy_up)
    angle_settle = float(getattr(passive, "angle", 0.0))
    thrust_settle = max(0.0, float(getattr(passive, "thrust_level", 0.0)))
    mass = max(0.5, float(getattr(passive, "mass", 1.0)))
    time_remaining = settle_dt
    while time_remaining > 1e-9:
        step_dt = min(_SETTLE_STEP_S, time_remaining)
        if settle_angle_target is None:
            target_angle = retrograde_angle_target(vx=vx_settle, vy_up=vy_settle)
        else:
            target_angle = float(settle_angle_target)
        angle_delta = _angle_diff(angle_settle, target_angle)
        angle_step = max(
            -(_SETTLE_ROTATION_RATE * step_dt),
            min(_SETTLE_ROTATION_RATE * step_dt, angle_delta),
        )
        angle_mid = angle_settle + (0.5 * angle_step)
        thrust_next = max(0.0, thrust_settle - (thrust_down_rate * step_dt))
        thrust_avg = 0.5 * (thrust_settle + thrust_next)
        thrust_acc = _SETTLE_THRUST_EFFECT_SCALE * (thrust_avg * max_power) / mass
        thrust_ax = math.sin(angle_mid) * thrust_acc
        thrust_ay = math.cos(angle_mid) * thrust_acc
        net_ay = thrust_ay - _GRAVITY_MAG
        x_settle += (vx_settle * step_dt) + (0.5 * thrust_ax * step_dt * step_dt)
        y_settle += (vy_settle * step_dt) + (0.5 * net_ay * step_dt * step_dt)
        vx_settle += thrust_ax * step_dt
        vy_settle += net_ay * step_dt
        angle_settle += angle_step
        thrust_settle = thrust_next
        time_remaining -= step_dt
    dx_settle = target_x - x_settle
    dy_settle = target_y - y_settle
    settled_passive = SimpleNamespace(
        x=x_settle,
        y=y_settle,
        vx=vx_settle,
        vy_up=vy_settle,
    )
    projection = estimate_target_y_projection(
        dx=dx_settle,
        dy=dy_settle,
        vx=vx_settle,
        vy_up=vy_settle,
        x=x_settle,
        y=y_settle,
        min_t_fall=0.0,
        gravity_mag=_GRAVITY_MAG,
    )
    return evaluate_boost_quality(
        bot,
        passive=cast(Sensors, settled_passive),
        dx=dx_settle,
        dy=dy_settle,
        projection=projection,
        dx_anchor_abs=dx_anchor_abs,
    )


def boost_cut_wind_down_s(
    bot,
    *,
    passive: Sensors,
    minimum_s: float,
) -> float:
    settle_s = max(0.0, float(minimum_s))
    thrust_start = max(0.0, float(getattr(passive, "thrust_level", 0.0)))
    idle_thrust_max = max(0.0, float(bot._cfg.boost_cutoff_idle_thrust_max))
    if thrust_start <= idle_thrust_max:
        return settle_s
    thrust_down_rate = 1.8
    vehicle_info = getattr(bot, "vehicle_info", None)
    if vehicle_info is not None:
        thrust_down_rate = max(0.0, float(vehicle_info.thrust_decrease_rate))
    if thrust_down_rate <= 1e-6:
        return settle_s
    wind_down_s = (thrust_start - idle_thrust_max) / thrust_down_rate
    return max(settle_s, float(wind_down_s))


__all__ = [
    "BoostObjectiveGeometry",
    "BoostQualityStatus",
    "apex_target_and_tolerance",
    "descent_angle_ratio_bounds",
    "descent_angle_slope_bounds",
    "evaluate_boost_quality",
    "evaluate_boost_quality_after_settle",
    "projected_impact_angle_deg",
    "select_reference_times",
    "boost_cut_wind_down_s",
    "boost_dx_limit",
    "boost_objective_geometry",
    "transfer_dy_for_boost",
]
