"""Optimizer-first powered descent bot (ZEM/ZEV replacement).

This version uses a receding-horizon convex optimizer to generate coupled
horizontal/vertical thrust commands from a single objective each replan cycle.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from bots._ballistics import (
    BallisticProjection,
    build_projection_query,
    estimate_ballistic_projection_from_result,
)
from bots._bot_math import clamp, engine_profile, finite_altitude, rate_limit_angle_command, stable
from bots._optimizer_pdg import PDGOptimizer, PDGOptimizerConfig, PDGPlan
from bots._targeting import pick_target, target_half_width
from core.bot import Bot, BotAction, PassiveSensors, QueryBot
from core.bot_queries import BotQuery, BotQueryResults
from core.config import GRAVITY

_GRAVITY_MAG = abs(float(GRAVITY))
_QUERY_PROJECTION = "zem_projection"


@dataclass(frozen=True)
class ZemZevConfig:
    # Receding horizon scheduling
    replan_hz_setup: float = 2.5
    replan_hz_coast: float = 4.0
    replan_hz_terminal: float = 7.0
    replan_dx_error_setup: float = 48.0
    replan_dy_error_setup: float = 30.0
    replan_vx_error_setup: float = 7.0
    replan_vy_error_setup: float = 7.0
    replan_dx_error_coast: float = 32.0
    replan_dy_error_coast: float = 22.0
    replan_vx_error_coast: float = 5.0
    replan_vy_error_coast: float = 5.0
    replan_dx_error_terminal: float = 24.0
    replan_dy_error_terminal: float = 18.0
    replan_vx_error_terminal: float = 4.0
    replan_vy_error_terminal: float = 4.0
    fallback_hold_steps: int = 12
    long_horizon_altitude: float = 120.0
    long_horizon_time_to_go: float = 6.0
    high_alt_coast_vy_boost_alt: float = 180.0
    high_alt_coast_vy_boost_max: float = 1.10
    high_alt_floor_relax_alt: float = 160.0
    high_alt_floor_relax_min_scale: float = 0.80

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
    touchdown_rescue_altitude: float = 4.5
    touchdown_rescue_vy_ratio: float = 1.8
    touchdown_rescue_tilt: float = 0.14
    touchdown_rescue_alt_floor: float = 0.8

    # Safety brake when descent rate is critical
    emergency_vy: float = 12.0
    emergency_alt: float = 220.0

    # Telemetry gates for focused launch/coast evals and phase tracking
    setup_gate_projected_dx_abs: float = 60.0
    setup_gate_projected_dx_target_ratio: float = 1.1
    setup_gate_vx_track_abs: float = 4.0
    setup_gate_vx_track_ratio: float = 0.20
    setup_gate_vy_up_max: float = -1.0
    terminal_gate_t_fall_s: float = 4.5
    terminal_gate_projected_dx_abs: float = 18.0
    terminal_gate_projected_dx_target_ratio: float = 0.4
    terminal_gate_vy_up_max: float = -4.0
    touchdown_phase_altitude: float = 4.0
    touchdown_phase_speed: float = 2.5

    # Launch-from-pad bootstrap when starting landed with a different target.
    launch_takeoff_clear_altitude: float = 10.0
    launch_takeoff_thrust: float = 0.9


class ZemZevBot(QueryBot):
    def __init__(self, behavior: str = "zem_zev") -> None:
        super().__init__()
        self._cfg = ZemZevConfig()
        self._optimizer_short = PDGOptimizer(PDGOptimizerConfig(horizon_steps=28))
        self._optimizer_long = PDGOptimizer(PDGOptimizerConfig(horizon_steps=36))

        self._behavior = "zem_zev"
        self._prev_angle_cmd = 0.0
        self._angle_cmd_initialized = False
        self._thrust_enabled = False
        self._last_target_half = 55.0

        self._plan: PDGPlan | None = None
        self._plan_elapsed = 0.0
        self._replan_timer = 0.0
        self._fallback_steps_remaining = 0
        self._last_solve_ms = 0.0
        self._last_solver_status = ""
        self._solve_count = 0
        self._solve_ms_sum = 0.0
        self._solve_ms_samples: list[float] = []
        self._fallback_frames = 0

        self._elapsed_time_s = 0.0
        self._active_phase = "setup"
        self._setup_gate_done = False
        self._setup_gate_time: float | None = None
        self._setup_gate_altitude: float | None = None
        self._setup_gate_projected_dx: float | None = None
        self._terminal_gate_done = False
        self._terminal_gate_time: float | None = None
        self._terminal_gate_altitude: float | None = None
        self._terminal_gate_projected_dx: float | None = None
        self._last_projection_dx: float | None = None
        self._last_projection_t_fall: float | None = None
        self._auto_target_uid: str | None = None
        self._launch_takeoff_active = False

        self.set_behavior(behavior)

    def set_behavior(self, behavior: str) -> None:
        key = str(behavior).strip().lower().replace("-", "_")
        if key != "zem_zev":
            raise ValueError(
                f"Unknown zem_zev behavior '{behavior}'. Expected one of: zem_zev"
            )
        self._behavior = "zem_zev"
        self._reset_state()
        self._auto_target_uid = None
        self._launch_takeoff_active = False

    def _reset_state(self) -> None:
        self._prev_angle_cmd = 0.0
        self._angle_cmd_initialized = False
        self._thrust_enabled = False
        self._plan = None
        self._plan_elapsed = 0.0
        self._replan_timer = 0.0
        self._fallback_steps_remaining = 0
        self._last_solve_ms = 0.0
        self._last_solver_status = ""
        self._last_target_half = 55.0
        self._solve_count = 0
        self._solve_ms_sum = 0.0
        self._solve_ms_samples = []
        self._fallback_frames = 0
        self._elapsed_time_s = 0.0
        self._active_phase = "setup"
        self._setup_gate_done = False
        self._setup_gate_time = None
        self._setup_gate_altitude = None
        self._setup_gate_projected_dx = None
        self._terminal_gate_done = False
        self._terminal_gate_time = None
        self._terminal_gate_altitude = None
        self._terminal_gate_projected_dx = None
        self._last_projection_dx = None
        self._last_projection_t_fall = None

    @staticmethod
    def _contact_distance(contact) -> float:
        try:
            return abs(float(contact.distance))
        except (TypeError, ValueError):
            rel_x = float(getattr(contact, "rel_x", 0.0))
            rel_y = float(getattr(contact, "rel_y", 0.0))
            return math.hypot(rel_x, rel_y)

    def _landed_contact_uid(self, passive: PassiveSensors) -> str | None:
        contacts = passive.radar_contacts or []
        if not contacts:
            return None
        landed = min(contacts, key=self._contact_distance)
        return landed.uid

    def _resolve_target_contact(self, passive: PassiveSensors):
        contacts = passive.radar_contacts or []
        if not contacts:
            return None

        forced_uid = self.pinned_target_uid or self._auto_target_uid
        if forced_uid:
            for contact in contacts:
                if contact.uid == forced_uid:
                    return contact

        if passive.state == "landed" and self.pinned_target_uid is None and len(contacts) >= 2:
            landed_uid = self._landed_contact_uid(passive)
            for contact in contacts:
                if contact.uid is not None and contact.uid != landed_uid:
                    self._auto_target_uid = contact.uid
                    return contact

        return pick_target(passive, pinned_uid=self.pinned_target_uid)

    def _takeoff_thrust(self, max_throttle: float) -> float:
        return clamp(self._cfg.launch_takeoff_thrust, 0.0, max_throttle)

    @property
    def behavior(self) -> str:
        return self._behavior

    @staticmethod
    def _percentile(values: list[float], p: float) -> float:
        if not values:
            return 0.0
        sorted_values = sorted(values)
        if len(sorted_values) == 1:
            return sorted_values[0]
        clamped = clamp(float(p), 0.0, 1.0)
        idx = (len(sorted_values) - 1) * clamped
        lo = int(idx)
        hi = min(lo + 1, len(sorted_values) - 1)
        if lo == hi:
            return sorted_values[lo]
        frac = idx - lo
        return (sorted_values[lo] * (1.0 - frac)) + (sorted_values[hi] * frac)

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
        step_dt = max(1e-3, float(self._plan.step_dt))
        idx = int(self._plan_elapsed / step_dt)
        return max(0, min(len(self._plan.ax) - 1, idx))

    def _select_optimizer(self, *, phase: str, alt: float, vy_up: float) -> PDGOptimizer:
        if phase in ("setup", "coast"):
            return self._optimizer_long
        if phase == "terminal":
            return self._optimizer_short
        cfg = self._cfg
        down_speed = max(0.0, -float(vy_up))
        t_go = float("inf") if down_speed <= 1e-3 else (max(0.0, alt) / down_speed)
        if alt >= cfg.long_horizon_altitude or t_go >= cfg.long_horizon_time_to_go:
            return self._optimizer_long
        return self._optimizer_short

    def _replan_policy_for_phase(self, phase: str) -> tuple[float, float, float, float, float]:
        cfg = self._cfg
        if phase == "setup":
            return (
                cfg.replan_hz_setup,
                cfg.replan_dx_error_setup,
                cfg.replan_dy_error_setup,
                cfg.replan_vx_error_setup,
                cfg.replan_vy_error_setup,
            )
        if phase == "terminal":
            return (
                cfg.replan_hz_terminal,
                cfg.replan_dx_error_terminal,
                cfg.replan_dy_error_terminal,
                cfg.replan_vx_error_terminal,
                cfg.replan_vy_error_terminal,
            )
        return (
            cfg.replan_hz_coast,
            cfg.replan_dx_error_coast,
            cfg.replan_dy_error_coast,
            cfg.replan_vx_error_coast,
            cfg.replan_vy_error_coast,
        )

    def _state_deviation_requires_replan(
        self,
        passive: PassiveSensors,
        *,
        dx_err_lim: float,
        dy_err_lim: float,
        vx_err_lim: float,
        vy_err_lim: float,
    ) -> bool:
        if self._plan is None or not self._plan.feasible:
            return True
        idx = self._plan_index()
        err_x = abs(float(passive.x) - float(self._plan.x[idx]))
        err_y = abs(float(passive.y) - float(self._plan.y[idx]))
        err_vx = abs(float(passive.vx) - float(self._plan.vx[idx]))
        err_vy = abs(float(passive.vy_up) - float(self._plan.vy[idx]))
        return (
            err_x > dx_err_lim
            or err_y > dy_err_lim
            or err_vx > vx_err_lim
            or err_vy > vy_err_lim
        )

    def _solve_plan(
        self,
        *,
        passive: PassiveSensors,
        dx: float,
        dy: float,
        max_thrust_accel: float,
        min_thrust_accel: float,
        nominal_thrust_accel: float,
        phase: str,
    ) -> PDGPlan | None:
        alt = max(0.0, finite_altitude(passive))
        target_x = float(passive.x) + dx
        target_y = float(passive.y) + dy
        max_tilt = self._resolve_max_tilt(alt, dx, float(passive.vx))
        # Nominal-first schedule: OD is reserve, not baseline burn design.
        target_vy = self._desired_terminal_vy(alt, nominal_thrust_accel, max_tilt)
        descent_floor_vy = self._descent_floor_vy(alt, nominal_thrust_accel, max_tilt)
        descent_floor_weight_scale = 1.0
        if phase in ("setup", "coast"):
            if alt > self._cfg.high_alt_coast_vy_boost_alt:
                # Allow slightly faster commanded descent when far/high to reduce hover-like nibbling.
                vy_alpha = clamp(
                    (alt - self._cfg.high_alt_coast_vy_boost_alt)
                    / max(1e-3, 3.0 * self._cfg.high_alt_coast_vy_boost_alt),
                    0.0,
                    1.0,
                )
                vy_boost = 1.0 + (
                    vy_alpha * max(0.0, self._cfg.high_alt_coast_vy_boost_max - 1.0)
                )
                target_vy = min(target_vy * vy_boost, -self._cfg.braking_min_speed)
            if alt > self._cfg.high_alt_floor_relax_alt:
                relax_alpha = clamp(
                    (alt - self._cfg.high_alt_floor_relax_alt)
                    / max(1e-3, 3.0 * self._cfg.high_alt_floor_relax_alt),
                    0.0,
                    1.0,
                )
                descent_floor_weight_scale = 1.0 - (
                    relax_alpha * max(0.0, 1.0 - self._cfg.high_alt_floor_relax_min_scale)
                )
        optimizer = self._select_optimizer(phase=phase, alt=alt, vy_up=float(passive.vy_up))

        plan = optimizer.solve(
            x=float(passive.x),
            y=float(passive.y),
            vx=float(passive.vx),
            vy=float(passive.vy_up),
            target_x=target_x,
            target_y=target_y,
            target_vy=target_vy,
            max_thrust_accel=max_thrust_accel,
            min_thrust_accel=min_thrust_accel,
            nominal_thrust_accel=nominal_thrust_accel,
            max_tilt_rad=max_tilt,
            descent_floor_vy=descent_floor_vy,
            gravity_mag=_GRAVITY_MAG,
            pad_half_width=self._last_target_half,
            altitude_hint=alt,
            descent_floor_weight_scale=descent_floor_weight_scale,
            warm_start=self._plan,
        )
        if plan is not None:
            self._last_solve_ms = float(plan.solve_time_ms)
            self._last_solver_status = str(plan.status)
            self._solve_count += 1
            self._solve_ms_sum += self._last_solve_ms
            self._solve_ms_samples.append(self._last_solve_ms)
        return plan

    def _update_phase_tracking(
        self,
        *,
        passive: PassiveSensors,
        dx: float,
        alt: float,
        projection: BallisticProjection,
    ) -> None:
        cfg = self._cfg
        projected_dx = float(projection.projected_dx)
        t_fall = max(0.0, float(projection.t_fall))
        self._last_projection_dx = projected_dx
        self._last_projection_t_fall = t_fall

        track_vx = dx / max(0.75, t_fall)
        setup_dx_limit = max(
            cfg.setup_gate_projected_dx_abs,
            cfg.setup_gate_projected_dx_target_ratio * self._last_target_half,
        )
        setup_vx_limit = max(
            cfg.setup_gate_vx_track_abs,
            cfg.setup_gate_vx_track_ratio * abs(track_vx),
        )
        setup_ready = (
            abs(projected_dx) <= setup_dx_limit
            and abs(float(passive.vx) - track_vx) <= setup_vx_limit
            and float(passive.vy_up) <= cfg.setup_gate_vy_up_max
        )
        if setup_ready and (not self._setup_gate_done):
            self._setup_gate_done = True
            self._setup_gate_time = self._elapsed_time_s
            self._setup_gate_altitude = alt
            self._setup_gate_projected_dx = projected_dx

        terminal_dx_limit = max(
            cfg.terminal_gate_projected_dx_abs,
            cfg.terminal_gate_projected_dx_target_ratio * self._last_target_half,
        )
        terminal_ready = (
            t_fall <= cfg.terminal_gate_t_fall_s
            and abs(projected_dx) <= terminal_dx_limit
            and float(passive.vy_up) <= cfg.terminal_gate_vy_up_max
        )
        if terminal_ready and (not self._terminal_gate_done):
            self._terminal_gate_done = True
            self._terminal_gate_time = self._elapsed_time_s
            self._terminal_gate_altitude = alt
            self._terminal_gate_projected_dx = projected_dx

        speed = math.hypot(float(passive.vx), float(passive.vy_up))
        if alt <= cfg.touchdown_phase_altitude and speed <= cfg.touchdown_phase_speed:
            self._active_phase = "touchdown"
        elif self._terminal_gate_done or terminal_ready:
            self._active_phase = "terminal"
        elif self._setup_gate_done or setup_ready:
            self._active_phase = "coast"
        else:
            self._active_phase = "setup"

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

        mass = max(0.5, float(passive.mass))
        thrust_acc = math.hypot(a_x, max(0.0, a_y))
        thrust = (mass * thrust_acc) / max(max_power, 1e-3)
        thrust = clamp(thrust, 0.0, max_throttle)
        idle_angle_target: float | None = None
        off_threshold = cfg.throttle_off_threshold_scale * min_throttle
        if self._thrust_enabled:
            if thrust < off_threshold:
                self._thrust_enabled = False
        elif thrust >= min_throttle:
            self._thrust_enabled = True

        if not self._thrust_enabled:
            thrust = 0.0
            if alt > cfg.touchdown_zero_alt and abs(float(passive.vx)) > 0.5:
                idle_angle_target = clamp(
                    math.copysign(max_tilt_now, -float(passive.vx)),
                    -max_tilt_now,
                    max_tilt_now,
                )
        elif thrust > 0.0:
            thrust = max(min_throttle, thrust)
        if idle_angle_target is not None:
            angle_cmd = rate_limit_angle_command(
                idle_angle_target,
                self._prev_angle_cmd,
                dt,
                max_rate=cfg.angle_rate,
            )

        # Low-altitude rescue: if descent is outside the braking envelope, bias
        # toward vertical braking and compute required throttle from kinematics.
        down_speed = max(0.0, -float(passive.vy_up))
        rescue_limit = self._braking_speed_limit(alt, max_thrust_accel, max_tilt_now)
        if (
            alt <= cfg.touchdown_rescue_altitude
            and down_speed > (cfg.touchdown_rescue_vy_ratio * rescue_limit)
        ):
            rescue_angle_target = 0.0
            if abs(float(passive.vx)) > cfg.touchdown_zero_vx:
                rescue_angle_target = math.copysign(cfg.touchdown_rescue_tilt, -float(passive.vx))
            rescue_angle_target = clamp(
                rescue_angle_target,
                -cfg.touchdown_rescue_tilt,
                cfg.touchdown_rescue_tilt,
            )
            angle_cmd = rate_limit_angle_command(
                rescue_angle_target,
                self._prev_angle_cmd,
                dt,
                max_rate=cfg.angle_rate,
            )

            alt_eff = max(cfg.touchdown_rescue_alt_floor, alt - cfg.touchdown_zero_alt)
            v_excess = max(0.0, down_speed - cfg.vy_touch_cap)
            required_net_brake = (v_excess * v_excess) / (2.0 * alt_eff)
            required_ay = _GRAVITY_MAG + required_net_brake
            required_accel = required_ay / max(0.2, math.cos(angle_cmd))
            required_thrust = (mass * required_accel) / max(max_power, 1e-3)
            thrust = max(thrust, clamp(required_thrust, 0.0, max_throttle))
            if thrust >= min_throttle:
                self._thrust_enabled = True
        self._prev_angle_cmd = angle_cmd

        return BotAction(target_thrust=thrust, target_angle=angle_cmd, refuel=False)

    def plan(self, dt: float, passive: PassiveSensors) -> list[BotQuery]:
        _ = dt
        if passive.state != "flying":
            return []
        target = self._resolve_target_contact(passive)
        if target is not None:
            dx = float(target.x) - float(passive.x)
        else:
            dx = 0.0
        query = build_projection_query(
            query_id=_QUERY_PROJECTION,
            dx=dx,
            alt=max(0.0, finite_altitude(passive)),
            vx=float(passive.vx),
            vy_up=float(passive.vy_up),
            x=float(passive.x),
            y=float(passive.y),
            clearance=0.0,
        )
        if query is None:
            return []
        return [query]

    def act(
        self,
        dt: float,
        passive: PassiveSensors,
        results: BotQueryResults,
    ) -> BotAction:
        if passive.state == "crashed":
            self._reset_state()
            self._auto_target_uid = None
            self._launch_takeoff_active = False
            action = BotAction(0.0, passive.angle, False, status="zem_zev:crashed")
            self.status = action.status
            return action
        if passive.state == "out_of_fuel":
            self._reset_state()
            self._auto_target_uid = None
            self._launch_takeoff_active = False
            action = BotAction(0.0, passive.angle, False, status="zem_zev:out_of_fuel")
            self.status = action.status
            return action

        if passive.state == "landed":
            self._reset_state()

        max_power, min_throttle, max_throttle, _ramp_up = engine_profile(self.vehicle_info)
        target = self._resolve_target_contact(passive)
        target_uid = target.uid if target is not None else None

        if passive.state == "landed":
            landed_uid = self._landed_contact_uid(passive)
            if target_uid is None or landed_uid == target_uid:
                self._launch_takeoff_active = False
                action = BotAction(0.0, 0.0, False, status="zem_zev:landed")
                self.status = action.status
                return action

            self._launch_takeoff_active = True
            action = BotAction(
                self._takeoff_thrust(max_throttle),
                0.0,
                False,
                status="zem_zev:takeoff",
            )
            self.status = action.status
            return action

        if passive.state != "flying":
            self._reset_state()
            self._launch_takeoff_active = False
            action = BotAction(0.0, passive.angle, False, status=f"zem_zev:{passive.state}")
            self.status = action.status
            return action

        alt = max(0.0, finite_altitude(passive))
        if self._launch_takeoff_active and alt < self._cfg.launch_takeoff_clear_altitude:
            action = BotAction(
                self._takeoff_thrust(max_throttle),
                0.0,
                False,
                status="zem_zev:clear_pad",
            )
            self.status = action.status
            return action
        if self._launch_takeoff_active and alt >= self._cfg.launch_takeoff_clear_altitude:
            self._launch_takeoff_active = False

        if not self._angle_cmd_initialized:
            self._prev_angle_cmd = float(passive.angle)
            self._angle_cmd_initialized = True

        mass = max(0.5, float(passive.mass))
        max_force = max_power * max_throttle
        nominal_force = max_power * min(1.0, max_throttle)
        min_force = max_power * min_throttle
        max_thrust_accel = max(0.1, max_force / mass)
        nominal_thrust_accel = max(0.1, nominal_force / mass)
        min_thrust_accel = max(0.0, min_force / mass)

        if target is not None:
            dx = float(target.x) - float(passive.x)
            dy = float(target.y) - float(passive.y)
            self._last_target_half = target_half_width(getattr(target, "size", None))
        else:
            dx = 0.0
            dy = -max(0.0, finite_altitude(passive))

        self._elapsed_time_s += max(0.0, float(dt))
        projection = estimate_ballistic_projection_from_result(
            dx=dx,
            alt=alt,
            vx=float(passive.vx),
            vy_up=float(passive.vy_up),
            x=float(passive.x),
            result=results.get(_QUERY_PROJECTION),
        )
        self._update_phase_tracking(
            passive=passive,
            dx=dx,
            alt=alt,
            projection=projection,
        )
        replan_hz, dx_err_lim, dy_err_lim, vx_err_lim, vy_err_lim = self._replan_policy_for_phase(
            self._active_phase
        )

        self._replan_timer -= max(0.0, dt)
        self._plan_elapsed += max(0.0, dt)

        need_replan = (
            self._plan is None
            or not self._plan.feasible
            or self._replan_timer <= 0.0
            or self._state_deviation_requires_replan(
                passive,
                dx_err_lim=dx_err_lim,
                dy_err_lim=dy_err_lim,
                vx_err_lim=vx_err_lim,
                vy_err_lim=vy_err_lim,
            )
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
                nominal_thrust_accel=nominal_thrust_accel,
                phase=self._active_phase,
            )
            if plan is not None and plan.feasible:
                self._plan = plan
                self._plan_elapsed = 0.0
                self._replan_timer = 1.0 / max(1e-3, replan_hz)
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

        phase = self._active_phase
        mode = "opt"
        if self._plan is None or not self._plan.feasible:
            mode = "fallback"
            self._fallback_frames += 1
        action.status = (
            f"zem_zev:{mode} ph:{phase} dx:{stable(dx, 1):6.1f} "
            f"vx:{stable(passive.vx, 1):5.1f} vy:{stable(passive.vy_up, 1):5.1f} "
            f"rp:{int(solved_now)} slv:{stable(self._last_solve_ms, 1):4.1f}ms "
            f"st:{self._last_solver_status}"
        )
        self.status = action.status
        return action

    def get_evaluation_snapshot(self) -> dict[str, float | int | bool | str | None]:
        solve_ms_mean = 0.0
        if self._solve_count > 0:
            solve_ms_mean = self._solve_ms_sum / max(1, self._solve_count)
        return {
            "kind": "zem_zev",
            "phase": self._active_phase,
            "projected_dx": self._last_projection_dx,
            "t_fall": self._last_projection_t_fall,
            "setup_gate_done": self._setup_gate_done,
            "setup_gate_time": self._setup_gate_time,
            "setup_gate_altitude": self._setup_gate_altitude,
            "setup_gate_projected_dx": self._setup_gate_projected_dx,
            "terminal_gate_done": self._terminal_gate_done,
            "terminal_gate_time": self._terminal_gate_time,
            "terminal_gate_altitude": self._terminal_gate_altitude,
            "terminal_gate_projected_dx": self._terminal_gate_projected_dx,
            "solve_count": self._solve_count,
            "solve_ms_mean": solve_ms_mean,
            "solve_ms_p90": self._percentile(self._solve_ms_samples, 0.9),
            "fallback_frames": self._fallback_frames,
        }



def create_bot() -> Bot:
    return ZemZevBot()



def list_behavior_names() -> tuple[str, ...]:
    return ("zem_zev",)


__all__ = ["ZemZevBot", "create_bot", "list_behavior_names"]
