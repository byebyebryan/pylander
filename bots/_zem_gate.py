from __future__ import annotations

import math
from dataclasses import dataclass

from bots._ballistics import estimate_ground_time_to_impact
from core.bot import Sensors
from core.config import GRAVITY

_GRAVITY_MAG = abs(float(GRAVITY))


@dataclass(frozen=True)
class FlareGateCandidate:
    burn_time_s: float
    required_accel_ratio: float
    upward_accel: float
    tilt_feasible: bool
    ready: bool


@dataclass(frozen=True)
class FlareGateDecision:
    mode: str
    burn_time_s: float
    latest_safe_margin_s: float
    required_accel_ratio: float


def _required_control_accel(
    *,
    dx: float,
    dy: float,
    vx: float,
    vy_up: float,
    target_vx: float,
    target_vy_up: float,
    t_go: float,
) -> tuple[float, float]:
    t = max(1e-3, float(t_go))
    t2 = t * t
    zem_x = float(dx) - (float(vx) * t)
    zem_y = float(dy) - (float(vy_up) * t) + (0.5 * _GRAVITY_MAG * t2)
    zev_x = float(target_vx) - float(vx)
    zev_y = float(target_vy_up) - float(vy_up) + (_GRAVITY_MAG * t)
    ax = ((6.0 * zem_x) / t2) - ((2.0 * zev_x) / t)
    ay = ((6.0 * zem_y) / t2) - ((2.0 * zev_y) / t)
    return ax, ay


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(float(lo), min(float(hi), float(value)))


def _max_tilt(bot, *, alt: float, dx: float, dy: float, vx: float) -> float:
    return bot._resolve_max_tilt(
        max(0.0, float(alt)),
        float(dx),
        float(vx),
        dy=float(dy),
        phase="terminal",
    )


def _nominal_burn_time_candidates(
    bot,
    *,
    passive: Sensors,
    alt: float,
    dx: float,
    dy: float,
    nominal_thrust_accel: float,
) -> tuple[list[float], float, float]:
    max_tilt = _max_tilt(
        bot,
        alt=alt,
        dx=dx,
        dy=dy,
        vx=float(passive.vx),
    )
    target_vy_up = float(bot._desired_terminal_vy(max(0.0, float(alt)), nominal_thrust_accel, max_tilt))
    down_speed = max(0.0, -float(passive.vy_up))
    target_down_speed = max(0.0, -target_vy_up)
    vertical_up_accel = max(
        0.1,
        (float(nominal_thrust_accel) * math.cos(max_tilt)) - _GRAVITY_MAG,
    )
    lateral_accel = max(
        0.5,
        float(nominal_thrust_accel) * math.sin(max_tilt),
    )
    t_v_nom = max(0.0, down_speed - target_down_speed) / vertical_up_accel
    t_x_nom = abs(float(passive.vx)) / lateral_accel
    burn_time_nom = _clamp(
        max(t_v_nom, t_x_nom) + float(bot._cfg.flare_gate_nominal_buffer_s),
        float(bot._cfg.flare_gate_burn_time_min_s),
        float(bot._cfg.flare_gate_burn_time_max_s),
    )
    candidate_times: list[float] = []
    for raw_time in (
        burn_time_nom - float(bot._cfg.flare_gate_burn_time_offset_short_s),
        burn_time_nom,
        burn_time_nom + float(bot._cfg.flare_gate_burn_time_offset_long_s),
    ):
        burn_time = _clamp(
            raw_time,
            float(bot._cfg.flare_gate_burn_time_min_s),
            float(bot._cfg.flare_gate_burn_time_max_s),
        )
        if any(abs(existing - burn_time) <= 1e-6 for existing in candidate_times):
            continue
        candidate_times.append(burn_time)
    candidate_times.sort()
    return candidate_times, max_tilt, target_vy_up


def _evaluate_candidate(
    *,
    dx: float,
    dy: float,
    passive: Sensors,
    burn_time_s: float,
    target_vy_up: float,
    max_tilt: float,
    thrust_accel: float,
    ratio_limit: float,
    min_upward_accel: float,
) -> FlareGateCandidate:
    ax_req, ay_req = _required_control_accel(
        dx=float(dx),
        dy=float(dy),
        vx=float(passive.vx),
        vy_up=float(passive.vy_up),
        target_vx=0.0,
        target_vy_up=float(target_vy_up),
        t_go=float(burn_time_s),
    )
    required_norm = math.hypot(ax_req, ay_req)
    required_ratio = required_norm / max(1e-6, float(thrust_accel))
    tilt_tan = math.tan(max(0.02, float(max_tilt)))
    tilt_feasible = ay_req > 0.0 and abs(ax_req) <= (tilt_tan * ay_req)
    ready = (
        ay_req >= float(min_upward_accel)
        and tilt_feasible
        and required_ratio <= float(ratio_limit)
    )
    return FlareGateCandidate(
        burn_time_s=float(burn_time_s),
        required_accel_ratio=float(required_ratio),
        upward_accel=float(ay_req),
        tilt_feasible=tilt_feasible,
        ready=ready,
    )


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
    latest_safe_time = max(t_brake_v, t_brake_x) + float(bot._cfg.flare_gate_latest_safe_buffer_s)
    return float(time_to_impact) - latest_safe_time


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
    del dt, min_thrust_accel

    latest_safe_margin_s = _latest_safe_margin_s(
        bot,
        passive=passive,
        dx=dx,
        max_thrust_accel=max_thrust_accel,
        thrust_ramp_up=thrust_ramp_up,
    )
    candidate_times, max_tilt, target_vy_up = _nominal_burn_time_candidates(
        bot,
        passive=passive,
        alt=alt,
        dx=dx,
        dy=dy,
        nominal_thrust_accel=nominal_thrust_accel,
    )
    nominal_candidates = [
        _evaluate_candidate(
            dx=dx,
            dy=dy,
            passive=passive,
            burn_time_s=burn_time_s,
            target_vy_up=target_vy_up,
            max_tilt=max_tilt,
            thrust_accel=nominal_thrust_accel,
            ratio_limit=float(bot._cfg.flare_gate_nominal_ratio),
            min_upward_accel=float(bot._cfg.flare_gate_nominal_min_up_accel),
        )
        for burn_time_s in candidate_times
    ]
    best_nominal = next((candidate for candidate in nominal_candidates if candidate.ready), None)
    if best_nominal is not None:
        bot._flare_gate_ready_ticks += 1
        bot._flare_gate_required_accel_ratio = best_nominal.required_accel_ratio
    else:
        bot._flare_gate_ready_ticks = 0
        bot._flare_gate_required_accel_ratio = (
            min(
                (candidate.required_accel_ratio for candidate in nominal_candidates),
                default=0.0,
            )
        )
    bot._flare_gate_latest_safe_margin_s = latest_safe_margin_s

    if (
        best_nominal is not None
        and bot._flare_gate_ready_ticks >= max(1, int(bot._cfg.flare_gate_hysteresis_ticks))
    ):
        return FlareGateDecision(
            mode="nominal_ready",
            burn_time_s=best_nominal.burn_time_s,
            latest_safe_margin_s=latest_safe_margin_s,
            required_accel_ratio=best_nominal.required_accel_ratio,
        )

    if latest_safe_margin_s <= 0.0:
        bot._flare_gate_ready_ticks = 0
        latest_safe_candidates = [
            _evaluate_candidate(
                dx=dx,
                dy=dy,
                passive=passive,
                burn_time_s=burn_time_s,
                target_vy_up=target_vy_up,
                max_tilt=max_tilt,
                thrust_accel=max_thrust_accel,
                ratio_limit=float("inf"),
                min_upward_accel=0.0,
            )
            for burn_time_s in candidate_times
        ]
        best_safe = min(
            latest_safe_candidates,
            key=lambda candidate: (
                not candidate.tilt_feasible,
                candidate.required_accel_ratio,
                candidate.burn_time_s,
            ),
        )
        bot._flare_gate_required_accel_ratio = best_safe.required_accel_ratio
        return FlareGateDecision(
            mode="latest_safe",
            burn_time_s=best_safe.burn_time_s,
            latest_safe_margin_s=latest_safe_margin_s,
            required_accel_ratio=best_safe.required_accel_ratio,
        )

    return None
