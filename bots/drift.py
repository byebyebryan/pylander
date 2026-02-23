"""Two-phase drift bot: lateral travel first, then vertical descent."""

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
class DriftPhaseConfig:
    align_position: float = 18.0
    align_velocity: float = 1.4
    vertical_phase_altitude: float = 42.0
    force_vertical_altitude: float = 18.0
    lateral_brake_accel: float = 2.8
    lateral_full_cruise_distance: float = 230.0
    lateral_min_commit_speed: float = 4.2
    lateral_cruise_speed_min: float = 6.5
    lateral_cruise_speed_max: float = 15.0
    lateral_cruise_speed_alt_gain: float = 0.04
    vertical_angle_cap_high: float = 0.28
    vertical_angle_cap_low: float = 0.16


DRIFT_POLICY = replace(
    BALANCED_POLICY,
    status_prefix="drift",
    coast_horiz_deadband=8.0,
)


class DriftBot(StrategyDescentBot):
    def __init__(self) -> None:
        super().__init__(DRIFT_POLICY)
        self._phase_cfg = DriftPhaseConfig()

    def _is_vertical_phase(self, alt: float, dx: float, vx: float) -> bool:
        aligned = (
            abs(dx) <= self._phase_cfg.align_position
            and abs(vx) <= self._phase_cfg.align_velocity
        )
        descent_ready = (
            alt <= self._phase_cfg.vertical_phase_altitude
            and abs(dx) <= (self._phase_cfg.align_position * 1.4)
            and abs(vx) <= (self._phase_cfg.align_velocity * 1.8)
        )
        return aligned or descent_ready or alt <= self._phase_cfg.force_vertical_altitude

    def _lateral_speed_setpoint(self, dx: float, alt: float) -> float:
        abs_dx = abs(dx)
        if abs_dx < 1e-6:
            return 0.0
        cruise_cap = clamp(
            self._phase_cfg.lateral_cruise_speed_min
            + (self._phase_cfg.lateral_cruise_speed_alt_gain * alt),
            self._phase_cfg.lateral_cruise_speed_min,
            self._phase_cfg.lateral_cruise_speed_max,
        )
        brake_profile = math.sqrt(
            max(0.0, 2.0 * self._phase_cfg.lateral_brake_accel * abs_dx)
        )
        if abs_dx >= self._phase_cfg.lateral_full_cruise_distance:
            speed_mag = cruise_cap
        else:
            speed_mag = min(cruise_cap, brake_profile)
            if abs_dx >= 80.0:
                speed_mag = max(speed_mag, self._phase_cfg.lateral_min_commit_speed)
        return math.copysign(speed_mag, dx)

    def _lateral_guidance(
        self,
        passive,
        target: RadarContact,
        *,
        max_force: float,
        max_throttle: float,
        ramp_up: float,
    ) -> GuidanceTargets:
        _ = max_force, max_throttle, ramp_up
        alt = max(0.0, passive.altitude if math.isfinite(passive.altitude) else 0.0)
        dx = target.x - passive.x
        vx_sp = self._lateral_speed_setpoint(dx, alt)

        # Keep descending while translating laterally; no climb-to-travel mode.
        vy_sp = -clamp(1.2 + (0.22 * math.sqrt(max(0.0, alt))), 1.1, 5.8)
        if alt < 32.0:
            vy_sp = -clamp(0.6 + (0.08 * alt), 0.8, 2.2)

        return GuidanceTargets(
            phase="lateral_travel",
            vertical_mode="drift_lateral",
            vx_sp=vx_sp,
            vy_sp=vy_sp,
            dx=dx,
            alt=alt,
            burn_altitude=0.0,
        )

    def _guidance(
        self,
        passive,
        target: RadarContact,
        *,
        max_force: float,
        max_throttle: float,
        ramp_up: float,
    ) -> GuidanceTargets:
        dx = target.x - passive.x
        alt = passive.altitude if math.isfinite(passive.altitude) else 1e9
        if not self._is_vertical_phase(alt, dx, passive.vx):
            return self._lateral_guidance(
                passive,
                target,
                max_force=max_force,
                max_throttle=max_throttle,
                ramp_up=ramp_up,
            )

        guidance = super()._guidance(
            passive,
            target,
            max_force=max_force,
            max_throttle=max_throttle,
            ramp_up=ramp_up,
        )
        if guidance.phase in ("terminal_burn", "flare", "touchdown"):
            return guidance
        return GuidanceTargets(
            phase="vertical_descent",
            vertical_mode=guidance.vertical_mode,
            vx_sp=clamp(guidance.dx * 0.09, -1.6, 1.6),
            vy_sp=guidance.vy_sp,
            dx=guidance.dx,
            alt=guidance.alt,
            burn_altitude=guidance.burn_altitude,
        )

    def _horizontal_controller(
        self,
        passive,
        vx_sp: float,
    ) -> float:
        vx_err = vx_sp - passive.vx
        high_speed = abs(vx_sp) > 2.0
        gain = 0.95 if high_speed else 0.65
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
        if self._is_vertical_phase(alt, dx, passive.vx):
            cap = (
                self._phase_cfg.vertical_angle_cap_high
                if alt > 20.0
                else self._phase_cfg.vertical_angle_cap_low
            )
            action.target_angle = clamp(action.target_angle, -cap, cap)
        return action


def create_bot() -> Bot:
    return DriftBot()


__all__ = ["DriftBot", "create_bot"]
