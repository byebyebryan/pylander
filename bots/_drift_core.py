"""Shared drift guidance/control core for drift strategy variants."""

from __future__ import annotations

import math
from dataclasses import dataclass, replace

from bots._descent_core import BALANCED_POLICY, GuidanceTargets, clamp


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
    if guidance.vertical_mode == "terminal_burn" and abs_dx > max(16.0, 0.75 * cone_limit):
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
    if vertical_mode == "coast" and abs_dx > cone_limit:
        # Keep drift runs thrust-backed during correction, not ballistic.
        vertical_mode = "drift_coast"
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


DRIFT_POLICY = replace(
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


__all__ = [
    "DRIFT_POLICY",
    "DriftCourseConfig",
    "apply_drift_guidance",
    "cap_low_altitude_angle",
]
