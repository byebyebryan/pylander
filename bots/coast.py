"""Coast phase bot: efficient path correction before flare takeover."""

from __future__ import annotations

import math
from dataclasses import dataclass, replace

from bots._ballistics import ballistic_time_to_impact, estimate_ballistic_projection
from bots._bot_math import (
    clamp,
    coerce_finite,
    engine_profile,
    finite_altitude,
    rate_limit_angle_command,
    stable,
    vehicle_limits,
)
from bots._coast_tracking import (
    COAST_POLICY,
    CoastCourseConfig,
    apply_coast_guidance,
    cone_dx_limit,
    coupled_brake_window,
    lateral_tracking_command,
    resolve_coast_behavior,
)
from bots._drop_guidance import compute_drop_guidance
from bots._guidance_limits import cap_low_altitude_angle
from bots._guidance_types import GuidanceTargets
from bots._targeting import pick_target
from bots._terminal_burn import (
    TerminalBurnModel,
    compute_terminal_burn_estimate,
    is_terminal_burn_imminent,
)
from bots.flare import FlareBot
from core.bot import ActiveSensors, Bot, BotAction, PassiveSensors, VehicleInfo
from core.sensor import RadarContact


@dataclass(frozen=True)
class CoastHandoffConfig:
    altitude_max: float = 240.0
    cone_scale: float = 0.45
    center_tolerance: float = 7.0
    target_edge_margin: float = 8.0
    vx_err_cap: float = 5.5
    descending_vy_max: float = 2.0
    require_burn_imminent: bool = True
    burn_altitude_margin: float = 120.0
    burn_time_margin: float = 1.5
    t_fall_max: float = 9.5
    consecutive_pass_frames: int = 3
    burn_enter_time_margin: float = 0.65
    burn_activation_down_speed_min: float = 0.6
    retrograde_align_speed_min: float = 2.0
    retrograde_align_max_error_deg: float = 30.0
    retrograde_align_altitude_margin: float = 180.0


_BURN_MODEL = TerminalBurnModel()


def _angle_diff(a: float, b: float) -> float:
    return (b - a + math.pi) % (2.0 * math.pi) - math.pi


def _retrograde_angle(vx: float, vy_up: float) -> float:
    return math.atan2(-float(vx), -float(vy_up))


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


def _cfg_attr(cfg: CoastCourseConfig, key: str, default: float) -> float:
    value = getattr(cfg, key, default)
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return float(default)
    if not math.isfinite(numeric):
        return float(default)
    return numeric


def _cfg_bool_attr(cfg: CoastCourseConfig, key: str, default: bool) -> bool:
    value = getattr(cfg, key, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        text = value.strip().lower()
        if text in {"1", "true", "yes", "on"}:
            return True
        if text in {"0", "false", "no", "off"}:
            return False
        return bool(default)
    if isinstance(value, (int, float)):
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return bool(default)
        if not math.isfinite(numeric):
            return bool(default)
        return bool(numeric)
    return bool(default)


def _resolve_handoff_cfg(cfg: CoastCourseConfig) -> CoastHandoffConfig:
    defaults = CoastHandoffConfig()
    return CoastHandoffConfig(
        altitude_max=_cfg_attr(cfg, "flare_handoff_altitude_max", defaults.altitude_max),
        cone_scale=_cfg_attr(cfg, "flare_handoff_cone_scale", defaults.cone_scale),
        center_tolerance=_cfg_attr(
            cfg,
            "flare_handoff_center_tolerance",
            defaults.center_tolerance,
        ),
        target_edge_margin=_cfg_attr(
            cfg,
            "flare_handoff_target_edge_margin",
            defaults.target_edge_margin,
        ),
        vx_err_cap=_cfg_attr(cfg, "flare_handoff_vx_err_cap", defaults.vx_err_cap),
        descending_vy_max=_cfg_attr(
            cfg,
            "flare_handoff_descending_vy_max",
            defaults.descending_vy_max,
        ),
        require_burn_imminent=_cfg_bool_attr(
            cfg,
            "flare_handoff_require_burn_imminent",
            defaults.require_burn_imminent,
        ),
        burn_altitude_margin=_cfg_attr(
            cfg,
            "flare_handoff_burn_altitude_margin",
            defaults.burn_altitude_margin,
        ),
        burn_time_margin=_cfg_attr(
            cfg,
            "flare_handoff_burn_time_margin",
            defaults.burn_time_margin,
        ),
        t_fall_max=_cfg_attr(cfg, "flare_handoff_t_fall_max", defaults.t_fall_max),
        consecutive_pass_frames=max(
            1,
            int(
                _cfg_attr(
                    cfg,
                    "flare_handoff_consecutive_pass_frames",
                    float(defaults.consecutive_pass_frames),
                )
            ),
        ),
        burn_enter_time_margin=_cfg_attr(
            cfg,
            "flare_handoff_burn_enter_time_margin",
            defaults.burn_enter_time_margin,
        ),
        burn_activation_down_speed_min=_cfg_attr(
            cfg,
            "flare_handoff_burn_activation_down_speed_min",
            defaults.burn_activation_down_speed_min,
        ),
        retrograde_align_speed_min=_cfg_attr(
            cfg,
            "flare_handoff_retrograde_speed_min",
            defaults.retrograde_align_speed_min,
        ),
        retrograde_align_max_error_deg=_cfg_attr(
            cfg,
            "flare_handoff_retrograde_max_error_deg",
            defaults.retrograde_align_max_error_deg,
        ),
        retrograde_align_altitude_margin=_cfg_attr(
            cfg,
            "flare_handoff_retrograde_align_altitude_margin",
            defaults.retrograde_align_altitude_margin,
        ),
    )


def should_handoff_to_flare(
    guidance: GuidanceTargets,
    cfg: CoastCourseConfig,
    *,
    passive: PassiveSensors | None = None,
    max_force: float | None = None,
    max_throttle: float | None = None,
    ramp_up: float | None = None,
    vx: float | None = None,
    vy_up: float | None = None,
    angle_rad: float | None = None,
    active: ActiveSensors | None = None,
    x: float | None = None,
    y: float | None = None,
    target_size: float | None = None,
    clearance: float = 0.0,
    consecutive_passes: int = 0,
    required_passes: int | None = None,
    debug: dict[str, object] | None = None,
) -> bool:
    handoff_cfg = _resolve_handoff_cfg(cfg)
    alt = max(0.0, float(guidance.alt))
    safe_vx = float(vx) if vx is not None and math.isfinite(vx) else 0.0
    safe_vy_up = float(vy_up) if vy_up is not None and math.isfinite(vy_up) else 0.0
    projection = estimate_ballistic_projection(
        dx=guidance.dx,
        alt=alt,
        vx=safe_vx,
        vy_up=safe_vy_up,
        x=x,
        y=y,
        active=active,
        clearance=clearance,
    )
    projected_dx = projection.projected_dx
    cone_limit = cone_dx_limit(alt, cfg)
    handoff_cone = max(4.0, handoff_cfg.cone_scale * cone_limit)
    target_half = _target_half_width(target_size)
    center_tol = min(
        max(0.5, target_half - handoff_cfg.target_edge_margin),
        max(0.5, handoff_cfg.center_tolerance),
    )
    inside_target = abs(projected_dx) <= target_half
    centered = abs(projected_dx) <= max(handoff_cone, center_tol)
    emergency_inside = abs(projected_dx) <= max(3.0 * target_half, 3.0 * center_tol)
    vx_needed = safe_vx + (projected_dx / max(0.5, projection.t_fall))
    vx_err = abs(vx_needed - safe_vx)
    speed_ready = vx_err <= handoff_cfg.vx_err_cap
    descending = safe_vy_up <= handoff_cfg.descending_vy_max
    alt_ready = alt <= handoff_cfg.altitude_max
    t_fall_ready = projection.t_fall <= handoff_cfg.t_fall_max
    retrograde_target_angle = _retrograde_angle(safe_vx, safe_vy_up)
    retrograde_angle_error_deg = None
    speed_mag = math.hypot(safe_vx, safe_vy_up)
    if speed_mag <= handoff_cfg.retrograde_align_speed_min:
        retrograde_ready = True
    else:
        if angle_rad is None:
            retrograde_ready = False
        else:
            try:
                craft_angle = float(angle_rad)
            except (TypeError, ValueError):
                retrograde_ready = False
            else:
                if not math.isfinite(craft_angle):
                    retrograde_ready = False
                else:
                    angle_error = abs(_angle_diff(craft_angle, retrograde_target_angle))
                    retrograde_angle_error_deg = math.degrees(angle_error)
                    retrograde_ready = (
                        angle_error <= math.radians(handoff_cfg.retrograde_align_max_error_deg)
                    )

    burn_ready = True
    burn_altitude = None
    time_to_brake = None
    time_to_impact = None
    if (
        handoff_cfg.require_burn_imminent
        and passive is not None
        and max_force is not None
        and max_throttle is not None
        and ramp_up is not None
    ):
        _, up_acc_max = vehicle_limits(passive, float(max_force))
        time_to_impact, _ = ballistic_time_to_impact(passive, active)
        burn = compute_terminal_burn_estimate(
            alt=alt,
            track_dx=projected_dx,
            vy_up=float(passive.vy_up),
            thrust_level=float(passive.thrust_level),
            up_acc_max=up_acc_max,
            max_throttle=float(max_throttle),
            ramp_up=float(ramp_up),
            time_to_impact=float(time_to_impact),
            burn_enter_time_margin=handoff_cfg.burn_enter_time_margin,
            model=_BURN_MODEL,
        )
        burn_altitude = float(burn.burn_altitude)
        time_to_brake = float(burn.time_to_brake)
        burn_ready = is_terminal_burn_imminent(
            alt=alt,
            burn_altitude=burn_altitude,
            burn_activation_down_speed_min=handoff_cfg.burn_activation_down_speed_min,
            estimate=burn,
            time_to_impact=float(time_to_impact),
            altitude_margin=handoff_cfg.burn_altitude_margin,
            time_margin=handoff_cfg.burn_time_margin,
        )

    raw_ready = (
        centered
        and inside_target
        and speed_ready
        and descending
        and alt_ready
        and t_fall_ready
        and retrograde_ready
        and burn_ready
    )
    emergency_ready = (
        emergency_inside
        and descending
        and alt_ready
        and t_fall_ready
        and retrograde_ready
        and burn_ready
    )
    raw_ready = raw_ready or emergency_ready
    required = (
        handoff_cfg.consecutive_pass_frames
        if required_passes is None
        else max(1, int(required_passes))
    )
    pass_count = max(0, int(consecutive_passes))
    pass_count_after_sample = (pass_count + 1) if raw_ready else 0
    handoff_ready = raw_ready and (pass_count_after_sample >= required)
    if debug is not None:
        debug.update(
            {
                "projected_dx": projected_dx,
                "impact_x": projection.impact_x,
                "target_x": projection.target_x,
                "sensor_used": projection.used_sensor,
                "centered": centered,
                "inside_target": inside_target,
                "emergency_inside": emergency_inside,
                "emergency_ready": emergency_ready,
                "speed_ready": speed_ready,
                "descending": descending,
                "alt_ready": alt_ready,
                "t_fall": projection.t_fall,
                "t_fall_ready": t_fall_ready,
                "retrograde_ready": retrograde_ready,
                "retrograde_target_angle": retrograde_target_angle,
                "retrograde_angle_error_deg": retrograde_angle_error_deg,
                "burn_ready": burn_ready,
                "burn_altitude": burn_altitude,
                "time_to_brake": time_to_brake,
                "time_to_impact": time_to_impact,
                "vx_needed": vx_needed,
                "vx_err": vx_err,
                "handoff_cone": handoff_cone,
                "target_half": target_half,
                "raw_ready": raw_ready,
                "consecutive_passes": pass_count,
                "pass_count_after_sample": pass_count_after_sample,
                "required_passes": required,
            }
        )
    return handoff_ready


class CoastBot(Bot):
    def __init__(self, behavior: str = "coast") -> None:
        super().__init__()
        self._policy = COAST_POLICY
        self._course_cfg = CoastCourseConfig()
        self._handoff_cfg = _resolve_handoff_cfg(self._course_cfg)
        self._behavior = "coast"
        self._prev_angle_cmd = 0.0
        self._ballistic_debug_summary = ""
        self._last_guidance: GuidanceTargets | None = None
        self._active_sensors: ActiveSensors | None = None
        self._handoff_done = False
        self._handoff_pass_frames = 0
        self._handoff_snapshot: dict[str, float | bool | str | None] | None = None
        self._handoff_event_summary = ""
        self._last_target_size: float | None = None
        self._flare_delegate = FlareBot()
        self._coast_primary_impulse_frames = 52
        self._coast_cleanup_impulse_frames = 40
        self._coast_impulse_cooldown_frames = 60
        self._coast_primary_trigger_dx = 20.0
        self._coast_cleanup_trigger_dx = 100.0
        self._coast_impulse_abort_altitude = 115.0
        self._coast_impulse_descending_vy_max = -0.8
        self._coast_impulse_frames_remaining = 0
        self._coast_impulse_cooldown_remaining = 0
        self._coast_primary_impulse_used = False
        self._coast_cleanup_impulse_used = False
        self.set_behavior(behavior)

    def set_vehicle_info(self, info: VehicleInfo):
        super().set_vehicle_info(info)
        self._flare_delegate.set_vehicle_info(info)

    def set_behavior(self, behavior: str) -> None:
        key = str(behavior).strip().lower()
        if key != "coast":
            raise ValueError(f"Unknown coast behavior '{behavior}'. Expected one of: coast")
        _, policy, cfg = resolve_coast_behavior("coast")
        self._policy = policy
        self._course_cfg = cfg
        self._handoff_cfg = _resolve_handoff_cfg(cfg)
        self._behavior = "coast"
        self._ballistic_debug_summary = ""
        self._handoff_done = False
        self._handoff_pass_frames = 0
        self._handoff_snapshot = None
        self._handoff_event_summary = ""
        self._last_target_size = None
        self._flare_delegate.set_behavior("flare")
        self._coast_impulse_frames_remaining = 0
        self._coast_impulse_cooldown_remaining = 0
        self._coast_primary_impulse_used = False
        self._coast_cleanup_impulse_used = False

    @property
    def behavior(self) -> str:
        return self._behavior

    def _reset_runtime_state(self) -> None:
        self._handoff_done = False
        self._handoff_pass_frames = 0
        self._handoff_snapshot = None
        self._handoff_event_summary = ""
        self._last_target_size = None
        self._last_guidance = None
        self._ballistic_debug_summary = ""
        self._flare_delegate.set_behavior("flare")
        self._coast_impulse_frames_remaining = 0
        self._coast_impulse_cooldown_remaining = 0
        self._coast_primary_impulse_used = False
        self._coast_cleanup_impulse_used = False
        if self.vehicle_info is not None:
            self._flare_delegate.set_vehicle_info(self.vehicle_info)

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
            self._reset_runtime_state()
        self._active_sensors = active
        try:
            if passive.state in ("landed", "crashed", "out_of_fuel"):
                action = BotAction(
                    0.0,
                    passive.angle,
                    False,
                    status=f"{self._policy.status_prefix}:{passive.state}",
                )
                self.status = action.status
                return action

            max_power, min_throttle, max_throttle, ramp_up = self._engine_profile()
            max_force = max_power * max_throttle
            _, up_acc_max = vehicle_limits(passive, max_force)

            target = pick_target(passive)
            if target is None:
                t_impact, impact_source = ballistic_time_to_impact(passive, active)
                self._ballistic_debug_summary = (
                    f"ball tti:{stable(t_impact, 1):4.1f} "
                    f"src:{'s' if impact_source == 'sensor' else 'a'} "
                    "burn:0"
                )
                alt = finite_altitude(passive)
                a_up_sp = self._vertical_controller(
                    passive,
                    vy_sp=-1.0,
                    alt=alt,
                    vertical_mode="flare",
                    up_acc_max=up_acc_max,
                )
                action = self._allocate_controls(
                    dt,
                    passive,
                    a_x_sp=0.0,
                    a_up_sp=a_up_sp,
                    dx=0.0,
                    alt=alt,
                    vertical_mode="flare",
                    max_power=max_power,
                    min_throttle=min_throttle,
                    max_throttle=max_throttle,
                )
                action.status = f"{self._policy.status_prefix}:search"
                self.status = action.status
                return action

            guidance = self._guidance(
                passive,
                target,
                max_force=max_force,
                max_throttle=max_throttle,
                ramp_up=ramp_up,
                active=active,
            )
            if self._behavior == "coast" and self._handoff_done:
                flare_action = self._flare_delegate.update(dt, passive, active)
                self.status = flare_action.status
                return flare_action

            if guidance.vertical_mode in ("coast", "coast_hold") and abs(guidance.dx) <= self._policy.coast_horiz_deadband:
                deadband = max(1e-3, self._policy.coast_horiz_deadband)
                deadband_ratio = max(0.0, min(1.0, abs(guidance.dx) / deadband))
                softened_vx_sp = guidance.vx_sp * deadband_ratio
                a_x_sp = self._horizontal_controller(passive, softened_vx_sp)
            else:
                a_x_sp = self._horizontal_controller(passive, guidance.vx_sp)
            a_up_sp = self._vertical_controller(
                passive,
                guidance.vy_sp,
                guidance.alt,
                guidance.vertical_mode,
                up_acc_max,
            )
            action = self._allocate_controls(
                dt,
                passive,
                a_x_sp=a_x_sp,
                a_up_sp=a_up_sp,
                dx=guidance.dx,
                alt=guidance.alt,
                vertical_mode=guidance.vertical_mode,
                max_power=max_power,
                min_throttle=min_throttle,
                max_throttle=max_throttle,
            )
            action.status = (
                f"{self._policy.status_prefix}:{guidance.phase} dx:{stable(guidance.dx, 1):6.1f} "
                f"vx:{stable(passive.vx, 1):5.1f} vy:{stable(passive.vy_up, 1):5.1f} "
                f"vys:{stable(guidance.vy_sp, 1):5.1f} "
                f"balt:{stable(guidance.burn_altitude, 1):5.1f}"
            )
            self.status = action.status
            return action
        finally:
            self._active_sensors = None

    def _engine_profile(self) -> tuple[float, float, float, float]:
        return engine_profile(self.vehicle_info)

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
    ) -> dict[str, float | bool | str | None]:
        impact_x = self._snapshot_float(handoff_debug.get("impact_x"))
        target_x = self._snapshot_float(handoff_debug.get("target_x"))
        projected_dx = self._snapshot_float(handoff_debug.get("projected_dx"))
        handoff_x = float(passive.x)
        handoff_y = float(passive.y)
        handoff_vx = float(passive.vx)
        handoff_vy_up = float(passive.vy_up)
        handoff_dx = None
        if target_x is not None:
            handoff_dx = target_x - handoff_x
        return {
            "kind": "coast",
            "handoff_done": True,
            "projected_dx": projected_dx,
            "impact_x": impact_x,
            "target_x": target_x,
            "x": handoff_x,
            "y": handoff_y,
            "dx": handoff_dx,
            "vx": handoff_vx,
            "vy_up": handoff_vy_up,
            "speed": math.hypot(handoff_vx, handoff_vy_up),
            "horizontal_speed": abs(handoff_vx),
            "altitude": float(passive.altitude),
            "angle_rad": float(passive.angle),
            "on_track": bool(handoff_debug.get("centered")),
            "inside_target": bool(handoff_debug.get("inside_target")),
            "speed_ready": bool(handoff_debug.get("speed_ready")),
            "descending": bool(handoff_debug.get("descending")),
            "t_fall_ready": bool(handoff_debug.get("t_fall_ready")),
            "sensor_used": bool(handoff_debug.get("sensor_used")),
            "vx_err": self._snapshot_float(handoff_debug.get("vx_err")),
            "t_fall": self._snapshot_float(handoff_debug.get("t_fall")),
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
        coast_debug: dict[str, object] = {}
        guidance = apply_coast_guidance(
            base_guidance,
            self._course_cfg,
            vx=passive.vx,
            vy_up=passive.vy_up,
            active=self._active_sensors,
            x=passive.x,
            y=passive.y,
            clearance=self._ballistic_clearance(),
            debug=coast_debug,
        )
        guidance = self._shape_coast_impulse(
            guidance,
            projected_dx=coast_debug.get("projected_dx"),
            vy_up=passive.vy_up,
        )
        target_size = coerce_finite(getattr(target, "size", None), float("nan"))
        if not math.isfinite(target_size):
            target_size = None
        self._last_target_size = target_size

        handoff_debug: dict[str, object] = {}
        if not self._handoff_done and should_handoff_to_flare(
            guidance,
            self._course_cfg,
            passive=passive,
            max_force=max_force,
            max_throttle=max_throttle,
            ramp_up=ramp_up,
            vx=passive.vx,
            vy_up=passive.vy_up,
            angle_rad=passive.angle,
            active=self._active_sensors,
            x=passive.x,
            y=passive.y,
            target_size=target_size,
            clearance=self._ballistic_clearance(),
            consecutive_passes=self._handoff_pass_frames,
            required_passes=self._handoff_cfg.consecutive_pass_frames,
            debug=handoff_debug,
        ):
            self._handoff_done = True
            self._handoff_pass_frames = int(handoff_debug.get("pass_count_after_sample", 0))
            self._handoff_snapshot = self._build_handoff_snapshot(handoff_debug, passive)
            self._handoff_event_summary = (
                "handoff_evt "
                f"pdx:{float(handoff_debug.get('projected_dx', 0.0)):5.1f} "
                f"on:{int(bool(handoff_debug.get('centered')))} "
                f"in:{int(bool(handoff_debug.get('inside_target')))} "
                f"spd:{int(bool(handoff_debug.get('speed_ready')))} "
                f"des:{int(bool(handoff_debug.get('descending')))} "
                f"retro:{int(bool(handoff_debug.get('retrograde_ready')))} "
                f"pass:{int(handoff_debug.get('pass_count_after_sample', 0))}/"
                f"{int(handoff_debug.get('required_passes', 1))}"
            )
        elif not self._handoff_done:
            if bool(handoff_debug.get("raw_ready")):
                self._handoff_pass_frames += 1
            else:
                self._handoff_pass_frames = 0
        self._ballistic_debug_summary = (
            f"ball pdx:{float(coast_debug.get('projected_dx', 0.0)):6.1f} "
            f"tf:{float(coast_debug.get('t_fall', 0.0)):4.1f} "
            f"src:{'s' if bool(coast_debug.get('sensor_used')) else 'a'}"
        )
        self._last_guidance = guidance
        return guidance

    def _start_impulse(self, *, frames: int) -> None:
        self._coast_impulse_frames_remaining = max(0, int(frames))

    def _step_impulse_timer(self) -> None:
        if self._coast_impulse_frames_remaining <= 0:
            return
        self._coast_impulse_frames_remaining -= 1
        if self._coast_impulse_frames_remaining == 0:
            self._coast_impulse_cooldown_remaining = self._coast_impulse_cooldown_frames

    def _shape_coast_impulse(
        self,
        guidance: GuidanceTargets,
        *,
        projected_dx: object,
        vy_up: float,
    ) -> GuidanceTargets:
        if self._coast_impulse_frames_remaining > 0:
            if (
                guidance.vertical_mode in ("terminal_burn", "touchdown")
                and float(guidance.alt) <= self._coast_impulse_abort_altitude
            ):
                self._coast_impulse_frames_remaining = 0
                self._coast_impulse_cooldown_remaining = 0
                return guidance
            self._step_impulse_timer()
            return replace(guidance, vertical_mode="coast_hold")
        if self._coast_impulse_cooldown_remaining > 0:
            self._coast_impulse_cooldown_remaining -= 1
            if guidance.vertical_mode in ("coast_hold", "align"):
                return replace(guidance, vertical_mode="coast")
            return guidance
        if guidance.vertical_mode in ("terminal_burn", "touchdown"):
            return guidance

        projected_abs = (
            abs(float(projected_dx))
            if isinstance(projected_dx, (int, float)) and math.isfinite(float(projected_dx))
            else abs(float(guidance.dx))
        )
        projected_signed = (
            float(projected_dx)
            if isinstance(projected_dx, (int, float)) and math.isfinite(float(projected_dx))
            else float(guidance.dx)
        )
        overshoot_correction = (projected_signed * float(guidance.dx)) < 0.0
        primary_frames = self._coast_primary_impulse_frames
        cleanup_frames = self._coast_cleanup_impulse_frames
        if overshoot_correction:
            primary_frames = int(round(1.75 * primary_frames))
            cleanup_frames = int(round(1.60 * cleanup_frames))
        descending = float(vy_up) <= self._coast_impulse_descending_vy_max
        eligible_phase = guidance.phase in ("coast", "align")
        eligible_for_impulse = eligible_phase and descending
        if (
            (not self._coast_primary_impulse_used)
            and projected_abs >= self._coast_primary_trigger_dx
            and eligible_for_impulse
        ):
            self._coast_primary_impulse_used = True
            self._start_impulse(frames=primary_frames)
            self._step_impulse_timer()
            return replace(guidance, vertical_mode="coast_hold")
        if (
            self._coast_cleanup_impulse_frames > 0
            and self._coast_primary_impulse_used
            and (not self._coast_cleanup_impulse_used)
            and projected_abs >= self._coast_cleanup_trigger_dx
            and eligible_for_impulse
        ):
            self._coast_cleanup_impulse_used = True
            self._start_impulse(frames=cleanup_frames)
            self._step_impulse_timer()
            return replace(guidance, vertical_mode="coast_hold")
        if guidance.vertical_mode in ("coast_hold", "align"):
            return replace(guidance, vertical_mode="coast")
        return guidance

    def get_evaluation_snapshot(self) -> dict[str, float | bool | str | None]:
        if self._handoff_snapshot is None:
            return {"kind": "coast", "handoff_done": bool(self._handoff_done)}
        return dict(self._handoff_snapshot)

    def _terminal_brake_altitude(
        self,
        passive: PassiveSensors,
        alt: float,
        dx: float,
        burn_altitude: float,
        spool_time: float,
        max_force: float,
    ) -> float:
        max_tilt = 0.18 if alt < 20.0 else 0.56
        window = coupled_brake_window(
            self._course_cfg,
            alt=alt,
            dx=dx,
            vx=passive.vx,
            vy_up=passive.vy_up,
            mass=passive.mass,
            max_force=max_force,
            max_tilt=max_tilt,
            spool_time=spool_time,
            vertical_brake_alt=burn_altitude,
        )
        return window.combined_brake_alt

    def _horizontal_controller(
        self,
        passive: PassiveSensors,
        vx_sp: float,
    ) -> float:
        guidance = self._last_guidance
        if guidance is None or not passive.radar_contacts:
            return (0.65 * (vx_sp - passive.vx)) - (0.08 * passive.ax)
        tracker = lateral_tracking_command(
            self._course_cfg,
            dx=guidance.dx,
            alt=guidance.alt,
            vx=passive.vx,
            vy_up=passive.vy_up,
            ax=passive.ax,
            vx_guidance=vx_sp,
            active=self._active_sensors,
            x=passive.x,
            y=passive.y,
            clearance=self._ballistic_clearance(),
        )
        return tracker.ax_target

    def _vertical_controller(
        self,
        passive: PassiveSensors,
        vy_sp: float,
        alt: float,
        vertical_mode: str,
        up_acc_max: float,
    ) -> float:
        if vertical_mode in ("coast", "eco_glide", "speed_dive"):
            return 0.0
        if vertical_mode == "coast_hold":
            burst_up = 11.0 if alt >= 60.0 else 10.4
            return clamp(burst_up, 10.2, 11.4)
        if vertical_mode == "terminal_burn":
            brake_gain = (
                self._policy.terminal_brake_gain_high_alt
                if alt > 8.0
                else self._policy.terminal_brake_gain_low_alt
            )
            a_up_cmd = 9.8 + (brake_gain * up_acc_max)
            if passive.vy_up > -0.7:
                a_up_cmd = min(a_up_cmd, 9.8 + (0.45 * up_acc_max))
            return a_up_cmd

        vy_err = vy_sp - passive.vy_up
        a_up_cmd = 9.8 + (0.38 * vy_err)
        if alt < 7.0:
            a_up_cmd += 0.08
        if alt < 3.0 and passive.vy_up > -0.45:
            a_up_cmd -= 0.12
        return a_up_cmd

    def _fuel_ratio(self, passive: PassiveSensors) -> float:
        max_fuel = max(1e-6, float(passive.max_fuel))
        return clamp(float(passive.fuel) / max_fuel, 0.0, 1.0)

    def _can_use_overdrive(
        self,
        passive: PassiveSensors,
        *,
        vertical_mode: str,
        alt: float,
    ) -> bool:
        if not self._policy.allow_overdrive:
            return False
        if self._fuel_ratio(passive) < self._policy.min_fuel_ratio_for_overdrive:
            return False
        if self._policy.overdrive_requires_terminal_burn and vertical_mode != "terminal_burn":
            return False
        return (
            passive.vy_up < self._policy.emergency_vy_threshold
            or (
                alt < self._policy.emergency_low_alt
                and passive.vy_up < self._policy.emergency_low_alt_vy_threshold
            )
        )

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
        max_power: float,
        min_throttle: float,
        max_throttle: float,
    ) -> BotAction:
        max_force = max_power * max_throttle
        mass, _ = vehicle_limits(passive, max_force)
        req = clamp((a_x_sp * mass) / max(max_force, 1e-3), -0.95, 0.95)
        align_retrograde = (
            (not self._handoff_done)
            and vertical_mode in ("coast", "align")
            and alt
            <= (self._handoff_cfg.altitude_max + self._handoff_cfg.retrograde_align_altitude_margin)
            and math.hypot(float(passive.vx), float(passive.vy_up))
            > self._handoff_cfg.retrograde_align_speed_min
        )
        max_tilt = 0.18 if alt < 20.0 else 0.56
        if vertical_mode == "coast_hold":
            # Coast impulse: prioritize lateral delta-v with a strong tilted burn.
            burst_tilt = min(max_tilt, 0.56 if alt >= 20.0 else 0.30)
            direction = 1.0 if a_x_sp >= 0.0 else -1.0
            angle_cmd = direction * burst_tilt
        else:
            angle_cmd = math.asin(req)
            angle_cmd = clamp(angle_cmd, -max_tilt, max_tilt)
        if align_retrograde:
            angle_cmd = _retrograde_angle(passive.vx, passive.vy_up)
        angle_cmd = rate_limit_angle_command(angle_cmd, self._prev_angle_cmd, dt)
        self._prev_angle_cmd = angle_cmd

        cos_term = max(0.25, abs(math.cos(angle_cmd)))
        thrust = (mass * a_up_sp) / max(max_power * cos_term, 1e-3)
        if alt < 9.0 and abs(dx) <= 10.0 and not align_retrograde:
            angle_cmd = 0.0
        if alt < 2.5 and abs(dx) <= 7.0 and abs(passive.vx) < 0.6 and abs(passive.vy_up) < 0.9:
            thrust = 0.0
            angle_cmd = 0.0

        soft_cap = min(self._policy.overdrive_soft_cap, max_throttle)
        if thrust > soft_cap and not self._can_use_overdrive(
            passive,
            vertical_mode=vertical_mode,
            alt=alt,
        ):
            thrust = soft_cap
        thrust = clamp(thrust, 0.0, max_throttle)
        if thrust > 0.0:
            thrust = max(min_throttle, thrust)
        if vertical_mode == "coast_hold" and thrust > 0.0:
            thrust = max(thrust, min(max_throttle, 1.0))
        if thrust <= 1e-5 and not align_retrograde:
            angle_cmd = 0.0

        action = BotAction(target_thrust=thrust, target_angle=angle_cmd, refuel=False)
        action.target_angle = cap_low_altitude_angle(
            action.target_angle,
            alt=alt,
            dx=dx,
            cfg=self._course_cfg,
        )
        return action

    def get_headless_stats(self) -> str:
        base = super().get_headless_stats()
        if self._ballistic_debug_summary:
            base = f"{base} {self._ballistic_debug_summary}" if base else self._ballistic_debug_summary
        if not self._handoff_event_summary:
            return base
        if not base:
            return self._handoff_event_summary
        return f"{base} {self._handoff_event_summary}"


def create_bot() -> Bot:
    return CoastBot()


def list_behavior_names() -> tuple[str, ...]:
    return ("coast",)


__all__ = [
    "CoastBot",
    "CoastHandoffConfig",
    "create_bot",
    "list_behavior_names",
    "should_handoff_to_flare",
]
