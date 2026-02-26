"""Plunge bot with simplified terminal burn and flare logic."""

from __future__ import annotations

import math
from dataclasses import dataclass

from bots._ballistics import ballistic_time_to_impact, estimate_ballistic_projection
from bots._bot_math import clamp, engine_profile, finite_altitude, normalize_behavior_key, stable, vehicle_limits
from bots._coast_core import GuidanceTargets
from bots._drop_control import (
    allocate_controls,
    can_use_overdrive,
    horizontal_controller,
    vertical_controller,
)
from bots._targeting import pick_target
from core.bot import ActiveSensors, Bot, BotAction, PassiveSensors
from core.sensor import RadarContact


@dataclass(frozen=True)
class PlungePolicy:
    status_prefix: str = "plunge"
    align_band: float = 10.0
    sensor_time_to_brake_buffer_scale: float = 0.75
    touchdown_altitude: float = 4.2
    touchdown_track_band: float = 8.0
    coast_horiz_deadband: float = 14.0
    terminal_brake_gain_high_alt: float = 0.94
    terminal_brake_gain_low_alt: float = 0.82
    overdrive_soft_cap: float = 1.0
    allow_overdrive: bool = True
    overdrive_requires_terminal_burn: bool = True
    emergency_vy_threshold: float = -6.0
    emergency_low_alt: float = 12.0
    emergency_low_alt_vy_threshold: float = -3.5
    min_fuel_ratio_for_overdrive: float = 0.16


BALANCED_PLUNGE_POLICY = PlungePolicy()


class PlungeBot(Bot):
    def __init__(self, behavior: str = "balanced") -> None:
        super().__init__()
        self._policy = BALANCED_PLUNGE_POLICY
        self._behavior = "balanced"
        self._prev_angle_cmd = 0.0
        self._ballistic_debug_summary = ""
        self.set_behavior(behavior)

    def set_behavior(self, behavior: str) -> None:
        key = normalize_behavior_key(behavior)
        if key != "balanced":
            raise ValueError(
                f"Unknown plunge behavior '{behavior}'. Expected one of: balanced"
            )
        self._behavior = "balanced"
        self._policy = BALANCED_PLUNGE_POLICY

    @property
    def behavior(self) -> str:
        return self._behavior

    def _engine_profile(self) -> tuple[float, float, float, float]:
        return engine_profile(self.vehicle_info)

    def _can_use_overdrive(
        self,
        passive: PassiveSensors,
        *,
        vertical_mode: str,
        alt: float,
    ) -> bool:
        return can_use_overdrive(
            self._policy,
            passive,
            vertical_mode=vertical_mode,
            alt=alt,
        )

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
        alt = finite_altitude(passive)
        dx = float(target.x) - float(passive.x)
        projection = estimate_ballistic_projection(
            dx=dx,
            alt=alt,
            vx=passive.vx,
            vy_up=passive.vy_up,
            x=passive.x,
            y=passive.y,
            active=active,
            clearance=0.0,
            segment_length=20.0,
            max_points=192,
            min_t_fall=0.0,
        )
        track_dx = projection.projected_dx
        _, up_acc_max = vehicle_limits(passive, max_force)

        down_speed = max(0.0, -float(passive.vy_up))
        nominal_throttle = min(1.0, max_throttle)
        spool_time = max(0.0, nominal_throttle - max(0.0, float(passive.thrust_level))) / max(
            1e-3,
            ramp_up,
        )
        spool_distance = (down_speed * spool_time) + (4.9 * spool_time * spool_time)
        flare_speed = clamp(0.45 + (0.11 * alt), 0.6, 2.2)
        speed_to_kill = max(0.0, down_speed - flare_speed)
        stop_distance = (speed_to_kill * speed_to_kill) / (2.0 * max(1e-3, up_acc_max))
        burn_margin = 2.1 + (0.12 * max(0.0, abs(track_dx) - self._policy.align_band))
        burn_altitude = stop_distance + spool_distance + burn_margin

        time_to_impact, impact_source = ballistic_time_to_impact(passive, active)
        time_to_brake = spool_time + (speed_to_kill / max(1e-3, up_acc_max))
        time_buffer = 0.15
        if impact_source == "sensor":
            time_buffer *= self._policy.sensor_time_to_brake_buffer_scale
        burn_now = bool(
            down_speed > 0.5
            and (
                alt <= burn_altitude
                or time_to_impact <= (time_to_brake + time_buffer)
            )
        )

        if burn_now:
            phase = "burn"
            vertical_mode = "terminal_burn"
            vy_sp = -clamp(0.45 + (0.10 * alt), 0.35, 2.0)
            vx_sp = clamp(0.10 * track_dx, -1.2, 1.2)
        elif alt <= 10.0:
            phase = "flare"
            vertical_mode = "flare"
            # Fade descent target toward zero as we approach the ground.
            vy_sp = -clamp(0.08 * alt, 0.04, 0.9)
            vx_sp = clamp(0.12 * track_dx, -0.8, 0.8)
        else:
            phase = "coast"
            vertical_mode = "coast"
            vy_sp = -clamp(1.1 + (0.28 * math.sqrt(max(0.0, alt))), 1.2, 5.5)
            vx_sp = clamp(0.08 * track_dx, -2.6, 2.6)

        if alt < self._policy.touchdown_altitude and abs(track_dx) <= self._policy.touchdown_track_band:
            phase = "touchdown"
            vertical_mode = "flare"
            vy_sp = -clamp(0.3 + (0.06 * alt), 0.2, 0.7)
            vx_sp = clamp(vx_sp, -0.5, 0.5)

        self._ballistic_debug_summary = (
            f"ball tti:{stable(time_to_impact, 1):4.1f} "
            f"src:{'s' if impact_source == 'sensor' else 'a'} "
            f"pdx:{stable(track_dx, 1):5.1f} "
            f"burn:{int(burn_now)}"
        )
        return GuidanceTargets(
            phase=phase,
            vertical_mode=vertical_mode,
            vx_sp=vx_sp,
            vy_sp=vy_sp,
            dx=dx,
            alt=alt,
            burn_altitude=burn_altitude,
        )

    def update(
        self,
        dt: float,
        passive: PassiveSensors,
        active: ActiveSensors,
    ) -> BotAction:
        if passive.state in ("landed", "crashed", "out_of_fuel"):
            self._ballistic_debug_summary = ""
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
            a_x_sp = horizontal_controller(passive, vx_sp=0.0)
            a_up_sp = vertical_controller(
                self._policy,
                passive,
                vy_sp=-0.6,
                alt=alt,
                vertical_mode="flare",
                up_acc_max=up_acc_max,
            )
            action, self._prev_angle_cmd = allocate_controls(
                self._policy,
                dt,
                passive,
                a_x_sp=a_x_sp,
                a_up_sp=a_up_sp,
                dx=0.0,
                alt=alt,
                vertical_mode="flare",
                prev_angle_cmd=self._prev_angle_cmd,
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
        if guidance.vertical_mode == "coast" and abs(guidance.dx) <= self._policy.coast_horiz_deadband:
            a_x_sp = 0.0
        else:
            a_x_sp = horizontal_controller(passive, guidance.vx_sp)
        a_up_sp = vertical_controller(
            self._policy,
            passive,
            guidance.vy_sp,
            guidance.alt,
            guidance.vertical_mode,
            up_acc_max,
        )
        action, self._prev_angle_cmd = allocate_controls(
            self._policy,
            dt,
            passive,
            a_x_sp=a_x_sp,
            a_up_sp=a_up_sp,
            dx=guidance.dx,
            alt=guidance.alt,
            vertical_mode=guidance.vertical_mode,
            prev_angle_cmd=self._prev_angle_cmd,
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

    def get_headless_stats(self) -> str:
        base = super().get_headless_stats()
        if not self._ballistic_debug_summary:
            return base
        if not base:
            return self._ballistic_debug_summary
        return f"{base} {self._ballistic_debug_summary}"


def create_bot() -> Bot:
    return PlungeBot()


def list_behavior_names() -> tuple[str, ...]:
    return ("balanced",)


__all__ = ["PlungeBot", "create_bot", "list_behavior_names"]
