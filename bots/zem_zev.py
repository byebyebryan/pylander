"""Unified ZEM/ZEV powered-descent bot."""

from __future__ import annotations

import math
from dataclasses import dataclass

from bots._ballistics import ballistic_time_to_impact, estimate_ballistic_projection
from bots._bot_math import clamp, engine_profile, finite_altitude, stable
from bots._drop_control import rate_limit_angle_command
from bots._targeting import pick_target
from core.bot import ActiveSensors, Bot, BotAction, PassiveSensors
from core.config import GRAVITY


@dataclass(frozen=True)
class ZemZevConfig:
    t_go_min: float = 0.8
    t_go_max: float = 12.0
    zem_pos_gain_x: float = 2.0
    zem_pos_gain_y: float = 0.3
    zev_vel_gain_x: float = 1.0
    zev_vel_gain_y: float = 0.15
    vy_target_base: float = 0.25
    vy_target_sqrt_gain: float = 0.07
    vy_target_min: float = 0.25
    vy_target_max: float = 2.4
    anti_hover_alt: float = 24.0
    anti_hover_dx: float = 24.0
    anti_hover_vy_min: float = 1.0
    net_ax_cap: float = 8.8
    net_ax_cap_low_alt: float = 4.2
    net_ax_cap_low_alt_threshold: float = 22.0
    thrust_ay_cap: float = 22.0
    max_tilt: float = 0.62
    max_tilt_low_alt: float = 0.18
    max_tilt_low_alt_far: float = 0.34
    low_alt_tilt_alt: float = 20.0
    low_alt_tilt_dx: float = 12.0
    low_alt_tilt_vx: float = 2.4
    angle_rate: float = 2.4
    touchdown_zero_alt: float = 2.4
    touchdown_zero_dx: float = 7.0
    touchdown_zero_vx: float = 0.55
    touchdown_zero_vy: float = 0.9
    emergency_vy: float = 12.0
    emergency_alt: float = 240.0
    stop_margin: float = 3.5
    brake_gain: float = 0.4


class ZemZevBot(Bot):
    def __init__(self, behavior: str = "zem_zev") -> None:
        super().__init__()
        self._cfg = ZemZevConfig()
        self._behavior = "zem_zev"
        self._prev_angle_cmd = 0.0
        self._debug_summary = ""
        self.set_behavior(behavior)

    def set_behavior(self, behavior: str) -> None:
        key = str(behavior).strip().lower().replace("-", "_")
        if key != "zem_zev":
            raise ValueError(
                f"Unknown zem_zev behavior '{behavior}'. Expected one of: zem_zev"
            )
        self._behavior = "zem_zev"
        self._prev_angle_cmd = 0.0
        self._debug_summary = ""

    @property
    def behavior(self) -> str:
        return self._behavior

    def _ballistic_clearance(self) -> float:
        if self.vehicle_info is None:
            return 0.0
        return max(0.0, 0.5 * float(self.vehicle_info.height))

    def _resolve_target_error(self, passive: PassiveSensors) -> tuple[float, float]:
        target = pick_target(passive)
        if target is not None:
            return float(target.x) - float(passive.x), float(target.y) - float(passive.y)
        return 0.0, -max(0.0, finite_altitude(passive))

    def _t_go(self, passive: PassiveSensors, active: ActiveSensors, dx: float) -> tuple[float, float]:
        cfg = self._cfg
        alt = max(0.0, finite_altitude(passive))
        projection = estimate_ballistic_projection(
            dx=dx,
            alt=alt,
            vx=passive.vx,
            vy_up=passive.vy_up,
            x=passive.x,
            y=passive.y,
            active=active,
            clearance=self._ballistic_clearance(),
            segment_length=20.0,
            max_points=192,
        )
        return clamp(float(projection.t_fall), cfg.t_go_min, cfg.t_go_max), float(
            projection.projected_dx
        )

    def _desired_terminal_vy(self, alt: float, dx: float, vx: float) -> float:
        cfg = self._cfg
        vy_mag = clamp(
            cfg.vy_target_base + (cfg.vy_target_sqrt_gain * math.sqrt(max(0.0, alt))),
            cfg.vy_target_min,
            cfg.vy_target_max,
        )
        if alt <= cfg.anti_hover_alt and (abs(dx) > cfg.anti_hover_dx or abs(vx) > 2.0):
            vy_mag = max(vy_mag, cfg.anti_hover_vy_min)
        return -vy_mag

    def _zem_zev_thrust_accel(
        self,
        passive: PassiveSensors,
        *,
        dx: float,
        dy: float,
        t_go: float,
    ) -> tuple[float, float, float, float]:
        cfg = self._cfg
        gravity_mag = abs(float(GRAVITY))
        g_up = -gravity_mag
        vx = float(passive.vx)
        vy = float(passive.vy_up)
        vy_target = self._desired_terminal_vy(max(0.0, finite_altitude(passive)), dx, vx)

        zem_x = dx - (vx * t_go)
        zem_y = dy - (vy * t_go) - (0.5 * g_up * t_go * t_go)
        zev_x = 0.0 - (vx + (0.0 * t_go))
        zev_y = vy_target - (vy + (g_up * t_go))

        ax_cmd = (
            (cfg.zem_pos_gain_x / max(1e-3, t_go * t_go)) * zem_x
            + (cfg.zev_vel_gain_x / max(1e-3, t_go)) * zev_x
        )
        ay_cmd = (
            (cfg.zem_pos_gain_y / max(1e-3, t_go * t_go)) * zem_y
            + (cfg.zev_vel_gain_y / max(1e-3, t_go)) * zev_y
        )

        ax_cap = cfg.net_ax_cap
        if finite_altitude(passive) <= cfg.net_ax_cap_low_alt_threshold:
            ax_cap = min(ax_cap, cfg.net_ax_cap_low_alt)
        ax_cmd = clamp(ax_cmd, -ax_cap, ax_cap)
        ay_cmd = clamp(ay_cmd, 0.0, cfg.thrust_ay_cap)
        return ax_cmd, ay_cmd, zem_x, zev_x

    def update(
        self,
        dt: float,
        passive: PassiveSensors,
        active: ActiveSensors,
    ) -> BotAction:
        if passive.state in ("landed", "crashed", "out_of_fuel"):
            action = BotAction(0.0, passive.angle, False, status=f"zem_zev:{passive.state}")
            self.status = action.status
            self._debug_summary = ""
            return action

        cfg = self._cfg
        max_power, min_throttle, max_throttle, _ = engine_profile(self.vehicle_info)
        mass = max(0.5, float(passive.mass))
        gravity_mag = abs(float(GRAVITY))
        max_force = max_power * max_throttle
        up_acc_max = max(0.1, (max_force / mass) - gravity_mag)

        dx, dy = self._resolve_target_error(passive)
        t_go, projected_dx = self._t_go(passive, active, dx)
        a_x_thrust, a_up_thrust, zem_x, zev_x = self._zem_zev_thrust_accel(
            passive,
            dx=dx,
            dy=dy,
            t_go=t_go,
        )
        alt = max(0.0, finite_altitude(passive))
        down_speed = max(0.0, -float(passive.vy_up))
        flare_speed = clamp(0.45 + (0.11 * alt), 0.7, 6.0)
        speed_to_kill = max(0.0, down_speed - flare_speed)
        stop_distance = (speed_to_kill * speed_to_kill) / (2.0 * max(1e-3, up_acc_max))
        if alt <= (stop_distance + cfg.stop_margin):
            a_up_thrust = max(a_up_thrust, gravity_mag + (cfg.brake_gain * up_acc_max))
        if down_speed >= cfg.emergency_vy and alt <= cfg.emergency_alt:
            a_up_thrust = max(a_up_thrust, gravity_mag + up_acc_max)
        a_up_thrust = clamp(a_up_thrust, 0.0, gravity_mag + up_acc_max)

        max_tilt = cfg.max_tilt
        if alt < cfg.low_alt_tilt_alt:
            if abs(dx) <= cfg.low_alt_tilt_dx and abs(float(passive.vx)) <= cfg.low_alt_tilt_vx:
                max_tilt = cfg.max_tilt_low_alt
            else:
                max_tilt = cfg.max_tilt_low_alt_far
        angle_target = math.atan2(a_x_thrust, max(0.2, a_up_thrust))
        angle_target = clamp(angle_target, -max_tilt, max_tilt)
        angle_cmd = rate_limit_angle_command(
            angle_target,
            self._prev_angle_cmd,
            dt,
            max_rate=cfg.angle_rate,
        )
        self._prev_angle_cmd = angle_cmd

        thrust_acc = math.hypot(a_x_thrust, a_up_thrust)
        thrust = (mass * thrust_acc) / max(max_power, 1e-3)
        if (
            alt < cfg.touchdown_zero_alt
            and abs(dx) <= cfg.touchdown_zero_dx
            and abs(float(passive.vx)) <= cfg.touchdown_zero_vx
            and abs(float(passive.vy_up)) <= cfg.touchdown_zero_vy
        ):
            thrust = 0.0
            angle_cmd = 0.0
        thrust = clamp(thrust, 0.0, max_throttle)
        if thrust > 0.0:
            thrust = max(min_throttle, thrust)

        tti, tti_source = ballistic_time_to_impact(passive, active)
        self._debug_summary = (
            f"zem tgo:{stable(t_go, 2):4.1f} "
            f"pdx:{stable(projected_dx, 1):5.1f} "
            f"zx:{stable(zem_x, 1):6.1f} "
            f"zvx:{stable(zev_x, 1):5.1f} "
            f"tti:{stable(tti, 1):4.1f}{tti_source[:1]}"
        )
        action = BotAction(
            target_thrust=thrust,
            target_angle=angle_cmd,
            refuel=False,
            status=(
                f"zem_zev:tgo dx:{stable(dx, 1):6.1f} "
                f"vx:{stable(passive.vx, 1):5.1f} vy:{stable(passive.vy_up, 1):5.1f}"
            ),
        )
        self.status = action.status
        return action

    def get_headless_stats(self) -> str:
        base = super().get_headless_stats()
        if not self._debug_summary:
            return base
        if not base:
            return self._debug_summary
        return f"{base} {self._debug_summary}"


def create_bot() -> Bot:
    return ZemZevBot()


def list_behavior_names() -> tuple[str, ...]:
    return ("zem_zev",)


__all__ = ["ZemZevBot", "create_bot", "list_behavior_names"]

