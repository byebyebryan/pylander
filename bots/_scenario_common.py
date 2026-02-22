"""Shared primitives for scenario-focused specialist bots."""

from __future__ import annotations

from dataclasses import dataclass
import math

from core.bot import ActiveSensors, Bot, BotAction, PassiveSensors
from core.sensor import RadarContact


@dataclass(frozen=True)
class SpecialistConfig:
    name: str
    # Planner gate/shape
    planner_enabled: bool = False
    planner_dx_threshold: float = 260.0
    planner_dist_threshold: float = 320.0
    planner_replan_interval: float = 1.0
    planner_pos_error: float = 120.0
    planner_vel_error: float = 7.0
    transfer_speed: float = 20.0
    transfer_vy_limit: float = 4.0
    transfer_clearance: float = 40.0
    # Direct tracking
    align_band: float = 14.0
    direct_vx_gain: float = 0.08
    direct_vx_cap: float = 14.0
    # Vertical profile
    descend_fast: float = -5.2
    descend_mid: float = -3.6
    descend_slow: float = -1.8
    touchdown_vy: float = -0.9
    far_altitude: float = 90.0
    mid_altitude: float = 35.0
    hold_alt_if_offset: float = 30.0
    # Control gains/limits
    k_vx: float = 0.48
    k_ax: float = 0.12
    k_vy: float = 0.14
    k_alt: float = 0.02
    max_tilt: float = 0.65
    near_tilt: float = 0.16
    near_tilt_altitude: float = 20.0
    max_thrust_bias: float = 0.12
    # Plan handoff
    transfer_complete_dx: float = 65.0
    transfer_complete_vx: float = 5.0


@dataclass
class TransferPlan:
    created_at: float
    duration: float
    start_x: float
    start_y: float
    waypoint_x: float
    waypoint_y: float
    vx_sp: float
    vy_sp: float

    @property
    def expires_at(self) -> float:
        return self.created_at + self.duration


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _pick_target(passive: PassiveSensors) -> RadarContact | None:
    contacts = passive.radar_contacts or []
    if not contacts:
        return None
    inner = [c for c in contacts if c.is_inner_lock]
    candidates = inner if inner else contacts
    return min(candidates, key=lambda c: c.distance)


def _finite_altitude(passive: PassiveSensors) -> float:
    if math.isfinite(passive.altitude):
        return passive.altitude
    return 1e9


class SpecialistBot(Bot):
    """Base specialist bot with optional transfer planner."""

    def __init__(self, config: SpecialistConfig):
        super().__init__()
        self.config = config
        self._sim_t = 0.0
        self._mode = "direct_descent"
        self._plan: TransferPlan | None = None
        self._prev_angle_cmd = 0.0

    def _should_use_planner(self, dx: float, distance: float) -> bool:
        cfg = self.config
        if not cfg.planner_enabled:
            return False
        return abs(dx) >= cfg.planner_dx_threshold or distance >= cfg.planner_dist_threshold

    def _estimate_transfer_clearance(
        self,
        passive: PassiveSensors,
        active: ActiveSensors,
        target: RadarContact,
    ) -> float:
        cfg = self.config
        cruise_y = max(passive.y, target.y) + cfg.transfer_clearance
        if not callable(getattr(active, "terrain_profile", None)):
            return cruise_y
        profile = active.terrain_profile(passive.x, target.x, samples=20, lod=0)
        if not profile:
            return cruise_y
        max_terrain_y = max(y for _, y in profile)
        return max(cruise_y, max_terrain_y + cfg.transfer_clearance)

    def _make_transfer_plan(
        self,
        passive: PassiveSensors,
        active: ActiveSensors,
        target: RadarContact,
    ) -> TransferPlan:
        cfg = self.config
        waypoint_y = self._estimate_transfer_clearance(passive, active, target)
        dx = target.x - passive.x
        dy = waypoint_y - passive.y
        duration = _clamp(abs(dx) / max(cfg.transfer_speed, 1.0), 1.0, 4.0)
        vx_sp = _clamp(dx / max(duration, 1e-3), -cfg.transfer_speed, cfg.transfer_speed)
        vy_sp = _clamp(
            dy / max(duration, 1e-3),
            -cfg.transfer_vy_limit,
            cfg.transfer_vy_limit,
        )
        return TransferPlan(
            created_at=self._sim_t,
            duration=duration,
            start_x=passive.x,
            start_y=passive.y,
            waypoint_x=target.x,
            waypoint_y=waypoint_y,
            vx_sp=vx_sp,
            vy_sp=vy_sp,
        )

    def _plan_stale(self, passive: PassiveSensors, plan: TransferPlan) -> bool:
        cfg = self.config
        if self._sim_t >= plan.expires_at:
            return True
        elapsed = self._sim_t - plan.created_at
        expected_x = plan.start_x + plan.vx_sp * elapsed
        expected_y = plan.start_y + plan.vy_sp * elapsed
        pos_err = math.hypot(passive.x - expected_x, passive.y - expected_y)
        vel_err = abs(passive.vx - plan.vx_sp)
        return pos_err >= cfg.planner_pos_error or vel_err >= cfg.planner_vel_error

    def _direct_targets(
        self,
        passive: PassiveSensors,
        target: RadarContact,
    ) -> tuple[float, float]:
        cfg = self.config
        alt = _finite_altitude(passive)
        dx = target.x - passive.x
        vx_sp = _clamp(dx * cfg.direct_vx_gain, -cfg.direct_vx_cap, cfg.direct_vx_cap)

        if alt > cfg.far_altitude:
            vy_sp = cfg.descend_fast
        elif alt > cfg.mid_altitude:
            vy_sp = cfg.descend_mid
        else:
            vy_sp = cfg.descend_slow

        # Avoid descending while still significantly offset from pad x.
        if abs(dx) > cfg.align_band and alt < cfg.hold_alt_if_offset:
            vy_sp = max(vy_sp, 0.8)

        # Commit to touchdown profile once nearly centered.
        if abs(dx) <= cfg.align_band and alt < 12.0:
            vy_sp = cfg.touchdown_vy
            vx_sp = _clamp(vx_sp, -1.0, 1.0)

        return vx_sp, vy_sp

    def _control_action(
        self,
        dt: float,
        passive: PassiveSensors,
        vx_sp: float,
        vy_sp: float,
        dx: float,
    ) -> BotAction:
        cfg = self.config
        alt = _finite_altitude(passive)
        mass = max(0.5, passive.mass)
        max_thrust_power = (
            self.vehicle_info.max_thrust_power if self.vehicle_info is not None else 50.0
        )

        # Lateral control: velocity tracking -> desired tilt.
        vx_err = vx_sp - passive.vx
        a_x_sp = cfg.k_vx * vx_err - cfg.k_ax * passive.ax
        req = _clamp((a_x_sp * mass) / max(max_thrust_power, 1e-3), -0.95, 0.95)
        angle_cmd = math.asin(req)
        max_tilt = cfg.near_tilt if alt < cfg.near_tilt_altitude else cfg.max_tilt
        angle_cmd = _clamp(angle_cmd, -max_tilt, max_tilt)

        # Angle slew helps reduce oscillation.
        max_delta = 2.0 * max(dt, 1e-3)
        angle_cmd = _clamp(
            angle_cmd,
            self._prev_angle_cmd - max_delta,
            self._prev_angle_cmd + max_delta,
        )
        self._prev_angle_cmd = angle_cmd

        # Vertical thrust around hover with small altitude hold.
        cos_term = max(0.25, abs(math.cos(angle_cmd)))
        hover = (9.8 * mass) / max(max_thrust_power * cos_term, 1e-3)
        e_vy = vy_sp - passive.vy_up
        alt_sp = 6.0 if abs(dx) <= cfg.align_band else 16.0
        e_alt = alt_sp - alt
        target_thrust = hover + (cfg.k_vy * e_vy) + (cfg.k_alt * e_alt)

        if alt < 18.0 and passive.vy_up < -2.2:
            target_thrust += cfg.max_thrust_bias
        if alt < 10.0 and abs(dx) <= cfg.align_band:
            angle_cmd = 0.0

        target_thrust = _clamp(target_thrust, 0.0, 1.0)
        return BotAction(target_thrust=target_thrust, target_angle=angle_cmd, refuel=False)

    def update(
        self,
        dt: float,
        passive: PassiveSensors,
        active: ActiveSensors,
    ) -> BotAction:
        self._sim_t += dt
        if passive.state in ("landed", "crashed", "out_of_fuel"):
            action = BotAction(0.0, passive.angle, False, status=passive.state.upper())
            self.status = action.status
            self._plan = None
            self._mode = "direct_descent"
            return action

        target = _pick_target(passive)
        if target is None:
            action = self._control_action(dt, passive, vx_sp=0.0, vy_sp=-1.0, dx=0.0)
            action.status = f"{self.config.name}:search"
            self.status = action.status
            return action

        dx = target.x - passive.x
        dy = target.y - passive.y
        distance = math.hypot(dx, dy)

        use_planner = self._should_use_planner(dx, distance)
        if use_planner:
            if (
                self._plan is None
                or (self._sim_t - self._plan.created_at) >= self.config.planner_replan_interval
                or self._plan_stale(passive, self._plan)
            ):
                self._plan = self._make_transfer_plan(passive, active, target)
            self._mode = "transfer_plan"
            vx_sp = self._plan.vx_sp
            vy_sp = self._plan.vy_sp
            if (
                abs(dx) <= self.config.transfer_complete_dx
                and abs(passive.vx) <= self.config.transfer_complete_vx
            ):
                self._plan = None
                self._mode = "direct_descent"
                vx_sp, vy_sp = self._direct_targets(passive, target)
        else:
            self._plan = None
            self._mode = "direct_descent"
            vx_sp, vy_sp = self._direct_targets(passive, target)

        action = self._control_action(dt, passive, vx_sp=vx_sp, vy_sp=vy_sp, dx=dx)
        action.status = (
            f"{self.config.name}:{self._mode} dx:{dx:6.1f} "
            f"vx:{passive.vx:5.1f} vy:{passive.vy_up:5.1f}"
        )
        self.status = action.status
        return action
