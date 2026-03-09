from __future__ import annotations

import math
from dataclasses import dataclass

from bots._ballistics import estimate_ground_time_to_impact
from bots._optimizer_pdg import PDGPlan
from core.bot import Sensors
from core.config import GRAVITY

_GRAVITY_MAG = abs(float(GRAVITY))


@dataclass(frozen=True)
class FlareGateProbe:
    horizon_steps: int
    horizon_s: float
    required_accel_ratio: float
    terminal_dx: float
    terminal_y_err: float
    terminal_speed: float
    peak_accel_ratio: float
    od_excess_s: float
    score: float
    plan: PDGPlan


@dataclass(frozen=True)
class FlareGateDecision:
    mode: str
    probe: FlareGateProbe
    latest_safe_margin_s: float


def _required_control_accel(
    *,
    dx: float,
    dy: float,
    vx: float,
    vy_up: float,
    t_go: float,
) -> tuple[float, float]:
    t = max(1e-3, float(t_go))
    t2 = t * t
    zem_x = float(dx) - (float(vx) * t)
    zem_y = float(dy) - (float(vy_up) * t) + (0.5 * _GRAVITY_MAG * t2)
    zev_x = -float(vx)
    zev_y = -float(vy_up) + (_GRAVITY_MAG * t)
    ax = ((6.0 * zem_x) / t2) - ((2.0 * zev_x) / t)
    ay = ((6.0 * zem_y) / t2) - ((2.0 * zev_y) / t)
    return ax, ay


def _coast_prefilter_viable(
    bot,
    *,
    dx: float,
    dy: float,
    passive: Sensors,
    max_thrust_accel: float,
) -> tuple[list[int], float]:
    viable: list[int] = []
    best_ratio = float("inf")
    max_tilt = bot._resolve_max_tilt(
        max(0.0, float(passive.altitude)),
        float(dx),
        float(passive.vx),
        dy=float(dy),
        phase="terminal",
    )
    tilt_tan = math.tan(max(0.02, max_tilt))
    for steps in bot._cfg.flare_gate_horizon_steps:
        optimizer = bot._optimizer_flare_probe.get(int(steps))
        if optimizer is None:
            continue
        t_go = optimizer.step_dt * optimizer.horizon_steps
        ax_req, ay_req = _required_control_accel(
            dx=float(dx),
            dy=float(dy),
            vx=float(passive.vx),
            vy_up=float(passive.vy_up),
            t_go=t_go,
        )
        required_norm = math.hypot(ax_req, ay_req)
        ratio = required_norm / max(1e-6, float(max_thrust_accel))
        best_ratio = min(best_ratio, ratio)
        if ay_req <= bot._cfg.flare_gate_prefilter_min_up_accel:
            continue
        if abs(ax_req) > (tilt_tan * ay_req):
            continue
        if ratio > bot._cfg.flare_gate_prefilter_max_ratio:
            continue
        viable.append(int(steps))
    return viable, best_ratio if math.isfinite(best_ratio) else 0.0


def _latest_safe_margin_s(
    bot,
    *,
    passive: Sensors,
    dx: float,
    max_thrust_accel: float,
    thrust_ramp_up: float,
) -> float:
    down_speed = max(0.0, -float(passive.vy_up))
    max_tilt = bot._resolve_max_tilt(
        max(0.0, float(passive.altitude)),
        float(dx),
        float(passive.vx),
        dy=-max(0.0, float(passive.altitude)),
        phase="terminal",
    )
    spool_time = max(0.0, 1.0 - max(0.0, float(passive.thrust_level))) / max(
        1e-3,
        float(thrust_ramp_up),
    )
    vertical_up_accel = max(
        0.1,
        (float(max_thrust_accel) * math.cos(max_tilt)) - _GRAVITY_MAG,
    )
    lateral_accel = max(
        0.5,
        float(max_thrust_accel) * math.sin(max_tilt),
    )
    time_to_impact = estimate_ground_time_to_impact(
        altitude=max(0.0, float(passive.altitude)),
        vy_up=float(passive.vy_up),
        min_t_fall=0.0,
    )
    t_brake_v = spool_time + (down_speed / vertical_up_accel)
    t_brake_x = abs(float(passive.vx)) / lateral_accel
    latest_safe_time = max(t_brake_v, t_brake_x) + bot._cfg.flare_gate_latest_safe_buffer_s
    return float(time_to_impact) - latest_safe_time


def _probe_from_plan(
    *,
    plan: PDGPlan,
    target_x: float,
    target_y: float,
    nominal_thrust_accel: float,
) -> FlareGateProbe:
    norms = [math.hypot(float(ax), float(ay)) for ax, ay in zip(plan.ax, plan.ay)]
    peak_accel = max(norms) if norms else 0.0
    nominal = max(1e-6, float(nominal_thrust_accel))
    od_excess_s = (
        sum(max(0.0, norm - nominal) / nominal for norm in norms) * float(plan.step_dt)
        if norms
        else 0.0
    )
    terminal_dx = float(plan.x[-1]) - float(target_x)
    terminal_y_err = float(plan.y[-1]) - float(target_y)
    terminal_speed = math.hypot(float(plan.vx[-1]), float(plan.vy[-1]))
    score = (
        abs(terminal_dx)
        + (4.0 * abs(terminal_y_err))
        + (6.0 * terminal_speed)
        + (20.0 * od_excess_s)
        + (10.0 * max(0.0, (peak_accel / nominal) - 1.0))
    )
    return FlareGateProbe(
        horizon_steps=len(plan.ax),
        horizon_s=float(plan.step_dt) * len(plan.ax),
        required_accel_ratio=0.0,
        terminal_dx=terminal_dx,
        terminal_y_err=terminal_y_err,
        terminal_speed=terminal_speed,
        peak_accel_ratio=peak_accel / nominal,
        od_excess_s=od_excess_s,
        score=score,
        plan=plan,
    )


def evaluate_flare_gate(
    bot,
    *,
    dt: float,
    passive: Sensors,
    dx: float,
    dy: float,
    alt: float,
    max_thrust_accel: float,
    min_thrust_accel: float,
    nominal_thrust_accel: float,
    thrust_ramp_up: float,
) -> FlareGateDecision | None:
    bot._flare_probe_timer = max(0.0, bot._flare_probe_timer - max(0.0, float(dt)))
    latest_safe_margin_s = _latest_safe_margin_s(
        bot,
        passive=passive,
        dx=dx,
        max_thrust_accel=max_thrust_accel,
        thrust_ramp_up=thrust_ramp_up,
    )
    viable_steps, prefilter_ratio = _coast_prefilter_viable(
        bot,
        dx=dx,
        dy=dy,
        passive=passive,
        max_thrust_accel=max_thrust_accel,
    )
    bot._flare_gate_required_accel_ratio = prefilter_ratio
    bot._flare_gate_latest_safe_margin_s = latest_safe_margin_s

    force_probe = latest_safe_margin_s <= bot._cfg.flare_gate_force_probe_margin_s
    if bot._flare_probe_timer > 1e-6 and not force_probe:
        return None
    if (not viable_steps) and (not force_probe):
        return None

    bot._flare_probe_timer = 1.0 / max(1e-3, float(bot._cfg.flare_gate_probe_hz))
    target_x = float(passive.x) + float(dx)
    target_y = float(passive.y) + float(dy)
    exact_dx_tol = max(
        float(bot._cfg.flare_gate_exact_dx_abs),
        float(bot._last_target_half),
    )
    exact_candidates: list[FlareGateProbe] = []
    safe_candidates: list[FlareGateProbe] = []

    for steps in bot._cfg.flare_gate_horizon_steps:
        if (steps not in viable_steps) and (not force_probe):
            continue
        optimizer = bot._optimizer_flare_probe.get(int(steps))
        if optimizer is None:
            continue
        max_tilt = bot._resolve_max_tilt(
            alt,
            dx,
            float(passive.vx),
            dy=dy,
            phase="terminal",
        )
        plan = optimizer.solve(
            x=float(passive.x),
            y=float(passive.y),
            vx=float(passive.vx),
            vy=float(passive.vy_up),
            target_x=target_x,
            target_y=target_y,
            y_floor=min(float(passive.y), target_y) - 8.0,
            target_vy=float(bot._cfg.flare_gate_probe_target_vy),
            max_thrust_accel=max_thrust_accel,
            min_thrust_accel=min_thrust_accel,
            nominal_thrust_accel=nominal_thrust_accel,
            max_tilt_rad=max_tilt,
            descent_floor_vy=float(bot._cfg.flare_gate_probe_descent_floor_vy),
            gravity_mag=_GRAVITY_MAG,
            pad_half_width=bot._last_target_half,
            altitude_hint=max(0.0, float(alt)),
            warm_start=None,
            terminal_x_tol=float(bot._cfg.flare_gate_probe_terminal_x_tol),
        )
        if plan is None:
            continue
        bot._flare_probe_count += 1
        bot._flare_probe_ms_sum += float(plan.solve_time_ms)
        bot._flare_probe_ms_samples.append(float(plan.solve_time_ms))
        if not plan.feasible:
            continue
        probe = _probe_from_plan(
            plan=plan,
            target_x=target_x,
            target_y=target_y,
            nominal_thrust_accel=nominal_thrust_accel,
        )
        probe = FlareGateProbe(
            horizon_steps=probe.horizon_steps,
            horizon_s=probe.horizon_s,
            required_accel_ratio=prefilter_ratio,
            terminal_dx=probe.terminal_dx,
            terminal_y_err=probe.terminal_y_err,
            terminal_speed=probe.terminal_speed,
            peak_accel_ratio=probe.peak_accel_ratio,
            od_excess_s=probe.od_excess_s,
            score=probe.score,
            plan=probe.plan,
        )
        if (
            abs(probe.terminal_y_err) <= bot._cfg.flare_gate_terminal_alt_err_m
            and probe.terminal_speed <= bot._cfg.flare_gate_exact_terminal_speed_mps
            and abs(probe.terminal_dx) <= exact_dx_tol
            and probe.peak_accel_ratio <= bot._cfg.flare_gate_exact_peak_ratio
            and probe.od_excess_s <= bot._cfg.flare_gate_exact_od_excess_s
        ):
            exact_candidates.append(probe)
        if (
            abs(probe.terminal_y_err) <= bot._cfg.flare_gate_terminal_alt_err_m
            and probe.terminal_speed <= bot._cfg.flare_gate_safe_terminal_speed_mps
            and probe.peak_accel_ratio <= bot._cfg.flare_gate_safe_peak_ratio
            and probe.od_excess_s <= bot._cfg.flare_gate_safe_od_excess_s
        ):
            safe_candidates.append(probe)

    if exact_candidates:
        best = min(
            exact_candidates,
            key=lambda probe: (
                probe.od_excess_s,
                probe.terminal_speed,
                abs(probe.terminal_dx),
                probe.horizon_s,
            ),
        )
        return FlareGateDecision(
            mode="green_exact",
            probe=best,
            latest_safe_margin_s=latest_safe_margin_s,
        )

    if safe_candidates and latest_safe_margin_s <= bot._cfg.flare_gate_amber_margin_s:
        best = min(
            safe_candidates,
            key=lambda probe: (
                abs(probe.terminal_dx),
                probe.terminal_speed,
                probe.od_excess_s,
                probe.horizon_s,
            ),
        )
        return FlareGateDecision(
            mode="amber_min_error",
            probe=best,
            latest_safe_margin_s=latest_safe_margin_s,
        )

    return None
