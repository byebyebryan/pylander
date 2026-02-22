"""Unified descent bot for the benchmark descent level."""

from __future__ import annotations

import math
from dataclasses import dataclass

from core.bot import ActiveSensors, Bot, BotAction, PassiveSensors
from core.sensor import RadarContact


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


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
    vx_sp: float
    vy_sp: float
    dx: float
    alt: float
    terminal_burn: bool


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
    def _vehicle_limits(passive: PassiveSensors, max_thrust: float) -> tuple[float, float]:
        mass = max(0.5, passive.mass)
        up_acc_max = max(0.1, (max_thrust / mass) - 9.8)
        return mass, up_acc_max

    def _guidance(
        self,
        passive: PassiveSensors,
        target: RadarContact,
        *,
        max_thrust: float,
    ) -> _GuidanceTargets:
        alt = self._finite_altitude(passive)
        dx = target.x - passive.x
        abs_dx = abs(dx)
        _, up_acc_max = self._vehicle_limits(passive, max_thrust)

        align_band = 10.0
        vx_cap = _clamp(3.6 + (0.042 * alt), 3.6, 11.5)
        vx_sp = _clamp(dx * 0.11, -vx_cap, vx_cap)

        # Continuous descent profile: faster at high altitude, smoothly tapering near ground.
        vy_sp = -(0.6 + (0.43 * math.sqrt(max(0.0, alt))))
        vy_sp = _clamp(vy_sp, -8.0, -1.1)

        if abs_dx > align_band and alt < 45.0:
            vy_sp = max(vy_sp, -1.35)
            vx_sp = _clamp(dx * 0.14, -8.5, 8.5)

        down_speed = max(0.0, -passive.vy_up)
        time_to_impact = alt / max(0.1, down_speed) if down_speed > 0.1 else float("inf")
        time_to_stop = down_speed / max(up_acc_max, 1e-3)
        stop_distance = (down_speed * down_speed) / (2.0 * max(up_acc_max, 1e-3))
        terminal_burn = bool(
            down_speed > 0.8
            and (
                time_to_impact <= (time_to_stop + 0.35)
                or alt <= (stop_distance + 7.0)
            )
        )

        if terminal_burn and alt < 22.0:
            vy_sp = -_clamp(0.35 + (0.16 * alt), 0.4, 1.4)
        if abs_dx <= align_band and alt < 16.0:
            vy_sp = max(vy_sp, -0.75)
            vx_sp = _clamp(vx_sp, -0.8, 0.8)

        if alt < 5.0 and abs_dx <= 8.0:
            phase = "touchdown"
        elif terminal_burn:
            phase = "terminal_burn"
        elif abs_dx > align_band and alt < 45.0:
            phase = "align"
        else:
            phase = "descent"
        return _GuidanceTargets(
            phase=phase,
            vx_sp=vx_sp,
            vy_sp=vy_sp,
            dx=dx,
            alt=alt,
            terminal_burn=terminal_burn,
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
        dx: float,
        terminal_burn: bool,
    ) -> float:
        vy_err = vy_sp - passive.vy_up
        alt_sp = 3.5 if abs(dx) <= 10.0 else 8.0
        alt_err = alt_sp - alt
        # This is target upward acceleration; gravity is added in allocator.
        a_up_cmd = 9.8 + (0.19 * vy_err) + (0.012 * alt_err)
        if terminal_burn:
            a_up_cmd += 0.08
        if alt < 20.0 and passive.vy_up < -3.2:
            a_up_cmd += 0.12
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
    ) -> BotAction:
        max_thrust = (
            self.vehicle_info.max_thrust_power if self.vehicle_info is not None else 50.0
        )
        max_thrust = max(1e-3, max_thrust)
        mass, _ = self._vehicle_limits(passive, max_thrust)

        # Parallel allocator: lateral acceleration chooses tilt.
        req = _clamp((a_x_sp * mass) / max_thrust, -0.95, 0.95)
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
        thrust = (mass * a_up_sp) / max(max_thrust * cos_term, 1e-3)
        if alt < 9.0 and abs(dx) <= 10.0:
            angle_cmd = 0.0
        if alt < 2.5 and abs(dx) <= 7.0 and abs(passive.vx) < 0.6 and abs(passive.vy_up) < 0.9:
            thrust = 0.0
            angle_cmd = 0.0

        thrust = _clamp(thrust, 0.0, 1.0)
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

        max_thrust = (
            self.vehicle_info.max_thrust_power if self.vehicle_info is not None else 50.0
        )
        max_thrust = max(1e-3, max_thrust)

        target = _pick_target(passive)
        if target is None:
            a_x_sp = self._horizontal_controller(passive, vx_sp=0.0)
            a_up_sp = self._vertical_controller(
                passive,
                vy_sp=-1.0,
                alt=self._finite_altitude(passive),
                dx=0.0,
                terminal_burn=False,
            )
            action = self._allocate_controls(
                dt,
                passive,
                a_x_sp=a_x_sp,
                a_up_sp=a_up_sp,
                dx=0.0,
                alt=self._finite_altitude(passive),
            )
            action.status = "descent:search"
            self.status = action.status
            return action

        guidance = self._guidance(passive, target, max_thrust=max_thrust)
        a_x_sp = self._horizontal_controller(passive, guidance.vx_sp)
        a_up_sp = self._vertical_controller(
            passive,
            guidance.vy_sp,
            guidance.alt,
            guidance.dx,
            guidance.terminal_burn,
        )
        action = self._allocate_controls(
            dt,
            passive,
            a_x_sp=a_x_sp,
            a_up_sp=a_up_sp,
            dx=guidance.dx,
            alt=guidance.alt,
        )

        action.status = (
            f"descent:{guidance.phase} dx:{guidance.dx:6.1f} "
            f"vx:{passive.vx:5.1f} vy:{passive.vy_up:5.1f} "
            f"vys:{guidance.vy_sp:5.1f}"
        )
        self.status = action.status
        return action


def create_bot() -> Bot:
    return DescentBot()


__all__ = ["DescentBot", "create_bot"]
