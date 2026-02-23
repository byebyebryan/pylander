"""Drift-first bot: descent with continuous lateral course correction."""

from __future__ import annotations

import math
from dataclasses import dataclass, replace

from bots._descent_core import (
    BALANCED_POLICY,
    GuidanceTargets,
    StrategyDescentBot,
    clamp,
)
from core.bot import Bot
from core.sensor import RadarContact


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
    fast_descent_min_altitude: float = 26.0
    fast_descent_base: float = 1.8
    fast_descent_sqrt_gain: float = 0.28
    fast_descent_cap: float = 6.4
    low_altitude_angle_limit_alt: float = 14.0
    low_altitude_angle_limit_dx: float = 24.0
    low_altitude_angle_cap: float = 0.16


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


class DriftBot(StrategyDescentBot):
    def __init__(self) -> None:
        super().__init__(DRIFT_POLICY)
        self._course_cfg = DriftCourseConfig()

    def _cone_dx_limit(self, alt: float) -> float:
        return clamp(
            self._course_cfg.cone_dx_base + (self._course_cfg.cone_dx_per_alt * alt),
            self._course_cfg.cone_dx_base,
            self._course_cfg.cone_dx_max,
        )

    def _correction_vx_cap(self, alt: float) -> float:
        if alt <= self._course_cfg.correction_vx_low_alt_threshold:
            return self._course_cfg.correction_vx_low_alt_cap
        return self._course_cfg.correction_vx_high_alt_cap

    def _guidance(
        self,
        passive,
        target: RadarContact,
        *,
        max_force: float,
        max_throttle: float,
        ramp_up: float,
    ) -> GuidanceTargets:
        guidance = super()._guidance(
            passive,
            target,
            max_force=max_force,
            max_throttle=max_throttle,
            ramp_up=ramp_up,
        )
        if guidance.phase in ("flare", "touchdown"):
            return guidance

        alt = max(0.0, guidance.alt)
        abs_dx = abs(guidance.dx)
        cone_limit = self._cone_dx_limit(alt)
        vx_cap = self._correction_vx_cap(alt)
        if guidance.vertical_mode == "terminal_burn" and abs_dx > max(16.0, 0.75 * cone_limit):
            vx_cap = max(vx_cap, 2.2)
        vx_sp = clamp(guidance.vx_sp, -vx_cap, vx_cap)

        if abs_dx > cone_limit:
            excess = abs_dx - cone_limit
            correction_vx = clamp(
                self._course_cfg.correction_vx_min
                + (self._course_cfg.correction_vx_per_excess * excess)
                + (self._course_cfg.correction_vx_per_alt * alt),
                self._course_cfg.correction_vx_min,
                vx_cap,
            )
            vx_sp = math.copysign(max(abs(vx_sp), correction_vx), guidance.dx)

        vy_sp = guidance.vy_sp
        vertical_mode = guidance.vertical_mode
        if vertical_mode == "coast" and abs_dx > cone_limit:
            # Keep drift runs thrust-backed during correction, not ballistic.
            vertical_mode = "drift_coast"
        if (
            guidance.vertical_mode == "coast"
            and alt >= self._course_cfg.fast_descent_min_altitude
        ):
            fast_descent_vy = -clamp(
                self._course_cfg.fast_descent_base
                + (self._course_cfg.fast_descent_sqrt_gain * math.sqrt(alt)),
                self._course_cfg.fast_descent_base,
                self._course_cfg.fast_descent_cap,
            )
            vy_sp = min(vy_sp, fast_descent_vy)

        phase = "drift" if guidance.phase in ("coast", "align") else guidance.phase
        return replace(
            guidance,
            phase=phase,
            vertical_mode=vertical_mode,
            vx_sp=vx_sp,
            vy_sp=vy_sp,
        )

    def _horizontal_controller(
        self,
        passive,
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
        passive,
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
        if alt <= self._course_cfg.low_altitude_angle_limit_alt and abs(dx) <= self._course_cfg.low_altitude_angle_limit_dx:
            cap = self._course_cfg.low_altitude_angle_cap
            action.target_angle = clamp(action.target_angle, -cap, cap)
        return action


def create_bot() -> Bot:
    return DriftBot()


__all__ = ["DriftBot", "create_bot"]
