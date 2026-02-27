"""Phased ZEM/ZEV powered-descent bot.

Three-phase terminal controller:
  preflare_coast  -> retrograde coast, engine off, wait for feasibility gate
  terminal_burn   -> ZEM/ZEV 2-axis guidance with feasibility-root ignition
  touchdown       -> low-alt settle and engine cutoff

The flare gate uses a 1-D feasibility root-find: compute the thrust
acceleration magnitude the ZEM/ZEV law would request at the current state
and compare it against engine limits.  When the required accel first
crosses into the feasible band (accounting for min-thrust floor and
hysteresis), the bot commits to terminal burn.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from bots._ballistics import (
    BallisticProjection,
    ballistic_time_to_impact,
    estimate_ballistic_projection,
)
from bots._bot_math import (
    clamp,
    engine_profile,
    finite_altitude,
    rate_limit_angle_command,
    stable,
)
from bots._targeting import pick_target, target_half_width
from core.bot import ActiveSensors, Bot, BotAction, PassiveSensors
from core.config import GRAVITY

_GRAVITY_MAG = abs(float(GRAVITY))


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ZemZevConfig:
    # ZEM/ZEV gains (standard proportional form: a = Kp/t² ZEM + Kv/t ZEV)
    # Vertical gains are aggressive (need to stop quickly); lateral gains
    # are moderate so the controller doesn't demand impossible corrections
    # at large miss distances.
    zem_pos_gain_x: float = 3.0
    zem_pos_gain_y: float = 6.0
    zev_vel_gain_x: float = 1.8
    zev_vel_gain_y: float = 3.6

    # Gain-schedule floor: bounds effective Kp/t² and Kv/t at short
    # prediction horizons.  ZEM/ZEV miss terms still use real t_go.
    t_go_floor: float = 1.0

    # Desired touchdown vertical speed schedule
    vy_target_base: float = 0.25
    vy_target_sqrt_gain: float = 0.07
    vy_target_min: float = 0.25
    vy_target_max: float = 2.4

    # Anti-hover: prevent stalling when still far from pad
    anti_hover_alt: float = 24.0
    anti_hover_dx: float = 24.0
    anti_hover_vy_min: float = 1.0

    # Lateral accel caps
    net_ax_cap: float = 8.8
    net_ax_cap_low_alt: float = 4.2
    net_ax_cap_low_alt_threshold: float = 22.0

    # Vertical accel cap
    thrust_ay_cap: float = 22.0

    # Tilt limits (terminal needs more authority for lateral correction)
    max_tilt: float = 0.78
    max_tilt_low_alt: float = 0.18
    max_tilt_low_alt_far: float = 0.34
    low_alt_tilt_alt: float = 20.0
    low_alt_tilt_dx: float = 12.0
    low_alt_tilt_vx: float = 2.4

    # Angle rate limit
    angle_rate: float = 2.4
    angle_rate_coast: float = 2.8

    # Retrograde coast attitude
    retrograde_hold_speed_min: float = 3.0
    retrograde_hold_max_tilt: float = 1.28

    # Touchdown cutoff thresholds
    touchdown_alt: float = 4.0
    touchdown_entry_dx: float = 8.0
    touchdown_entry_vx: float = 2.0
    touchdown_zero_alt: float = 2.4
    touchdown_zero_dx: float = 7.0
    touchdown_zero_vx: float = 0.55
    touchdown_zero_vy: float = 0.9
    touchdown_descent_base: float = 0.48
    touchdown_descent_gain: float = 0.09
    touchdown_descent_min: float = 0.45
    touchdown_descent_max: float = 1.10

    # Emergency brake
    emergency_vy: float = 12.0
    emergency_alt: float = 240.0

    # Stopping-distance brake
    stop_margin: float = 3.5
    brake_gain: float = 0.4

    # Feasibility gate
    gate_accel_margin: float = 0.85
    gate_commit_hold_frames: int = 6
    gate_min_down_speed: float = 0.6
    # Lateral miss → earlier ignition: burn_alt += lateral_gate_gain * |projected_dx|
    gate_lateral_gain: float = 0.25
    gate_lateral_deadband: float = 15.0

    # Damping: measured-accel feedback
    ax_damping: float = 0.10

    # Low-alt lateral gain taper
    low_alt_gain_taper_alt: float = 8.0
    low_alt_gain_taper_min: float = 0.35

    # Lateral deadband near touchdown
    lateral_deadband_alt: float = 6.0
    lateral_deadband_dx: float = 3.0

    # Terminal descent speed floor
    terminal_min_sink_vy: float = 1.2
    terminal_min_sink_gain: float = 0.30

    # Anti-hover near ground in terminal
    terminal_hover_cap_gain: float = 0.22

    # Projection parameters
    projection_segment_length: float = 20.0
    projection_max_points: int = 192


# ---------------------------------------------------------------------------
# Bot
# ---------------------------------------------------------------------------

class ZemZevBot(Bot):
    def __init__(self, behavior: str = "zem_zev") -> None:
        super().__init__()
        self._cfg = ZemZevConfig()
        self._behavior = "zem_zev"
        self._prev_angle_cmd = 0.0
        self._angle_cmd_initialized = False
        self._debug_summary = ""
        self._phase = "preflare_coast"
        self._gate_hold = 0
        self._last_t_go = 1.0
        self._last_projected_dx = 0.0
        self._last_target_half = 55.0
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
        self._debug_summary = ""
        self._phase = "preflare_coast"
        self._gate_hold = 0
        self._last_t_go = 1.0
        self._last_projected_dx = 0.0
        self._last_target_half = 55.0

    @property
    def behavior(self) -> str:
        return self._behavior

    # -- helpers --

    def _ballistic_clearance(self) -> float:
        if self.vehicle_info is None:
            return 0.0
        return max(0.0, 0.5 * float(self.vehicle_info.height))

    def _project(
        self,
        passive: PassiveSensors,
        active: ActiveSensors,
        dx: float,
    ) -> BallisticProjection:
        cfg = self._cfg
        alt = max(0.0, finite_altitude(passive))
        return estimate_ballistic_projection(
            dx=dx,
            alt=alt,
            vx=passive.vx,
            vy_up=passive.vy_up,
            x=passive.x,
            y=passive.y,
            active=active,
            clearance=self._ballistic_clearance(),
            segment_length=cfg.projection_segment_length,
            max_points=int(cfg.projection_max_points),
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

    # -- feasibility gate --

    @staticmethod
    def _zem_zev_vertical_accel(
        dy: float,
        vy: float,
        vy_target: float,
        t_go: float,
        kp_y: float,
        kv_y: float,
    ) -> float:
        """Vertical ZEM/ZEV acceleration command at given state."""
        g = _GRAVITY_MAG
        t2 = max(1e-6, t_go * t_go)
        t1 = max(1e-6, t_go)
        zem_y = dy - vy * t_go + 0.5 * g * t2
        zev_y = vy_target - (vy - g * t_go)
        return (kp_y / t2) * zem_y + (kv_y / t1) * zev_y

    def _feasibility_gate(
        self,
        *,
        alt: float,
        dy: float,
        vy: float,
        vy_target: float,
        t_go: float,
        up_acc_max: float,
        min_accel: float,
        down_speed: float,
        projected_dx: float,
        thrust_level: float,
        max_throttle: float,
        ramp_up: float,
    ) -> bool:
        """Return True when vertical ZEM/ZEV burn is feasible and should start.

        Gates on vertical axis only — lateral corrections are handled by
        tilt during the burn. Also triggers on stopping-distance safety
        (including engine spool-up margin), with extra altitude margin
        proportional to lateral miss so shallow entries fire the burn
        earlier.
        """
        cfg = self._cfg
        if down_speed < cfg.gate_min_down_speed:
            return False

        ay_req = self._zem_zev_vertical_accel(
            dy, vy, vy_target, t_go,
            cfg.zem_pos_gain_y, cfg.zev_vel_gain_y,
        )
        available = _GRAVITY_MAG + up_acc_max
        vert_feasible = (
            ay_req >= min_accel
            and ay_req <= available * (1.0 / cfg.gate_accel_margin)
        )

        # Stopping-distance gate with spool-up and lateral-miss margins
        nominal_throttle = min(1.0, max_throttle)
        spool_time = max(
            0.0, nominal_throttle - max(0.0, thrust_level)
        ) / max(1e-3, ramp_up)
        spool_distance = down_speed * spool_time + 0.5 * _GRAVITY_MAG * spool_time * spool_time
        flare_speed = clamp(0.45 + 0.11 * alt, 0.7, 6.0)
        speed_to_kill = max(0.0, down_speed - flare_speed)
        stop_distance = (speed_to_kill * speed_to_kill) / (2.0 * max(1e-3, up_acc_max))
        lateral_margin = cfg.gate_lateral_gain * max(
            0.0, abs(projected_dx) - cfg.gate_lateral_deadband
        )
        stop_gate = alt <= (stop_distance + spool_distance + cfg.stop_margin + lateral_margin)

        # Emergency: must commit if falling fast at moderate altitude
        emergency = down_speed >= cfg.emergency_vy and alt <= cfg.emergency_alt

        return vert_feasible or stop_gate or emergency

    # -- ZEM/ZEV thrust accel --

    def _zem_zev_thrust_accel(
        self,
        passive: PassiveSensors,
        *,
        dx: float,
        dy: float,
        t_go: float,
    ) -> tuple[float, float, float, float]:
        cfg = self._cfg
        g = _GRAVITY_MAG
        vx = float(passive.vx)
        vy = float(passive.vy_up)
        alt = max(0.0, finite_altitude(passive))
        vy_target = self._desired_terminal_vy(alt, dx, vx)

        t_eff = max(cfg.t_go_floor, t_go)
        t2 = t_eff * t_eff
        t1 = t_eff

        zem_x = dx - vx * t_go
        zem_y = dy - vy * t_go + 0.5 * g * t_go * t_go
        zev_x = -vx
        zev_y = vy_target - (vy - g * t_go)

        ax_cmd = (cfg.zem_pos_gain_x / t2) * zem_x + (cfg.zev_vel_gain_x / t1) * zev_x
        ay_cmd = (cfg.zem_pos_gain_y / t2) * zem_y + (cfg.zev_vel_gain_y / t1) * zev_y

        # Measured-accel damping
        ax_cmd -= cfg.ax_damping * float(passive.ax)

        # Low-alt gain taper
        if alt < cfg.low_alt_gain_taper_alt:
            taper = max(
                cfg.low_alt_gain_taper_min,
                alt / max(1.0, cfg.low_alt_gain_taper_alt),
            )
            ax_cmd *= taper

        # Lateral deadband near touchdown
        if alt < cfg.lateral_deadband_alt and abs(dx) < cfg.lateral_deadband_dx:
            ax_cmd *= 0.3

        ax_cap = cfg.net_ax_cap
        if alt <= cfg.net_ax_cap_low_alt_threshold:
            ax_cap = min(ax_cap, cfg.net_ax_cap_low_alt)
        ax_cmd = clamp(ax_cmd, -ax_cap, ax_cap)
        ay_cmd = clamp(ay_cmd, 0.0, cfg.thrust_ay_cap)
        return ax_cmd, ay_cmd, zem_x, zev_x

    # -- phase logic --

    def _select_phase(
        self,
        *,
        alt: float,
        dx: float,
        projected_dx: float,
        vx: float,
        gate_pass: bool,
    ) -> str:
        cfg = self._cfg

        # Touchdown: low alt + low lateral error
        if (
            alt <= cfg.touchdown_alt
            and abs(projected_dx) <= cfg.touchdown_entry_dx
            and abs(vx) <= cfg.touchdown_entry_vx
        ):
            return "touchdown"

        # Very low alt over pad -> force touchdown
        if alt <= cfg.touchdown_zero_alt + 1.0 and abs(dx) <= self._last_target_half:
            return "touchdown"

        prev = self._phase

        if prev == "preflare_coast":
            if gate_pass:
                self._gate_hold = cfg.gate_commit_hold_frames
                return "terminal_burn"
            return "preflare_coast"

        if prev == "terminal_burn":
            # Once committed, stay in terminal unless touchdown criteria met
            if self._gate_hold > 0:
                self._gate_hold -= 1
            return "terminal_burn"

        if prev == "touchdown":
            return "touchdown"

        return "preflare_coast"

    # -- main update --

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
            self._debug_summary = ""
            return action

        if not self._angle_cmd_initialized:
            self._prev_angle_cmd = float(passive.angle)
            self._angle_cmd_initialized = True

        max_power, min_throttle, max_throttle, _ = engine_profile(self.vehicle_info)
        mass = max(0.5, float(passive.mass))
        max_force = max_power * max_throttle
        up_acc_max = max(0.1, (max_force / mass) - _GRAVITY_MAG)
        min_force = max_power * min_throttle
        min_accel = min_force / mass

        target = pick_target(passive, pinned_uid=self.pinned_target_uid)
        if target is not None:
            dx = float(target.x) - float(passive.x)
            dy = float(target.y) - float(passive.y)
            self._last_target_half = target_half_width(getattr(target, "size", None))
        else:
            dx = 0.0
            dy = -max(0.0, finite_altitude(passive))

        projection = self._project(passive, active, dx)
        t_go = max(0.1, float(projection.t_fall))
        projected_dx = float(projection.projected_dx)
        self._last_t_go = t_go
        self._last_projected_dx = projected_dx

        alt = max(0.0, finite_altitude(passive))
        vx = float(passive.vx)
        vy = float(passive.vy_up)
        down_speed = max(0.0, -vy)
        vy_target = self._desired_terminal_vy(alt, dx, vx)

        gate_pass = self._feasibility_gate(
            alt=alt, dy=dy, vy=vy, vy_target=vy_target,
            t_go=t_go,
            up_acc_max=up_acc_max,
            min_accel=min_accel,
            down_speed=down_speed,
            projected_dx=projected_dx,
            thrust_level=float(passive.thrust_level),
            max_throttle=max_throttle,
            ramp_up=engine_profile(self.vehicle_info)[3],
        )

        phase = self._select_phase(
            alt=alt, dx=dx, projected_dx=projected_dx, vx=vx,
            gate_pass=gate_pass,
        )
        self._phase = phase

        # --- control per phase ---

        if phase == "preflare_coast":
            action = self._coast_control(dt, passive, alt, dx, vx, vy, down_speed, up_acc_max,
                                         max_power, min_throttle, max_throttle)
        elif phase == "terminal_burn":
            action = self._terminal_control(dt, passive, alt, dx, dy, t_go, projected_dx,
                                            down_speed, up_acc_max,
                                            max_power, min_throttle, max_throttle, mass)
        else:
            action = self._touchdown_control(dt, passive, alt, dx, vx, vy,
                                             max_power, min_throttle, max_throttle, mass)

        tti, tti_source = ballistic_time_to_impact(passive, active)
        self._debug_summary = (
            f"zem {phase[:4]} tgo:{stable(t_go, 2):4.1f} "
            f"pdx:{stable(projected_dx, 1):5.1f} "
            f"tti:{stable(tti, 1):4.1f}{tti_source[:1]}"
        )
        action.status = (
            f"zem_zev:{phase} dx:{stable(dx, 1):6.1f} "
            f"vx:{stable(vx, 1):5.1f} vy:{stable(vy, 1):5.1f}"
        )
        self.status = action.status
        return action

    # -- phase controllers --

    def _coast_control(
        self,
        dt: float,
        passive: PassiveSensors,
        alt: float,
        dx: float,
        vx: float,
        vy: float,
        down_speed: float,
        up_acc_max: float,
        max_power: float,
        min_throttle: float,
        max_throttle: float,
    ) -> BotAction:
        """Preflare coast: engine off, retrograde attitude bias.

        Emergency brake overrides if stopping distance is critical.
        """
        cfg = self._cfg

        # Emergency brake check
        flare_speed = clamp(0.45 + 0.11 * alt, 0.7, 6.0)
        speed_to_kill = max(0.0, down_speed - flare_speed)
        stop_distance = (speed_to_kill * speed_to_kill) / (2.0 * max(1e-3, up_acc_max))
        need_brake = (
            alt <= (stop_distance + cfg.stop_margin)
            or (down_speed >= cfg.emergency_vy and alt <= cfg.emergency_alt)
        )

        if need_brake:
            a_up = _GRAVITY_MAG + (cfg.brake_gain * up_acc_max)
            if down_speed >= cfg.emergency_vy:
                a_up = _GRAVITY_MAG + up_acc_max
            mass = max(0.5, float(passive.mass))
            thrust = (mass * a_up) / max(max_power, 1e-3)
            thrust = clamp(thrust, 0.0, max_throttle)
            if thrust > 0.0:
                thrust = max(min_throttle, thrust)
            angle_target = 0.0
        else:
            thrust = 0.0
            # Retrograde attitude
            speed_mag = math.hypot(vx, vy)
            if speed_mag >= cfg.retrograde_hold_speed_min:
                angle_target = math.atan2(-vx, -vy)
                angle_target = clamp(
                    angle_target,
                    -cfg.retrograde_hold_max_tilt,
                    cfg.retrograde_hold_max_tilt,
                )
            else:
                angle_target = 0.0

        angle_cmd = rate_limit_angle_command(
            angle_target,
            self._prev_angle_cmd,
            dt,
            max_rate=cfg.angle_rate_coast,
        )
        self._prev_angle_cmd = angle_cmd
        return BotAction(target_thrust=thrust, target_angle=angle_cmd, refuel=False)

    def _terminal_control(
        self,
        dt: float,
        passive: PassiveSensors,
        alt: float,
        dx: float,
        dy: float,
        t_go: float,
        projected_dx: float,
        down_speed: float,
        up_acc_max: float,
        max_power: float,
        min_throttle: float,
        max_throttle: float,
        mass: float,
    ) -> BotAction:
        """Terminal burn: full ZEM/ZEV 2-axis guidance."""
        cfg = self._cfg

        a_x, a_up, _, _ = self._zem_zev_thrust_accel(
            passive, dx=dx, dy=dy, t_go=t_go,
        )

        # Stopping-distance safety brake
        flare_speed = clamp(0.45 + 0.11 * alt, 0.7, 6.0)
        speed_to_kill = max(0.0, down_speed - flare_speed)
        stop_distance = (speed_to_kill * speed_to_kill) / (2.0 * max(1e-3, up_acc_max))
        if alt <= (stop_distance + cfg.stop_margin):
            a_up = max(a_up, _GRAVITY_MAG + (cfg.brake_gain * up_acc_max))
        if down_speed >= cfg.emergency_vy and alt <= cfg.emergency_alt:
            a_up = max(a_up, _GRAVITY_MAG + up_acc_max)
        a_up = clamp(a_up, 0.0, _GRAVITY_MAG + up_acc_max)

        # Prevent climb + force descent.  Target sink rate scales with
        # altitude and lateral miss so the controller descends faster
        # when far from target (fuel-saving) and gently near touchdown.
        vy_now = float(passive.vy_up)
        dx_mag = abs(dx)
        miss_factor = clamp(dx_mag / 100.0, 0.0, 1.0)
        target_sink = -clamp(
            0.45 + 0.11 * alt + 3.0 * miss_factor,
            0.7, 8.0,
        )
        if vy_now > target_sink:
            overshoot = vy_now - target_sink
            a_up = min(a_up, _GRAVITY_MAG - 0.6 * overshoot)

        # Tilt and angle
        max_tilt = cfg.max_tilt
        if alt < cfg.low_alt_tilt_alt:
            if abs(dx) <= cfg.low_alt_tilt_dx and abs(float(passive.vx)) <= cfg.low_alt_tilt_vx:
                max_tilt = cfg.max_tilt_low_alt
            else:
                max_tilt = cfg.max_tilt_low_alt_far

        angle_target = math.atan2(a_x, max(0.2, a_up))
        angle_target = clamp(angle_target, -max_tilt, max_tilt)
        angle_cmd = rate_limit_angle_command(
            angle_target,
            self._prev_angle_cmd,
            dt,
            max_rate=cfg.angle_rate,
        )
        self._prev_angle_cmd = angle_cmd

        # Thrust allocation
        thrust_acc = math.hypot(a_x, max(0.0, a_up))
        thrust = (mass * thrust_acc) / max(max_power, 1e-3)
        thrust = clamp(thrust, 0.0, max_throttle)
        if thrust > 0.0:
            thrust = max(min_throttle, thrust)

        return BotAction(target_thrust=thrust, target_angle=angle_cmd, refuel=False)

    def _touchdown_control(
        self,
        dt: float,
        passive: PassiveSensors,
        alt: float,
        dx: float,
        vx: float,
        vy: float,
        max_power: float,
        min_throttle: float,
        max_throttle: float,
        mass: float,
    ) -> BotAction:
        """Touchdown: gentle settle with engine cutoff when nearly still."""
        cfg = self._cfg

        # Touchdown cutoff
        if (
            alt < cfg.touchdown_zero_alt
            and abs(dx) <= cfg.touchdown_zero_dx
            and abs(vx) <= cfg.touchdown_zero_vx
            and abs(vy) <= cfg.touchdown_zero_vy
        ):
            angle_cmd = rate_limit_angle_command(
                0.0, self._prev_angle_cmd, dt, max_rate=cfg.angle_rate,
            )
            self._prev_angle_cmd = angle_cmd
            return BotAction(target_thrust=0.0, target_angle=0.0, refuel=False)

        vy_sp = -clamp(
            cfg.touchdown_descent_base + cfg.touchdown_descent_gain * alt,
            cfg.touchdown_descent_min,
            cfg.touchdown_descent_max,
        )
        vy_err = vy_sp - vy
        a_up = _GRAVITY_MAG + 0.38 * vy_err
        if alt < 7.0:
            a_up += 0.08
        if alt < 3.0 and vy > -0.45:
            a_up -= 0.12
        a_up = clamp(a_up, 0.0, _GRAVITY_MAG + 3.0)

        # Gentle lateral damp
        a_x = clamp(-0.42 * vx - 0.10 * float(passive.ax), -1.2, 1.2)

        max_tilt = min(cfg.max_tilt_low_alt, 0.12 if alt < 5.0 else 0.20)
        angle_target = math.atan2(a_x, max(0.2, a_up))
        angle_target = clamp(angle_target, -max_tilt, max_tilt)
        angle_cmd = rate_limit_angle_command(
            angle_target, self._prev_angle_cmd, dt, max_rate=cfg.angle_rate,
        )
        self._prev_angle_cmd = angle_cmd

        thrust_acc = math.hypot(a_x, max(0.0, a_up))
        thrust = (mass * thrust_acc) / max(max_power, 1e-3)
        thrust = clamp(thrust, 0.0, max_throttle)
        if thrust > 0.0:
            thrust = max(min_throttle, thrust)

        return BotAction(target_thrust=thrust, target_angle=angle_cmd, refuel=False)

    # -- stats --

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
