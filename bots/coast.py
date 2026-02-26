"""Coast correction bot: kill lateral speed and refine landing."""

from __future__ import annotations

import math

from bots._ballistics import ballistic_time_to_impact
from bots._bot_math import coerce_finite, engine_profile, finite_altitude, stable, vehicle_limits
from bots._coast_core import (
    COAST_POLICY,
    CoastCourseConfig,
    GuidanceTargets,
    apply_coast_guidance,
    cap_low_altitude_angle,
    compute_drop_guidance,
    coupled_brake_window,
    lateral_tracking_command,
    resolve_coast_behavior,
    should_handoff_to_flare,
)
from bots._drop_control import allocate_controls, vertical_controller
from bots._targeting import pick_target
from core.bot import ActiveSensors, Bot, BotAction, PassiveSensors
from core.sensor import RadarContact


class CoastBot(Bot):
    def __init__(self, behavior: str = "coast") -> None:
        super().__init__()
        self._policy = COAST_POLICY
        self._course_cfg = CoastCourseConfig()
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
        self.set_behavior(behavior)

    def set_behavior(self, behavior: str) -> None:
        key = str(behavior).strip().lower()
        if key != "coast":
            raise ValueError(
                f"Unknown coast behavior '{behavior}'. Expected one of: coast"
            )
        _, policy, cfg = resolve_coast_behavior("coast")
        self._policy = policy
        self._course_cfg = cfg
        self._behavior = "coast"
        self._ballistic_debug_summary = ""
        self._handoff_done = False
        self._handoff_pass_frames = 0
        self._handoff_snapshot = None
        self._handoff_event_summary = ""
        self._last_target_size = None

    @property
    def behavior(self) -> str:
        return self._behavior

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
            self._handoff_done = False
            self._handoff_pass_frames = 0
            self._handoff_snapshot = None
            self._handoff_event_summary = ""
            self._last_target_size = None
            self._last_guidance = None
            self._ballistic_debug_summary = ""
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
            if guidance.vertical_mode in ("coast", "coast_hold") and abs(
                guidance.dx
            ) <= self._policy.coast_horiz_deadband:
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
        target_size = coerce_finite(getattr(target, "size", None), float("nan"))
        if not math.isfinite(target_size):
            target_size = None
        self._last_target_size = target_size
        handoff_debug: dict[str, object] = {}
        if not self._handoff_done and should_handoff_to_flare(
            guidance,
            self._course_cfg,
            vx=passive.vx,
            vy_up=passive.vy_up,
            active=self._active_sensors,
            x=passive.x,
            y=passive.y,
            target_size=target_size,
            clearance=self._ballistic_clearance(),
            consecutive_passes=self._handoff_pass_frames,
            required_passes=self._course_cfg.flare_handoff_consecutive_pass_frames,
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
        return vertical_controller(
            self._policy,
            passive,
            vy_sp,
            alt,
            vertical_mode,
            up_acc_max,
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
        action, self._prev_angle_cmd = allocate_controls(
            self._policy,
            dt,
            passive,
            a_x_sp=a_x_sp,
            a_up_sp=a_up_sp,
            alt=alt,
            dx=dx,
            vertical_mode=vertical_mode,
            prev_angle_cmd=self._prev_angle_cmd,
            max_power=max_power,
            min_throttle=min_throttle,
            max_throttle=max_throttle,
        )
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
            if base:
                base = f"{base} {self._ballistic_debug_summary}"
            else:
                base = self._ballistic_debug_summary
        if not self._handoff_event_summary:
            return base
        if not base:
            return self._handoff_event_summary
        return f"{base} {self._handoff_event_summary}"


def create_bot() -> Bot:
    return CoastBot()


def list_behavior_names() -> tuple[str, ...]:
    return ("coast",)


__all__ = ["CoastBot", "create_bot", "list_behavior_names"]
