"""Drift-first bot: ballistic transfer → coast → terminal descent."""

from __future__ import annotations

import enum
import math

from bots._descent_core import (
    GuidanceTargets,
    StrategyDescentBot,
    clamp,
    finite_altitude,
    pick_target,
    rate_limit_angle_command,
    stable,
    vehicle_limits,
)
from bots._drift_core import (
    DRIFT_BALANCED_POLICY,
    DRIFT_BALANCED_TRANSFER,
    DriftCourseConfig,
    TransferBurnConfig,
    apply_drift_guidance,
    cap_low_altitude_angle,
    compute_transfer_plan,
    list_drift_behavior_names,
    predict_landing_x,
    resolve_drift_behavior,
)
from core.bot import ActiveSensors, Bot, BotAction, PassiveSensors
from core.sensor import RadarContact


class _Phase(enum.Enum):
    TRANSFER_BURN = "transfer"
    COAST = "coast"
    TERMINAL = "terminal"


class DriftBot(StrategyDescentBot):
    def __init__(self, behavior: str = "balanced") -> None:
        super().__init__(DRIFT_BALANCED_POLICY)
        self._course_cfg = DriftCourseConfig()
        self._transfer_cfg: TransferBurnConfig = DRIFT_BALANCED_TRANSFER
        self._behavior = "balanced"
        self._phase = _Phase.TRANSFER_BURN
        self._transfer_vx_initial: float | None = None
        self._transfer_vx_target: float | None = None
        self.set_behavior(behavior)

    def set_behavior(self, behavior: str) -> None:
        key, policy, cfg, transfer_cfg = resolve_drift_behavior(behavior)
        self._policy = policy
        self._course_cfg = cfg
        self._transfer_cfg = transfer_cfg
        self._behavior = key
        # Reset phase state so a new run starts from the beginning.
        self._phase = _Phase.TRANSFER_BURN
        self._transfer_vx_initial = None
        self._transfer_vx_target = None

    @property
    def behavior(self) -> str:
        return self._behavior

    def _guidance(
        self,
        passive: PassiveSensors,
        target: RadarContact,
        *,
        max_force: float,
        max_throttle: float,
        ramp_up: float,
    ) -> GuidanceTargets:
        base_guidance = super()._guidance(
            passive,
            target,
            max_force=max_force,
            max_throttle=max_throttle,
            ramp_up=ramp_up,
        )
        return apply_drift_guidance(base_guidance, self._course_cfg)

    def _horizontal_controller(
        self,
        passive: PassiveSensors,
        vx_sp: float,
    ) -> float:
        vx_err = vx_sp - passive.vx
        abs_vx_sp = abs(vx_sp)
        alt = passive.altitude if math.isfinite(passive.altitude) else 0.0
        if self._behavior == "efficiency":
            if alt >= 95.0 and abs_vx_sp >= 2.8:
                gain = 1.35
                accel_damping = 0.02
            elif abs_vx_sp > 2.2:
                gain = 1.12
                accel_damping = 0.04
            else:
                gain = 0.78
                accel_damping = 0.085
        elif alt >= 120.0 and abs_vx_sp >= 3.0:
            gain = 1.1
            accel_damping = 0.035
        elif abs_vx_sp > 2.4:
            gain = 0.95
            accel_damping = 0.055
        else:
            gain = 0.72
            accel_damping = 0.1
        return (gain * vx_err) - (accel_damping * passive.ax)

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
        action = super()._allocate_controls(
            dt,
            passive,
            a_x_sp=a_x_sp,
            a_up_sp=a_up_sp,
            alt=alt,
            dx=dx,
            vertical_mode=vertical_mode,
        )
        action.target_angle = cap_low_altitude_angle(
            action.target_angle,
            alt=alt,
            dx=dx,
            cfg=self._course_cfg,
        )
        return action

    def _update_transfer_burn(
        self,
        dt: float,
        passive: PassiveSensors,
        target: RadarContact,
        alt: float,
        dx: float,
        active: ActiveSensors,
    ) -> BotAction:
        cfg = self._transfer_cfg

        # Not enough altitude to coast meaningfully — go straight to terminal.
        if alt < cfg.min_coast_altitude:
            self._phase = _Phase.TERMINAL
            self._transfer_vx_target = None
            return super().update(dt, passive, active)

        # Recompute target vx from current state every frame (adapts as altitude changes).
        vx_needed, _ = compute_transfer_plan(alt, dx, passive.vx, passive.vy_up)
        self._transfer_vx_target = vx_needed
        dvx = vx_needed - passive.vx

        # On first frame: decide whether to commit to the ballistic approach.
        # If the required reversal exceeds the threshold, fall back to the old continuous
        # approach — large reversals cost more in fuel than the coast saves.
        if self._transfer_vx_initial is None:
            if cfg.max_transfer_dvx > 0.0 and abs(dvx) > cfg.max_transfer_dvx:
                self._phase = _Phase.TERMINAL
                self._transfer_vx_target = None
                return super().update(dt, passive, active)
            self._transfer_vx_initial = passive.vx

        # Switch to coast when vx is on target.
        if abs(dvx) < cfg.vx_tolerance:
            self._phase = _Phase.COAST
            self._transfer_vx_target = None
            return self._update_coast(dt, passive, target, alt, dx, active)

        # Proportional tilt: full deflection when far, ease off near tolerance.
        approach_zone = cfg.vx_tolerance * 3.0
        tilt_frac = min(1.0, abs(dvx) / max(approach_zone, 0.01))
        raw_angle = math.copysign(tilt_frac * cfg.max_tilt, dvx)

        angle_cmd = rate_limit_angle_command(
            raw_angle,
            self._prev_angle_cmd,
            dt,
        )
        self._prev_angle_cmd = angle_cmd

        _, _, max_throttle, _ = self._engine_profile()
        action = BotAction(target_thrust=max_throttle, target_angle=angle_cmd, refuel=False)
        action.status = (
            f"drift:transfer dx:{stable(dx, 1):6.1f} vx:{stable(passive.vx, 1):5.1f}"
            f" dvx:{stable(dvx, 1):5.1f} vxt:{stable(vx_needed, 1):5.1f}"
        )
        self.status = action.status
        return action

    def _update_coast(
        self,
        dt: float,
        passive: PassiveSensors,
        target: RadarContact,
        alt: float,
        dx: float,
        active: ActiveSensors,
    ) -> BotAction:
        cfg = self._transfer_cfg
        max_power, min_throttle, max_throttle, ramp_up = self._engine_profile()
        max_force = max_power * max_throttle

        # Check whether terminal braking should start.
        guidance = self._guidance(
            passive, target, max_force=max_force, max_throttle=max_throttle, ramp_up=ramp_up
        )
        if guidance.vertical_mode == "terminal_burn" or alt < 20.0:
            self._phase = _Phase.TERMINAL
            self._transfer_vx_target = None
            return super().update(dt, passive, active)

        # Soft-coast: if descending too fast, apply minimum gravity compensation to cap
        # downspeed and keep terminal entry costs sane. This is NOT hovering — it only fires
        # when descent rate exceeds the cap, and at the minimum thrust to hold it.
        if cfg.max_coast_descent_rate != 0.0 and passive.vy_up < cfg.max_coast_descent_rate:
            mass, _ = vehicle_limits(passive, max_force)
            grav_comp = (mass * 9.8) / max(max_force, 1e-3)
            thrust = clamp(grav_comp, 0.0, max_throttle)
            if thrust > 0.0:
                thrust = max(min_throttle, thrust)
            angle_cmd = rate_limit_angle_command(
                0.0,
                self._prev_angle_cmd,
                dt,
            )
            self._prev_angle_cmd = angle_cmd
            action = BotAction(target_thrust=thrust, target_angle=angle_cmd, refuel=False)
            action.status = (
                f"drift:softcap vx:{stable(passive.vx, 1):5.1f} vy:{stable(passive.vy_up, 1):5.1f}"
            )
            self.status = action.status
            return action

        # Predict where we'd land on the current ballistic arc.
        predicted_x = predict_landing_x(passive.x, passive.vx, alt, passive.vy_up)
        pred_err = predicted_x - target.x

        if cfg.coast_correction_enabled and abs(pred_err) > cfg.coast_correction_threshold:
            # Small correction: tilt against the landing error at moderate throttle.
            # Negative sign: land right of target (pred_err > 0) → tilt left (negative angle).
            raw_angle = clamp(-pred_err * cfg.coast_correction_angle_scale, -0.35, 0.35)
            angle_cmd = rate_limit_angle_command(
                raw_angle,
                self._prev_angle_cmd,
                dt,
            )
            self._prev_angle_cmd = angle_cmd
            thrust = max_throttle * cfg.coast_correction_throttle
            if thrust > 0.0:
                thrust = max(min_throttle, thrust)
            action = BotAction(target_thrust=thrust, target_angle=angle_cmd, refuel=False)
            action.status = (
                f"drift:correction dx:{stable(dx, 1):6.1f} vx:{stable(passive.vx, 1):5.1f}"
                f" perr:{stable(pred_err, 1):6.1f}"
            )
        else:
            # True coast: engine off, let the ship level.
            angle_cmd = rate_limit_angle_command(
                0.0,
                self._prev_angle_cmd,
                dt,
            )
            self._prev_angle_cmd = angle_cmd
            action = BotAction(target_thrust=0.0, target_angle=angle_cmd, refuel=False)
            action.status = (
                f"drift:coast dx:{stable(dx, 1):6.1f} vx:{stable(passive.vx, 1):5.1f}"
                f" perr:{stable(pred_err, 1):6.1f} balt:{stable(guidance.burn_altitude, 1):5.1f}"
            )
        self.status = action.status
        return action

    def update(
        self,
        dt: float,
        passive: PassiveSensors,
        active: ActiveSensors,
    ) -> BotAction:
        if passive.state in ("landed", "crashed", "out_of_fuel"):
            action = BotAction(
                0.0,
                passive.angle,
                False,
                status=f"{self._policy.status_prefix}:{passive.state}",
            )
            self.status = action.status
            return action

        target = pick_target(passive)
        if target is None:
            max_power, _, max_throttle, _ = self._engine_profile()
            max_force = max_power * max_throttle
            _, up_acc_max = vehicle_limits(passive, max_force)
            alt = finite_altitude(passive)
            a_x_sp = self._horizontal_controller(passive, vx_sp=0.0)
            a_up_sp = self._vertical_controller(
                passive,
                vy_sp=-1.0,
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
            )
            action.status = f"{self._policy.status_prefix}:search"
            self.status = action.status
            return action

        alt = finite_altitude(passive)
        dx = target.x - passive.x

        if self._phase == _Phase.TRANSFER_BURN:
            return self._update_transfer_burn(dt, passive, target, alt, dx, active)
        if self._phase == _Phase.COAST:
            return self._update_coast(dt, passive, target, alt, dx, active)
        # TERMINAL: full descent-core logic (guidance, horizontal/vertical controllers).
        return super().update(dt, passive, active)


def create_bot() -> Bot:
    return DriftBot()


def list_behavior_names() -> tuple[str, ...]:
    return list_drift_behavior_names()


__all__ = ["DriftBot", "create_bot", "list_behavior_names"]
