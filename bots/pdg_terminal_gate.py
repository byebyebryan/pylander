from __future__ import annotations

import math
import time
from dataclasses import dataclass, field, replace

from bots.common_ballistics import (
    BallisticProjection,
    estimate_ground_time_to_impact,
    estimate_target_y_projection,
)
from bots.pdg_terrain_divert import (
    TerrainDivertPrefilter,
    TerrainDivertProbe,
    evaluate_terrain_divert_probe,
    evaluate_terminal_clip_probe,
    prefilter_terrain_divert,
)
from core.bot import Sensors
from core.config import GRAVITY

_GRAVITY_MAG = abs(float(GRAVITY))


@dataclass(frozen=True)
class TerminalGateCandidate:
    burn_time_s: float
    required_accel_ratio: float
    upward_accel: float
    tilt_feasible: bool
    ready: bool


@dataclass(frozen=True)
class TerminalGateDecision:
    mode: str
    burn_time_s: float
    latest_safe_margin_s: float
    required_accel_ratio: float


@dataclass(frozen=True)
class LatestSafeState:
    margin_s: float
    best_candidate: TerminalGateCandidate


@dataclass(frozen=True)
class TerminalGateEvaluation:
    decision: TerminalGateDecision | None
    latest_safe_state: LatestSafeState
    best_nominal: TerminalGateCandidate | None
    nominal_ready_ticks: int
    state_ready_ticks: int
    required_accel_ratio: float
    terrain_divert: TerrainDivertProbe = field(
        default_factory=lambda: TerrainDivertProbe(active=False)
    )


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


def _height_to_target(*, dy: float) -> float:
    return max(0.0, -float(dy))


def _candidate_is_feasible(
    candidate: TerminalGateCandidate, *, ratio_limit: float
) -> bool:
    return candidate.tilt_feasible and candidate.required_accel_ratio <= float(
        ratio_limit
    )


def _candidate_preference_key(candidate: TerminalGateCandidate) -> tuple[float, float]:
    return (
        float(candidate.required_accel_ratio),
        float(candidate.burn_time_s),
    )


def _max_tilt(
    bot,
    *,
    alt: float,
    dx: float,
    dy: float,
    vx: float,
    vy_up: float,
    max_thrust_accel: float,
    lateral_dx: float | None = None,
) -> float:
    return bot._resolve_max_tilt(
        max(0.0, float(alt)),
        float(dx),
        float(vx),
        dy=float(dy),
        phase="terminal",
        vy_up=float(vy_up),
        max_thrust_accel=float(max_thrust_accel),
        lateral_dx=None if lateral_dx is None else float(lateral_dx),
    )


def _burn_time_candidates(
    bot,
    *,
    passive: Sensors,
    alt: float,
    dx: float,
    dy: float,
    thrust_accel: float,
    tilt_accel: float,
    lateral_dx: float | None = None,
    include_max_time: bool = False,
) -> tuple[list[float], float, float]:
    max_tilt = _max_tilt(
        bot,
        alt=alt,
        dx=dx,
        dy=dy,
        vx=float(passive.vx),
        vy_up=float(passive.vy_up),
        max_thrust_accel=float(tilt_accel),
        lateral_dx=lateral_dx,
    )
    target_vy_up = float(
        bot._desired_terminal_vy(max(0.0, float(alt)), thrust_accel, max_tilt)
    )
    down_speed = max(0.0, -float(passive.vy_up))
    target_down_speed = max(0.0, -target_vy_up)
    vertical_up_accel = max(
        0.1,
        (float(thrust_accel) * math.cos(max_tilt)) - _GRAVITY_MAG,
    )
    lateral_accel = max(
        0.5,
        float(thrust_accel) * math.sin(max_tilt),
    )
    t_v_nom = max(0.0, down_speed - target_down_speed) / vertical_up_accel
    t_x_nom = abs(float(passive.vx)) / lateral_accel
    burn_time_nom = _clamp(
        max(t_v_nom, t_x_nom) + float(bot._cfg.terminal_gate_nominal_buffer_s),
        float(bot._cfg.terminal_gate_burn_time_min_s),
        float(bot._cfg.terminal_gate_burn_time_max_s),
    )
    candidate_times: list[float] = []
    for raw_time in (
        burn_time_nom - float(bot._cfg.terminal_gate_burn_time_offset_short_s),
        burn_time_nom,
        burn_time_nom + float(bot._cfg.terminal_gate_burn_time_offset_long_s),
    ):
        burn_time = _clamp(
            raw_time,
            float(bot._cfg.terminal_gate_burn_time_min_s),
            float(bot._cfg.terminal_gate_burn_time_max_s),
        )
        if any(abs(existing - burn_time) <= 1e-6 for existing in candidate_times):
            continue
        candidate_times.append(burn_time)
    if include_max_time:
        max_time = float(bot._cfg.terminal_gate_burn_time_max_s)
        if not any(abs(existing - max_time) <= 1e-6 for existing in candidate_times):
            candidate_times.append(max_time)
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
) -> TerminalGateCandidate:
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
    return TerminalGateCandidate(
        burn_time_s=float(burn_time_s),
        required_accel_ratio=float(required_ratio),
        upward_accel=float(ay_req),
        tilt_feasible=tilt_feasible,
        ready=ready,
    )


def _latest_safe_state(
    bot,
    *,
    passive: Sensors,
    dx: float,
    lateral_dx: float | None = None,
    dy: float,
    alt: float,
    max_thrust_accel: float,
    thrust_ramp_up: float,
) -> LatestSafeState:
    lateral_miss = float(dx) if lateral_dx is None else float(lateral_dx)
    height_to_target = _height_to_target(dy=dy)
    down_speed = max(0.0, -float(passive.vy_up))
    max_tilt = _max_tilt(
        bot,
        alt=height_to_target,
        dx=dx,
        dy=dy,
        vx=float(passive.vx),
        vy_up=float(passive.vy_up),
        max_thrust_accel=max_thrust_accel,
        lateral_dx=lateral_dx,
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
        altitude=height_to_target,
        vy_up=float(passive.vy_up),
        min_t_fall=0.0,
    )
    candidate_times, max_tilt, target_vy_up = _burn_time_candidates(
        bot,
        passive=passive,
        alt=alt,
        dx=dx,
        dy=dy,
        thrust_accel=max_thrust_accel,
        tilt_accel=max_thrust_accel,
        lateral_dx=lateral_dx,
        include_max_time=True,
    )
    t_brake_v = down_speed / vertical_up_accel
    t_brake_x = bot._terminal_lateral_correction_time(
        dx=lateral_miss,
        vx=float(passive.vx),
        lateral_accel=lateral_accel,
    )
    latest_safe_candidates = [
        _evaluate_candidate(
            dx=dx,
            dy=dy,
            passive=passive,
            burn_time_s=burn_time_s,
            target_vy_up=target_vy_up,
            max_tilt=max_tilt,
            thrust_accel=max_thrust_accel,
            ratio_limit=1.0,
            min_upward_accel=0.0,
        )
        for burn_time_s in candidate_times
    ]
    feasible_candidates = [
        candidate
        for candidate in latest_safe_candidates
        if _candidate_is_feasible(candidate, ratio_limit=1.0)
    ]
    if feasible_candidates:
        best_candidate = min(feasible_candidates, key=_candidate_preference_key)
    else:
        best_candidate = min(
            latest_safe_candidates,
            key=lambda candidate: (
                not candidate.tilt_feasible,
                candidate.required_accel_ratio,
                candidate.burn_time_s,
            ),
        )
    latest_safe_time = (
        spool_time
        + max(t_brake_v, t_brake_x)
        + float(bot._cfg.terminal_gate_latest_safe_buffer_s)
    )
    return LatestSafeState(
        margin_s=float(time_to_impact) - latest_safe_time,
        best_candidate=best_candidate,
    )


def _evaluate_terminal_gate_core(
    bot,
    *,
    current_ready_ticks: int,
    passive: Sensors,
    dx: float,
    projected_dx: float | None,
    dy: float,
    alt: float,
    max_thrust_accel: float,
    nominal_thrust_accel: float,
    thrust_ramp_up: float,
) -> TerminalGateEvaluation:
    latest_safe_state = _latest_safe_state(
        bot,
        passive=passive,
        dx=dx,
        lateral_dx=projected_dx,
        dy=dy,
        alt=alt,
        max_thrust_accel=max_thrust_accel,
        thrust_ramp_up=thrust_ramp_up,
    )
    latest_safe_margin_s = latest_safe_state.margin_s
    candidate_times, max_tilt, target_vy_up = _burn_time_candidates(
        bot,
        passive=passive,
        alt=alt,
        dx=dx,
        dy=dy,
        thrust_accel=nominal_thrust_accel,
        tilt_accel=max_thrust_accel,
        lateral_dx=projected_dx,
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
            ratio_limit=float(bot._cfg.terminal_gate_nominal_ratio),
            min_upward_accel=float(bot._cfg.terminal_gate_nominal_min_up_accel),
        )
        for burn_time_s in candidate_times
    ]
    ready_candidates = [candidate for candidate in nominal_candidates if candidate.ready]
    best_nominal = (
        min(ready_candidates, key=_candidate_preference_key)
        if ready_candidates
        else None
    )

    nominal_ready_ticks = (
        current_ready_ticks + 1 if best_nominal is not None else 0
    )
    required_accel_ratio = (
        best_nominal.required_accel_ratio
        if best_nominal is not None
        else min(
            (candidate.required_accel_ratio for candidate in nominal_candidates),
            default=0.0,
        )
    )
    state_ready_ticks = nominal_ready_ticks

    decision: TerminalGateDecision | None = None
    if best_nominal is not None and nominal_ready_ticks >= max(
        1, int(bot._cfg.terminal_gate_hysteresis_ticks)
    ):
        decision = TerminalGateDecision(
            mode="nominal_ready",
            burn_time_s=best_nominal.burn_time_s,
            latest_safe_margin_s=latest_safe_margin_s,
            required_accel_ratio=best_nominal.required_accel_ratio,
        )
    elif latest_safe_margin_s <= 0.0:
        state_ready_ticks = 0
        required_accel_ratio = latest_safe_state.best_candidate.required_accel_ratio
        decision = TerminalGateDecision(
            mode="latest_safe",
            burn_time_s=latest_safe_state.best_candidate.burn_time_s,
            latest_safe_margin_s=latest_safe_margin_s,
            required_accel_ratio=latest_safe_state.best_candidate.required_accel_ratio,
        )

    return TerminalGateEvaluation(
        decision=decision,
        latest_safe_state=latest_safe_state,
        best_nominal=best_nominal,
        nominal_ready_ticks=nominal_ready_ticks,
        state_ready_ticks=state_ready_ticks,
        required_accel_ratio=required_accel_ratio,
        terrain_divert=TerrainDivertProbe(active=False),
    )


def _passive_coast_step(passive: Sensors, *, dt: float) -> Sensors:
    step_dt = max(0.0, float(dt))
    next_x = float(passive.x) + (float(passive.vx) * step_dt)
    next_y = (
        float(passive.y)
        + (float(passive.vy_up) * step_dt)
        - (0.5 * _GRAVITY_MAG * step_dt * step_dt)
    )
    delta_y = next_y - float(passive.y)
    return replace(
        passive,
        x=next_x,
        y=next_y,
        altitude=max(0.0, float(passive.altitude) + delta_y),
        vx=float(passive.vx),
        vy_up=float(passive.vy_up) - (_GRAVITY_MAG * step_dt),
        ax=0.0,
        ay_up=-_GRAVITY_MAG,
        thrust_level=0.0,
    )


def _lookahead_projection(
    *,
    passive: Sensors,
    target_x: float,
    target_y: float,
) -> tuple[float, float, BallisticProjection]:
    dx = float(target_x) - float(passive.x)
    dy = float(target_y) - float(passive.y)
    projection = estimate_target_y_projection(
        dx=dx,
        dy=dy,
        vx=float(passive.vx),
        vy_up=float(passive.vy_up),
        x=float(passive.x),
        y=float(passive.y),
    )
    return dx, dy, projection


def _should_defer_latest_safe_entry(
    bot,
    *,
    dt: float,
    passive: Sensors,
    dx: float,
    dy: float,
    projected_dx: float | None,
    max_thrust_accel: float,
    nominal_thrust_accel: float,
    thrust_ramp_up: float,
    current_latest_safe_feasible: bool,
    current_latest_safe_ratio: float,
    current_ready_ticks: int,
) -> bool:
    if projected_dx is None or float(dt) <= 1e-6 or float(passive.vy_up) <= 0.0:
        return False

    x_tol = float(bot._phase_terminal_x_tol("terminal"))
    if abs(float(projected_dx)) > x_tol:
        return False

    target_x = float(passive.x) + float(dx)
    target_y = float(passive.y) + float(dy)
    predicted_passive = passive
    predicted_ready_ticks = max(0, int(current_ready_ticks))

    while True:
        predicted_passive = _passive_coast_step(predicted_passive, dt=dt)
        pred_dx, pred_dy, predicted_projection = _lookahead_projection(
            passive=predicted_passive,
            target_x=target_x,
            target_y=target_y,
        )
        pred_alt = _height_to_target(dy=pred_dy)
        if abs(float(predicted_projection.projected_dx)) > x_tol:
            break

        evaluation = _evaluate_terminal_gate_core(
            bot,
            current_ready_ticks=predicted_ready_ticks,
            passive=predicted_passive,
            dx=pred_dx,
            projected_dx=float(predicted_projection.projected_dx),
            dy=pred_dy,
            alt=pred_alt,
            max_thrust_accel=max_thrust_accel,
            nominal_thrust_accel=nominal_thrust_accel,
            thrust_ramp_up=thrust_ramp_up,
        )
        if (
            evaluation.decision is not None
            and evaluation.decision.mode == "nominal_ready"
        ):
            return True

        future_latest_safe = evaluation.latest_safe_state.best_candidate
        future_latest_safe_feasible = _candidate_is_feasible(
            future_latest_safe,
            ratio_limit=1.0,
        )
        if future_latest_safe_feasible and (
            (not current_latest_safe_feasible)
            or (
                future_latest_safe.required_accel_ratio
                < (float(current_latest_safe_ratio) - 1e-3)
            )
        ):
            return True

        time_to_impact = estimate_ground_time_to_impact(
            altitude=pred_alt,
            vy_up=float(predicted_passive.vy_up),
            min_t_fall=0.0,
        )
        if float(predicted_passive.vy_up) <= 0.0 or time_to_impact <= 0.0:
            break

        predicted_ready_ticks = evaluation.nominal_ready_ticks

    return False


def evaluate_terminal_gate(
    bot,
    *,
    dt: float,
    passive: Sensors,
    dx: float,
    projected_dx: float | None,
    dy: float,
    alt: float,
    max_thrust_accel: float,
    min_thrust_accel: float,
    nominal_thrust_accel: float,
    thrust_ramp_up: float,
) -> TerminalGateDecision | None:
    del min_thrust_accel

    state = bot.state
    evaluation = _evaluate_terminal_gate_core(
        bot,
        current_ready_ticks=int(state._terminal_gate_ready_ticks),
        passive=passive,
        dx=dx,
        projected_dx=projected_dx,
        dy=dy,
        alt=alt,
        max_thrust_accel=max_thrust_accel,
        nominal_thrust_accel=nominal_thrust_accel,
        thrust_ramp_up=thrust_ramp_up,
    )

    state._terminal_gate_ready_ticks = evaluation.state_ready_ticks
    state._terminal_gate_required_accel_ratio = evaluation.required_accel_ratio
    state._terminal_gate_latest_safe_margin_s = evaluation.latest_safe_state.margin_s
    state._terrain_divert_mode = None
    state._terrain_divert_margin_min = None
    state._terrain_divert_first_limit_t = None
    state._terrain_divert_worst_x = None
    state._terrain_divert_worst_y = None
    state._terrain_divert_horizon_s = None
    state._terrain_divert_sample_count = 0

    terrain_divert_prefilter: TerrainDivertPrefilter | None = None
    if evaluation.decision is None or evaluation.decision.mode == "latest_safe":
        terrain_divert_prefilter = prefilter_terrain_divert(
            bot,
            passive=passive,
            projected_dx=projected_dx,
        )
        if terrain_divert_prefilter.should_probe:
            probe_start = time.perf_counter()
            terrain_divert = evaluate_terrain_divert_probe(
                bot,
                passive=passive,
                projected_dx=projected_dx,
                max_thrust_accel=max_thrust_accel,
            )
            probe_ms = (time.perf_counter() - probe_start) * 1000.0
            state._terminal_probe_count += 1
            state._terminal_probe_ms_sum += probe_ms
            state._terminal_probe_ms_samples.append(probe_ms)
            state._terrain_divert_mode = terrain_divert.mode
            state._terrain_divert_margin_min = terrain_divert.min_margin
            state._terrain_divert_first_limit_t = terrain_divert.first_limit_t
            state._terrain_divert_worst_x = terrain_divert.worst_x
            state._terrain_divert_worst_y = terrain_divert.worst_y
            state._terrain_divert_horizon_s = terrain_divert.horizon_s
            state._terrain_divert_sample_count = terrain_divert.sample_count
            if (
                terrain_divert.active
                and terrain_divert.min_margin is not None
                and float(terrain_divert.min_margin)
                <= float(bot._cfg.terrain_divert_trigger_margin)
            ):
                evaluation = replace(
                    evaluation,
                    decision=TerminalGateDecision(
                        mode="terrain_divert",
                        burn_time_s=evaluation.latest_safe_state.best_candidate.burn_time_s,
                        latest_safe_margin_s=evaluation.latest_safe_state.margin_s,
                        required_accel_ratio=evaluation.latest_safe_state.best_candidate.required_accel_ratio,
                    ),
                    state_ready_ticks=0,
                    required_accel_ratio=evaluation.latest_safe_state.best_candidate.required_accel_ratio,
                    terrain_divert=terrain_divert,
                )
        if evaluation.decision is None:
            probe_start = time.perf_counter()
            terrain_clip = evaluate_terminal_clip_probe(
                bot,
                passive=passive,
                dx=dx,
                ax_cmd=0.0,
                ay_cmd=0.0,
            )
            if terrain_clip.sample_count > 0:
                probe_ms = (time.perf_counter() - probe_start) * 1000.0
                state._terminal_probe_count += 1
                state._terminal_probe_ms_sum += probe_ms
                state._terminal_probe_ms_samples.append(probe_ms)
                state._terrain_divert_mode = "descent_clip"
                state._terrain_divert_margin_min = terrain_clip.min_margin
                state._terrain_divert_first_limit_t = terrain_clip.first_limit_t
                state._terrain_divert_worst_x = terrain_clip.worst_x
                state._terrain_divert_worst_y = terrain_clip.worst_y
                state._terrain_divert_horizon_s = terrain_clip.horizon_s
                state._terrain_divert_sample_count = terrain_clip.sample_count
            if terrain_clip.active:
                evaluation = replace(
                    evaluation,
                    decision=TerminalGateDecision(
                        mode="terrain_clip",
                        burn_time_s=evaluation.latest_safe_state.best_candidate.burn_time_s,
                        latest_safe_margin_s=evaluation.latest_safe_state.margin_s,
                        required_accel_ratio=evaluation.latest_safe_state.best_candidate.required_accel_ratio,
                    ),
                    state_ready_ticks=0,
                    required_accel_ratio=evaluation.latest_safe_state.best_candidate.required_accel_ratio,
                )

    if (
        evaluation.decision is not None
        and evaluation.decision.mode == "latest_safe"
        and _should_defer_latest_safe_entry(
            bot,
            dt=dt,
            passive=passive,
            dx=dx,
            dy=dy,
            projected_dx=projected_dx,
            max_thrust_accel=max_thrust_accel,
            nominal_thrust_accel=nominal_thrust_accel,
            thrust_ramp_up=thrust_ramp_up,
            current_latest_safe_feasible=_candidate_is_feasible(
                evaluation.latest_safe_state.best_candidate,
                ratio_limit=1.0,
            ),
            current_latest_safe_ratio=evaluation.decision.required_accel_ratio,
            current_ready_ticks=evaluation.nominal_ready_ticks,
        )
    ):
        return None

    return evaluation.decision
