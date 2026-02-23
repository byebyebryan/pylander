"""Unified descent bot for the benchmark descent level."""

from __future__ import annotations

import math
from dataclasses import dataclass

from core.bot import ActiveSensors, Bot, BotAction, PassiveSensors
from core.sensor import RadarContact


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _stable(value: float, digits: int = 1) -> float:
    epsilon = 0.5 * (10.0 ** (-digits))
    return 0.0 if abs(value) < epsilon else value


def _pick_target(passive: PassiveSensors) -> RadarContact | None:
    contacts = passive.radar_contacts or []
    if not contacts:
        return None
    inner = [c for c in contacts if c.is_inner_lock]
    candidates = inner if inner else contacts
    return min(candidates, key=lambda c: c.distance)


@dataclass(frozen=True)
class _GuidanceTargets:
    phase: str
    vertical_mode: str
    vx_sp: float
    vy_sp: float
    dx: float
    alt: float
    burn_altitude: float


class DescentBot(Bot):
    def __init__(self) -> None:
        super().__init__()
        self._prev_angle_cmd = 0.0

    @staticmethod
    def _finite_altitude(passive: PassiveSensors) -> float:
        if math.isfinite(passive.altitude):
            return passive.altitude
        return 1e9

    @staticmethod
    def _vehicle_limits(passive: PassiveSensors, max_force: float) -> tuple[float, float]:
        mass = max(0.5, passive.mass)
        up_acc_max = max(0.1, (max_force / mass) - 9.8)
        return mass, up_acc_max

    def _engine_profile(self) -> tuple[float, float, float, float]:
        if self.vehicle_info is None:
            return 50.0, 0.0, 1.0, 2.0
        max_power = max(1e-3, float(self.vehicle_info.max_thrust_power))
        max_throttle = max(0.0, float(self.vehicle_info.max_thrust))
        min_throttle = max(0.0, min(float(self.vehicle_info.min_thrust), max_throttle))
        ramp_up = max(0.1, float(self.vehicle_info.thrust_increase_rate))
        return max_power, min_throttle, max_throttle, ramp_up

    def _guidance(
        self,
        passive: PassiveSensors,
        target: RadarContact,
        *,
        max_force: float,
        max_throttle: float,
        ramp_up: float,
    ) -> _GuidanceTargets:
        alt = self._finite_altitude(passive)
        dx = target.x - passive.x
        abs_dx = abs(dx)
        _, up_acc_max = self._vehicle_limits(passive, max_force)

        align_band = 10.0
        vx_cap = _clamp(2.2 + (0.03 * alt), 2.2, 8.0)
        vx_sp = _clamp(dx * 0.09, -vx_cap, vx_cap)

        down_speed = max(0.0, -passive.vy_up)
        nominal_throttle = min(1.0, max_throttle)
        spool_time = max(0.0, nominal_throttle - max(0.0, passive.thrust_level)) / ramp_up
        spool_distance = (down_speed * spool_time) + (4.9 * spool_time * spool_time)
        flare_speed = _clamp(0.45 + (0.11 * alt), 0.7, 2.5)
        speed_to_kill = max(0.0, down_speed - flare_speed)
        stop_distance = (speed_to_kill * speed_to_kill) / (2.0 * max(up_acc_max, 1e-3))
        burn_margin = 2.1 + (0.12 * max(0.0, abs_dx - align_band))
        burn_altitude = stop_distance + spool_distance + burn_margin

        time_to_impact = alt / max(0.1, down_speed) if down_speed > 0.1 else float("inf")
        time_to_brake = spool_time + (speed_to_kill / max(up_acc_max, 1e-3))
        burn_now = bool(
            down_speed > 0.6
            and (
                alt <= burn_altitude
                or time_to_impact <= (time_to_brake + 0.2)
            )
        )

        if burn_now:
            vertical_mode = "terminal_burn"
            vy_sp = -_clamp(0.45 + (0.11 * alt), 0.55, 2.2)
            vx_sp = _clamp(vx_sp, -1.2, 1.2)
        elif alt < 7.0 and abs_dx <= 10.0:
            vertical_mode = "flare"
            vy_sp = -_clamp(0.35 + (0.09 * alt), 0.45, 1.0)
            vx_sp = _clamp(vx_sp, -0.8, 0.8)
        elif abs_dx > align_band and alt < 45.0:
            phase = "align"
            vertical_mode = "coast"
            vy_sp = -_clamp(1.1 + (0.18 * math.sqrt(max(0.0, alt))), 1.2, 3.0)
            vx_sp = _clamp(dx * 0.13, -7.5, 7.5)
        else:
            vertical_mode = "coast"
            vy_sp = -_clamp(1.2 + (0.3 * math.sqrt(max(0.0, alt))), 1.4, 6.0)

        if alt < 4.2 and abs_dx <= 8.0:
            phase = "touchdown"
            vertical_mode = "flare"
            vy_sp = -_clamp(0.3 + (0.07 * alt), 0.4, 0.75)
        elif burn_now:
            phase = "terminal_burn"
        elif vertical_mode == "flare":
            phase = "flare"
        elif abs_dx > align_band and alt < 45.0:
            phase = "align"
        else:
            phase = "coast"

        return _GuidanceTargets(
            phase=phase,
            vertical_mode=vertical_mode,
            vx_sp=vx_sp,
            vy_sp=vy_sp,
            dx=dx,
            alt=alt,
            burn_altitude=burn_altitude,
        )

    def _horizontal_controller(
        self,
        passive: PassiveSensors,
        vx_sp: float,
    ) -> float:
        vx_err = vx_sp - passive.vx
        return (0.5 * vx_err) - (0.1 * passive.ax)

    def _vertical_controller(
        self,
        passive: PassiveSensors,
        vy_sp: float,
        alt: float,
        vertical_mode: str,
        up_acc_max: float,
    ) -> float:
        if vertical_mode == "coast":
            return 0.0
        if vertical_mode == "terminal_burn":
            brake_gain = 0.94 if alt > 8.0 else 0.82
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
        max_power, min_throttle, max_throttle, _ = self._engine_profile()
        max_force = max_power * max_throttle
        mass, _ = self._vehicle_limits(passive, max_force)

        # Parallel allocator: lateral acceleration chooses tilt.
        req = _clamp((a_x_sp * mass) / max(max_force, 1e-3), -0.95, 0.95)
        angle_cmd = math.asin(req)
        max_tilt = 0.18 if alt < 20.0 else 0.56
        angle_cmd = _clamp(angle_cmd, -max_tilt, max_tilt)

        # Rate-limited command to keep motion smooth and reliable.
        max_delta = 2.2 * max(dt, 1e-3)
        angle_cmd = _clamp(
            angle_cmd,
            self._prev_angle_cmd - max_delta,
            self._prev_angle_cmd + max_delta,
        )
        self._prev_angle_cmd = angle_cmd

        cos_term = max(0.25, abs(math.cos(angle_cmd)))
        thrust = (mass * a_up_sp) / max(max_power * cos_term, 1e-3)
        if alt < 9.0 and abs(dx) <= 10.0:
            angle_cmd = 0.0
        if alt < 2.5 and abs(dx) <= 7.0 and abs(passive.vx) < 0.6 and abs(passive.vy_up) < 0.9:
            thrust = 0.0
            angle_cmd = 0.0

        emergency_overdrive = vertical_mode == "terminal_burn" and (
            passive.vy_up < -6.0 or (alt < 12.0 and passive.vy_up < -3.5)
        )
        if thrust > 1.0 and not emergency_overdrive:
            thrust = 1.0

        thrust = _clamp(thrust, 0.0, max_throttle)
        if thrust > 0.0:
            thrust = max(min_throttle, thrust)
        return BotAction(target_thrust=thrust, target_angle=angle_cmd, refuel=False)

    def update(
        self,
        dt: float,
        passive: PassiveSensors,
        active: ActiveSensors,
    ) -> BotAction:
        _ = active
        if passive.state in ("landed", "crashed", "out_of_fuel"):
            action = BotAction(0.0, passive.angle, False, status=f"descent:{passive.state}")
            self.status = action.status
            return action

        max_power, _, max_throttle, ramp_up = self._engine_profile()
        max_force = max_power * max_throttle
        _, up_acc_max = self._vehicle_limits(passive, max_force)

        target = _pick_target(passive)
        if target is None:
            a_x_sp = self._horizontal_controller(passive, vx_sp=0.0)
            a_up_sp = self._vertical_controller(
                passive,
                vy_sp=-1.0,
                alt=self._finite_altitude(passive),
                vertical_mode="flare",
                up_acc_max=up_acc_max,
            )
            action = self._allocate_controls(
                dt,
                passive,
                a_x_sp=a_x_sp,
                a_up_sp=a_up_sp,
                dx=0.0,
                alt=self._finite_altitude(passive),
                vertical_mode="flare",
            )
            action.status = "descent:search"
            self.status = action.status
            return action

        guidance = self._guidance(
            passive,
            target,
            max_force=max_force,
            max_throttle=max_throttle,
            ramp_up=ramp_up,
        )
        if guidance.vertical_mode == "coast" and abs(guidance.dx) <= 14.0:
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
        )

        action.status = (
            f"descent:{guidance.phase} dx:{_stable(guidance.dx, 1):6.1f} "
            f"vx:{_stable(passive.vx, 1):5.1f} vy:{_stable(passive.vy_up, 1):5.1f} "
            f"vys:{_stable(guidance.vy_sp, 1):5.1f} "
            f"balt:{_stable(guidance.burn_altitude, 1):5.1f}"
        )
        self.status = action.status
        return action


def create_bot() -> Bot:
    return DescentBot()


__all__ = ["DescentBot", "create_bot"]
