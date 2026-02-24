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
    cone_dx_base=9.0,
    cone_dx_per_alt=0.16,
    cone_dx_max=120.0,
    correction_vx_min=2.0,
    correction_vx_per_excess=0.07,
    correction_vx_per_alt=0.009,
    correction_vx_high_alt_cap=8.0,
    correction_vx_low_alt_cap=3.2,
    correction_vx_low_alt_threshold=34.0,
    terminal_burn_correction_vx_floor=4.6,
    drift_coast_enter_scale=0.9,
    drift_coast_min_altitude=8.0,
    drift_coast_descent_floor=1.8,
)
DRIFT_EFFICIENCY_COURSE = replace(
    DRIFT_BALANCED_COURSE,
    cone_dx_base=22.0,
    cone_dx_per_alt=0.30,
    cone_dx_max=230.0,
    correction_vx_min=1.5,
    correction_vx_per_excess=0.05,
    correction_vx_per_alt=0.006,
    correction_vx_high_alt_cap=6.8,
    correction_vx_low_alt_cap=2.6,
    correction_vx_low_alt_threshold=22.0,
    terminal_burn_correction_vx_floor=3.6,
    low_altitude_angle_limit_alt=11.0,
    low_altitude_angle_limit_dx=18.0,
    low_altitude_angle_cap=0.22,
    drift_coast_enter_scale=1.35,
    drift_coast_min_altitude=24.0,
    drift_coast_descent_floor=0.0,
    terminal_correction_cone_scale=1.0,
)
DRIFT_ACCURACY_COURSE = replace(
    DRIFT_BALANCED_COURSE,
    cone_dx_base=6.0,
    cone_dx_per_alt=0.11,
    cone_dx_max=95.0,
    correction_vx_min=2.4,
    correction_vx_per_excess=0.11,
    correction_vx_per_alt=0.012,
    correction_vx_high_alt_cap=8.8,
    correction_vx_low_alt_cap=3.4,
    correction_vx_low_alt_threshold=38.0,
    terminal_burn_correction_vx_floor=5.2,
    low_altitude_angle_limit_alt=20.0,
    low_altitude_angle_limit_dx=30.0,
    low_altitude_angle_cap=0.10,
    drift_coast_enter_scale=0.62,
    drift_coast_min_altitude=0.0,
    drift_coast_descent_floor=2.2,
    terminal_correction_cone_scale=0.58,
)

_DRIFT_BEHAVIORS: dict[str, tuple[DescentPolicy, DriftCourseConfig]] = {
    "balanced": (DRIFT_BALANCED_POLICY, DRIFT_BALANCED_COURSE),
    "efficiency": (DRIFT_EFFICIENCY_POLICY, DRIFT_EFFICIENCY_COURSE),
    "accuracy": (DRIFT_ACCURACY_POLICY, DRIFT_ACCURACY_COURSE),
}


def resolve_drift_behavior(
    behavior: str,
) -> tuple[str, DescentPolicy, DriftCourseConfig]:
    key, value = resolve_behavior(
        behavior,
        _DRIFT_BEHAVIORS,
        context="drift",
    )
    policy, cfg = value
    return key, policy, cfg


def list_drift_behavior_names() -> tuple[str, ...]:
    return tuple(sorted(_DRIFT_BEHAVIORS))


__all__ = [
    "DRIFT_BALANCED_POLICY",
    "DriftCourseConfig",
    "apply_drift_guidance",
    "cap_low_altitude_angle",
    "list_drift_behavior_names",
    "resolve_drift_behavior",
]
