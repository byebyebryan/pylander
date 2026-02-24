"""Drift-first bot: descent with continuous lateral course correction."""

from __future__ import annotations

from bots._descent_core import GuidanceTargets, StrategyDescentBot
from bots._drift_core import (
    DRIFT_BALANCED_POLICY,
    DriftCourseConfig,
    apply_drift_guidance,
    cap_low_altitude_angle,
    list_drift_behavior_names,
    resolve_drift_behavior,
)
from core.bot import Bot, PassiveSensors
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
        high_speed = abs(vx_sp) > 2.4
        gain = 0.9 if high_speed else 0.7
        accel_damping = 0.06 if high_speed else 0.1
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
    ):
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
