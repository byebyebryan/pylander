"""Launch setup bot: hard side-burn setup, then hand off to coast."""

from __future__ import annotations

import math
from dataclasses import replace
from typing import Any

from bots._ballistics import estimate_ballistic_projection
from bots._bot_math import clamp, coerce_finite, rate_limit_angle_command, resolve_behavior
from bots._coast_tracking import (
    COAST_COURSE,
    COAST_POLICY,
    CoastCourseConfig,
    apply_coast_guidance,
    cone_dx_limit,
)
from bots._drop_guidance import DropPolicy, compute_drop_guidance
from bots._guidance_types import GuidanceTargets
from bots._launch_setup import (
    LaunchSetupConfig,
    ballistic_reference_vy,
    handoff_alignment,
    predict_response_state,
    predict_response_world_state,
    setup_fuel_reserve_threshold,
)
from bots._sideburn_control import resolve_sideburn_target_angle
from bots.coast import CoastBot
from core.bot import ActiveSensors, Bot, BotAction, PassiveSensors
from core.sensor import RadarContact

def should_handoff_to_coast(
    guidance: GuidanceTargets,
    course_cfg: CoastCourseConfig,
    setup_cfg: LaunchSetupConfig,
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
    current_projection = estimate_ballistic_projection(
        dx=float(guidance.dx),
        alt=alt,
        vx=safe_vx,
        vy_up=safe_vy_up,
        x=x,
        y=y,
        active=active,
        clearance=clearance,
    )
    dx_pred, alt_pred, vx_pred, vy_pred = predict_response_state(
        dx=float(guidance.dx),
        alt=alt,
        vx=safe_vx,
        vy_up=safe_vy_up,
        delay_s=setup_cfg.setup_response_delay_s,
    )
    x_pred, y_pred = predict_response_world_state(
        x=x,
        y=y,
        vx=safe_vx,
        vy_up=safe_vy_up,
        delay_s=setup_cfg.setup_response_delay_s,
    )
    planned_vy_up = ballistic_reference_vy(guidance, setup_cfg, vy_pred)
    projection = estimate_ballistic_projection(
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
    on_track, centered, inside_target, center_tol, target_half = handoff_alignment(
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
    ) = handoff_alignment(
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
    return track_ready and speed_ready and not_falling_short


def apply_launch_setup_guidance(
    guidance: GuidanceTargets,
    course_cfg: CoastCourseConfig,
    setup_cfg: LaunchSetupConfig,
    *,
    vx: float | None,
    vy_up: float | None,
    active: ActiveSensors | None = None,
    x: float | None = None,
    y: float | None = None,
    target_size: float | None = None,
    clearance: float = 0.0,
) -> GuidanceTargets:
    _ = course_cfg
    alt = max(0.0, float(guidance.alt))
    safe_vx = float(vx) if vx is not None and math.isfinite(vx) else 0.0
    safe_vy_up = float(vy_up) if vy_up is not None and math.isfinite(vy_up) else 0.0
    dx_pred, alt_pred, vx_pred, vy_pred = predict_response_state(
        dx=float(guidance.dx),
        alt=alt,
        vx=safe_vx,
        vy_up=safe_vy_up,
        delay_s=setup_cfg.setup_response_delay_s,
    )
    x_pred, y_pred = predict_response_world_state(
        x=x,
        y=y,
        vx=safe_vx,
        vy_up=safe_vy_up,
        delay_s=setup_cfg.setup_response_delay_s,
    )
    planned_vy_up = ballistic_reference_vy(guidance, setup_cfg, vy_pred)
    projection = estimate_ballistic_projection(
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
    _, centered, inside_target, _, _ = handoff_alignment(
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
        phase="launch_setup_sideburn",
        vertical_mode="launch_sideburn",
        vx_sp=vx_sp,
        vy_sp=max(float(guidance.vy_sp), setup_cfg.setup_descent_vy_target),
    )


LAUNCH_POLICY = replace(
    COAST_POLICY,
    status_prefix="launch",
    use_projected_lateral_error=True,
)
LAUNCH_COURSE = replace(
    COAST_COURSE,
    # Launch handoff often carries high lateral speed; start braking earlier.
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
_LAUNCH_BEHAVIORS: dict[str, tuple[DropPolicy, CoastCourseConfig, LaunchSetupConfig]] = {
    "launch": (LAUNCH_POLICY, LAUNCH_COURSE, LaunchSetupConfig()),
}


def resolve_launch_behavior(
    behavior: str,
) -> tuple[str, DropPolicy, CoastCourseConfig, LaunchSetupConfig]:
    key, value = resolve_behavior(
        behavior,
        _LAUNCH_BEHAVIORS,
        context="launch",
    )
    policy, course_cfg, setup_cfg = value
    return key, policy, course_cfg, setup_cfg


def list_launch_behavior_names() -> tuple[str, ...]:
    return tuple(sorted(_LAUNCH_BEHAVIORS))


class LaunchBot(CoastBot):
    def __init__(self, behavior: str = "launch") -> None:
        super().__init__(behavior=behavior)
        self._setup_phase_seen = False
        self._setup_handoff_done = False
        self._setup_burn_active = False
        self._setup_burn_complete = False
        self._setup_burn_frames = 0
        self._setup_direction = 0.0
        self._active_sensors: ActiveSensors | None = None
        self._debug_projection_summary = ""
        self._handoff_event_summary = ""
        self._last_target_size: float | None = None
        self._handoff_snapshot: dict[str, Any] | None = None

    def set_behavior(self, behavior: str) -> None:
        key, policy, cfg, setup_cfg = resolve_launch_behavior(behavior)
        self._policy = policy
        self._course_cfg = cfg
        self._setup_cfg = setup_cfg
        self._behavior = key
        self._setup_phase_seen = False
        self._setup_handoff_done = False
        self._setup_burn_active = False
        self._setup_burn_complete = False
        self._setup_burn_frames = 0
        self._setup_direction = 0.0
        self._active_sensors = None
        self._ballistic_debug_summary = ""
        self._debug_projection_summary = ""
        self._handoff_event_summary = ""
        self._last_target_size = None
        self._handoff_snapshot = None

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
            self._setup_handoff_done = False
            self._setup_burn_active = False
            self._setup_burn_complete = False
            self._setup_burn_frames = 0
            self._setup_direction = 0.0
            self._ballistic_debug_summary = ""
            self._debug_projection_summary = ""
            self._handoff_event_summary = ""
            self._last_target_size = None
            self._handoff_snapshot = None
        self._active_sensors = active
        try:
            action = super().update(dt, passive, active)
            if passive.state == "flying" and self._setup_handoff_done:
                handoff_context: dict[str, Any] = {
                    "pinned_target_uid": self.pinned_target_uid,
                }
                snapshot = self.get_evaluation_snapshot()
                if isinstance(snapshot, dict) and bool(snapshot.get("handoff_done")):
                    handoff_context["evaluation_snapshot"] = dict(snapshot)
                action.handoff_to = CoastBot()
                action.handoff_context = handoff_context
                action.active_bot = "coast"
                action.stage = "handoff"
                if not action.status:
                    action.status = "launch:handoff_coast"
                self.status = action.status
            return action
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

    @staticmethod
    def _snapshot_float(value: object) -> float | None:
        if not isinstance(value, (int, float)):
            return None
        numeric = float(value)
        if not math.isfinite(numeric):
            return None
        return numeric

    def _build_handoff_snapshot(
        self,
        handoff_debug: dict[str, object],
        passive: PassiveSensors,
    ) -> dict[str, Any]:
        impact_x = self._snapshot_float(handoff_debug.get("impact_x"))
        target_x = self._snapshot_float(handoff_debug.get("target_x"))
        impact_error = None
        if impact_x is not None and target_x is not None:
            impact_error = abs(impact_x - target_x)
        current_impact_x = self._snapshot_float(handoff_debug.get("current_impact_x"))
        current_target_x = self._snapshot_float(handoff_debug.get("current_target_x"))
        current_impact_error = None
        if current_impact_x is not None and current_target_x is not None:
            current_impact_error = abs(current_impact_x - current_target_x)
        handoff_x = float(passive.x)
        handoff_y = float(passive.y)
        handoff_vx = float(passive.vx)
        handoff_vy_up = float(passive.vy_up)
        handoff_dx = None
        if target_x is not None:
            handoff_dx = target_x - handoff_x
        return {
            "kind": "launch",
            "handoff_done": True,
            "projected_dx": self._snapshot_float(handoff_debug.get("projected_dx")),
            "impact_x": impact_x,
            "target_x": target_x,
            "impact_error": impact_error,
            "current_impact_x": current_impact_x,
            "current_target_x": current_target_x,
            "current_impact_error": current_impact_error,
            "on_track": bool(handoff_debug.get("on_track")),
            "centered": bool(handoff_debug.get("centered")),
            "inside_target": bool(handoff_debug.get("inside_target")),
            "not_falling_short": bool(handoff_debug.get("not_falling_short")),
            "speed_ready": bool(handoff_debug.get("speed_ready")),
            "angle_rad": float(passive.angle),
            "altitude": float(passive.altitude),
            "x": handoff_x,
            "y": handoff_y,
            "dx": handoff_dx,
            "vx": handoff_vx,
            "vy_up": handoff_vy_up,
            "speed": math.hypot(handoff_vx, handoff_vy_up),
            "horizontal_speed": abs(handoff_vx),
        }

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
        base_guidance, _ = compute_drop_guidance(
            self._policy,
            passive,
            target,
            max_force=max_force,
            max_throttle=max_throttle,
            ramp_up=ramp_up,
            active=active,
            terminal_brake_altitude_fn=self._terminal_brake_altitude,
        )
        current_guidance = replace(
            base_guidance,
            dx=float(target.x) - float(passive.x),
            alt=float(passive.altitude),
        )
        current_projection = estimate_ballistic_projection(
            dx=current_guidance.dx,
            alt=current_guidance.alt,
            vx=passive.vx,
            vy_up=passive.vy_up,
            x=passive.x,
            y=passive.y,
            active=self._active_sensors,
            clearance=self._ballistic_clearance(),
        )
        target_size = coerce_finite(getattr(target, "size", None), float("nan"))
        if not math.isfinite(target_size):
            target_size = None
        self._last_target_size = target_size
        current_on_track, current_centered, current_inside_target, current_center_tol, current_target_half = handoff_alignment(
            projected_dx=current_projection.projected_dx,
            t_fall=current_projection.t_fall,
            target_size=target_size,
            setup_cfg=self._setup_cfg,
        )
        setup_guidance = apply_launch_setup_guidance(
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
        handoff_gate = should_handoff_to_coast(
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
        )
        cone_limit = cone_dx_limit(max(0.0, float(passive.altitude)), self._course_cfg)
        burn_end_dx = max(
            self._setup_cfg.setup_burn_end_cone_ratio * cone_limit,
            current_target_half + self._setup_cfg.setup_burn_end_target_margin,
        )
        burn_speed_ready = abs(float(setup_guidance.vx_sp) - float(passive.vx)) <= max(
            2.5,
            float(self._setup_cfg.setup_vx_deadband),
        )
        burn_done = (
            abs(current_projection.projected_dx) <= burn_end_dx and burn_speed_ready
        )
        safety_guard = current_projection.t_fall <= self._setup_cfg.setup_burn_safety_t_fall_s
        handoff_debug.update(
            {
                "burn_done": burn_done,
                "burn_speed_ready": burn_speed_ready,
                "burn_end_dx": burn_end_dx,
                "safety_guard": safety_guard,
                "setup_burn_active": self._setup_burn_active,
                "setup_burn_complete": self._setup_burn_complete,
                "setup_burn_frames": self._setup_burn_frames,
            }
        )
        if self._setup_handoff_done:
            guidance = apply_coast_guidance(
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
            if not self._setup_phase_seen:
                self._setup_phase_seen = True
                self._setup_burn_active = True
                self._setup_burn_complete = False
                self._setup_burn_frames = 0
            if self._setup_burn_active:
                self._setup_burn_frames += 1
                min_frames = max(1, int(self._setup_cfg.setup_burn_min_frames))
                can_end_setup_burn = (
                    self._setup_burn_frames >= min_frames
                    and (burn_done or handoff_gate)
                )
                if can_end_setup_burn:
                    self._setup_burn_active = False
                    self._setup_burn_complete = True
                else:
                    guidance = setup_guidance
            if not self._setup_burn_active:
                handoff_reason = None
                if self._setup_burn_complete:
                    handoff_reason = "burn_complete"
                elif handoff_gate:
                    handoff_reason = "gate"
                if handoff_reason is not None:
                    self._setup_handoff_done = True
                    handoff_debug["handoff_reason"] = handoff_reason
                    self._handoff_snapshot = self._build_handoff_snapshot(
                        handoff_debug,
                        passive,
                    )
                    self._handoff_event_summary = (
                        "handoff_evt "
                        f"reason:{handoff_reason} "
                        f"pdx:{self._fmt_debug_float(handoff_debug.get('projected_dx'))} "
                        f"pix:{self._fmt_debug_float(handoff_debug.get('impact_x'))} "
                        f"ptx:{self._fmt_debug_float(handoff_debug.get('target_x'))} "
                        f"on:{int(bool(handoff_debug.get('on_track')))} "
                        f"ctr:{int(bool(handoff_debug.get('centered')))} "
                        f"in:{int(bool(handoff_debug.get('inside_target')))} "
                        f"ns:{int(bool(handoff_debug.get('not_falling_short')))} "
                        f"spd:{int(bool(handoff_debug.get('speed_ready')))}"
                    )
                    guidance = apply_coast_guidance(
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
            f"bf:{self._setup_burn_frames:02d} "
            f"ba:{int(self._setup_burn_active)} "
            f"bc:{int(self._setup_burn_complete)} "
            f"hf:{int(self._setup_handoff_done)}"
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

    def get_evaluation_snapshot(self) -> dict[str, Any] | None:
        if self._handoff_snapshot is None:
            return {"kind": "launch", "handoff_done": bool(self._setup_handoff_done)}
        return dict(self._handoff_snapshot)

    def _coast_burn_command(self, *, guidance: GuidanceTargets, **kwargs):
        # Keep coast burn state dormant during launch-sideburn setup.
        if not self._setup_handoff_done:
            self._coast_burn_plan = None
            self._coast_burn_active = False
            self._coast_burn_done = False
            self._coast_burn_elapsed_s = 0.0
            self._coast_burn_state_summary = "idle"
            return None
        return super()._coast_burn_command(guidance=guidance, **kwargs)

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
            and guidance.phase == "launch_setup_sideburn"
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
        max_power: float | None = None,
        min_throttle: float | None = None,
        max_throttle: float | None = None,
        angle_override: float | None = None,
        thrust_override: float | None = None,
    ) -> BotAction:
        if vertical_mode != "launch_sideburn":
            return super()._allocate_controls(
                dt,
                passive,
                a_x_sp=a_x_sp,
                a_up_sp=a_up_sp,
                alt=alt,
                dx=dx,
                vertical_mode=vertical_mode,
                max_power=max_power if max_power is not None else self._engine_profile()[0],
                min_throttle=min_throttle if min_throttle is not None else self._engine_profile()[1],
                max_throttle=max_throttle if max_throttle is not None else self._engine_profile()[2],
                angle_override=angle_override,
                thrust_override=thrust_override,
            )
        if max_power is None or min_throttle is None or max_throttle is None:
            max_power, min_throttle, max_throttle, _ = self._engine_profile()
        mass = max(0.5, passive.mass)
        projection_now = estimate_ballistic_projection(
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
        _, centered_now, inside_target_now, _, _ = handoff_alignment(
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

        target_angle = self._setup_direction * resolve_sideburn_target_angle(
            projected_dx=projected_dx_now,
            cone_limit=cone_limit_now,
            vy_up=float(passive.vy_up),
            base_angle=self._setup_cfg.setup_sideburn_angle_rad,
            min_angle=self._setup_cfg.setup_sideburn_angle_min_rad,
            max_angle=self._setup_cfg.setup_sideburn_angle_max_rad,
            upward_vy_target=self._setup_cfg.setup_sideburn_upward_vy_target,
            upward_angle_gain=self._setup_cfg.setup_sideburn_upward_angle_gain,
        )
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
        reserve_fuel = setup_fuel_reserve_threshold(
            self._setup_cfg,
            max_fuel=float(passive.max_fuel),
        )
        fuel_guard_active = float(passive.fuel) <= reserve_fuel
        if boost_mode and not fuel_guard_active:
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
        if fuel_guard_active and centered_now and inside_target_now and abs(projected_dx_now) <= cone_limit_now:
            ax_target = 0.0
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
        if fuel_guard_active and thrust > 0.0:
            thrust = min(thrust, max(min_throttle, self._setup_cfg.setup_sideburn_min_thrust))
        return BotAction(target_thrust=thrust, target_angle=angle_cmd, refuel=False)


def create_bot() -> Bot:
    return LaunchBot()


def list_behavior_names() -> tuple[str, ...]:
    return ("launch",)


__all__ = [
    "LaunchBot",
    "LaunchSetupConfig",
    "apply_launch_setup_guidance",
    "create_bot",
    "list_behavior_names",
    "list_launch_behavior_names",
    "resolve_launch_behavior",
    "should_handoff_to_coast",
]
