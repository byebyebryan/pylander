"""Drift correction bot: kill lateral speed and refine landing."""

from __future__ import annotations

import math

from bots._descent_core import (
    GuidanceTargets,
    StrategyDescentBot,
)
from bots._drift_core import (
    DRIFT_BALANCED_POLICY,
    DriftCourseConfig,
    apply_drift_guidance,
    cap_low_altitude_angle,
    list_drift_behavior_names,
    resolve_drift_behavior,
)
from core.bot import Bot, BotAction, PassiveSensors
from core.sensor import RadarContact


class DriftBot(StrategyDescentBot):
    def __init__(self, behavior: str = "balanced") -> None:
        super().__init__(DRIFT_BALANCED_POLICY)
        self._course_cfg = DriftCourseConfig()
        self._behavior = "balanced"
        self.set_behavior(behavior)

    def set_behavior(self, behavior: str) -> None:
        key, policy, cfg = resolve_drift_behavior(behavior)
        self._policy = policy
        self._course_cfg = cfg
        self._behavior = key

    @property
    def behavior(self) -> str:
        return self._behavior

    def _guidance(
        self,
        passive: PassiveSensors,
        target: RadarContact,
        *,
        max_force: float,
        max_throttle: float,
        ramp_up: float,
    ) -> GuidanceTargets:
        base_guidance = super()._guidance(
            passive,
            target,
            max_force=max_force,
            max_throttle=max_throttle,
            ramp_up=ramp_up,
        )
        return apply_drift_guidance(base_guidance, self._course_cfg)

    def _horizontal_controller(
        self,
        passive: PassiveSensors,
        vx_sp: float,
    ) -> float:
        vx_err = vx_sp - passive.vx
        abs_vx_sp = abs(vx_sp)
        alt = passive.altitude if math.isfinite(passive.altitude) else 0.0
        if self._behavior == "efficiency":
            if alt >= 95.0 and abs_vx_sp >= 2.8:
                gain = 1.35
                accel_damping = 0.02
            elif abs_vx_sp > 2.2:
                gain = 1.12
                accel_damping = 0.04
            else:
                gain = 0.78
                accel_damping = 0.085
        elif alt >= 120.0 and abs_vx_sp >= 3.0:
            gain = 1.1
            accel_damping = 0.035
        elif abs_vx_sp > 2.4:
            gain = 0.95
            accel_damping = 0.055
        else:
            gain = 0.72
            accel_damping = 0.1
        return (gain * vx_err) - (accel_damping * passive.ax)

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
