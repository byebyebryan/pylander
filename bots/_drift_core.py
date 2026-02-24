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
from core.bot import ActiveSensors
from core.terrain import ballistic_fall_time


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
    lateral_velocity_gain: float = 0.95
    lateral_accel_damping: float = 0.08
    lateral_position_gain: float = 0.45
    lateral_position_term_cap: float = 3.5
    lateral_accel_cap: float = 8.5
    lateral_tgo_min: float = 1.0
    lateral_tgo_max: float = 11.0
    sensor_lateral_tgo_min: float = 0.7
    sensor_lateral_tgo_max: float = 12.5
    lateral_track_min_weight: float = 0.35
    lateral_track_dx_full: float = 60.0
    sensor_track_weight_boost: float = 0.08
    lateral_soft_zone_alt: float = 16.0
    lateral_soft_zone_dx: float = 14.0
    lateral_soft_zone_scale: float = 0.55
    lateral_stop_accel_estimate: float = 5.0
    lateral_stop_vx_margin: float = 0.92
    lateral_zero_vx_dx: float = 55.0
    lateral_zero_vx_alt: float = 40.0
    lateral_zero_vx_cap: float = 1.6
    lateral_terminal_zero_vx_dx: float = 24.0
    lateral_terminal_zero_vx_alt: float = 18.0
    lateral_terminal_zero_vx_cap: float = 1.0
    coupled_vertical_reserve_up_acc: float = 1.6
    coupled_lateral_efficiency: float = 0.86
    coupled_lateral_min_speed: float = 2.5
    coupled_brake_margin_scale: float = 1.08
    coupled_brake_margin_time: float = 0.25
    coupled_lateral_alt_margin: float = 5.0
    drift_coast_max_alt: float = 220.0
    drift_coast_min_entry_vx: float = 9.0


@dataclass(frozen=True)
class DriftLateralTracker:
    vx_target: float
    ax_target: float


@dataclass(frozen=True)
class DriftBrakeWindow:
    vertical_brake_alt: float
    lateral_brake_alt: float
    combined_brake_alt: float
    lateral_time_to_stop: float
    time_to_target: float


@dataclass(frozen=True)
class DriftBallisticProjection:
    projected_dx: float
    t_fall: float
    target_x: float | None
    impact_x: float | None
    used_sensor: bool


def _coerce_finite(value: float | None, default: float = 0.0) -> float:
    if value is None:
        return default
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(numeric):
        return default
    return numeric


def _estimate_ballistic_projection(
    *,
    dx: float,
    alt: float,
    vx: float | None,
    vy_up: float | None,
    x: float | None,
    y: float | None,
    active: ActiveSensors | None,
    clearance: float,
) -> DriftBallisticProjection:
    safe_alt = max(0.0, _coerce_finite(alt, 0.0))
    safe_vx = _coerce_finite(vx, 0.0)
    safe_vy = _coerce_finite(vy_up, 0.0)
    safe_dx = _coerce_finite(dx, 0.0)
    fallback_t_fall = ballistic_fall_time(altitude=safe_alt, vy_up=safe_vy)
    fallback_projected_dx = safe_dx - (safe_vx * fallback_t_fall)

    safe_x = _coerce_finite(x, float("nan"))
    safe_y = _coerce_finite(y, float("nan"))
    target_x: float | None = None
    fallback_impact_x: float | None = None
    if math.isfinite(safe_x):
        target_x = safe_x + safe_dx
        fallback_impact_x = safe_x + (safe_vx * fallback_t_fall)
    fallback = DriftBallisticProjection(
        projected_dx=fallback_projected_dx,
        t_fall=fallback_t_fall,
        target_x=target_x,
        impact_x=fallback_impact_x,
        used_sensor=False,
    )
    if active is None or not (math.isfinite(safe_x) and math.isfinite(safe_y)):
        return fallback

    distance_budget = max(
        600.0,
        abs(safe_dx) + (abs(safe_vx) * max(2.0, fallback_t_fall)) + 300.0,
    )
    try:
        traj = active.ballistic_trajectory(
            x=safe_x,
            y=safe_y,
            vx=safe_vx,
            vy_up=safe_vy,
            max_distance=min(5000.0, distance_budget),
            segment_length=22.0,
            max_points=192,
            lod=0,
            clearance=max(0.0, float(clearance)),
        )
    except Exception:
        return fallback
    if not isinstance(traj, dict) or not bool(traj.get("hit")):
        return fallback
    hit_x_raw = traj.get("hit_x")
    if not isinstance(hit_x_raw, (int, float)) or not math.isfinite(float(hit_x_raw)):
        return fallback

    target_x = safe_x + safe_dx
    sensor_projected_dx = target_x - float(hit_x_raw)
    hit_time = traj.get("hit_time")
    duration = traj.get("duration")
    sensor_t_fall = _coerce_finite(hit_time, _coerce_finite(duration, fallback_t_fall))
    return DriftBallisticProjection(
        projected_dx=sensor_projected_dx,
        t_fall=max(0.5, sensor_t_fall),
        target_x=target_x,
        impact_x=float(hit_x_raw),
        used_sensor=True,
    )


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


def coupled_brake_window(
    cfg: DriftCourseConfig,
    *,
    alt: float,
    dx: float,
    vx: float,
    vy_up: float,
    mass: float,
    max_force: float,
    max_tilt: float,
    spool_time: float,
    vertical_brake_alt: float,
) -> DriftBrakeWindow:
    abs_dx = abs(dx)
    abs_vx = abs(vx)
    moving_toward_target = (abs_dx > 1e-3) and ((dx * vx) > 0.0)
    safe_mass = max(0.5, mass)
    total_accel = max_force / safe_mass
    lateral_accel_tilt = max(0.0, total_accel * abs(math.sin(max_tilt)))
    reserve_up_acc = 9.8 + cfg.coupled_vertical_reserve_up_acc
    lateral_accel_coupled = math.sqrt(max(0.0, (total_accel * total_accel) - (reserve_up_acc * reserve_up_acc)))
    lateral_budget = max(
        0.25,
        min(lateral_accel_tilt, lateral_accel_coupled) * cfg.coupled_lateral_efficiency,
    )
    time_to_stop = abs_vx / lateral_budget
    time_to_target = abs_dx / max(abs_vx, 1e-3) if moving_toward_target else float("inf")
    lateral_brake_time = (
        spool_time
        + cfg.coupled_brake_margin_time
        + (cfg.coupled_brake_margin_scale * time_to_stop)
    )
    down_speed = max(0.0, -vy_up)
    lateral_brake_alt = 0.0
    if (
        moving_toward_target
        and abs_vx >= cfg.coupled_lateral_min_speed
        and time_to_target <= lateral_brake_time
    ):
        lateral_brake_alt = (
            (down_speed * lateral_brake_time)
            + (4.9 * lateral_brake_time * lateral_brake_time)
            + cfg.coupled_lateral_alt_margin
        )
    combined_brake_alt = max(vertical_brake_alt, lateral_brake_alt)
    return DriftBrakeWindow(
        vertical_brake_alt=vertical_brake_alt,
        lateral_brake_alt=lateral_brake_alt,
        combined_brake_alt=combined_brake_alt,
        lateral_time_to_stop=time_to_stop,
        time_to_target=time_to_target,
    )


def apply_drift_guidance(
    guidance: GuidanceTargets,
    cfg: DriftCourseConfig,
    *,
    vx: float | None = None,
    vy_up: float | None = None,
    active: ActiveSensors | None = None,
    x: float | None = None,
    y: float | None = None,
    clearance: float = 0.0,
    debug: dict[str, object] | None = None,
) -> GuidanceTargets:
    if guidance.phase in ("flare", "touchdown"):
        return guidance

    alt = max(0.0, guidance.alt)
    projection = _estimate_ballistic_projection(
        dx=guidance.dx,
        alt=alt,
        vx=vx,
        vy_up=vy_up,
        x=x,
        y=y,
        active=active,
        clearance=clearance,
    )
    projected_dx = projection.projected_dx
    abs_projected_dx = abs(projected_dx)
    cone_limit = cone_dx_limit(alt, cfg)
    vx_cap = correction_vx_cap(alt, cfg)
    current_vx = float(vx) if vx is not None and math.isfinite(vx) else 0.0
    vx_needed = 0.0
    vx_need_mag = 0.0
    if guidance.vertical_mode == "terminal_burn":
        vx_needed = guidance.dx / max(0.5, projection.t_fall)
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
        if (
            abs(guidance.dx) <= cfg.lateral_terminal_zero_vx_dx
            and alt <= cfg.lateral_terminal_zero_vx_alt
        ):
            # In late terminal near target, prioritize low lateral speed over centering speed.
            vx_sp = clamp(
                vx_sp,
                -cfg.lateral_terminal_zero_vx_cap,
                cfg.lateral_terminal_zero_vx_cap,
            )

    vy_sp = guidance.vy_sp
    vertical_mode = guidance.vertical_mode
    drift_coast_limit = cone_limit * max(0.1, cfg.drift_coast_enter_scale)
    if (
        vertical_mode == "coast"
        and alt >= cfg.drift_coast_min_altitude
        and alt <= cfg.drift_coast_max_alt
        and abs(current_vx) >= cfg.drift_coast_min_entry_vx
        and abs_projected_dx > drift_coast_limit
        and correction_active
    ):
        # Keep drift runs thrust-backed during correction, not ballistic.
        vertical_mode = "drift_coast"
    if vertical_mode == "drift_coast" and cfg.drift_coast_descent_floor > 0.0:
        vy_sp = min(vy_sp, -cfg.drift_coast_descent_floor)
    if vertical_mode == "coast" and alt >= cfg.fast_descent_min_altitude:
        vy_sp = min(vy_sp, fast_descent_vy(alt, cfg))
    if debug is not None:
        debug.update(
            {
                "projected_dx": projected_dx,
                "t_fall": projection.t_fall,
                "impact_x": projection.impact_x,
                "target_x": projection.target_x,
                "sensor_used": projection.used_sensor,
            }
        )

    phase = "drift" if guidance.phase in ("coast", "align") else guidance.phase
    return replace(
        guidance,
        phase=phase,
        vertical_mode=vertical_mode,
        vx_sp=vx_sp,
        vy_sp=vy_sp,
    )


def lateral_tracking_command(
    cfg: DriftCourseConfig,
    *,
    dx: float,
    alt: float,
    vx: float,
    vy_up: float,
    ax: float,
    vx_guidance: float,
    active: ActiveSensors | None = None,
    x: float | None = None,
    y: float | None = None,
    clearance: float = 0.0,
) -> DriftLateralTracker:
    safe_alt = max(0.0, alt)
    projection = _estimate_ballistic_projection(
        dx=dx,
        alt=safe_alt,
        vx=vx,
        vy_up=vy_up,
        x=x,
        y=y,
        active=active,
        clearance=clearance,
    )
    tgo_min = cfg.lateral_tgo_min
    tgo_max = cfg.lateral_tgo_max
    if projection.used_sensor:
        tgo_min = min(tgo_min, cfg.sensor_lateral_tgo_min)
        tgo_max = max(tgo_max, cfg.sensor_lateral_tgo_max)
    t_go = clamp(
        projection.t_fall,
        tgo_min,
        tgo_max,
    )
    vx_cap = correction_vx_cap(safe_alt, cfg)
    vx_track = clamp(dx / max(0.5, t_go), -vx_cap, vx_cap)
    track_weight = clamp(
        abs(dx) / max(1e-3, cfg.lateral_track_dx_full),
        cfg.lateral_track_min_weight,
        1.0,
    )
    if projection.used_sensor and abs(dx) > 8.0:
        track_weight = clamp(
            track_weight + cfg.sensor_track_weight_boost,
            cfg.lateral_track_min_weight,
            1.0,
        )
    vx_target = ((1.0 - track_weight) * vx_guidance) + (track_weight * vx_track)
    abs_dx = abs(dx)
    moving_toward_target = (abs_dx > 1e-3) and ((dx * vx) > 0.0)
    if moving_toward_target:
        # Keep lateral speed within what can be stopped by remaining offset.
        vx_stop_cap = math.sqrt(max(0.0, 2.0 * cfg.lateral_stop_accel_estimate * abs_dx))
        vx_stop_cap *= cfg.lateral_stop_vx_margin
        vx_target = math.copysign(min(abs(vx_target), vx_stop_cap), dx)
    if abs_dx <= cfg.lateral_zero_vx_dx and safe_alt <= cfg.lateral_zero_vx_alt:
        vx_cap_near = cfg.lateral_zero_vx_cap
        vx_target = clamp(vx_target, -vx_cap_near, vx_cap_near)
    vx_err = vx_target - vx
    pos_term = clamp(
        dx / max(1e-3, t_go * t_go),
        -cfg.lateral_position_term_cap,
        cfg.lateral_position_term_cap,
    )
    ax_target = (
        (cfg.lateral_velocity_gain * vx_err)
        + (cfg.lateral_position_gain * pos_term)
        - (cfg.lateral_accel_damping * ax)
    )
    if safe_alt <= cfg.lateral_soft_zone_alt and abs(dx) <= cfg.lateral_soft_zone_dx:
        ax_target *= cfg.lateral_soft_zone_scale
    ax_target = clamp(ax_target, -cfg.lateral_accel_cap, cfg.lateral_accel_cap)
    return DriftLateralTracker(vx_target=vx_target, ax_target=ax_target)


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
    lateral_gain=1.12,
    descent_rate_scale=1.0,
    burn_margin_scale=0.94,
    time_to_brake_buffer=0.14,
    coast_horiz_deadband=4.0,
    terminal_brake_gain_high_alt=0.98,
    terminal_brake_gain_low_alt=0.86,
)
DRIFT_COURSE = replace(
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
    lateral_velocity_gain=0.98,
    lateral_accel_damping=0.07,
    lateral_position_gain=0.52,
    lateral_position_term_cap=3.8,
    lateral_accel_cap=8.2,
    lateral_tgo_min=1.0,
    lateral_tgo_max=10.5,
    sensor_lateral_tgo_min=0.75,
    sensor_lateral_tgo_max=12.0,
    lateral_track_min_weight=0.0,
    lateral_track_dx_full=56.0,
    sensor_track_weight_boost=0.1,
    lateral_soft_zone_alt=14.0,
    lateral_soft_zone_dx=12.0,
    lateral_soft_zone_scale=0.5,
    lateral_stop_accel_estimate=5.4,
    lateral_stop_vx_margin=0.9,
    lateral_zero_vx_dx=28.0,
    lateral_zero_vx_alt=34.0,
    lateral_zero_vx_cap=1.8,
    lateral_terminal_zero_vx_dx=24.0,
    lateral_terminal_zero_vx_alt=14.0,
    lateral_terminal_zero_vx_cap=0.9,
    coupled_vertical_reserve_up_acc=1.8,
    coupled_lateral_efficiency=0.84,
    coupled_lateral_min_speed=3.0,
    coupled_brake_margin_scale=1.12,
    coupled_brake_margin_time=0.3,
    coupled_lateral_alt_margin=6.0,
    drift_coast_max_alt=200.0,
    drift_coast_min_entry_vx=10.0,
)

_DRIFT_BEHAVIORS: dict[str, tuple[DescentPolicy, DriftCourseConfig]] = {
    "drift": (DRIFT_POLICY, DRIFT_COURSE),
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
    "DRIFT_POLICY",
    "DriftCourseConfig",
    "DriftBrakeWindow",
    "DriftLateralTracker",
    "apply_drift_guidance",
    "cap_low_altitude_angle",
    "coupled_brake_window",
    "lateral_tracking_command",
    "list_drift_behavior_names",
    "resolve_drift_behavior",
]
