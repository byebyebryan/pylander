"""Shared launch setup math and handoff helpers."""

from __future__ import annotations

import math
from dataclasses import dataclass

from bots._bot_math import clamp
from bots._guidance_types import GuidanceTargets
from bots._targeting import target_half_width


@dataclass(frozen=True)
class LaunchSetupConfig:
    handoff_projected_dx_ratio: float = 0.85
    setup_vx_cap: float = 92.0
    setup_vx_floor: float = 6.0
    setup_descent_vy_target: float = -2.2
    setup_response_delay_s: float = 0.65
    setup_ballistic_vy_blend: float = 0.45
    handoff_force_coast_altitude: float = 90.0
    setup_vx_deadband: float = 3.8
    setup_sideburn_angle_rad: float = 1.30
    setup_sideburn_angle_min_rad: float = 1.00
    setup_sideburn_angle_max_rad: float = 1.40
    setup_sideburn_upward_vy_target: float = 4.0
    setup_sideburn_upward_angle_gain: float = 0.55
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
    setup_burn_min_frames: int = 12
    setup_burn_end_cone_ratio: float = 1.25
    setup_burn_end_target_margin: float = 16.0
    setup_burn_safety_t_fall_s: float = 1.0


def predict_response_state(
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
    dx_pred = dx - (vx * lag)
    alt_pred = max(0.0, alt + (vy_up * lag) - (4.9 * lag * lag))
    vy_pred = vy_up - (9.8 * lag)
    return dx_pred, alt_pred, vx, vy_pred


def predict_response_world_state(
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


def ballistic_reference_vy(
    guidance: GuidanceTargets,
    setup_cfg: LaunchSetupConfig,
    vy_pred: float,
) -> float:
    envelope_vy = min(float(guidance.vy_sp), setup_cfg.setup_descent_vy_target)
    blend = clamp(setup_cfg.setup_ballistic_vy_blend, 0.0, 1.0)
    mixed_vy = envelope_vy + (blend * (vy_pred - envelope_vy))
    return clamp(mixed_vy, min(vy_pred, envelope_vy), max(vy_pred, envelope_vy))


def handoff_alignment(
    *,
    projected_dx: float,
    t_fall: float,
    target_size: float | None,
    setup_cfg: LaunchSetupConfig,
) -> tuple[bool, bool, bool, float, float]:
    target_half = target_half_width(target_size)
    dynamic_tol = (
        setup_cfg.handoff_center_tolerance_base
        + (setup_cfg.handoff_center_tolerance_per_s * max(0.0, t_fall))
    )
    center_tol = clamp(
        dynamic_tol,
        setup_cfg.handoff_center_tolerance_min,
        setup_cfg.handoff_center_tolerance_cap,
    )
    center_tol = min(
        center_tol,
        max(0.5, target_half - setup_cfg.handoff_target_edge_margin),
    )
    inside_target = abs(projected_dx) <= target_half
    centered = abs(projected_dx) <= center_tol
    return centered and inside_target, centered, inside_target, center_tol, target_half


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
    "ballistic_reference_vy",
    "handoff_alignment",
    "predict_response_state",
    "predict_response_world_state",
    "setup_fuel_reserve_threshold",
]
