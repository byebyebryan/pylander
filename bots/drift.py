"""Drift correction bot: kill lateral speed and refine landing."""

from __future__ import annotations

from bots._drop_core import (
    GuidanceTargets,
    StrategyDropBot,
)
from bots._drift_core import (
    DRIFT_POLICY,
    DriftCourseConfig,
    apply_drift_guidance,
    cap_low_altitude_angle,
    coupled_brake_window,
    lateral_tracking_command,
    list_drift_behavior_names,
    resolve_drift_behavior,
)
from core.bot import ActiveSensors, Bot, BotAction, PassiveSensors
from core.sensor import RadarContact


class DriftBot(StrategyDropBot):
    def __init__(self, behavior: str = "drift") -> None:
        super().__init__(DRIFT_POLICY)
        self._course_cfg = DriftCourseConfig()
        self._behavior = "drift"
        self._last_guidance: GuidanceTargets | None = None
        self._active_sensors: ActiveSensors | None = None
        self.set_behavior(behavior)

    def set_behavior(self, behavior: str) -> None:
        key, policy, cfg = resolve_drift_behavior(behavior)
        self._policy = policy
        self._course_cfg = cfg
        self._behavior = key
        self._ballistic_debug_summary = ""

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
        self._active_sensors = active
        try:
            return super().update(dt, passive, active)
        finally:
            self._active_sensors = None

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
        base_guidance = super()._guidance(
            passive,
            target,
            max_force=max_force,
            max_throttle=max_throttle,
            ramp_up=ramp_up,
            active=active,
        )
        drift_debug: dict[str, object] = {}
        guidance = apply_drift_guidance(
            base_guidance,
            self._course_cfg,
            vx=passive.vx,
            vy_up=passive.vy_up,
            active=self._active_sensors,
            x=passive.x,
            y=passive.y,
            clearance=self._ballistic_clearance(),
            debug=drift_debug,
        )
        self._ballistic_debug_summary = (
            f"ball pdx:{float(drift_debug.get('projected_dx', 0.0)):6.1f} "
            f"tf:{float(drift_debug.get('t_fall', 0.0)):4.1f} "
            f"src:{'s' if bool(drift_debug.get('sensor_used')) else 'a'}"
        )
        self._last_guidance = guidance
        return guidance

    def _terminal_brake_altitude(
        self,
        passive: PassiveSensors,
        *,
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
        action = super()._allocate_controls(
            dt,
            passive,
            a_x_sp=a_x_sp,
            a_up_sp=a_up_sp,
            alt=alt,
            dx=dx,
            vertical_mode=vertical_mode,
        )
        action.target_angle = cap_low_altitude_angle(
            action.target_angle,
            alt=alt,
            dx=dx,
            cfg=self._course_cfg,
        )
        return action


def create_bot() -> Bot:
    return DriftBot()


def list_behavior_names() -> tuple[str, ...]:
    return list_drift_behavior_names()


__all__ = ["DriftBot", "create_bot", "list_behavior_names"]
