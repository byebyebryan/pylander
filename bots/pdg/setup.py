from __future__ import annotations

import math
from dataclasses import dataclass

from bots._ballistics import ballistic_apex_from_state, estimate_target_y_projection
from core.bot import Sensors
from core.config import GRAVITY

_GRAVITY_MAG = abs(float(GRAVITY))


@dataclass(frozen=True)
class SetupQualityStatus:
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


def _direction_sign(bot, *, dx: float) -> float:
    if bot._shape_window_started:
        delta = float(bot._shape_target_x) - float(bot._shape_start_x)
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
    transfer_dy = transfer_dy_for_setup(bot, dy=dy)
    apex_target = bot._shape_apex_target(float(dx_anchor_abs)) + max(
        0.0,
        transfer_dy * float(bot._cfg.setup_apex_height_per_uphill_dy),
    ) + max(0.0, -transfer_dy)
    cfg = bot._cfg
    apex_tolerance = max(
        float(cfg.setup_gate_apex_tol_abs),
        float(cfg.setup_gate_apex_tol_ratio) * apex_target,
    )
    return apex_target, apex_tolerance


def transfer_dy_for_setup(bot, *, dy: float) -> float:
    transfer_dy = float(dy)
    if bool(getattr(bot, "_shape_window_started", False)):
        transfer_dy = float(getattr(bot, "_shape_target_y", 0.0)) - float(
            getattr(bot, "_shape_start_y", 0.0)
        )
    return transfer_dy


def descent_angle_ratio_bounds(bot) -> tuple[float, float]:
    cfg = bot._cfg
    angle_min = max(1.0, float(cfg.setup_descent_angle_deg_min))
    angle_max = max(angle_min + 1.0, float(cfg.setup_descent_angle_deg_max))
    ratio_min = 2.0 / max(1e-3, math.tan(math.radians(angle_max)))
    ratio_max = 2.0 / max(1e-3, math.tan(math.radians(angle_min)))
    return ratio_min, ratio_max


def descent_angle_slope_bounds(bot) -> tuple[float, float]:
    cfg = bot._cfg
    angle_min = max(1.0, float(cfg.setup_descent_angle_deg_min))
    angle_max = max(angle_min + 1.0, float(cfg.setup_descent_angle_deg_max))
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
    use_live_reference = float(dy) >= float(bot._cfg.uphill_setup_dy_min)
    ref_x = float(passive.x)
    ref_y = float(passive.y)
    ref_vx = float(passive.vx)
    ref_vy = float(passive.vy_up)
    if (not use_live_reference) and plan is not None and getattr(plan, "feasible", False):
        ref_x = float(plan.x[-1])
        ref_y = float(plan.y[-1])
        ref_vx = float(plan.vx[-1])
        ref_vy = float(plan.vy[-1])

    dx_anchor_abs = bot._shape_anchor_dx_abs if bot._shape_window_started else abs(float(dx))
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


def evaluate_setup_quality(
    bot,
    *,
    passive: Sensors,
    dx: float,
    dy: float,
    projection,
    dx_anchor_abs: float,
) -> SetupQualityStatus:
    cfg = bot._cfg
    transfer_dy = transfer_dy_for_setup(bot, dy=dy)
    descending_transfer = transfer_dy < 0.0
    apex_target, apex_tolerance = apex_target_and_tolerance(
        bot,
        dx_anchor_abs=dx_anchor_abs,
        dy=dy,
    )
    dx_limit = max(
        float(cfg.setup_gate_projected_dx_abs),
        float(cfg.setup_gate_projected_dx_target_ratio) * float(bot._last_target_half),
    )
    ratio_min, ratio_max = descent_angle_ratio_bounds(bot)

    target_x = float(passive.x) + float(dx)
    target_y = float(bot._last_target_y)
    direction_sign = _direction_sign(bot, dx=dx)
    apex = ballistic_apex_from_state(
        x=float(passive.x),
        y=float(passive.y),
        vx=float(passive.vx),
        vy_up=float(passive.vy_up),
        gravity_mag=_GRAVITY_MAG,
    )
    projected_apex_over_target = float(apex.y_apex) - target_y
    d_pa_signed = None
    if apex.x_apex is not None:
        d_pa_signed = direction_sign * (target_x - float(apex.x_apex))
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
    elif abs(projected_apex_over_target - apex_target) > apex_tolerance:
        verdict = "apex"
        passed = False
    elif impact_angle is None:
        verdict = "angle"
        passed = False
    elif impact_angle < float(cfg.setup_descent_angle_deg_min):
        verdict = "angle"
        passed = False
    elif (not descending_transfer) and impact_angle > float(cfg.setup_descent_angle_deg_max):
        verdict = "angle"
        passed = False
    elif d_pa_signed is None or d_pa_signed <= 0.0:
        verdict = "angle"
        passed = False
    elif projected_apex_over_target > 1e-6:
        if (not descending_transfer) and d_pa_signed < (ratio_min * projected_apex_over_target):
            verdict = "angle"
            passed = False
        elif d_pa_signed > (ratio_max * projected_apex_over_target):
            verdict = "angle"
            passed = False

    return SetupQualityStatus(
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


__all__ = [
    "SetupQualityStatus",
    "apex_target_and_tolerance",
    "descent_angle_ratio_bounds",
    "descent_angle_slope_bounds",
    "evaluate_setup_quality",
    "projected_impact_angle_deg",
    "select_reference_times",
    "transfer_dy_for_setup",
]
