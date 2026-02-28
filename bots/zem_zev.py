"""Optimizer-first powered descent bot (ZEM/ZEV replacement).

This version uses a receding-horizon convex optimizer to generate coupled
horizontal/vertical thrust commands from a single objective each replan cycle.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from bots._bot_math import clamp, engine_profile, finite_altitude, rate_limit_angle_command, stable
from bots._optimizer_pdg import PDGOptimizer, PDGOptimizerConfig, PDGPlan
from bots._targeting import pick_target, target_half_width
from core.bot import ActiveSensors, Bot, BotAction, PassiveSensors
from core.config import GRAVITY

_GRAVITY_MAG = abs(float(GRAVITY))


@dataclass(frozen=True)
class ZemZevConfig:
    # Receding horizon scheduling
    replan_hz: float = 6.0
    replan_dx_error: float = 24.0
    replan_dy_error: float = 18.0
    replan_vx_error: float = 4.0
    replan_vy_error: float = 4.0
    fallback_hold_steps: int = 12

    # Attitude/allocator limits
    max_tilt: float = 0.78
    max_tilt_low_alt: float = 0.18
    max_tilt_low_alt_far: float = 0.34
    low_alt_tilt_alt: float = 20.0
    low_alt_tilt_dx: float = 12.0
    low_alt_tilt_vx: float = 2.4
    angle_rate: float = 2.4
    throttle_off_threshold_scale: float = 0.85

    # Braking-envelope vertical speed schedule (time-optimal leaning).
    braking_alt_margin: float = 6.0
    braking_tilt_scale: float = 1.00
    braking_accel_safety: float = 0.58
    braking_min_speed: float = 1.2
    braking_max_speed: float = 55.0
    braking_target_ratio: float = 0.48
    braking_floor_ratio: float = 0.22
    vy_low_alt_cap_alt: float = 40.0
    vy_low_alt_cap: float = 9.5
    vy_touch_cap_alt: float = 8.0
    vy_touch_cap: float = 2.4

    # Touchdown cut
    touchdown_zero_alt: float = 2.4
    touchdown_zero_vx: float = 0.55
    touchdown_zero_vy: float = 0.95

    # Safety brake when descent rate is critical
    emergency_vy: float = 12.0
    emergency_alt: float = 220.0


class ZemZevBot(Bot):
    def __init__(self, behavior: str = "zem_zev") -> None:
        super().__init__()
        self._cfg = ZemZevConfig()
        self._optimizer = PDGOptimizer(PDGOptimizerConfig())

        self._behavior = "zem_zev"
        self._prev_angle_cmd = 0.0
        self._angle_cmd_initialized = False
        self._last_target_half = 55.0

        self._plan: PDGPlan | None = None
        self._plan_elapsed = 0.0
        self._replan_timer = 0.0
        self._fallback_steps_remaining = 0
        self._last_solve_ms = 0.0
        self._last_solver_status = ""

        self.set_behavior(behavior)

    def set_behavior(self, behavior: str) -> None:
        key = str(behavior).strip().lower().replace("-", "_")
        if key != "zem_zev":
            raise ValueError(
                f"Unknown zem_zev behavior '{behavior}'. Expected one of: zem_zev"
            )
        self._behavior = "zem_zev"
        self._reset_state()

    def _reset_state(self) -> None:
        self._prev_angle_cmd = 0.0
        self._angle_cmd_initialized = False
        self._plan = None
        self._plan_elapsed = 0.0
        self._replan_timer = 0.0
        self._fallback_steps_remaining = 0
        self._last_solve_ms = 0.0
        self._last_solver_status = ""
        self._last_target_half = 55.0

    @property
    def behavior(self) -> str:
        return self._behavior

    def _braking_speed_limit(self, alt: float, max_thrust_accel: float, max_tilt: float) -> float:
        cfg = self._cfg
        alt_eff = max(0.0, alt - cfg.braking_alt_margin)
        tilt_eff = cfg.braking_tilt_scale * max_tilt
        vertical_brake = max(
            0.7,
            cfg.braking_accel_safety * ((max_thrust_accel * math.cos(tilt_eff)) - _GRAVITY_MAG),
        )
        speed = math.sqrt(max(0.0, (cfg.vy_touch_cap * cfg.vy_touch_cap) + (2.0 * vertical_brake * alt_eff)))
        return clamp(speed, cfg.braking_min_speed, cfg.braking_max_speed)

    def _desired_terminal_vy(self, alt: float, max_thrust_accel: float, max_tilt: float) -> float:
        cfg = self._cfg
        vy_mag = cfg.braking_target_ratio * self._braking_speed_limit(alt, max_thrust_accel, max_tilt)
        if alt <= cfg.vy_low_alt_cap_alt:
            vy_mag = min(vy_mag, cfg.vy_low_alt_cap)
        if alt <= cfg.vy_touch_cap_alt:
            vy_mag = min(vy_mag, cfg.vy_touch_cap)
        return -max(cfg.braking_min_speed, vy_mag)

    def _descent_floor_vy(self, alt: float, max_thrust_accel: float, max_tilt: float) -> float:
        cfg = self._cfg
        vy_mag = cfg.braking_floor_ratio * self._braking_speed_limit(alt, max_thrust_accel, max_tilt)
        if alt <= cfg.vy_low_alt_cap_alt:
            vy_mag = min(vy_mag, cfg.vy_low_alt_cap + 1.2)
        if alt <= cfg.vy_touch_cap_alt:
            vy_mag = min(vy_mag, cfg.vy_touch_cap + 0.3)
        return -max(cfg.braking_min_speed, vy_mag)

    def _resolve_max_tilt(self, alt: float, dx: float, vx: float) -> float:
        cfg = self._cfg
        if alt < cfg.low_alt_tilt_alt:
            if abs(dx) <= cfg.low_alt_tilt_dx and abs(vx) <= cfg.low_alt_tilt_vx:
                return cfg.max_tilt_low_alt
            return cfg.max_tilt_low_alt_far
        return cfg.max_tilt

    def _plan_index(self) -> int:
        if self._plan is None:
            return 0
        step_dt = max(1e-3, float(self._optimizer._cfg.step_dt))
        idx = int(self._plan_elapsed / step_dt)
        return max(0, min(len(self._plan.ax) - 1, idx))

    def _state_deviation_requires_replan(self, passive: PassiveSensors) -> bool:
        if self._plan is None or not self._plan.feasible:
            return True
        idx = self._plan_index()
        cfg = self._cfg
        err_x = abs(float(passive.x) - float(self._plan.x[idx]))
        err_y = abs(float(passive.y) - float(self._plan.y[idx]))
        err_vx = abs(float(passive.vx) - float(self._plan.vx[idx]))
        err_vy = abs(float(passive.vy_up) - float(self._plan.vy[idx]))
        return (
            err_x > cfg.replan_dx_error
            or err_y > cfg.replan_dy_error
            or err_vx > cfg.replan_vx_error
            or err_vy > cfg.replan_vy_error
        )

    def _solve_plan(
        self,
        *,
        passive: PassiveSensors,
        dx: float,
        dy: float,
        max_thrust_accel: float,
        min_thrust_accel: float,
    ) -> PDGPlan | None:
        alt = max(0.0, finite_altitude(passive))
        target_x = float(passive.x) + dx
        target_y = float(passive.y) + dy
        max_tilt = self._resolve_max_tilt(alt, dx, float(passive.vx))
        target_vy = self._desired_terminal_vy(alt, max_thrust_accel, max_tilt)
        descent_floor_vy = self._descent_floor_vy(alt, max_thrust_accel, max_tilt)

        plan = self._optimizer.solve(
            x=float(passive.x),
            y=float(passive.y),
            vx=float(passive.vx),
            vy=float(passive.vy_up),
            target_x=target_x,
            target_y=target_y,
            target_vy=target_vy,
            max_thrust_accel=max_thrust_accel,
            min_thrust_accel=min_thrust_accel,
            max_tilt_rad=max_tilt,
            descent_floor_vy=descent_floor_vy,
            warm_start=self._plan,
        )
        if plan is not None:
            self._last_solve_ms = float(plan.solve_time_ms)
            self._last_solver_status = str(plan.status)
        return plan

    def _command_from_plan(
        self,
        *,
        dt: float,
        passive: PassiveSensors,
        dx: float,
        alt: float,
        max_power: float,
        min_throttle: float,
        max_throttle: float,
        max_thrust_accel: float,
    ) -> BotAction:
        cfg = self._cfg

        # Touchdown hard cut when essentially settled.
        if (
            alt <= cfg.touchdown_zero_alt
            and abs(dx) <= self._last_target_half
            and abs(float(passive.vx)) <= cfg.touchdown_zero_vx
            and abs(float(passive.vy_up)) <= cfg.touchdown_zero_vy
        ):
            angle_cmd = rate_limit_angle_command(
                0.0, self._prev_angle_cmd, dt, max_rate=cfg.angle_rate
            )
            self._prev_angle_cmd = angle_cmd
            return BotAction(target_thrust=0.0, target_angle=0.0, refuel=False)

        if self._plan is None or not self._plan.feasible:
            # Optimizer-first fallback: aggressive vertical brake with light lateral damping.
            vx = float(passive.vx)
            vy = float(passive.vy_up)
            down_speed = max(0.0, -vy)
            a_y = _GRAVITY_MAG + (0.72 * max_thrust_accel)
            if down_speed >= cfg.emergency_vy and alt <= cfg.emergency_alt:
                a_y = _GRAVITY_MAG + max_thrust_accel
            a_y = clamp(a_y, 0.0, _GRAVITY_MAG + max_thrust_accel)
            a_x = clamp((-0.55 * vx) + (-0.04 * dx), -7.0, 7.0)
        else:
            idx = self._plan_index()
            a_x = float(self._plan.ax[idx])
            a_y = float(self._plan.ay[idx])

            # keep commands physical before allocation
            a_y = clamp(a_y, 0.0, max_thrust_accel)
            max_tilt = self._resolve_max_tilt(alt, dx, float(passive.vx))
            tilt_tan = math.tan(max_tilt)
            a_x = clamp(a_x, -tilt_tan * max(0.2, a_y), tilt_tan * max(0.2, a_y))

        # Convert accel command to actuator targets.
        max_tilt_now = self._resolve_max_tilt(alt, dx, float(passive.vx))
        angle_target = math.atan2(a_x, max(0.2, a_y))
        angle_target = clamp(angle_target, -max_tilt_now, max_tilt_now)
        angle_cmd = rate_limit_angle_command(
            angle_target,
            self._prev_angle_cmd,
            dt,
            max_rate=cfg.angle_rate,
        )
        self._prev_angle_cmd = angle_cmd

        mass = max(0.5, float(passive.mass))
        thrust_acc = math.hypot(a_x, max(0.0, a_y))
        thrust = (mass * thrust_acc) / max(max_power, 1e-3)
        thrust = clamp(thrust, 0.0, max_throttle)
        if thrust <= (cfg.throttle_off_threshold_scale * min_throttle):
            thrust = 0.0
        elif thrust > 0.0:
            thrust = max(min_throttle, thrust)

        return BotAction(target_thrust=thrust, target_angle=angle_cmd, refuel=False)

    def update(
        self,
        dt: float,
        passive: PassiveSensors,
        active: ActiveSensors,
    ) -> BotAction:
        if passive.state != "flying":
            self._reset_state()
        if passive.state in ("landed", "crashed", "out_of_fuel"):
            action = BotAction(0.0, passive.angle, False, status=f"zem_zev:{passive.state}")
            self.status = action.status
            return action

        if not self._angle_cmd_initialized:
            self._prev_angle_cmd = float(passive.angle)
            self._angle_cmd_initialized = True

        max_power, min_throttle, max_throttle, _ramp_up = engine_profile(self.vehicle_info)
        mass = max(0.5, float(passive.mass))
        max_force = max_power * max_throttle
        min_force = max_power * min_throttle
        max_thrust_accel = max(0.1, max_force / mass)
        min_thrust_accel = max(0.0, min_force / mass)

        target = pick_target(passive, pinned_uid=self.pinned_target_uid)
        if target is not None:
            dx = float(target.x) - float(passive.x)
            dy = float(target.y) - float(passive.y)
            self._last_target_half = target_half_width(getattr(target, "size", None))
        else:
            dx = 0.0
            dy = -max(0.0, finite_altitude(passive))

        alt = max(0.0, finite_altitude(passive))

        self._replan_timer -= max(0.0, dt)
        self._plan_elapsed += max(0.0, dt)

        need_replan = (
            self._plan is None
            or not self._plan.feasible
            or self._replan_timer <= 0.0
            or self._state_deviation_requires_replan(passive)
        )

        solved_now = False
        if need_replan:
            solved_now = True
            plan = self._solve_plan(
                passive=passive,
                dx=dx,
                dy=dy,
                max_thrust_accel=max_thrust_accel,
                min_thrust_accel=min_thrust_accel,
            )
            if plan is not None and plan.feasible:
                self._plan = plan
                self._plan_elapsed = 0.0
                self._replan_timer = 1.0 / max(1e-3, self._cfg.replan_hz)
                self._fallback_steps_remaining = int(self._cfg.fallback_hold_steps)
            else:
                if self._fallback_steps_remaining > 0 and self._plan is not None and self._plan.feasible:
                    self._fallback_steps_remaining -= 1
                else:
                    self._plan = None

        action = self._command_from_plan(
            dt=dt,
            passive=passive,
            dx=dx,
            alt=alt,
            max_power=max_power,
            min_throttle=min_throttle,
            max_throttle=max_throttle,
            max_thrust_accel=max_thrust_accel,
        )

        phase = "opt"
        if self._plan is None or not self._plan.feasible:
            phase = "fallback"
        action.status = (
            f"zem_zev:{phase} dx:{stable(dx, 1):6.1f} "
            f"vx:{stable(passive.vx, 1):5.1f} vy:{stable(passive.vy_up, 1):5.1f} "
            f"rp:{int(solved_now)} slv:{stable(self._last_solve_ms, 1):4.1f}ms "
            f"st:{self._last_solver_status}"
        )
        self.status = action.status
        return action



def create_bot() -> Bot:
    return ZemZevBot()



def list_behavior_names() -> tuple[str, ...]:
    return ("zem_zev",)


__all__ = ["ZemZevBot", "create_bot", "list_behavior_names"]
