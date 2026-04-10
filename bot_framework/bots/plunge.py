"""Plunge bot with simplified terminal burn and flare logic."""

from __future__ import annotations

import math
from dataclasses import dataclass

from .common_ballistics import (
    BallisticProjection,
    estimate_ground_time_to_impact,
    estimate_target_y_projection,
)
from .common_math import (
    _GRAVITY_MAG,
    clamp,
    engine_profile,
    finite_altitude,
    normalize_behavior_key,
    rate_limit_angle_command,
    stable,
    vehicle_limits,
)
from .common_targeting import pick_target
from game.core.bot import Bot, BotAction, BotDisplayState, Sensors
from game.core.sensor import RadarContact


@dataclass(frozen=True)
class GuidanceTargets:
    phase: str
    vertical_mode: str
    vx_sp: float
    vy_sp: float
    dx: float
    alt: float
    burn_altitude: float


@dataclass(frozen=True)
class PlungePolicy:
    status_prefix: str = "plunge"
    align_band: float = 10.0
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
        self._display_phase = "coast"
        self._display_summary = ""
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

    def _set_display_state(self, *, phase: str, summary: str) -> None:
        self._display_phase = phase
        self._display_summary = summary.strip()

    def _engine_profile(self) -> tuple[float, float, float, float]:
        return engine_profile(self.vehicle_info)

    def _can_use_overdrive(
        self,
        passive: Sensors,
        *,
        vertical_mode: str,
        alt: float,
    ) -> bool:
        if not self._policy.allow_overdrive:
            return False
        if self._fuel_ratio(passive) < self._policy.min_fuel_ratio_for_overdrive:
            return False
        if (
            self._policy.overdrive_requires_terminal_burn
            and vertical_mode != "terminal_burn"
        ):
            return False
        return passive.vy_up < self._policy.emergency_vy_threshold or (
            alt < self._policy.emergency_low_alt
            and passive.vy_up < self._policy.emergency_low_alt_vy_threshold
        )

    def _fuel_ratio(self, passive: Sensors) -> float:
        max_fuel = max(1e-6, float(passive.max_fuel))
        return clamp(float(passive.fuel) / max_fuel, 0.0, 1.0)

    def _horizontal_controller(self, passive: Sensors, vx_sp: float) -> float:
        vx_err = vx_sp - passive.vx
        return (0.5 * vx_err) - (0.1 * passive.ax)

    def _vertical_controller(
        self,
        passive: Sensors,
        vy_sp: float,
        alt: float,
        vertical_mode: str,
        up_acc_max: float,
    ) -> float:
        if vertical_mode in ("coast", "eco_glide", "speed_dive"):
            return 0.0
        if vertical_mode == "coast_hold":
            vy_err = vy_sp - passive.vy_up
            # Keep correction burns thrust-backed without drifting into hover.
            a_up_cmd = 7.2 + (0.2 * vy_err)
            max_up_cmd = _GRAVITY_MAG if alt < 14.0 else max(0.0, _GRAVITY_MAG - 0.55)
            return clamp(a_up_cmd, 4.8, max_up_cmd)
        if vertical_mode == "terminal_burn":
            brake_gain = (
                self._policy.terminal_brake_gain_high_alt
                if alt > 8.0
                else self._policy.terminal_brake_gain_low_alt
            )
            a_up_cmd = _GRAVITY_MAG + (brake_gain * up_acc_max)
            if passive.vy_up > -0.7:
                a_up_cmd = min(a_up_cmd, _GRAVITY_MAG + (0.45 * up_acc_max))
            return a_up_cmd

        vy_err = vy_sp - passive.vy_up
        a_up_cmd = _GRAVITY_MAG + (0.38 * vy_err)
        if alt < 7.0:
            a_up_cmd += 0.08
        if alt < 3.0 and passive.vy_up > -0.45:
            a_up_cmd -= 0.12
        return a_up_cmd

    def _allocate_controls(
        self,
        dt: float,
        passive: Sensors,
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
        angle_cmd = math.asin(req)
        max_tilt = 0.18 if alt < 20.0 else 0.56
        angle_cmd = clamp(angle_cmd, -max_tilt, max_tilt)

        angle_cmd = rate_limit_angle_command(
            angle_cmd,
            self._prev_angle_cmd,
            dt,
        )
        self._prev_angle_cmd = angle_cmd

        cos_term = max(0.25, abs(math.cos(angle_cmd)))
        thrust = (mass * a_up_sp) / max(max_power * cos_term, 1e-3)
        if alt < 9.0 and abs(dx) <= 10.0:
            angle_cmd = 0.0
        if (
            alt < 2.5
            and abs(dx) <= 7.0
            and abs(passive.vx) < 0.6
            and abs(passive.vy_up) < 0.9
        ):
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
        return BotAction(target_thrust=thrust, target_angle=angle_cmd, refuel=False)

    def _guidance(
        self,
        passive: Sensors,
        target: RadarContact,
        *,
        max_force: float,
        max_throttle: float,
        ramp_up: float,
        projection: BallisticProjection,
        time_to_impact: float,
    ) -> GuidanceTargets:
        alt = finite_altitude(passive)
        dx = float(target.x) - float(passive.x)
        track_dx = projection.projected_dx
        _, up_acc_max = vehicle_limits(passive, max_force)

        down_speed = max(0.0, -float(passive.vy_up))
        nominal_throttle = min(1.0, max_throttle)
        spool_time = max(
            0.0, nominal_throttle - max(0.0, float(passive.thrust_level))
        ) / max(
            1e-3,
            ramp_up,
        )
        spool_distance = (down_speed * spool_time) + (
            0.5 * _GRAVITY_MAG * spool_time * spool_time
        )
        flare_speed = clamp(0.45 + (0.11 * alt), 0.6, 2.2)
        speed_to_kill = max(0.0, down_speed - flare_speed)
        stop_distance = (speed_to_kill * speed_to_kill) / (2.0 * max(1e-3, up_acc_max))
        burn_margin = 2.1 + (0.12 * max(0.0, abs(track_dx) - self._policy.align_band))
        burn_altitude = stop_distance + spool_distance + burn_margin

        time_to_brake = spool_time + (speed_to_kill / max(1e-3, up_acc_max))
        time_buffer = 0.15
        burn_now = bool(
            down_speed > 0.5
            and (
                alt <= burn_altitude or time_to_impact <= (time_to_brake + time_buffer)
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

        if (
            alt < self._policy.touchdown_altitude
            and abs(track_dx) <= self._policy.touchdown_track_band
        ):
            phase = "touchdown"
            vertical_mode = "flare"
            vy_sp = -clamp(0.3 + (0.06 * alt), 0.2, 0.7)
            vx_sp = clamp(vx_sp, -0.5, 0.5)

        return GuidanceTargets(
            phase=phase,
            vertical_mode=vertical_mode,
            vx_sp=vx_sp,
            vy_sp=vy_sp,
            dx=dx,
            alt=alt,
            burn_altitude=burn_altitude,
        )

    def update(self, dt: float, sensors: Sensors) -> BotAction:
        passive = sensors
        if passive.state in ("landed", "crashed", "out_of_fuel"):
            action = BotAction(
                0.0,
                passive.angle,
                False,
                status=f"{self._policy.status_prefix} {passive.state}",
            )
            self._set_display_state(
                phase=str(passive.state), summary=str(passive.state)
            )
            self.status = action.status
            return action

        max_power, min_throttle, max_throttle, ramp_up = self._engine_profile()
        max_force = max_power * max_throttle
        _, up_acc_max = vehicle_limits(passive, max_force)
        time_to_impact = estimate_ground_time_to_impact(
            altitude=finite_altitude(passive),
            vy_up=passive.vy_up,
            min_t_fall=0.0,
        )

        target = pick_target(passive, pinned_uid=self.pinned_target_uid)
        if target is None:
            alt = finite_altitude(passive)
            a_x_sp = self._horizontal_controller(passive, vx_sp=0.0)
            a_up_sp = self._vertical_controller(
                passive,
                vy_sp=-0.6,
                alt=alt,
                vertical_mode="flare",
                up_acc_max=up_acc_max,
            )
            action = self._allocate_controls(
                dt,
                passive,
                a_x_sp=a_x_sp,
                a_up_sp=a_up_sp,
                dx=0.0,
                alt=alt,
                vertical_mode="flare",
                max_power=max_power,
                min_throttle=min_throttle,
                max_throttle=max_throttle,
            )
            action.status = f"{self._policy.status_prefix} search"
            self._set_display_state(phase="search", summary="searching target")
            self.status = action.status
            return action

        dx = float(target.x) - float(passive.x)
        dy = float(target.y) - float(passive.y)
        projection = estimate_target_y_projection(
            dx=dx,
            dy=dy,
            vx=passive.vx,
            vy_up=passive.vy_up,
            x=passive.x,
            y=passive.y,
            min_t_fall=0.0,
        )
        time_to_impact = projection.t_fall

        guidance = self._guidance(
            passive,
            target,
            max_force=max_force,
            max_throttle=max_throttle,
            ramp_up=ramp_up,
            projection=projection,
            time_to_impact=time_to_impact,
        )
        if (
            guidance.vertical_mode == "coast"
            and abs(guidance.dx) <= self._policy.coast_horiz_deadband
        ):
            a_x_sp = 0.0
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
            f"{self._policy.status_prefix} {guidance.phase} "
            f"dx={stable(guidance.dx, 1):.1f} vy={stable(passive.vy_up, 1):.1f}"
        )
        self._set_display_state(
            phase=guidance.phase,
            summary=(
                f"dx={stable(guidance.dx, 1):.1f} "
                f"vy={stable(passive.vy_up, 1):.1f}->{stable(guidance.vy_sp, 1):.1f}"
            ),
        )
        self.status = action.status
        return action

    def get_display_state(self) -> BotDisplayState | None:
        return BotDisplayState(
            bot_name="plunge",
            mode="flight",
            phase=self._display_phase,
            summary=self._display_summary,
        )


def create_bot() -> Bot:
    return PlungeBot()


def list_behavior_names() -> tuple[str, ...]:
    return ("balanced",)


__all__ = ["PlungeBot", "create_bot", "list_behavior_names"]
