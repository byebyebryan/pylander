"""Dedicated flare bot with coupled 2D terminal control."""

from __future__ import annotations

import math
from dataclasses import dataclass, replace

from bots._ballistics import ballistic_time_to_impact, estimate_ballistic_projection
from bots._bot_math import clamp, engine_profile, finite_altitude, stable, vehicle_limits
from bots._coast_core import COAST_POLICY, CoastCourseConfig, GuidanceTargets, cap_low_altitude_angle
from bots._drop_control import can_use_overdrive, rate_limit_angle_command, vertical_controller
from bots._launch_core import LaunchSetupConfig, resolve_sideburn_target_angle
from bots._targeting import pick_target
from core.bot import ActiveSensors, Bot, BotAction, PassiveSensors
from core.sensor import RadarContact


@dataclass(frozen=True)
class FlareControlConfig:
    sideburn_enter_dx: float = 60.0
    sideburn_enter_vx: float = 12.0
    sideburn_entry_alt_max: float = 680.0
    sideburn_force_low_alt: float = 260.0
    sideburn_force_vx: float = 34.0
    sideburn_min_dx_alt_ratio: float = 1.45
    sideburn_entry_alt_min: float = 95.0
    sideburn_exit_dx: float = 14.0
    sideburn_exit_vx: float = 1.7
    sideburn_release_frames: int = 5
    sideburn_max_frames: int = 420
    sideburn_exit_vx_relaxed: float = 4.2
    sideburn_exit_dx_relaxed: float = 70.0
    sideburn_exit_to_coupled_vx: float = 18.0
    sideburn_exit_to_coupled_dx: float = 220.0
    sideburn_exit_track_vx_ratio: float = 0.72
    sideburn_min_altitude: float = 14.0
    sideburn_vx_floor: float = 5.4
    sideburn_vx_floor_per_alt: float = 0.022
    sideburn_vx_cap: float = 120.0
    sideburn_ax_floor: float = 1.2
    sideburn_ax_cap: float = 8.8
    sideburn_vx_gain: float = 1.02
    sideburn_pos_gain: float = 0.022
    sideburn_switch_dx: float = 13.0
    sideburn_switch_vx: float = 1.4
    sideburn_flip_vx: float = 6.0
    sideburn_force_dx: float = 24.0
    sideburn_stop_distance_ratio: float = 0.58
    sideburn_urgent_vx: float = 50.0
    sideburn_urgent_projected_dx_min: float = 24.0
    sideburn_track_vx_buffer: float = 2.5
    sideburn_descent_base: float = 1.1
    sideburn_descent_gain: float = 0.17
    sideburn_descent_min: float = 1.0
    sideburn_descent_max: float = 3.4
    sideburn_hover_penalty: float = 0.52
    sideburn_abort_climb_vy: float = 1.2
    sideburn_reentry_cooldown_frames: int = 72
    sideburn_exit_burn_hold_frames: int = 700
    sideburn_entry_vy_max: float = 1.0
    sideburn_emergency_alt: float = 240.0
    sideburn_angle_rate: float = 3.2
    sideburn_max_tilt: float = 0.88
    coupled_tgo_min: float = 0.8
    coupled_tgo_max: float = 12.0
    coupled_vx_track_weight: float = 0.68
    coupled_vx_cap: float = 16.0
    coupled_near_dx: float = 20.0
    coupled_near_alt: float = 18.0
    coupled_near_vx_cap: float = 2.0
    coupled_descent_base: float = 0.95
    coupled_descent_gain: float = 0.45
    coupled_descent_min: float = 1.0
    coupled_descent_max: float = 14.0
    coupled_ax_pos_gain: float = 0.82
    coupled_ax_vel_gain: float = 0.98
    coupled_ax_damping: float = 0.07
    coupled_ax_cap: float = 8.8
    coupled_soft_alt: float = 15.0
    coupled_soft_dx: float = 12.0
    coupled_soft_scale: float = 0.56
    coupled_ay_pos_gain: float = 1.45
    coupled_ay_vel_gain: float = 0.88
    coupled_ay_damping: float = 0.05
    coupled_angle_rate: float = 2.2
    coupled_max_tilt: float = 0.62
    coupled_low_alt_tilt: float = 0.18
    coupled_low_alt_tilt_far: float = 0.34
    coupled_low_alt_tilt_dx: float = 12.0
    coupled_low_alt_tilt_vx: float = 2.4
    coupled_low_alt_vx_cap_alt: float = 60.0
    coupled_low_alt_vx_cap_gain: float = 0.7
    coupled_low_alt_vx_cap_min: float = 2.2
    coupled_low_alt_vx_cap_max: float = 7.0
    coupled_low_alt_ax_alt: float = 22.0
    coupled_low_alt_ax_cap: float = 4.4
    coupled_misaligned_alt: float = 14.0
    coupled_misaligned_vy_min: float = 1.25
    eco_glide_lateral_hold_alt: float = 80.0
    anti_hover_alt: float = 24.0
    anti_hover_dx: float = 24.0
    anti_hover_vy_floor: float = 0.8
    anti_hover_down_acc: float = 0.42
    emergency_vy: float = 6.0
    emergency_brake_gain: float = 0.24
    burn_enter_time_margin: float = 0.65
    burn_hold_frames: int = 8
    touchdown_altitude: float = 4.0
    touchdown_descent_base: float = 0.35
    touchdown_descent_gain: float = 0.07
    touchdown_descent_min: float = 0.35
    touchdown_descent_max: float = 0.85
    touchdown_entry_dx: float = 8.0
    touchdown_entry_vx: float = 2.0
    touchdown_zero_alt: float = 2.4
    touchdown_zero_dx: float = 7.0
    touchdown_zero_vx: float = 0.55
    touchdown_zero_vy: float = 0.9


class FlareBot(Bot):
    def __init__(self, behavior: str = "flare") -> None:
        super().__init__()
        self._policy = replace(COAST_POLICY, status_prefix="flare")
        self._control_cfg = FlareControlConfig()
        self._course_cfg = replace(
            CoastCourseConfig(),
            low_altitude_angle_limit_alt=10.0,
            low_altitude_angle_limit_dx=8.0,
            low_altitude_angle_cap=0.14,
        )
        self._sideburn_cfg = replace(
            LaunchSetupConfig(),
            setup_sideburn_angle_rad=1.18,
            setup_sideburn_angle_min_rad=0.95,
            setup_sideburn_angle_max_rad=1.35,
            setup_sideburn_upward_vy_target=1.4,
            setup_sideburn_upward_angle_gain=0.45,
            setup_sideburn_lateral_accel_floor=self._control_cfg.sideburn_ax_floor,
            setup_sideburn_lateral_accel_cap=self._control_cfg.sideburn_ax_cap,
            setup_sideburn_min_thrust=0.35,
            setup_sideburn_max_thrust=1.6,
        )
        self._active_sensors: ActiveSensors | None = None
        self._behavior = "flare"
        self._prev_angle_cmd = 0.0
        self._ballistic_debug_summary = ""
        self._last_guidance: GuidanceTargets | None = None
        self._last_projected_dx = 0.0
        self._last_t_go = 1.0
        self._projection_summary = ""
        self._sideburn_active = False
        self._sideburn_direction = 0.0
        self._sideburn_release_counter = 0
        self._sideburn_frame_count = 0
        self._sideburn_switch_hold = 0
        self._sideburn_reentry_cooldown = 0
        self._terminal_burn_hold = 0
        self.set_behavior(behavior)

    def set_behavior(self, behavior: str) -> None:
        key = str(behavior).strip().lower()
        if key != "flare":
            raise ValueError(f"Unknown flare behavior '{behavior}'. Expected one of: flare")
        self._behavior = "flare"
        self._ballistic_debug_summary = ""
        self._projection_summary = ""
        self._last_guidance = None
        self._last_projected_dx = 0.0
        self._last_t_go = 1.0
        self._sideburn_active = False
        self._sideburn_direction = 0.0
        self._sideburn_release_counter = 0
        self._sideburn_frame_count = 0
        self._sideburn_switch_hold = 0
        self._sideburn_reentry_cooldown = 0
        self._terminal_burn_hold = 0

    @property
    def behavior(self) -> str:
        return self._behavior

    def _ballistic_clearance(self) -> float:
        if self.vehicle_info is None:
            return 0.0
        return max(0.0, 0.5 * float(self.vehicle_info.height))

    def _terminal_brake_altitude(
        self,
        passive: PassiveSensors,
        *,
        alt: float,
        dx: float,
        burn_altitude: float,
        spool_time: float,
        max_force: float,
    ) -> float:
        _ = passive, alt, dx, spool_time, max_force
        return burn_altitude

    def _resolve_sideburn_direction(self, projected_dx: float, dx: float, vx: float) -> float:
        if self._sideburn_switch_hold > 0:
            self._sideburn_switch_hold -= 1
        if (
            self._sideburn_direction != 0.0
            and self._sideburn_switch_hold == 0
            and (self._sideburn_direction * vx) > self._control_cfg.sideburn_flip_vx
        ):
            self._sideburn_direction = -self._sideburn_direction
            self._sideburn_switch_hold = 24
            return self._sideburn_direction

        if abs(projected_dx) > 1e-3:
            candidate = math.copysign(1.0, projected_dx)
        elif abs(vx) > self._control_cfg.sideburn_switch_vx:
            candidate = -math.copysign(1.0, vx)
        elif abs(dx) > 1e-3:
            candidate = math.copysign(1.0, dx)
        elif abs(vx) > 1e-3:
            candidate = -math.copysign(1.0, vx)
        else:
            candidate = self._sideburn_direction if self._sideburn_direction != 0.0 else 1.0

        if self._sideburn_direction == 0.0:
            self._sideburn_direction = candidate
        elif candidate != self._sideburn_direction:
            if (
                self._sideburn_switch_hold == 0
                and
                abs(projected_dx) <= self._control_cfg.sideburn_switch_dx
                and abs(vx) <= self._control_cfg.sideburn_switch_vx
            ):
                self._sideburn_direction = candidate
                self._sideburn_switch_hold = 18
        return self._sideburn_direction

    def update(
        self,
        dt: float,
        passive: PassiveSensors,
        active: ActiveSensors,
    ) -> BotAction:
        if passive.state != "flying":
            self._sideburn_active = False
            self._sideburn_direction = 0.0
            self._sideburn_release_counter = 0
            self._sideburn_frame_count = 0
            self._sideburn_switch_hold = 0
            self._sideburn_reentry_cooldown = 0
            self._terminal_burn_hold = 0
            self._last_guidance = None
            self._projection_summary = ""
            self._ballistic_debug_summary = ""
        if passive.state in ("landed", "crashed", "out_of_fuel"):
            action = BotAction(
                0.0,
                passive.angle,
                False,
                status=f"{self._policy.status_prefix}:{passive.state}",
            )
            self.status = action.status
            return action
        self._active_sensors = active
        try:
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
                a_up_sp = self._vertical_controller(
                    passive,
                    vy_sp=-0.8,
                    alt=alt,
                    vertical_mode="flare",
                    up_acc_max=up_acc_max,
                )
                action = self._allocate_controls(
                    dt,
                    passive,
                    a_x_sp=0.0,
                    a_up_sp=a_up_sp,
                    dx=0.0,
                    alt=alt,
                    vertical_mode="flare",
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
                f"{self._policy.status_prefix}:{guidance.phase} dx:{stable(guidance.dx, 1):6.1f} "
                f"vx:{stable(passive.vx, 1):5.1f} vy:{stable(passive.vy_up, 1):5.1f} "
                f"vys:{stable(guidance.vy_sp, 1):5.1f} "
                f"balt:{stable(guidance.burn_altitude, 1):5.1f}"
            )
            self.status = action.status
            return action
        finally:
            self._active_sensors = None

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
        _ = max_throttle, ramp_up
        cfg = self._control_cfg
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
            clearance=self._ballistic_clearance(),
            segment_length=20.0,
            max_points=192,
        )
        track_dx = projection.projected_dx
        t_go = clamp(projection.t_fall, cfg.coupled_tgo_min, cfg.coupled_tgo_max)
        self._last_projected_dx = float(track_dx)
        self._last_t_go = float(t_go)

        abs_track_dx = abs(track_dx)
        abs_vx = abs(float(passive.vx))
        dx_alt_ratio = abs(dx) / max(1.0, alt)
        lateral_stop_distance = (abs_vx * abs_vx) / max(1e-3, 2.0 * cfg.sideburn_ax_cap)
        projected_overshoot = (dx * track_dx) < 0.0
        sideburn_speed_urgent = (
            projected_overshoot
            and abs_track_dx >= cfg.sideburn_urgent_projected_dx_min
            and
            abs_vx >= cfg.sideburn_urgent_vx
            and lateral_stop_distance >= (cfg.sideburn_stop_distance_ratio * abs(dx))
        )
        track_vx_need = abs(dx) / max(0.5, t_go)
        if self._sideburn_reentry_cooldown > 0:
            self._sideburn_reentry_cooldown -= 1
        if self._sideburn_active:
            self._sideburn_frame_count += 1
            sideburn_clear = (
                abs_track_dx <= cfg.sideburn_exit_dx and abs_vx <= cfg.sideburn_exit_vx
            )
            relaxed_clear = (
                abs_track_dx <= cfg.sideburn_exit_dx_relaxed
                and abs_vx <= cfg.sideburn_exit_vx_relaxed
            )
            handoff_vx_limit = max(
                cfg.sideburn_exit_to_coupled_vx,
                cfg.sideburn_exit_track_vx_ratio * track_vx_need,
            )
            handoff_clear = (
                abs_track_dx <= cfg.sideburn_exit_to_coupled_dx
                and abs_vx <= handoff_vx_limit
            )
            if sideburn_clear:
                self._sideburn_release_counter += 1
            elif relaxed_clear:
                self._sideburn_release_counter += 1
            elif handoff_clear:
                self._sideburn_release_counter += 1
            else:
                self._sideburn_release_counter = 0
            if (
                self._sideburn_release_counter >= cfg.sideburn_release_frames
                or self._sideburn_frame_count >= cfg.sideburn_max_frames
                or alt <= cfg.sideburn_min_altitude
                or float(passive.vy_up) >= cfg.sideburn_abort_climb_vy
            ):
                self._sideburn_active = False
                self._sideburn_release_counter = 0
                self._sideburn_frame_count = 0
                self._sideburn_direction = 0.0
                self._sideburn_switch_hold = 0
                self._sideburn_reentry_cooldown = max(
                    self._sideburn_reentry_cooldown,
                    int(cfg.sideburn_reentry_cooldown_frames),
                )
                self._terminal_burn_hold = max(
                    self._terminal_burn_hold,
                    int(cfg.sideburn_exit_burn_hold_frames),
                )
        elif (
            self._sideburn_reentry_cooldown <= 0
            and
            cfg.sideburn_min_altitude < alt <= cfg.sideburn_entry_alt_max
            and alt >= cfg.sideburn_entry_alt_min
            and float(passive.vy_up) <= cfg.sideburn_entry_vy_max
            and (
                (
                    projected_overshoot
                    and
                    dx_alt_ratio >= cfg.sideburn_min_dx_alt_ratio
                    and (
                        (
                            abs_track_dx >= cfg.sideburn_enter_dx
                            and abs_vx >= cfg.sideburn_enter_vx
                        )
                        or (
                            alt <= cfg.sideburn_force_low_alt
                            and abs_vx >= cfg.sideburn_force_vx
                            and abs_track_dx >= cfg.sideburn_urgent_projected_dx_min
                        )
                    )
                )
                or sideburn_speed_urgent
            )
        ):
            self._sideburn_active = True
            self._sideburn_release_counter = 0
            self._sideburn_frame_count = 0
            self._sideburn_switch_hold = 0

        touchdown_ready = (
            alt <= cfg.touchdown_altitude
            and abs_track_dx <= cfg.touchdown_entry_dx
            and abs(float(passive.vx)) <= cfg.touchdown_entry_vx
        )
        if touchdown_ready:
            phase = "touchdown"
            vertical_mode = "flare"
        elif self._sideburn_active:
            phase = "sideburn"
            vertical_mode = "coast_hold"
        else:
            phase = "coupled_terminal"
            vertical_mode = "terminal_burn"

        if phase == "sideburn":
            vx_target_mag = min(
                cfg.sideburn_vx_cap,
                max(
                    cfg.sideburn_vx_floor + (cfg.sideburn_vx_floor_per_alt * alt),
                    track_vx_need + cfg.sideburn_track_vx_buffer,
                ),
            )
            if abs(dx) > 1e-3:
                target_sign = math.copysign(1.0, dx)
            elif abs(float(passive.vx)) > 1e-3:
                target_sign = -math.copysign(1.0, float(passive.vx))
            else:
                target_sign = 1.0
            vx_sp = target_sign * vx_target_mag
            _ = self._resolve_sideburn_direction(track_dx, dx, passive.vx)
            vy_sp = -clamp(
                cfg.sideburn_descent_base + (cfg.sideburn_descent_gain * math.sqrt(max(0.0, alt))),
                cfg.sideburn_descent_min,
                cfg.sideburn_descent_max,
            )
        elif phase == "touchdown":
            vx_sp = clamp(-float(passive.vx), -cfg.coupled_near_vx_cap, cfg.coupled_near_vx_cap)
            vy_sp = -clamp(
                cfg.touchdown_descent_base + (cfg.touchdown_descent_gain * alt),
                cfg.touchdown_descent_min,
                cfg.touchdown_descent_max,
            )
        else:
            vx_track = track_dx / max(0.5, t_go)
            vx_stop = -float(passive.vx)
            vx_sp = (
                (cfg.coupled_vx_track_weight * vx_track)
                + ((1.0 - cfg.coupled_vx_track_weight) * vx_stop)
            )
            vx_sp = clamp(vx_sp, -cfg.coupled_vx_cap, cfg.coupled_vx_cap)
            if alt <= cfg.coupled_low_alt_vx_cap_alt:
                low_alt_vx_cap = clamp(
                    cfg.coupled_low_alt_vx_cap_min
                    + (cfg.coupled_low_alt_vx_cap_gain * math.sqrt(max(0.0, alt))),
                    cfg.coupled_low_alt_vx_cap_min,
                    cfg.coupled_low_alt_vx_cap_max,
                )
                vx_sp = clamp(vx_sp, -low_alt_vx_cap, low_alt_vx_cap)
            if abs_track_dx <= cfg.coupled_near_dx and alt <= cfg.coupled_near_alt:
                vx_sp = clamp(vx_sp, -cfg.coupled_near_vx_cap, cfg.coupled_near_vx_cap)
            vy_sp = -clamp(
                cfg.coupled_descent_base + (cfg.coupled_descent_gain * math.sqrt(max(0.0, alt))),
                cfg.coupled_descent_min,
                cfg.coupled_descent_max,
            )
            if (
                alt <= cfg.coupled_misaligned_alt
                and (
                    abs_track_dx > cfg.touchdown_entry_dx
                    or abs(float(passive.vx)) > cfg.touchdown_entry_vx
                )
            ):
                vy_sp = min(vy_sp, -cfg.coupled_misaligned_vy_min)

        _, up_acc_max = vehicle_limits(passive, max_force)
        down_speed = max(0.0, -float(passive.vy_up))
        nominal_throttle = min(1.0, max_throttle)
        spool_time = max(0.0, nominal_throttle - max(0.0, float(passive.thrust_level))) / max(
            1e-3,
            ramp_up,
        )
        spool_distance = (down_speed * spool_time) + (4.9 * spool_time * spool_time)
        flare_speed = clamp(0.45 + (0.11 * alt), 0.7, 2.5)
        speed_to_kill = max(0.0, down_speed - flare_speed)
        stop_distance = (speed_to_kill * speed_to_kill) / (2.0 * max(1e-3, up_acc_max))
        burn_margin = 2.1 + (0.12 * max(0.0, abs_track_dx - 8.0))
        burn_altitude = stop_distance + spool_distance + burn_margin
        burn_altitude = self._terminal_brake_altitude(
            passive,
            alt=alt,
            dx=track_dx,
            burn_altitude=burn_altitude,
            spool_time=spool_time,
            max_force=max_force,
        )
        time_to_impact, impact_source = ballistic_time_to_impact(passive, active)
        time_to_brake = spool_time + (speed_to_kill / max(1e-3, up_acc_max))
        raw_burn_now = bool(
            down_speed > 0.6
            and (
                alt <= burn_altitude
                or time_to_impact <= (time_to_brake + cfg.burn_enter_time_margin)
            )
        )
        if raw_burn_now:
            self._terminal_burn_hold = max(self._terminal_burn_hold, int(cfg.burn_hold_frames))
        elif self._terminal_burn_hold > 0:
            self._terminal_burn_hold -= 1
        hold_burn = (self._terminal_burn_hold > 0) and (not raw_burn_now)
        burn_now = raw_burn_now or hold_burn
        if phase == "coupled_terminal":
            if raw_burn_now:
                vertical_mode = "terminal_burn"
            elif hold_burn:
                vertical_mode = "flare"
            else:
                low_alt_misaligned = (
                    alt <= cfg.anti_hover_alt
                    and (
                        abs_track_dx > cfg.anti_hover_dx
                        or abs(float(passive.vx)) > cfg.touchdown_entry_vx
                    )
                )
                vertical_mode = "flare" if low_alt_misaligned else "eco_glide"
        guidance = GuidanceTargets(
            phase=phase,
            vertical_mode=vertical_mode,
            vx_sp=vx_sp,
            vy_sp=vy_sp,
            dx=dx,
            alt=alt,
            burn_altitude=burn_altitude,
        )
        self._last_guidance = guidance
        self._projection_summary = (
            f"proj pdx:{track_dx:6.1f} tf:{projection.t_fall:4.1f} "
            f"src:{'s' if projection.used_sensor else 'a'} "
            f"sb:{int(self._sideburn_active)} burn:{int(burn_now)} "
            f"tti:{time_to_impact:4.1f}{impact_source[:1]}"
        )
        return guidance

    def _horizontal_controller(
        self,
        passive: PassiveSensors,
        vx_sp: float,
    ) -> float:
        cfg = self._control_cfg
        guidance = self._last_guidance
        if guidance is None:
            return (0.6 * (vx_sp - passive.vx)) - (0.09 * passive.ax)

        if guidance.phase == "sideburn":
            t_go = max(0.5, self._last_t_go)
            vx_err = vx_sp - float(passive.vx)
            pos_term = self._last_projected_dx / max(1e-3, t_go * t_go)
            raw_ax = (1.05 * vx_err) + (0.28 * pos_term) - (0.06 * float(passive.ax))
            direction = self._resolve_sideburn_direction(
                self._last_projected_dx,
                guidance.dx,
                passive.vx,
            )
            ax_mag = abs(raw_ax)
            projected_overshoot = (guidance.dx * self._last_projected_dx) < 0.0
            if projected_overshoot and (
                abs(self._last_projected_dx) > cfg.sideburn_force_dx or abs(vx_err) > 1.0
            ):
                ax_mag = max(ax_mag, cfg.sideburn_ax_floor)
            return direction * clamp(ax_mag, 0.0, cfg.sideburn_ax_cap)

        if (
            guidance.vertical_mode == "eco_glide"
            and guidance.alt >= cfg.eco_glide_lateral_hold_alt
        ):
            return 0.0

        t_go = clamp(self._last_t_go, cfg.coupled_tgo_min, cfg.coupled_tgo_max)
        vx_err = vx_sp - float(passive.vx)
        pos_term = self._last_projected_dx / max(1e-3, t_go * t_go)
        vel_term = vx_err / max(1e-3, t_go)
        ax_target = (
            (cfg.coupled_ax_pos_gain * pos_term)
            + (cfg.coupled_ax_vel_gain * vel_term)
            - (cfg.coupled_ax_damping * float(passive.ax))
        )
        if guidance.alt <= cfg.coupled_soft_alt and abs(self._last_projected_dx) <= cfg.coupled_soft_dx:
            ax_target *= cfg.coupled_soft_scale
        ax_cap = cfg.coupled_ax_cap
        if guidance.alt <= cfg.coupled_low_alt_ax_alt:
            ax_cap = min(ax_cap, cfg.coupled_low_alt_ax_cap)
        return clamp(ax_target, -ax_cap, ax_cap)

    def _vertical_controller(
        self,
        passive: PassiveSensors,
        vy_sp: float,
        alt: float,
        vertical_mode: str,
        up_acc_max: float,
    ) -> float:
        cfg = self._control_cfg
        if vertical_mode == "coast_hold":
            vy_err = vy_sp - float(passive.vy_up)
            a_up_cmd = 6.7 + (0.16 * vy_err)
            if float(passive.vy_up) > -cfg.anti_hover_vy_floor:
                a_up_cmd -= cfg.sideburn_hover_penalty * (
                    float(passive.vy_up) + cfg.anti_hover_vy_floor
                )
            max_up_cmd = 9.2 if alt < 14.0 else 8.85
            a_up_cmd = clamp(a_up_cmd, 4.4, max_up_cmd)
            if (
                alt <= cfg.sideburn_emergency_alt
                and float(passive.vy_up) < -cfg.emergency_vy
            ):
                a_up_cmd = max(a_up_cmd, 9.8 + (cfg.emergency_brake_gain * up_acc_max))
            return clamp(a_up_cmd, 0.0, 9.8 + (0.55 * up_acc_max))
        return vertical_controller(
            self._policy,
            passive,
            vy_sp,
            alt,
            vertical_mode,
            up_acc_max,
        )

    def _allocate_sideburn_controls(
        self,
        dt: float,
        passive: PassiveSensors,
        *,
        a_x_sp: float,
        a_up_sp: float,
    ) -> BotAction:
        max_power, min_throttle, max_throttle, _ = self._engine_profile()
        mass = max(0.5, float(passive.mass))
        direction = self._sideburn_direction if self._sideburn_direction != 0.0 else 1.0
        cone_limit = max(8.0, 2.0 * self._control_cfg.sideburn_switch_dx)
        target_angle = direction * resolve_sideburn_target_angle(
            self._sideburn_cfg,
            projected_dx=self._last_projected_dx,
            cone_limit=cone_limit,
            vy_up=float(passive.vy_up),
        )
        target_angle = clamp(
            target_angle,
            -self._control_cfg.sideburn_max_tilt,
            self._control_cfg.sideburn_max_tilt,
        )
        angle_cmd = rate_limit_angle_command(
            target_angle,
            self._prev_angle_cmd,
            dt,
            max_rate=self._control_cfg.sideburn_angle_rate,
        )
        self._prev_angle_cmd = angle_cmd

        along_track_ax = direction * float(a_x_sp)
        ax_mag = max(0.0, along_track_ax)
        if abs(self._last_projected_dx) > self._control_cfg.sideburn_force_dx:
            ax_mag = max(ax_mag, self._control_cfg.sideburn_ax_floor)
        if (
            ax_mag <= 0.12
            and abs(self._last_projected_dx) <= self._control_cfg.sideburn_exit_dx
            and abs(float(passive.vx)) <= self._control_cfg.sideburn_exit_vx
        ):
            return BotAction(target_thrust=0.0, target_angle=angle_cmd, refuel=False)

        sin_term = max(0.2, abs(math.sin(angle_cmd)))
        cos_term = max(0.2, abs(math.cos(angle_cmd)))
        thrust_from_ax = (mass * ax_mag) / max(max_power * sin_term, 1e-3)
        thrust_from_up = (mass * max(0.0, float(a_up_sp))) / max(max_power * cos_term, 1e-3)
        thrust = max(thrust_from_ax, thrust_from_up)
        thrust = clamp(
            thrust,
            self._sideburn_cfg.setup_sideburn_min_thrust,
            min(max_throttle, self._sideburn_cfg.setup_sideburn_max_thrust),
        )
        if thrust > 0.0:
            thrust = max(min_throttle, thrust)
        return BotAction(target_thrust=thrust, target_angle=angle_cmd, refuel=False)

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
        if vertical_mode == "coast_hold":
            return self._allocate_sideburn_controls(
                dt,
                passive,
                a_x_sp=a_x_sp,
                a_up_sp=a_up_sp,
            )

        max_power, min_throttle, max_throttle, _ = self._engine_profile()
        max_force = max_power * max_throttle
        mass, _ = vehicle_limits(passive, max_force)
        up_component = max(0.0, float(a_up_sp))
        target_angle = math.atan2(float(a_x_sp), max(0.2, up_component))
        max_tilt = self._control_cfg.coupled_max_tilt
        if alt < 20.0:
            if (
                abs(dx) <= self._control_cfg.coupled_low_alt_tilt_dx
                and abs(float(passive.vx)) <= self._control_cfg.coupled_low_alt_tilt_vx
            ):
                max_tilt = self._control_cfg.coupled_low_alt_tilt
            else:
                max_tilt = self._control_cfg.coupled_low_alt_tilt_far
        target_angle = clamp(target_angle, -max_tilt, max_tilt)
        angle_cmd = rate_limit_angle_command(
            target_angle,
            self._prev_angle_cmd,
            dt,
            max_rate=self._control_cfg.coupled_angle_rate,
        )
        self._prev_angle_cmd = angle_cmd
        angle_cmd = cap_low_altitude_angle(
            angle_cmd,
            alt=alt,
            dx=dx,
            cfg=self._course_cfg,
        )

        thrust_acc = math.hypot(float(a_x_sp), up_component)
        thrust = (mass * thrust_acc) / max(max_power, 1e-3)
        if (
            alt < self._control_cfg.touchdown_zero_alt
            and abs(dx) <= self._control_cfg.touchdown_zero_dx
            and abs(float(passive.vx)) <= self._control_cfg.touchdown_zero_vx
            and abs(float(passive.vy_up)) <= self._control_cfg.touchdown_zero_vy
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

    def get_headless_stats(self) -> str:
        base = super().get_headless_stats()
        if self._ballistic_debug_summary:
            if base:
                base = f"{base} {self._ballistic_debug_summary}"
            else:
                base = self._ballistic_debug_summary
        if not self._projection_summary:
            return base
        if not base:
            return self._projection_summary
        return f"{base} {self._projection_summary}"


def create_bot() -> Bot:
    return FlareBot()


def list_behavior_names() -> tuple[str, ...]:
    return ("flare",)


__all__ = ["FlareBot", "create_bot", "list_behavior_names"]
