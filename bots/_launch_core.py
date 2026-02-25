"""Shared launch setup math and control helpers."""

from __future__ import annotations

import math
from dataclasses import dataclass

from bots._plunge_core import (
    BallisticProjection,
    GuidanceTargets,
    clamp,
    estimate_ballistic_projection,
)
from core.bot import ActiveSensors


@dataclass(frozen=True)
class LaunchSetupConfig:
    handoff_projected_dx_ratio: float = 0.85
    setup_vx_cap: float = 92.0
    setup_vx_floor: float = 6.0
    setup_descent_vy_target: float = -2.2
    setup_response_delay_s: float = 0.65
    setup_ballistic_vy_blend: float = 0.45
    handoff_force_coast_altitude: float = 420.0
    setup_vx_deadband: float = 1.6
    setup_sideburn_angle_rad: float = 1.40
    setup_sideburn_angle_min_rad: float = 1.40
    setup_sideburn_angle_max_rad: float = 1.40
    setup_sideburn_upward_vy_target: float = 0.0
    setup_sideburn_upward_angle_gain: float = 0.0
    setup_sideburn_lateral_accel_floor: float = 1.0
    setup_sideburn_lateral_accel_cap: float = 10.0
    setup_sideburn_min_thrust: float = 0.35
    setup_sideburn_max_thrust: float = 1.6
    setup_sideburn_boost_thrust: float = 1.25
    setup_sideburn_boost_dx_cone_ratio: float = 2.4
    setup_sideburn_boost_vx_err_min: float = 6.0
    handoff_center_tolerance_min: float = 4.5
    handoff_center_tolerance_base: float = 6.5
    handoff_center_tolerance_per_s: float = 1.8
    handoff_center_tolerance_cap: float = 24.0
    handoff_target_edge_margin: float = 8.0
    handoff_shortfall_guard_ratio: float = 0.12
    setup_fuel_reserve_ratio: float = 0.0
    setup_fuel_reserve_floor: float = 0.0


def _predict_response_state(
    *,
    dx: float,
    alt: float,
    vx: float,
    vy_up: float,
    delay_s: float,
) -> tuple[float, float, float, float]:
    lag = max(0.0, float(delay_s))
    if lag <= 1e-6:
        return dx, alt, vx, vy_up
    # Compensate for rotation + thrust spool delay by evaluating a short-horizon
    # predicted state instead of chasing an immediate-state ballistic solution.
    dx_pred = dx - (vx * lag)
    alt_pred = max(0.0, alt + (vy_up * lag) - (4.9 * lag * lag))
    vy_pred = vy_up - (9.8 * lag)
    return dx_pred, alt_pred, vx, vy_pred


def _predict_response_world_state(
    *,
    x: float | None,
    y: float | None,
    vx: float,
    vy_up: float,
    delay_s: float,
) -> tuple[float | None, float | None]:
    if (
        x is None
        or y is None
        or not (math.isfinite(float(x)) and math.isfinite(float(y)))
    ):
        return None, None
    lag = max(0.0, float(delay_s))
    if lag <= 1e-6:
        return float(x), float(y)
    x_pred = float(x) + (vx * lag)
    y_pred = float(y) + (vy_up * lag) - (4.9 * lag * lag)
    return x_pred, y_pred


def _estimate_ballistic_projection(
    *,
    dx: float,
    alt: float,
    vx: float,
    vy_up: float,
    x: float | None = None,
    y: float | None = None,
    active: ActiveSensors | None = None,
    clearance: float = 0.0,
) -> BallisticProjection:
    return estimate_ballistic_projection(
        dx=dx,
        alt=alt,
        vx=vx,
        vy_up=vy_up,
        x=x,
        y=y,
        active=active,
        clearance=clearance,
    )


def _ballistic_reference_vy(
    guidance: GuidanceTargets,
    setup_cfg: LaunchSetupConfig,
    vy_pred: float,
) -> float:
    envelope_vy = min(float(guidance.vy_sp), setup_cfg.setup_descent_vy_target)
    blend = clamp(setup_cfg.setup_ballistic_vy_blend, 0.0, 1.0)
    mixed_vy = envelope_vy + (blend * (vy_pred - envelope_vy))
    return clamp(mixed_vy, min(vy_pred, envelope_vy), max(vy_pred, envelope_vy))


def _target_half_width(target_size: float | None) -> float:
    if target_size is None:
        return 55.0
    try:
        numeric = abs(float(target_size))
    except (TypeError, ValueError):
        return 55.0
    if not math.isfinite(numeric):
        return 55.0
    return max(6.0, 0.5 * numeric)


def _handoff_alignment(
    *,
    projected_dx: float,
    t_fall: float,
    target_size: float | None,
    setup_cfg: LaunchSetupConfig,
) -> tuple[bool, bool, bool, float, float]:
    target_half = _target_half_width(target_size)
    dynamic_tol = (
        setup_cfg.handoff_center_tolerance_base
        + (setup_cfg.handoff_center_tolerance_per_s * max(0.0, t_fall))
    )
    center_tol = clamp(
        dynamic_tol,
        setup_cfg.handoff_center_tolerance_min,
        setup_cfg.handoff_center_tolerance_cap,
    )
    # Keep centered-tolerance strictly within the target footprint.
    center_tol = min(
        center_tol,
        max(0.5, target_half - setup_cfg.handoff_target_edge_margin),
    )
    inside_target = abs(projected_dx) <= target_half
    centered = abs(projected_dx) <= center_tol
    return centered and inside_target, centered, inside_target, center_tol, target_half


def resolve_sideburn_target_angle(
    setup_cfg: LaunchSetupConfig,
    *,
    projected_dx: float,
    cone_limit: float,
    vy_up: float,
) -> float:
    """Compute sideburn angle magnitude with optional climb bias."""
    min_angle = min(setup_cfg.setup_sideburn_angle_min_rad, setup_cfg.setup_sideburn_angle_max_rad)
    max_angle = max(setup_cfg.setup_sideburn_angle_min_rad, setup_cfg.setup_sideburn_angle_max_rad)
    base_angle = clamp(setup_cfg.setup_sideburn_angle_rad, min_angle, max_angle)
    if max_angle - min_angle <= 1e-6:
        return base_angle

    miss_ratio = clamp(abs(projected_dx) / max(1.0, cone_limit), 0.0, 2.0)
    center_bias = 0.16 * clamp(1.0 - miss_ratio, 0.0, 1.0)
    climb_target = max(0.0, setup_cfg.setup_sideburn_upward_vy_target)
    climb_gap = max(0.0, climb_target - float(vy_up))
    climb_bias = setup_cfg.setup_sideburn_upward_angle_gain * (climb_gap / max(1.0, climb_target))
    angle_mag = base_angle - center_bias - clamp(climb_bias, 0.0, 0.28)
    return clamp(angle_mag, min_angle, max_angle)


def setup_fuel_reserve_threshold(
    setup_cfg: LaunchSetupConfig,
    *,
    max_fuel: float,
) -> float:
    return max(
        float(setup_cfg.setup_fuel_reserve_floor),
        float(setup_cfg.setup_fuel_reserve_ratio) * max(0.0, float(max_fuel)),
    )


__all__ = [
    "LaunchSetupConfig",
    "_ballistic_reference_vy",
    "_estimate_ballistic_projection",
    "_handoff_alignment",
    "_predict_response_state",
    "_predict_response_world_state",
    "_target_half_width",
    "resolve_sideburn_target_angle",
    "setup_fuel_reserve_threshold",
]
