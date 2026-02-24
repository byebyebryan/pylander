"""Transfer setup bot: hard side-burn setup, then hand off to drift."""

from __future__ import annotations

import math
from dataclasses import dataclass, replace

from bots._descent_core import (
    DescentPolicy,
    GuidanceTargets,
    StrategyDescentBot,
    clamp,
    rate_limit_angle_command,
    resolve_behavior,
)
from bots._drift_core import (
    DRIFT_COURSE,
    DRIFT_POLICY,
    DriftCourseConfig,
    apply_drift_guidance,
    cone_dx_limit,
)
from bots.drift import DriftBot
from core.bot import Bot, BotAction, PassiveSensors
from core.sensor import RadarContact


@dataclass(frozen=True)
class TransferSetupConfig:
    handoff_projected_dx_ratio: float = 1.0
    setup_vx_cap: float = 80.0
    setup_vx_floor: float = 5.0
    setup_descent_vy_target: float = -2.2
    setup_response_delay_s: float = 0.65
    setup_ballistic_vy_blend: float = 0.45
    handoff_force_drift_altitude: float = 420.0
    setup_vx_deadband: float = 1.6
    setup_sideburn_angle_rad: float = 1.40
    setup_sideburn_lateral_accel_floor: float = 0.8
    setup_sideburn_lateral_accel_cap: float = 10.0
    setup_sideburn_min_thrust: float = 0.35
    setup_sideburn_max_thrust: float = 1.6
    setup_sideburn_boost_thrust: float = 1.25
    setup_sideburn_boost_dx_cone_ratio: float = 2.8
    setup_sideburn_boost_vx_err_min: float = 6.0


def _ballistic_fall_time(*, alt: float, vy_up: float, g: float = 9.8) -> float:
    disc = max(0.0, (vy_up * vy_up) + (2.0 * g * max(0.0, alt)))
    return max(0.5, (vy_up + math.sqrt(disc)) / g)


def _projected_ballistic_dx(
    *,
    dx: float,
    alt: float,
    vx: float,
    vy_up: float,
    g: float = 9.8,
) -> float:
    t_fall = _ballistic_fall_time(alt=alt, vy_up=vy_up, g=g)
    return dx - (vx * t_fall)


def _predict_response_state(
    *,
    dx: float,
    alt: float,
    vx: float,
    vy_up: float,
    delay_s: float,
) -> tuple[float, float, float, float]:
    lag = max(0.0, float(delay_s))
    if lag <= 1e-6:
        return dx, alt, vx, vy_up
    # Compensate for rotation + thrust spool delay by evaluating a short-horizon
    # predicted state instead of chasing an immediate-state ballistic solution.
    dx_pred = dx - (vx * lag)
    alt_pred = max(0.0, alt + (vy_up * lag) - (4.9 * lag * lag))
    vy_pred = vy_up - (9.8 * lag)
    return dx_pred, alt_pred, vx, vy_pred


def _ballistic_reference_vy(
    guidance: GuidanceTargets,
    setup_cfg: TransferSetupConfig,
    vy_pred: float,
) -> float:
    envelope_vy = min(float(guidance.vy_sp), setup_cfg.setup_descent_vy_target)
    blend = clamp(setup_cfg.setup_ballistic_vy_blend, 0.0, 1.0)
    mixed_vy = envelope_vy + (blend * (vy_pred - envelope_vy))
    return clamp(mixed_vy, vy_pred, envelope_vy)


def should_handoff_to_drift(
    guidance: GuidanceTargets,
    course_cfg: DriftCourseConfig,
    setup_cfg: TransferSetupConfig,
    *,
    vx: float | None,
    vy_up: float | None,
) -> bool:
    alt = max(0.0, float(guidance.alt))
    safe_vx = float(vx) if vx is not None and math.isfinite(vx) else 0.0
    safe_vy_up = float(vy_up) if vy_up is not None and math.isfinite(vy_up) else 0.0
    dx_pred, alt_pred, vx_pred, vy_pred = _predict_response_state(
        dx=float(guidance.dx),
        alt=alt,
        vx=safe_vx,
        vy_up=safe_vy_up,
        delay_s=setup_cfg.setup_response_delay_s,
    )
    planned_vy_up = _ballistic_reference_vy(guidance, setup_cfg, vy_pred)
    t_fall = _ballistic_fall_time(alt=alt_pred, vy_up=planned_vy_up)
    projected_dx = _projected_ballistic_dx(
        dx=dx_pred,
        alt=alt_pred,
        vx=vx_pred,
        vy_up=planned_vy_up,
    )
    cone_limit = cone_dx_limit(alt_pred, course_cfg)
    on_track = abs(projected_dx) <= max(
        24.0,
        setup_cfg.handoff_projected_dx_ratio * cone_limit,
    )
    vx_needed = dx_pred / max(0.5, t_fall)
    vx_err = abs(vx_needed - vx_pred)
    speed_ready = vx_err <= max(
        2.5,
        0.16 * max(abs(vx_needed), setup_cfg.setup_vx_floor),
    )
    if alt_pred <= setup_cfg.handoff_force_drift_altitude:
        return on_track
    return on_track and speed_ready


def apply_transfer_setup_guidance(
    guidance: GuidanceTargets,
    course_cfg: DriftCourseConfig,
    setup_cfg: TransferSetupConfig,
    *,
    vx: float | None,
    vy_up: float | None,
) -> GuidanceTargets:
    alt = max(0.0, float(guidance.alt))
    safe_vx = float(vx) if vx is not None and math.isfinite(vx) else 0.0
    safe_vy_up = float(vy_up) if vy_up is not None and math.isfinite(vy_up) else 0.0
    dx_pred, alt_pred, vx_pred, vy_pred = _predict_response_state(
        dx=float(guidance.dx),
        alt=alt,
        vx=safe_vx,
        vy_up=safe_vy_up,
        delay_s=setup_cfg.setup_response_delay_s,
    )
    planned_vy_up = _ballistic_reference_vy(guidance, setup_cfg, vy_pred)
    projected_dx = _projected_ballistic_dx(
        dx=dx_pred,
        alt=alt_pred,
        vx=vx_pred,
        vy_up=planned_vy_up,
    )
    t_fall = _ballistic_fall_time(alt=alt_pred, vy_up=planned_vy_up)
    cone_limit = cone_dx_limit(alt_pred, course_cfg)
    vx_cap = max(setup_cfg.setup_vx_floor, setup_cfg.setup_vx_cap)
    vx_needed = dx_pred / max(0.5, t_fall)
    vx_sp = clamp(vx_needed, -vx_cap, vx_cap)
    if abs(projected_dx) > max(20.0, 0.85 * cone_limit):
        vx_sp = math.copysign(max(abs(vx_sp), setup_cfg.setup_vx_floor), vx_needed)
    return replace(
        guidance,
        phase="transfer_setup_sideburn",
        vertical_mode="transfer_sideburn",
        vx_sp=vx_sp,
        vy_sp=max(float(guidance.vy_sp), setup_cfg.setup_descent_vy_target),
    )


TRANSFER_POLICY = replace(
    DRIFT_POLICY,
    status_prefix="transfer",
)
_TRANSFER_BEHAVIORS: dict[str, tuple[DescentPolicy, DriftCourseConfig, TransferSetupConfig]] = {
    "transfer": (TRANSFER_POLICY, DRIFT_COURSE, TransferSetupConfig()),
}


def resolve_transfer_behavior(
    behavior: str,
) -> tuple[str, DescentPolicy, DriftCourseConfig, TransferSetupConfig]:
    key, value = resolve_behavior(
        behavior,
        _TRANSFER_BEHAVIORS,
        context="transfer",
    )
    policy, course_cfg, setup_cfg = value
    return key, policy, course_cfg, setup_cfg


def list_transfer_behavior_names() -> tuple[str, ...]:
    return tuple(sorted(_TRANSFER_BEHAVIORS))


class TransferBot(DriftBot):
    def __init__(self, behavior: str = "transfer") -> None:
        super().__init__(behavior=behavior)
        self._setup_phase_seen = False
        self._handoff_done = False
        self._setup_direction = 0.0

    def set_behavior(self, behavior: str) -> None:
        key, policy, cfg, setup_cfg = resolve_transfer_behavior(behavior)
        self._policy = policy
        self._course_cfg = cfg
        self._setup_cfg = setup_cfg
        self._behavior = key
        self._setup_phase_seen = False
        self._handoff_done = False
        self._setup_direction = 0.0

    def update(
        self,
        dt: float,
        passive: PassiveSensors,
        active,
    ) -> BotAction:
        if passive.state != "flying":
            self._setup_phase_seen = False
            self._handoff_done = False
            self._setup_direction = 0.0
        return super().update(dt, passive, active)

    def _guidance(
        self,
        passive: PassiveSensors,
        target: RadarContact,
        *,
        max_force: float,
        max_throttle: float,
        ramp_up: float,
    ) -> GuidanceTargets:
        base_guidance = StrategyDescentBot._guidance(
            self,
            passive,
            target,
            max_force=max_force,
            max_throttle=max_throttle,
            ramp_up=ramp_up,
        )
        current_guidance = replace(
            base_guidance,
            dx=float(target.x) - float(passive.x),
            alt=float(passive.altitude),
        )
        setup_guidance = apply_transfer_setup_guidance(
            current_guidance,
            self._course_cfg,
            self._setup_cfg,
            vx=passive.vx,
            vy_up=passive.vy_up,
        )
        if self._handoff_done:
            guidance = apply_drift_guidance(
                current_guidance,
                self._course_cfg,
                vx=passive.vx,
                vy_up=passive.vy_up,
            )
        elif not self._setup_phase_seen:
            self._setup_phase_seen = True
            guidance = setup_guidance
        elif should_handoff_to_drift(
            current_guidance,
            self._course_cfg,
            self._setup_cfg,
            vx=passive.vx,
            vy_up=passive.vy_up,
        ):
            self._handoff_done = True
            guidance = apply_drift_guidance(
                current_guidance,
                self._course_cfg,
                vx=passive.vx,
                vy_up=passive.vy_up,
            )
        else:
            guidance = setup_guidance
        self._last_guidance = guidance
        return guidance

    def _horizontal_controller(
        self,
        passive: PassiveSensors,
        vx_sp: float,
    ) -> float:
        guidance = self._last_guidance
        if (
            guidance is not None
            and guidance.phase == "transfer_setup_sideburn"
        ):
            vx_err = vx_sp - passive.vx
            ax_target = (1.1 * vx_err) - (0.04 * passive.ax)
            return clamp(
                ax_target,
                -self._setup_cfg.setup_sideburn_lateral_accel_cap,
                self._setup_cfg.setup_sideburn_lateral_accel_cap,
            )
        return super()._horizontal_controller(passive, vx_sp)

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
        if vertical_mode != "transfer_sideburn":
            return super()._allocate_controls(
                dt,
                passive,
                a_x_sp=a_x_sp,
                a_up_sp=a_up_sp,
                alt=alt,
                dx=dx,
                vertical_mode=vertical_mode,
            )
        max_power, min_throttle, max_throttle, _ = self._engine_profile()
        mass = max(0.5, passive.mass)
        if abs(dx) > 1e-3:
            desired_direction = 1.0 if dx > 0.0 else -1.0
        elif abs(a_x_sp) > 1e-3:
            desired_direction = 1.0 if a_x_sp > 0.0 else -1.0
        elif abs(passive.vx) > 1e-3:
            desired_direction = -1.0 if passive.vx > 0.0 else 1.0
        else:
            desired_direction = 1.0
        if self._setup_direction == 0.0:
            self._setup_direction = desired_direction
        elif desired_direction != self._setup_direction and abs(dx) < 10.0:
            self._setup_direction = desired_direction

        target_angle = self._setup_direction * self._setup_cfg.setup_sideburn_angle_rad
        angle_cmd = rate_limit_angle_command(
            target_angle,
            self._prev_angle_cmd,
            dt,
            max_rate=3.2,
        )
        self._prev_angle_cmd = angle_cmd

        guidance_vx_sp = float(getattr(self._last_guidance, "vx_sp", 0.0))
        vx_err = guidance_vx_sp - float(passive.vx)
        along_track_err = self._setup_direction * vx_err
        along_track_ax = self._setup_direction * float(a_x_sp)
        ax_from_vx = min(
            self._setup_cfg.setup_sideburn_lateral_accel_cap,
            max(0.0, 0.9 * along_track_err),
        )
        ax_from_guidance = max(0.0, along_track_ax)
        ax_target = max(ax_from_guidance, ax_from_vx)
        t_fall_now = _ballistic_fall_time(
            alt=max(0.0, float(alt)),
            vy_up=float(passive.vy_up),
        )
        projected_dx_now = float(dx) - (float(passive.vx) * t_fall_now)
        along_track_miss = self._setup_direction * projected_dx_now
        cone_limit_now = cone_dx_limit(max(0.0, float(alt)), self._course_cfg)
        miss_outside_cone = abs(projected_dx_now) > (
            self._setup_cfg.handoff_projected_dx_ratio * cone_limit_now
        )
        if miss_outside_cone and along_track_miss > 0.0:
            ax_from_miss = along_track_miss / max(0.5, t_fall_now * t_fall_now)
            ax_target = max(
                ax_target,
                clamp(
                    ax_from_miss,
                    self._setup_cfg.setup_sideburn_lateral_accel_floor,
                    self._setup_cfg.setup_sideburn_lateral_accel_cap,
                ),
            )
        boost_mode = (
            miss_outside_cone
            and abs(projected_dx_now)
            > (self._setup_cfg.setup_sideburn_boost_dx_cone_ratio * cone_limit_now)
            and along_track_err > self._setup_cfg.setup_sideburn_boost_vx_err_min
        )
        if boost_mode:
            return BotAction(
                target_thrust=clamp(
                    self._setup_cfg.setup_sideburn_boost_thrust,
                    min_throttle,
                    min(max_throttle, self._setup_cfg.setup_sideburn_max_thrust),
                ),
                target_angle=angle_cmd,
                refuel=False,
            )
        if along_track_err > self._setup_cfg.setup_vx_deadband or (
            miss_outside_cone and along_track_miss > 0.0
        ):
            ax_target = max(ax_target, self._setup_cfg.setup_sideburn_lateral_accel_floor)
        else:
            ax_target = min(ax_target, 0.6)
        ax_target = clamp(ax_target, 0.0, self._setup_cfg.setup_sideburn_lateral_accel_cap)
        if ax_target <= 0.12:
            return BotAction(target_thrust=0.0, target_angle=angle_cmd, refuel=False)
        sin_term = max(0.2, abs(math.sin(angle_cmd)))
        thrust = (mass * ax_target) / max(max_power * sin_term, 1e-3)
        thrust = clamp(
            thrust,
            self._setup_cfg.setup_sideburn_min_thrust,
            min(max_throttle, self._setup_cfg.setup_sideburn_max_thrust),
        )
        if thrust > 0.0:
            thrust = max(min_throttle, thrust)
        return BotAction(target_thrust=thrust, target_angle=angle_cmd, refuel=False)


def create_bot() -> Bot:
    return TransferBot()


def list_behavior_names() -> tuple[str, ...]:
    return list_transfer_behavior_names()


__all__ = [
    "TransferBot",
    "TransferSetupConfig",
    "apply_transfer_setup_guidance",
    "create_bot",
    "list_behavior_names",
    "list_transfer_behavior_names",
    "resolve_transfer_behavior",
    "should_handoff_to_drift",
]
