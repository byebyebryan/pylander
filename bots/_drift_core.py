"""Shared drift guidance/control core for drift strategy variants."""

from __future__ import annotations

import math
from dataclasses import dataclass, replace

from bots._descent_core import (
    BALANCED_POLICY,
    DescentPolicy,
    GuidanceTargets,
    clamp,
    resolve_behavior,
)


@dataclass(frozen=True)
class DriftCourseConfig:
    cone_dx_base: float = 10.0
    cone_dx_per_alt: float = 0.18
    cone_dx_max: float = 130.0
    correction_vx_min: float = 1.8
    correction_vx_per_excess: float = 0.06
    correction_vx_per_alt: float = 0.008
    correction_vx_high_alt_cap: float = 7.4
    correction_vx_low_alt_cap: float = 3.0
    correction_vx_low_alt_threshold: float = 32.0
    terminal_burn_correction_vx_floor: float = 4.2
    fast_descent_min_altitude: float = 26.0
    fast_descent_base: float = 1.8
    fast_descent_sqrt_gain: float = 0.28
    fast_descent_cap: float = 6.4
    low_altitude_angle_limit_alt: float = 14.0
    low_altitude_angle_limit_dx: float = 24.0
    low_altitude_angle_cap: float = 0.16
    drift_coast_enter_scale: float = 1.0
    drift_coast_min_altitude: float = 0.0
    drift_coast_descent_floor: float = 0.0
    terminal_correction_cone_scale: float = 0.75


@dataclass(frozen=True)
class TransferBurnConfig:
    """Parameters for the ballistic transfer-burn phase."""

    # Max tilt (radians) during the burn. Higher = more horizontal thrust, less vertical.
    max_tilt: float = 0.9
    # Exit transfer when |vx - vx_target| < this (m/s).
    vx_tolerance: float = 1.0
    # Skip transfer/coast if starting altitude is below this (m); go straight to terminal.
    min_coast_altitude: float = 65.0
    # Cap total delta-vx from initial vx (0 = no cap). Prevents huge reversal burns on vx_away.
    max_transfer_dvx: float = 0.0
    # Soft descent-rate cap during coast (negative m/s, 0 = true free fall).
    # When vy_up drops below this, hold it with gravity compensation only.
    # Keeps terminal entry speed sane without burning throughout.
    max_coast_descent_rate: float = 0.0
    # Allow small mid-course corrections during coast.
    coast_correction_enabled: bool = False
    # Trigger correction when predicted-landing error exceeds this (m).
    coast_correction_threshold: float = 20.0
    # Correction tilt per unit of predicted landing error (rad/m).
    coast_correction_angle_scale: float = 0.004
    # Throttle fraction during coast correction burns.
    coast_correction_throttle: float = 0.35


def cone_dx_limit(alt: float, cfg: DriftCourseConfig) -> float:
    return clamp(
        cfg.cone_dx_base + (cfg.cone_dx_per_alt * alt),
        cfg.cone_dx_base,
        cfg.cone_dx_max,
    )


def correction_vx_cap(alt: float, cfg: DriftCourseConfig) -> float:
    if alt <= cfg.correction_vx_low_alt_threshold:
        return cfg.correction_vx_low_alt_cap
    return cfg.correction_vx_high_alt_cap


def fast_descent_vy(alt: float, cfg: DriftCourseConfig) -> float:
    return -clamp(
        cfg.fast_descent_base + (cfg.fast_descent_sqrt_gain * math.sqrt(alt)),
        cfg.fast_descent_base,
        cfg.fast_descent_cap,
    )


def compute_transfer_plan(
    h: float,
    dx: float,
    vx: float,
    vy_up: float,
    g: float = 9.8,
) -> tuple[float, float]:
    """Ballistic free-fall time and required horizontal speed to reach the target.

    Returns (vx_needed, t_fall). t_fall is floored at 0.5 s to stay stable
    when called close to the ground.
    """
    disc = max(0.0, vy_up * vy_up + 2.0 * g * max(0.0, h))
    t_fall = max(0.5, (vy_up + math.sqrt(disc)) / g)
    return dx / t_fall, t_fall


def predict_landing_x(
    x: float,
    vx: float,
    h: float,
    vy_up: float,
    g: float = 9.8,
) -> float:
    """Where we'd land if we free-fell from the current state (no thrust)."""
    disc = max(0.0, vy_up * vy_up + 2.0 * g * max(0.0, h))
    t_fall = max(0.01, (vy_up + math.sqrt(disc)) / g)
    return x + vx * t_fall


def apply_drift_guidance(guidance: GuidanceTargets, cfg: DriftCourseConfig) -> GuidanceTargets:
    if guidance.phase in ("flare", "touchdown"):
        return guidance

    alt = max(0.0, guidance.alt)
    abs_dx = abs(guidance.dx)
    cone_limit = cone_dx_limit(alt, cfg)
    vx_cap = correction_vx_cap(alt, cfg)
    if guidance.vertical_mode == "terminal_burn" and abs_dx > max(
        16.0,
        cfg.terminal_correction_cone_scale * cone_limit,
    ):
        vx_cap = max(vx_cap, cfg.terminal_burn_correction_vx_floor)
    vx_sp = clamp(guidance.vx_sp, -vx_cap, vx_cap)

    if abs_dx > cone_limit:
        excess = abs_dx - cone_limit
        correction_vx = clamp(
            cfg.correction_vx_min
            + (cfg.correction_vx_per_excess * excess)
            + (cfg.correction_vx_per_alt * alt),
            cfg.correction_vx_min,
            vx_cap,
        )
        vx_sp = math.copysign(max(abs(vx_sp), correction_vx), guidance.dx)

    vy_sp = guidance.vy_sp
    vertical_mode = guidance.vertical_mode
    drift_coast_limit = cone_limit * max(0.1, cfg.drift_coast_enter_scale)
    if (
        vertical_mode == "coast"
        and alt >= cfg.drift_coast_min_altitude
        and abs_dx > drift_coast_limit
    ):
        # Keep drift runs thrust-backed during correction, not ballistic.
        vertical_mode = "drift_coast"
    if vertical_mode == "drift_coast" and cfg.drift_coast_descent_floor > 0.0:
        vy_sp = min(vy_sp, -cfg.drift_coast_descent_floor)
    if vertical_mode == "coast" and alt >= cfg.fast_descent_min_altitude:
        vy_sp = min(vy_sp, fast_descent_vy(alt, cfg))

    phase = "drift" if guidance.phase in ("coast", "align") else guidance.phase
    return replace(
        guidance,
        phase=phase,
        vertical_mode=vertical_mode,
        vx_sp=vx_sp,
        vy_sp=vy_sp,
    )


def cap_low_altitude_angle(
    target_angle: float,
    *,
    alt: float,
    dx: float,
    cfg: DriftCourseConfig,
) -> float:
    if alt <= cfg.low_altitude_angle_limit_alt and abs(dx) <= cfg.low_altitude_angle_limit_dx:
        cap = cfg.low_altitude_angle_cap
        return clamp(target_angle, -cap, cap)
    return target_angle


DRIFT_BALANCED_POLICY = replace(
    BALANCED_POLICY,
    status_prefix="drift",
    lateral_gain=1.1,
    descent_rate_scale=1.03,
    burn_margin_scale=0.98,
    time_to_brake_buffer=0.1,
    coast_horiz_deadband=4.5,
    terminal_brake_gain_high_alt=1.0,
    terminal_brake_gain_low_alt=0.88,
)

DRIFT_EFFICIENCY_POLICY = replace(
    DRIFT_BALANCED_POLICY,
    status_prefix="drift_efficiency",
    lateral_gain=1.24,
    descent_rate_scale=1.24,
    burn_margin_scale=0.78,
    time_to_brake_buffer=0.0,
    coast_horiz_deadband=7.0,
    terminal_brake_gain_high_alt=1.12,
    terminal_brake_gain_low_alt=1.02,
)

DRIFT_ACCURACY_POLICY = replace(
    DRIFT_BALANCED_POLICY,
    status_prefix="drift_accuracy",
    descent_rate_scale=0.94,
    burn_margin_scale=1.12,
    time_to_brake_buffer=0.22,
    coast_horiz_deadband=3.2,
    terminal_brake_gain_high_alt=0.98,
    terminal_brake_gain_low_alt=0.82,
)

DRIFT_BALANCED_COURSE = replace(
    DriftCourseConfig(),
    correction_vx_min=2.2,
    correction_vx_per_excess=0.072,
    correction_vx_per_alt=0.0095,
    correction_vx_high_alt_cap=8.4,
    correction_vx_low_alt_cap=3.3,
)
DRIFT_EFFICIENCY_COURSE = replace(
    DRIFT_BALANCED_COURSE,
    cone_dx_base=20.0,
    cone_dx_per_alt=0.28,
    cone_dx_max=220.0,
    correction_vx_min=3.8,
    correction_vx_per_excess=0.14,
    correction_vx_per_alt=0.015,
    correction_vx_high_alt_cap=11.5,
    correction_vx_low_alt_cap=4.8,
    correction_vx_low_alt_threshold=24.0,
    terminal_burn_correction_vx_floor=6.4,
    low_altitude_angle_limit_alt=11.0,
    low_altitude_angle_limit_dx=18.0,
    low_altitude_angle_cap=0.24,
    drift_coast_enter_scale=0.82,
    drift_coast_min_altitude=22.0,
    drift_coast_descent_floor=3.4,
    terminal_correction_cone_scale=1.0,
)
DRIFT_ACCURACY_COURSE = replace(
    DRIFT_BALANCED_COURSE,
    cone_dx_base=8.0,
    cone_dx_per_alt=0.14,
    cone_dx_max=105.0,
    correction_vx_min=1.7,
    correction_vx_per_excess=0.08,
    correction_vx_per_alt=0.01,
    correction_vx_high_alt_cap=7.0,
    correction_vx_low_alt_cap=2.8,
    correction_vx_low_alt_threshold=36.0,
    terminal_burn_correction_vx_floor=4.4,
    low_altitude_angle_limit_alt=20.0,
    low_altitude_angle_limit_dx=30.0,
    low_altitude_angle_cap=0.12,
    drift_coast_enter_scale=0.72,
    drift_coast_min_altitude=0.0,
    drift_coast_descent_floor=1.4,
    terminal_correction_cone_scale=0.62,
)

# Efficiency: aggressive tilt, pure free-fall coast, no corrections.
# max_transfer_dvx acts as a fallback threshold: if the required reversal is larger than this
# (e.g. vx_away scenarios) the bot skips transfer and uses the old continuous approach instead,
# since large reversals cost more than they save.
DRIFT_EFFICIENCY_TRANSFER = TransferBurnConfig(
    max_tilt=1.1,
    vx_tolerance=1.5,
    min_coast_altitude=160.0,
    max_transfer_dvx=25.0,
    max_coast_descent_rate=0.0,
    coast_correction_enabled=False,
    coast_correction_threshold=999.0,
    coast_correction_angle_scale=0.003,
    coast_correction_throttle=0.0,
)

# Accuracy: moderate tilt for precise vx, coast corrections to hold the trajectory.
# vx_tolerance is tight so the initial pred_err is small (tolerance × t_fall < threshold).
# Same fallback threshold so vx_away also falls back to the old precise approach.
DRIFT_ACCURACY_TRANSFER = TransferBurnConfig(
    max_tilt=0.7,
    vx_tolerance=0.20,
    min_coast_altitude=160.0,
    max_transfer_dvx=25.0,
    max_coast_descent_rate=0.0,
    coast_correction_enabled=True,
    coast_correction_threshold=3.5,
    coast_correction_angle_scale=0.011,
    coast_correction_throttle=0.45,
)

# Balanced: midpoint.
DRIFT_BALANCED_TRANSFER = TransferBurnConfig(
    max_tilt=0.9,
    vx_tolerance=0.9,
    min_coast_altitude=150.0,
    max_transfer_dvx=25.0,
    max_coast_descent_rate=0.0,
    coast_correction_enabled=True,
    coast_correction_threshold=10.0,
    coast_correction_angle_scale=0.007,
    coast_correction_throttle=0.38,
)

_DRIFT_BEHAVIORS: dict[str, tuple[DescentPolicy, DriftCourseConfig, TransferBurnConfig]] = {
    "balanced": (DRIFT_BALANCED_POLICY, DRIFT_BALANCED_COURSE, DRIFT_BALANCED_TRANSFER),
    "efficiency": (DRIFT_EFFICIENCY_POLICY, DRIFT_EFFICIENCY_COURSE, DRIFT_EFFICIENCY_TRANSFER),
    "accuracy": (DRIFT_ACCURACY_POLICY, DRIFT_ACCURACY_COURSE, DRIFT_ACCURACY_TRANSFER),
}


def resolve_drift_behavior(
    behavior: str,
) -> tuple[str, DescentPolicy, DriftCourseConfig, TransferBurnConfig]:
    key, value = resolve_behavior(
        behavior,
        _DRIFT_BEHAVIORS,
        context="drift",
    )
    policy, cfg, transfer_cfg = value
    return key, policy, cfg, transfer_cfg


def list_drift_behavior_names() -> tuple[str, ...]:
    return tuple(sorted(_DRIFT_BEHAVIORS))


__all__ = [
    "DRIFT_ACCURACY_TRANSFER",
    "DRIFT_BALANCED_POLICY",
    "DRIFT_BALANCED_TRANSFER",
    "DRIFT_EFFICIENCY_TRANSFER",
    "DriftCourseConfig",
    "TransferBurnConfig",
    "apply_drift_guidance",
    "cap_low_altitude_angle",
    "compute_transfer_plan",
    "list_drift_behavior_names",
    "predict_landing_x",
    "resolve_drift_behavior",
]
