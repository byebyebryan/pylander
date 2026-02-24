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
    terminal_track_vx_deadband: float = 0.8
    terminal_track_vx_scale: float = 0.9
    terminal_track_vx_cap_max: float = 8.0


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


def _ballistic_fall_time(
    *,
    alt: float,
    vy_up: float,
    g: float = 9.8,
) -> float:
    disc = max(0.0, (vy_up * vy_up) + (2.0 * g * max(0.0, alt)))
    return max(0.5, (vy_up + math.sqrt(disc)) / g)


def _projected_ballistic_dx(
    *,
    dx: float,
    alt: float,
    vx: float | None,
    vy_up: float | None,
    g: float = 9.8,
) -> float:
    if vx is None or vy_up is None or not (math.isfinite(vx) and math.isfinite(vy_up)):
        return dx
    t_fall = _ballistic_fall_time(alt=alt, vy_up=vy_up, g=g)
    return dx - (vx * t_fall)


def apply_drift_guidance(
    guidance: GuidanceTargets,
    cfg: DriftCourseConfig,
    *,
    vx: float | None = None,
    vy_up: float | None = None,
) -> GuidanceTargets:
    if guidance.phase in ("flare", "touchdown"):
        return guidance

    alt = max(0.0, guidance.alt)
    projected_dx = _projected_ballistic_dx(
        dx=guidance.dx,
        alt=alt,
        vx=vx,
        vy_up=vy_up,
    )
    abs_projected_dx = abs(projected_dx)
    cone_limit = cone_dx_limit(alt, cfg)
    vx_cap = correction_vx_cap(alt, cfg)
    vx_needed = 0.0
    vx_need_mag = 0.0
    if guidance.vertical_mode == "terminal_burn":
        vy_for_fall = float(vy_up) if vy_up is not None and math.isfinite(vy_up) else 0.0
        t_fall = _ballistic_fall_time(alt=alt, vy_up=vy_for_fall)
        vx_needed = guidance.dx / t_fall
        vx_need_mag = abs(vx_needed)
        if vx_need_mag > cfg.terminal_track_vx_deadband:
            track_cap = clamp(
                cfg.terminal_track_vx_scale * vx_need_mag,
                0.0,
                cfg.terminal_track_vx_cap_max,
            )
            vx_cap = max(vx_cap, cfg.terminal_burn_correction_vx_floor, track_cap)
    if guidance.vertical_mode == "terminal_burn" and abs_projected_dx > max(
        16.0,
        cfg.terminal_correction_cone_scale * cone_limit,
    ):
        vx_cap = max(vx_cap, cfg.terminal_burn_correction_vx_floor)
    vx_sp = clamp(guidance.vx_sp, -vx_cap, vx_cap)
    correction_active = False

    if abs_projected_dx > cone_limit:
        excess = abs_projected_dx - cone_limit
        correction_vx = clamp(
            cfg.correction_vx_min
            + (cfg.correction_vx_per_excess * excess)
            + (cfg.correction_vx_per_alt * alt),
            cfg.correction_vx_min,
            vx_cap,
        )
        vx_sp = math.copysign(max(abs(vx_sp), correction_vx), projected_dx)
        correction_active = True

    if guidance.vertical_mode == "terminal_burn":
        if vx_need_mag > cfg.terminal_track_vx_deadband:
            blend = clamp(
                (vx_need_mag - cfg.terminal_track_vx_deadband)
                / max(0.2, cfg.terminal_track_vx_deadband),
                0.0,
                1.0,
            )
            terminal_vx_floor = clamp(
                blend * cfg.terminal_track_vx_scale * vx_needed,
                -vx_cap,
                vx_cap,
            )
            vx_sp = math.copysign(max(abs(vx_sp), abs(terminal_vx_floor)), terminal_vx_floor)

    vy_sp = guidance.vy_sp
    vertical_mode = guidance.vertical_mode
    drift_coast_limit = cone_limit * max(0.1, cfg.drift_coast_enter_scale)
    if (
        vertical_mode == "coast"
        and alt >= cfg.drift_coast_min_altitude
        and abs_projected_dx > drift_coast_limit
        and correction_active
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
    lateral_gain=1.12,
    descent_rate_scale=1.0,
    burn_margin_scale=0.94,
    time_to_brake_buffer=0.14,
    coast_horiz_deadband=4.0,
    terminal_brake_gain_high_alt=0.98,
    terminal_brake_gain_low_alt=0.86,
)

DRIFT_EFFICIENCY_POLICY = replace(
    DRIFT_BALANCED_POLICY,
    status_prefix="drift_efficiency",
    lateral_gain=1.0,
    descent_rate_scale=1.26,
    burn_margin_scale=0.74,
    time_to_brake_buffer=0.04,
    coast_horiz_deadband=8.5,
    terminal_brake_gain_high_alt=1.2,
    terminal_brake_gain_low_alt=1.08,
)

DRIFT_ACCURACY_POLICY = replace(
    DRIFT_BALANCED_POLICY,
    status_prefix="drift_accuracy",
    lateral_gain=1.34,
    descent_rate_scale=0.82,
    burn_margin_scale=1.26,
    time_to_brake_buffer=0.36,
    coast_horiz_deadband=2.0,
    terminal_brake_gain_high_alt=0.92,
    terminal_brake_gain_low_alt=0.78,
)

DRIFT_BALANCED_COURSE = replace(
    DriftCourseConfig(),
    cone_dx_base=18.0,
    cone_dx_per_alt=0.24,
    cone_dx_max=190.0,
    correction_vx_min=1.8,
    correction_vx_per_excess=0.09,
    correction_vx_per_alt=0.009,
    correction_vx_high_alt_cap=7.2,
    correction_vx_low_alt_cap=3.2,
    correction_vx_low_alt_threshold=33.0,
    terminal_burn_correction_vx_floor=4.8,
    drift_coast_enter_scale=1.1,
    drift_coast_min_altitude=18.0,
    drift_coast_descent_floor=1.2,
    terminal_correction_cone_scale=0.7,
    terminal_track_vx_deadband=0.75,
    terminal_track_vx_scale=0.92,
    terminal_track_vx_cap_max=8.0,
)
DRIFT_EFFICIENCY_COURSE = replace(
    DRIFT_BALANCED_COURSE,
    cone_dx_base=32.0,
    cone_dx_per_alt=0.38,
    cone_dx_max=300.0,
    correction_vx_min=1.0,
    correction_vx_per_excess=0.05,
    correction_vx_per_alt=0.005,
    correction_vx_high_alt_cap=6.0,
    correction_vx_low_alt_cap=3.0,
    correction_vx_low_alt_threshold=24.0,
    terminal_burn_correction_vx_floor=4.4,
    fast_descent_min_altitude=18.0,
    fast_descent_base=2.4,
    fast_descent_sqrt_gain=0.34,
    fast_descent_cap=8.2,
    low_altitude_angle_limit_alt=11.0,
    low_altitude_angle_limit_dx=18.0,
    low_altitude_angle_cap=0.22,
    drift_coast_enter_scale=1.6,
    drift_coast_min_altitude=260.0,
    drift_coast_descent_floor=0.0,
    terminal_correction_cone_scale=0.95,
    terminal_track_vx_deadband=0.35,
    terminal_track_vx_scale=1.08,
    terminal_track_vx_cap_max=10.0,
)
DRIFT_ACCURACY_COURSE = replace(
    DRIFT_BALANCED_COURSE,
    cone_dx_base=4.0,
    cone_dx_per_alt=0.08,
    cone_dx_max=68.0,
    correction_vx_min=2.9,
    correction_vx_per_excess=0.16,
    correction_vx_per_alt=0.015,
    correction_vx_high_alt_cap=9.8,
    correction_vx_low_alt_cap=4.2,
    correction_vx_low_alt_threshold=42.0,
    terminal_burn_correction_vx_floor=6.8,
    fast_descent_min_altitude=34.0,
    fast_descent_base=1.4,
    fast_descent_sqrt_gain=0.22,
    fast_descent_cap=4.8,
    low_altitude_angle_limit_alt=20.0,
    low_altitude_angle_limit_dx=30.0,
    low_altitude_angle_cap=0.10,
    drift_coast_enter_scale=0.55,
    drift_coast_min_altitude=8.0,
    drift_coast_descent_floor=1.4,
    terminal_correction_cone_scale=0.45,
    terminal_track_vx_deadband=0.95,
    terminal_track_vx_scale=0.78,
    terminal_track_vx_cap_max=7.0,
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
