"""Unified descent bot for the benchmark descent level."""

from __future__ import annotations

import math

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


class DescentBot(Bot):
    def __init__(self) -> None:
        super().__init__()
        self._prev_angle_cmd = 0.0

    @staticmethod
    def _finite_altitude(passive: PassiveSensors) -> float:
        if math.isfinite(passive.altitude):
            return passive.altitude
        return 1e9

    def _velocity_targets(
        self,
        passive: PassiveSensors,
        target: RadarContact,
    ) -> tuple[float, float, float, float]:
        alt = self._finite_altitude(passive)
        dx = target.x - passive.x
        abs_dx = abs(dx)

        align_band = 10.0
        vx_cap = _clamp(4.0 + (0.045 * alt), 4.0, 12.0)
        vx_sp = _clamp(dx * 0.1, -vx_cap, vx_cap)

        if alt > 180.0:
            vy_sp = -7.2
        elif alt > 130.0:
            vy_sp = -5.9
        elif alt > 90.0:
            vy_sp = -4.6
        elif alt > 55.0:
            vy_sp = -3.5
        elif alt > 30.0:
            vy_sp = -2.4
        else:
            vy_sp = -1.6

        if abs_dx > align_band and alt < 40.0:
            vy_sp = max(vy_sp, -1.2)
            vx_sp = _clamp(dx * 0.14, -8.0, 8.0)

        if abs_dx <= align_band and alt < 14.0:
            vy_sp = -0.85
            vx_sp = _clamp(vx_sp, -0.8, 0.8)

        return vx_sp, vy_sp, dx, alt

    def _control_action(
        self,
        dt: float,
        passive: PassiveSensors,
        vx_sp: float,
        vy_sp: float,
        dx: float,
        alt: float,
    ) -> BotAction:
        mass = max(0.5, passive.mass)
        max_thrust = (
            self.vehicle_info.max_thrust_power if self.vehicle_info is not None else 50.0
        )
        max_thrust = max(1e-3, max_thrust)

        vx_err = vx_sp - passive.vx
        a_x_sp = (0.52 * vx_err) - (0.1 * passive.ax)
        req = _clamp((a_x_sp * mass) / max_thrust, -0.95, 0.95)
        angle_cmd = math.asin(req)
        max_tilt = 0.18 if alt < 20.0 else 0.56
        angle_cmd = _clamp(angle_cmd, -max_tilt, max_tilt)

        max_delta = 2.2 * max(dt, 1e-3)
        angle_cmd = _clamp(
            angle_cmd,
            self._prev_angle_cmd - max_delta,
            self._prev_angle_cmd + max_delta,
        )
        self._prev_angle_cmd = angle_cmd

        cos_term = max(0.25, abs(math.cos(angle_cmd)))
        hover = (9.8 * mass) / max(max_thrust * cos_term, 1e-3)
        vy_err = vy_sp - passive.vy_up
        alt_sp = 4.0 if abs(dx) <= 10.0 else 8.5
        alt_err = alt_sp - alt
        thrust = hover + (0.17 * vy_err) + (0.014 * alt_err)

        if alt < 20.0 and passive.vy_up < -3.0:
            thrust += 0.1
        if alt < 9.0 and abs(dx) <= 10.0:
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

        target = _pick_target(passive)
        if target is None:
            action = self._control_action(
                dt,
                passive,
                vx_sp=0.0,
                vy_sp=-1.0,
                dx=0.0,
                alt=self._finite_altitude(passive),
            )
            action.status = "descent:search"
            self.status = action.status
            return action

        vx_sp, vy_sp, dx, alt = self._velocity_targets(passive, target)
        action = self._control_action(
            dt,
            passive,
            vx_sp=vx_sp,
            vy_sp=vy_sp,
            dx=dx,
            alt=alt,
        )

        if alt < 14.0 and abs(dx) <= 10.0:
            phase = "flare"
        elif abs(dx) > 10.0 and alt < 40.0:
            phase = "align"
        else:
            phase = "descent"
        action.status = (
            f"descent:{phase} dx:{dx:6.1f} "
            f"vx:{passive.vx:5.1f} vy:{passive.vy_up:5.1f}"
        )
        self.status = action.status
        return action


def create_bot() -> Bot:
    return DescentBot()


__all__ = ["DescentBot", "create_bot"]
