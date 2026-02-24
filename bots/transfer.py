"""Transfer setup bot: hard side-burn setup, then hand off to drift."""

from __future__ import annotations

import math
from dataclasses import dataclass, replace

from bots._descent_core import (
    DescentPolicy,
    GuidanceTargets,
    StrategyDescentBot,
    clamp,
    rate_limit_angle_command,
    resolve_behavior,
)
from bots._drift_core import (
    DRIFT_COURSE,
    DRIFT_POLICY,
    DriftCourseConfig,
    apply_drift_guidance,
    cone_dx_limit,
)
from bots.drift import DriftBot
from core.bot import ActiveSensors, Bot, BotAction, PassiveSensors
from core.sensor import RadarContact
from core.terrain import ballistic_fall_time


@dataclass(frozen=True)
class TransferSetupConfig:
    handoff_projected_dx_ratio: float = 0.85
    setup_vx_cap: float = 92.0
    setup_vx_floor: float = 6.0
    setup_descent_vy_target: float = -2.2
    setup_response_delay_s: float = 0.65
    setup_ballistic_vy_blend: float = 0.45
    handoff_force_drift_altitude: float = 420.0
    setup_vx_deadband: float = 1.6
    setup_sideburn_angle_rad: float = 1.40
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


@dataclass(frozen=True)
class _BallisticProjection:
    projected_dx: float
    t_fall: float
    target_x: float | None
    impact_x: float | None


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
    vx: float,
    vy_up: float,
    x: float | None = None,
    y: float | None = None,
    active: ActiveSensors | None = None,
    clearance: float = 0.0,
) -> _BallisticProjection:
    safe_alt = max(0.0, _coerce_finite(alt, 0.0))
    safe_vx = _coerce_finite(vx, 0.0)
    safe_vy_up = _coerce_finite(vy_up, 0.0)
    safe_dx = _coerce_finite(dx, 0.0)
    target_x = None
    if x is not None and math.isfinite(_coerce_finite(x, float("nan"))):
        target_x = _coerce_finite(x, 0.0) + safe_dx
    fallback_t_fall = ballistic_fall_time(altitude=safe_alt, vy_up=safe_vy_up)
    fallback_projected_dx = safe_dx - (safe_vx * fallback_t_fall)
    fallback_impact_x = None
    safe_x_for_fallback = _coerce_finite(x, float("nan"))
    if math.isfinite(safe_x_for_fallback):
        fallback_impact_x = safe_x_for_fallback + (safe_vx * fallback_t_fall)
    fallback = _BallisticProjection(
        projected_dx=fallback_projected_dx,
        t_fall=fallback_t_fall,
        target_x=target_x,
        impact_x=fallback_impact_x,
    )
    safe_x = _coerce_finite(x, float("nan"))
    safe_y = _coerce_finite(y, float("nan"))
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
            vy_up=safe_vy_up,
            max_distance=min(5000.0, distance_budget),
            segment_length=22.0,
            max_points=192,
            lod=0,
            clearance=max(0.0, float(clearance)),
        )
    except Exception:
        return fallback
    if not isinstance(traj, dict):
        return fallback
    if not bool(traj.get("hit")):
        return fallback
    hit_x_raw = traj.get("hit_x")
    if not isinstance(hit_x_raw, (int, float)) or not math.isfinite(float(hit_x_raw)):
        return fallback
    target_x = safe_x + safe_dx
    sensor_projected_dx = target_x - float(hit_x_raw)
    hit_time = traj.get("hit_time")
    duration = traj.get("duration")
    sensor_t_fall = _coerce_finite(hit_time, _coerce_finite(duration, fallback_t_fall))
    return _BallisticProjection(
        projected_dx=sensor_projected_dx,
        t_fall=max(0.5, sensor_t_fall),
        target_x=target_x,
        impact_x=float(hit_x_raw),
    )


def _ballistic_reference_vy(
    guidance: GuidanceTargets,
    setup_cfg: TransferSetupConfig,
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
    setup_cfg: TransferSetupConfig,
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


def should_handoff_to_drift(
    guidance: GuidanceTargets,
    course_cfg: DriftCourseConfig,
    setup_cfg: TransferSetupConfig,
    *,
    vx: float | None,
    vy_up: float | None,
    active: ActiveSensors | None = None,
    x: float | None = None,
    y: float | None = None,
    target_size: float | None = None,
    clearance: float = 0.0,
    debug: dict[str, object] | None = None,
) -> bool:
    _ = course_cfg
    alt = max(0.0, float(guidance.alt))
    safe_vx = float(vx) if vx is not None and math.isfinite(vx) else 0.0
    safe_vy_up = float(vy_up) if vy_up is not None and math.isfinite(vy_up) else 0.0
    current_projection = _estimate_ballistic_projection(
        dx=float(guidance.dx),
        alt=alt,
        vx=safe_vx,
        vy_up=safe_vy_up,
        x=x,
        y=y,
        active=active,
        clearance=clearance,
    )
    dx_pred, alt_pred, vx_pred, vy_pred = _predict_response_state(
        dx=float(guidance.dx),
        alt=alt,
        vx=safe_vx,
        vy_up=safe_vy_up,
        delay_s=setup_cfg.setup_response_delay_s,
    )
    x_pred, y_pred = _predict_response_world_state(
        x=x,
        y=y,
        vx=safe_vx,
        vy_up=safe_vy_up,
        delay_s=setup_cfg.setup_response_delay_s,
    )
    planned_vy_up = _ballistic_reference_vy(guidance, setup_cfg, vy_pred)
    projection = _estimate_ballistic_projection(
        dx=dx_pred,
        alt=alt_pred,
        vx=vx_pred,
        vy_up=planned_vy_up,
        x=x_pred,
        y=y_pred,
        active=active,
        clearance=clearance,
    )
    t_fall = projection.t_fall
    projected_dx = projection.projected_dx
    on_track, centered, inside_target, center_tol, target_half = _handoff_alignment(
        projected_dx=projected_dx,
        t_fall=t_fall,
        target_size=target_size,
        setup_cfg=setup_cfg,
    )
    (
        current_on_track,
        current_centered,
        current_inside_target,
        current_center_tol,
        _,
    ) = _handoff_alignment(
        projected_dx=current_projection.projected_dx,
        t_fall=current_projection.t_fall,
        target_size=target_size,
        setup_cfg=setup_cfg,
    )
    shortfall_guard = max(2.0, setup_cfg.handoff_shortfall_guard_ratio * target_half)
    shortfall_metric = projected_dx * math.copysign(1.0, float(guidance.dx))
    not_falling_short = shortfall_metric <= shortfall_guard
    current_shortfall_metric = current_projection.projected_dx * math.copysign(
        1.0,
        float(guidance.dx),
    )
    current_shortfall_guard = max(shortfall_guard, current_center_tol)
    current_not_falling_short = current_shortfall_metric <= current_shortfall_guard
    current_guard_pass = current_centered and current_inside_target and current_not_falling_short
    if on_track and not current_centered:
        track_ready = False
    else:
        track_ready = on_track or current_guard_pass
    vx_needed = vx_pred + (projected_dx / max(0.5, t_fall))
    vx_err = abs(vx_needed - vx_pred)
    speed_ready = vx_err <= max(
        2.5,
        0.16 * max(abs(vx_needed), setup_cfg.setup_vx_floor),
    )
    if debug is not None:
        debug.update(
            {
                "projected_dx": projected_dx,
                "on_track": on_track,
                "centered": centered,
                "inside_target": inside_target,
                "center_tolerance": center_tol,
                "target_half": target_half,
                "shortfall_guard": shortfall_guard,
                "not_falling_short": not_falling_short,
                "current_projected_dx": current_projection.projected_dx,
                "current_on_track": current_on_track,
                "current_centered": current_centered,
                "current_inside_target": current_inside_target,
                "current_center_tolerance": current_center_tol,
                "current_shortfall_guard": current_shortfall_guard,
                "current_not_falling_short": current_not_falling_short,
                "current_guard_pass": current_guard_pass,
                "track_ready": track_ready,
                "speed_ready": speed_ready,
                "alt_pred": alt_pred,
                "t_fall": t_fall,
                "vx_needed": vx_needed,
                "vx_err": vx_err,
                "impact_x": projection.impact_x,
                "target_x": projection.target_x,
                "current_impact_x": current_projection.impact_x,
                "current_target_x": current_projection.target_x,
            }
        )
    if alt_pred <= setup_cfg.handoff_force_drift_altitude:
        return track_ready and not_falling_short
    return track_ready and speed_ready and not_falling_short


def apply_transfer_setup_guidance(
    guidance: GuidanceTargets,
    course_cfg: DriftCourseConfig,
    setup_cfg: TransferSetupConfig,
    *,
    vx: float | None,
    vy_up: float | None,
    active: ActiveSensors | None = None,
    x: float | None = None,
    y: float | None = None,
    target_size: float | None = None,
    clearance: float = 0.0,
) -> GuidanceTargets:
    alt = max(0.0, float(guidance.alt))
    safe_vx = float(vx) if vx is not None and math.isfinite(vx) else 0.0
    safe_vy_up = float(vy_up) if vy_up is not None and math.isfinite(vy_up) else 0.0
    dx_pred, alt_pred, vx_pred, vy_pred = _predict_response_state(
        dx=float(guidance.dx),
        alt=alt,
        vx=safe_vx,
        vy_up=safe_vy_up,
        delay_s=setup_cfg.setup_response_delay_s,
    )
    x_pred, y_pred = _predict_response_world_state(
        x=x,
        y=y,
        vx=safe_vx,
        vy_up=safe_vy_up,
        delay_s=setup_cfg.setup_response_delay_s,
    )
    planned_vy_up = _ballistic_reference_vy(guidance, setup_cfg, vy_pred)
    projection = _estimate_ballistic_projection(
        dx=dx_pred,
        alt=alt_pred,
        vx=vx_pred,
        vy_up=planned_vy_up,
        x=x_pred,
        y=y_pred,
        active=active,
        clearance=clearance,
    )
    projected_dx = projection.projected_dx
    t_fall = projection.t_fall
    _, centered, inside_target, _, _ = _handoff_alignment(
        projected_dx=projected_dx,
        t_fall=t_fall,
        target_size=target_size,
        setup_cfg=setup_cfg,
    )
    vx_cap = max(setup_cfg.setup_vx_floor, setup_cfg.setup_vx_cap)
    vx_needed = vx_pred + (projected_dx / max(0.5, t_fall))
    vx_sp = clamp(vx_needed, -vx_cap, vx_cap)
    if not (centered and inside_target):
        vx_sp = math.copysign(max(abs(vx_sp), setup_cfg.setup_vx_floor), vx_needed)
    return replace(
        guidance,
        phase="transfer_setup_sideburn",
        vertical_mode="transfer_sideburn",
        vx_sp=vx_sp,
        vy_sp=max(float(guidance.vy_sp), setup_cfg.setup_descent_vy_target),
    )


TRANSFER_POLICY = replace(
    DRIFT_POLICY,
    status_prefix="transfer",
)
TRANSFER_COURSE = replace(
    DRIFT_COURSE,
    # Transfer handoff often carries high lateral speed; start braking earlier.
    correction_vx_per_excess=0.11,
    correction_vx_per_alt=0.011,
    correction_vx_high_alt_cap=28.0,
    correction_vx_low_alt_cap=8.0,
    correction_vx_low_alt_threshold=55.0,
    terminal_burn_correction_vx_floor=6.2,
    terminal_track_vx_scale=1.0,
    terminal_track_vx_cap_max=12.0,
    lateral_stop_accel_estimate=4.6,
    lateral_stop_vx_margin=0.95,
    lateral_zero_vx_dx=32.0,
    lateral_zero_vx_alt=52.0,
    lateral_zero_vx_cap=1.5,
    lateral_terminal_zero_vx_dx=22.0,
    lateral_terminal_zero_vx_alt=16.0,
    lateral_terminal_zero_vx_cap=1.2,
)
_TRANSFER_BEHAVIORS: dict[str, tuple[DescentPolicy, DriftCourseConfig, TransferSetupConfig]] = {
    "transfer": (TRANSFER_POLICY, TRANSFER_COURSE, TransferSetupConfig()),
}


def resolve_transfer_behavior(
    behavior: str,
) -> tuple[str, DescentPolicy, DriftCourseConfig, TransferSetupConfig]:
    key, value = resolve_behavior(
        behavior,
        _TRANSFER_BEHAVIORS,
        context="transfer",
    )
    policy, course_cfg, setup_cfg = value
    return key, policy, course_cfg, setup_cfg


def list_transfer_behavior_names() -> tuple[str, ...]:
    return tuple(sorted(_TRANSFER_BEHAVIORS))


class TransferBot(DriftBot):
    def __init__(self, behavior: str = "transfer") -> None:
        super().__init__(behavior=behavior)
        self._setup_phase_seen = False
        self._handoff_done = False
        self._setup_direction = 0.0
        self._active_sensors: ActiveSensors | None = None
        self._debug_projection_summary = ""
        self._handoff_event_summary = ""
        self._last_target_size: float | None = None

    def set_behavior(self, behavior: str) -> None:
        key, policy, cfg, setup_cfg = resolve_transfer_behavior(behavior)
        self._policy = policy
        self._course_cfg = cfg
        self._setup_cfg = setup_cfg
        self._behavior = key
        self._setup_phase_seen = False
        self._handoff_done = False
        self._setup_direction = 0.0
        self._active_sensors = None
        self._ballistic_debug_summary = ""
        self._debug_projection_summary = ""
        self._handoff_event_summary = ""
        self._last_target_size = None

    def _ballistic_clearance(self) -> float:
        if self.vehicle_info is None:
            return 0.0
        return max(0.0, 0.5 * float(self.vehicle_info.height))

    def update(
        self,
        dt: float,
        passive: PassiveSensors,
        active: ActiveSensors,
    ) -> BotAction:
        if passive.state != "flying":
            self._setup_phase_seen = False
            self._handoff_done = False
            self._setup_direction = 0.0
            self._ballistic_debug_summary = ""
            self._debug_projection_summary = ""
            self._handoff_event_summary = ""
            self._last_target_size = None
        self._active_sensors = active
        try:
            return super().update(dt, passive, active)
        finally:
            self._active_sensors = None

    @staticmethod
    def _fmt_debug_float(value: float | None) -> str:
        if value is None:
            return "na"
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return "na"
        if not math.isfinite(numeric):
            return "na"
        return f"{numeric:.1f}"

    def _guidance(
        self,
        passive: PassiveSensors,
        target: RadarContact,
        *,
        max_force: float,
        max_throttle: float,
        ramp_up: float,
        active: ActiveSensors | None = None,
    ) -> GuidanceTargets:
        base_guidance = StrategyDescentBot._guidance(
            self,
            passive,
            target,
            max_force=max_force,
            max_throttle=max_throttle,
            ramp_up=ramp_up,
            active=active,
        )
        current_guidance = replace(
            base_guidance,
            dx=float(target.x) - float(passive.x),
            alt=float(passive.altitude),
        )
        current_projection = _estimate_ballistic_projection(
            dx=current_guidance.dx,
            alt=current_guidance.alt,
            vx=passive.vx,
            vy_up=passive.vy_up,
            x=passive.x,
            y=passive.y,
            active=self._active_sensors,
            clearance=self._ballistic_clearance(),
        )
        target_size = _coerce_finite(getattr(target, "size", None), float("nan"))
        if not math.isfinite(target_size):
            target_size = None
        self._last_target_size = target_size
        current_on_track, current_centered, current_inside_target, current_center_tol, current_target_half = _handoff_alignment(
            projected_dx=current_projection.projected_dx,
            t_fall=current_projection.t_fall,
            target_size=target_size,
            setup_cfg=self._setup_cfg,
        )
        setup_guidance = apply_transfer_setup_guidance(
            current_guidance,
            self._course_cfg,
            self._setup_cfg,
            vx=passive.vx,
            vy_up=passive.vy_up,
            active=self._active_sensors,
            x=passive.x,
            y=passive.y,
            target_size=target_size,
            clearance=self._ballistic_clearance(),
        )
        handoff_debug: dict[str, object] = {}
        if self._handoff_done:
            guidance = apply_drift_guidance(
                current_guidance,
                self._course_cfg,
                vx=passive.vx,
                vy_up=passive.vy_up,
                active=self._active_sensors,
                x=passive.x,
                y=passive.y,
                clearance=self._ballistic_clearance(),
            )
        elif not self._setup_phase_seen:
            self._setup_phase_seen = True
            guidance = setup_guidance
        elif should_handoff_to_drift(
            current_guidance,
            self._course_cfg,
            self._setup_cfg,
            vx=passive.vx,
            vy_up=passive.vy_up,
            active=self._active_sensors,
            x=passive.x,
            y=passive.y,
            target_size=target_size,
            clearance=self._ballistic_clearance(),
            debug=handoff_debug,
        ):
            self._handoff_done = True
            self._handoff_event_summary = (
                "handoff_evt "
                f"pdx:{self._fmt_debug_float(handoff_debug.get('projected_dx'))} "
                f"pix:{self._fmt_debug_float(handoff_debug.get('impact_x'))} "
                f"ptx:{self._fmt_debug_float(handoff_debug.get('target_x'))} "
                f"on:{int(bool(handoff_debug.get('on_track')))} "
                f"ctr:{int(bool(handoff_debug.get('centered')))} "
                f"in:{int(bool(handoff_debug.get('inside_target')))} "
                f"ns:{int(bool(handoff_debug.get('not_falling_short')))} "
                f"spd:{int(bool(handoff_debug.get('speed_ready')))}"
            )
            guidance = apply_drift_guidance(
                current_guidance,
                self._course_cfg,
                vx=passive.vx,
                vy_up=passive.vy_up,
                active=self._active_sensors,
                x=passive.x,
                y=passive.y,
                clearance=self._ballistic_clearance(),
            )
        else:
            guidance = setup_guidance
        self._debug_projection_summary = (
            f"proj pdx:{current_projection.projected_dx:6.1f} "
            f"pix:{self._fmt_debug_float(current_projection.impact_x)} "
            f"ptx:{self._fmt_debug_float(current_projection.target_x)} "
            f"on:{int(current_on_track)} "
            f"ctr:{int(current_centered)} "
            f"in:{int(current_inside_target)} "
            f"ct:{current_center_tol:4.1f} "
            f"th:{current_target_half:4.1f} "
            f"hf:{int(self._handoff_done)}"
        )
        if handoff_debug:
            self._debug_projection_summary += (
                f" hdx:{self._fmt_debug_float(handoff_debug.get('projected_dx'))}"
                f" hon:{int(bool(handoff_debug.get('on_track')))}"
                f" hns:{int(bool(handoff_debug.get('not_falling_short')))}"
                f" hct:{self._fmt_debug_float(handoff_debug.get('center_tolerance'))}"
                f" hth:{self._fmt_debug_float(handoff_debug.get('target_half'))}"
                f" hsp:{int(bool(handoff_debug.get('speed_ready')))}"
            )
        self._last_guidance = guidance
        return guidance

    def get_headless_stats(self) -> str:
        base = super().get_headless_stats()
        if not base:
            return ""
        parts = [base]
        if self._debug_projection_summary:
            parts.append(self._debug_projection_summary)
        if self._handoff_event_summary:
            parts.append(self._handoff_event_summary)
        return " ".join(parts)

    def _horizontal_controller(
        self,
        passive: PassiveSensors,
        vx_sp: float,
    ) -> float:
        guidance = self._last_guidance
        if (
            guidance is not None
            and guidance.phase == "transfer_setup_sideburn"
        ):
            vx_err = vx_sp - passive.vx
            ax_target = (1.1 * vx_err) - (0.04 * passive.ax)
            return clamp(
                ax_target,
                -self._setup_cfg.setup_sideburn_lateral_accel_cap,
                self._setup_cfg.setup_sideburn_lateral_accel_cap,
            )
        return super()._horizontal_controller(passive, vx_sp)

    def _allocate_controls(
        self,
        dt: float,
        passive: PassiveSensors,
        *,
        a_x_sp: float,
        a_up_sp: float,
        alt: float,
        dx: float,
        vertical_mode: str,
    ) -> BotAction:
        if vertical_mode != "transfer_sideburn":
            return super()._allocate_controls(
                dt,
                passive,
                a_x_sp=a_x_sp,
                a_up_sp=a_up_sp,
                alt=alt,
                dx=dx,
                vertical_mode=vertical_mode,
            )
        max_power, min_throttle, max_throttle, _ = self._engine_profile()
        mass = max(0.5, passive.mass)
        projection_now = _estimate_ballistic_projection(
            dx=float(dx),
            alt=max(0.0, float(alt)),
            vx=float(passive.vx),
            vy_up=float(passive.vy_up),
            x=float(passive.x),
            y=float(passive.y),
            active=self._active_sensors,
            clearance=self._ballistic_clearance(),
        )
        projected_dx_now = projection_now.projected_dx
        t_fall_now = projection_now.t_fall
        cone_limit_now = cone_dx_limit(max(0.0, float(alt)), self._course_cfg)
        _, centered_now, inside_target_now, _, _ = _handoff_alignment(
            projected_dx=projected_dx_now,
            t_fall=t_fall_now,
            target_size=self._last_target_size,
            setup_cfg=self._setup_cfg,
        )
        if inside_target_now and (not centered_now) and abs(a_x_sp) > 1e-3:
            desired_direction = 1.0 if a_x_sp > 0.0 else -1.0
        elif abs(projected_dx_now) > 1e-3:
            desired_direction = 1.0 if projected_dx_now > 0.0 else -1.0
        elif abs(dx) > 1e-3:
            desired_direction = 1.0 if dx > 0.0 else -1.0
        elif abs(a_x_sp) > 1e-3:
            desired_direction = 1.0 if a_x_sp > 0.0 else -1.0
        elif abs(passive.vx) > 1e-3:
            desired_direction = -1.0 if passive.vx > 0.0 else 1.0
        else:
            desired_direction = 1.0
        if self._setup_direction == 0.0:
            self._setup_direction = desired_direction
        elif desired_direction != self._setup_direction and (
            (inside_target_now and not centered_now)
            or abs(a_x_sp) > 0.35
            or abs(projected_dx_now) < 10.0
            or abs(projected_dx_now) > (1.25 * cone_limit_now)
            or abs(dx) < 10.0
        ):
            self._setup_direction = desired_direction

        target_angle = self._setup_direction * self._setup_cfg.setup_sideburn_angle_rad
        angle_cmd = rate_limit_angle_command(
            target_angle,
            self._prev_angle_cmd,
            dt,
            max_rate=3.2,
        )
        self._prev_angle_cmd = angle_cmd

        guidance_vx_sp = float(getattr(self._last_guidance, "vx_sp", 0.0))
        vx_err = guidance_vx_sp - float(passive.vx)
        along_track_err = self._setup_direction * vx_err
        along_track_ax = self._setup_direction * float(a_x_sp)
        ax_from_vx = min(
            self._setup_cfg.setup_sideburn_lateral_accel_cap,
            max(0.0, 0.9 * along_track_err),
        )
        ax_from_guidance = max(0.0, along_track_ax)
        ax_target = max(ax_from_guidance, ax_from_vx)
        along_track_miss = self._setup_direction * projected_dx_now
        miss_outside_cone = abs(projected_dx_now) > (
            self._setup_cfg.handoff_projected_dx_ratio * cone_limit_now
        )
        if miss_outside_cone and along_track_miss > 0.0:
            ax_from_miss = along_track_miss / max(0.5, t_fall_now * t_fall_now)
            ax_target = max(
                ax_target,
                clamp(
                    ax_from_miss,
                    self._setup_cfg.setup_sideburn_lateral_accel_floor,
                    self._setup_cfg.setup_sideburn_lateral_accel_cap,
                ),
            )
        elif miss_outside_cone:
            ax_target = max(ax_target, self._setup_cfg.setup_sideburn_lateral_accel_floor)
        if not inside_target_now and along_track_miss > 0.0:
            ax_target = max(ax_target, self._setup_cfg.setup_sideburn_lateral_accel_floor)
        boost_mode = (
            miss_outside_cone
            and abs(projected_dx_now)
            > (self._setup_cfg.setup_sideburn_boost_dx_cone_ratio * cone_limit_now)
            and along_track_err > self._setup_cfg.setup_sideburn_boost_vx_err_min
        )
        if boost_mode:
            return BotAction(
                target_thrust=clamp(
                    self._setup_cfg.setup_sideburn_boost_thrust,
                    min_throttle,
                    min(max_throttle, self._setup_cfg.setup_sideburn_max_thrust),
                ),
                target_angle=angle_cmd,
                refuel=False,
            )
        if miss_outside_cone or along_track_err > self._setup_cfg.setup_vx_deadband:
            ax_target = max(ax_target, self._setup_cfg.setup_sideburn_lateral_accel_floor)
        elif centered_now and inside_target_now:
            ax_target = min(ax_target, 0.6)
        ax_target = clamp(ax_target, 0.0, self._setup_cfg.setup_sideburn_lateral_accel_cap)
        if ax_target <= 0.12 and centered_now and inside_target_now:
            return BotAction(target_thrust=0.0, target_angle=angle_cmd, refuel=False)
        sin_term = max(0.2, abs(math.sin(angle_cmd)))
        thrust = (mass * ax_target) / max(max_power * sin_term, 1e-3)
        thrust = clamp(
            thrust,
            self._setup_cfg.setup_sideburn_min_thrust,
            min(max_throttle, self._setup_cfg.setup_sideburn_max_thrust),
        )
        if thrust > 0.0:
            thrust = max(min_throttle, thrust)
        return BotAction(target_thrust=thrust, target_angle=angle_cmd, refuel=False)


def create_bot() -> Bot:
    return TransferBot()


def list_behavior_names() -> tuple[str, ...]:
    return list_transfer_behavior_names()


__all__ = [
    "TransferBot",
    "TransferSetupConfig",
    "apply_transfer_setup_guidance",
    "create_bot",
    "list_behavior_names",
    "list_transfer_behavior_names",
    "resolve_transfer_behavior",
    "should_handoff_to_drift",
]
