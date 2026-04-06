from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Any

from core.config import GRAVITY_MAG
from core.components import Engine, PhysicsState, Transform
from core.ecs import require_component
from core.maths import Vector2
from levels.common_scenarios import (
    BenchmarkRandomMode,
    SampleRange,
    angle_from_velocity,
    has_randomized_values,
    resolve_sample_value,
    scenario_seed,
    sync_engine_pose_velocity,
    validate_scenario_recoverability,
)
from levels.common_world import get_mass


_MAX_SETUP_ATTEMPTS = 64
_FULL_MARGIN_T_MIN = 1.0
_FULL_MARGIN_H_MIN = 30.0


@dataclass(frozen=True)
class TerminalSpawnCandidate:
    radius: float
    angle_deviation_deg: float
    target_flight_time_s: float
    direction: float
    entry_angle_deg: float
    start_dx: float
    start_dy: float
    start_pos: Any
    initial_vx: float
    initial_vy_up: float
    trim_time_s: float
    t_go_start_s: float
    focus_margin_m: float


def terminal_scenario_has_randomized_fields(scenario) -> bool:  # noqa: ANN001
    values: list[float | SampleRange] = [
        scenario.radius,
        scenario.angle_deviation_deg,
        scenario.target_flight_time_s,
    ]
    if scenario.projected_dx_error is not None:
        values.append(scenario.projected_dx_error)
    return has_randomized_values(tuple(values))


def sample_terminal_normal_candidate(
    *,
    scenario,
    seed: int,
    attempt: int,
    target_pos: Any,
    benchmark_random_mode: BenchmarkRandomMode,
) -> TerminalSpawnCandidate:
    seed_key = str(getattr(scenario, "seed_key", scenario.name) or scenario.name)
    scenario_hash = sum(ord(ch) for ch in seed_key)
    if benchmark_random_mode == "median":
        rng = random.Random(scenario_seed(seed, seed_key))
        radius = resolve_sample_value(scenario.radius, mode="median", rng=rng)
        angle_deviation_deg = resolve_sample_value(
            scenario.angle_deviation_deg,
            mode="median",
            rng=rng,
        )
        target_flight_time_s = max(
            1e-6,
            resolve_sample_value(scenario.target_flight_time_s, mode="median", rng=rng),
        )
    else:
        seed_index = abs(int(seed)) + 1 + (attempt * 37)
        radius_frac = _van_der_corput(seed_index + (scenario_hash * 3), 2)
        angle_frac = _van_der_corput(seed_index + (scenario_hash * 5), 3)
        time_frac = _van_der_corput(seed_index + (scenario_hash * 7), 5)

        radius = _sample_from_fraction(scenario.radius, radius_frac)
        angle_deviation_deg = _sample_from_fraction(
            scenario.angle_deviation_deg, angle_frac
        )
        target_flight_time_s = max(
            1e-6,
            _sample_from_fraction(scenario.target_flight_time_s, time_frac),
        )

    direction = -1.0 if ((int(seed) + scenario_hash + attempt) & 1) == 0 else 1.0
    entry_angle_deg = float(scenario.base_angle_deg) + float(angle_deviation_deg)
    entry_angle_rad = math.radians(entry_angle_deg)
    start_dx_mag = float(radius) * math.cos(entry_angle_rad)
    start_dy = float(radius) * math.sin(entry_angle_rad)
    start_dx = direction * start_dx_mag

    start_pos = Vector2(
        float(target_pos.x) + start_dx,
        float(target_pos.y) + start_dy,
    )
    initial_vx = (float(target_pos.x) - float(start_pos.x)) / target_flight_time_s
    initial_vy_up = (
        (float(target_pos.y) - float(start_pos.y))
        + (0.5 * GRAVITY_MAG * target_flight_time_s * target_flight_time_s)
    ) / target_flight_time_s

    return TerminalSpawnCandidate(
        radius=float(radius),
        angle_deviation_deg=float(angle_deviation_deg),
        target_flight_time_s=float(target_flight_time_s),
        direction=direction,
        entry_angle_deg=float(entry_angle_deg),
        start_dx=float(start_dx),
        start_dy=float(start_dy),
        start_pos=Vector2(start_pos),
        initial_vx=float(initial_vx),
        initial_vy_up=float(initial_vy_up),
        trim_time_s=0.0,
        t_go_start_s=float(target_flight_time_s),
        focus_margin_m=0.0,
    )


def resolve_terminal_error_spawn(
    *,
    scenario,
    seed: int,
    benchmark_random_mode: BenchmarkRandomMode,
    target_pos: Any,
) -> tuple[TerminalSpawnCandidate, dict[str, float]]:
    seed_key = str(getattr(scenario, "seed_key", scenario.name) or scenario.name)
    rng = random.Random(scenario_seed(seed, seed_key))

    direction = -1.0 if rng.random() < 0.5 else 1.0
    radius = resolve_sample_value(scenario.radius, mode=benchmark_random_mode, rng=rng)
    angle_deviation_deg = resolve_sample_value(
        scenario.angle_deviation_deg,
        mode=benchmark_random_mode,
        rng=rng,
    )
    target_flight_time_s = max(
        1e-6,
        resolve_sample_value(
            scenario.target_flight_time_s, mode=benchmark_random_mode, rng=rng
        ),
    )
    projected_dx_error_mag = abs(
        resolve_sample_value(
            scenario.projected_dx_error, mode=benchmark_random_mode, rng=rng
        )
    )
    if benchmark_random_mode == "median":
        projected_dx_error_sign = 1.0
    else:
        projected_dx_error_sign = -1.0 if rng.random() < 0.5 else 1.0
    projected_dx_error = projected_dx_error_sign * projected_dx_error_mag

    entry_angle_deg = float(scenario.base_angle_deg) + angle_deviation_deg
    entry_angle_rad = math.radians(entry_angle_deg)
    start_dx_mag = radius * math.cos(entry_angle_rad)
    start_dy = radius * math.sin(entry_angle_rad)
    start_dx = direction * start_dx_mag

    impact_target_x = float(target_pos.x) + projected_dx_error
    start_pos = Vector2(float(target_pos.x) + start_dx, float(target_pos.y) + start_dy)
    initial_vx = (impact_target_x - float(start_pos.x)) / target_flight_time_s
    initial_vy_up = (
        (float(target_pos.y) - float(start_pos.y))
        + (0.5 * GRAVITY_MAG * target_flight_time_s * target_flight_time_s)
    ) / target_flight_time_s

    candidate = TerminalSpawnCandidate(
        radius=float(radius),
        angle_deviation_deg=float(angle_deviation_deg),
        target_flight_time_s=float(target_flight_time_s),
        direction=float(direction),
        entry_angle_deg=float(entry_angle_deg),
        start_dx=float(start_dx),
        start_dy=float(start_dy),
        start_pos=Vector2(start_pos),
        initial_vx=float(initial_vx),
        initial_vy_up=float(initial_vy_up),
        trim_time_s=0.0,
        t_go_start_s=float(target_flight_time_s),
        focus_margin_m=0.0,
    )
    params = {
        "radius": float(radius),
        "entry_angle_deg": float(entry_angle_deg),
        "angle_deviation_deg": float(angle_deviation_deg),
        "target_flight_time_s": float(target_flight_time_s),
        "projected_dx_error": float(projected_dx_error),
        "projected_dx_error_mag": float(projected_dx_error_mag),
        "projected_dx_error_sign": float(projected_dx_error_sign),
        "direction": float(direction),
    }
    return candidate, params


def compute_terminal_accel_limits(actor) -> tuple[float, float]:
    engine = require_component(actor, Engine)
    total_mass = max(0.5, get_mass(actor))
    max_force = float(engine.max_power) * float(engine.max_thrust)
    a_total = max(0.1, max_force / total_mass)
    a_up_max = max(0.1, a_total - GRAVITY_MAG)
    a_lat_eff = max(0.5, 0.90 * a_total)
    return a_up_max, a_lat_eff


def validate_terminal_start_state(
    *,
    candidate: TerminalSpawnCandidate,
    target_pos: Any,
    a_up_max: float,
    a_lat_eff: float,
) -> tuple[bool, float, float, float]:
    altitude = float(candidate.start_pos.y) - float(target_pos.y)
    if altitude <= 0.0:
        return False, -1e9, -1e9, 0.0
    downspeed = max(0.0, -float(candidate.initial_vy_up))
    t_brake_v = downspeed / max(0.1, a_up_max)
    t_brake_h = abs(float(candidate.initial_vx)) / max(0.5, a_lat_eff)
    margin_t = float(candidate.t_go_start_s) - max(t_brake_v, t_brake_h)
    stop_distance = (downspeed * downspeed) / (2.0 * max(0.1, a_up_max))
    margin_h = altitude - stop_distance

    ok = margin_t >= _FULL_MARGIN_T_MIN and margin_h >= _FULL_MARGIN_H_MIN
    return ok, margin_t, margin_h, downspeed


def select_terminal_normal_spawn(
    *,
    actor,
    scenario,
    seed: int,
    benchmark_random_mode: BenchmarkRandomMode,
    target_pos: Any,
) -> tuple[TerminalSpawnCandidate, float, float, float]:
    a_up_max, a_lat_eff = compute_terminal_accel_limits(actor)

    selected: TerminalSpawnCandidate | None = None
    margin_t = 0.0
    margin_h = 0.0
    downspeed = 0.0
    for attempt in range(_MAX_SETUP_ATTEMPTS):
        candidate = sample_terminal_normal_candidate(
            scenario=scenario,
            seed=seed,
            attempt=attempt,
            target_pos=target_pos,
            benchmark_random_mode=benchmark_random_mode,
        )

        try:
            validate_scenario_recoverability(
                actor,
                scenario_name=scenario.name,
                spawn_clearance=max(
                    0.0, float(candidate.start_pos.y) - float(target_pos.y)
                ),
                initial_vy_up=float(candidate.initial_vy_up),
            )
        except ValueError:
            continue

        ok, margin_t, margin_h, downspeed = validate_terminal_start_state(
            candidate=candidate,
            target_pos=target_pos,
            a_up_max=a_up_max,
            a_lat_eff=a_lat_eff,
        )
        if ok:
            selected = candidate
            break

    if selected is None:
        raise ValueError(
            f"Scenario '{scenario.name}' failed terminal validity generation "
            f"(seed={seed}, attempts={_MAX_SETUP_ATTEMPTS})"
        )
    return selected, margin_t, margin_h, downspeed


def apply_terminal_spawn(
    actor, engine, candidate: TerminalSpawnCandidate, *, retrograde: bool
) -> None:
    trans = require_component(actor, Transform)
    phys = require_component(actor, PhysicsState)
    trans.pos = Vector2(candidate.start_pos)
    actor.start_pos = Vector2(candidate.start_pos)
    trans.rotation = angle_from_velocity(
        candidate.initial_vx,
        candidate.initial_vy_up,
        opposite=retrograde,
    )
    phys.vel = Vector2(candidate.initial_vx, candidate.initial_vy_up)
    sync_engine_pose_velocity(
        engine,
        trans.pos,
        trans.rotation,
        candidate.initial_vx,
        candidate.initial_vy_up,
        actor.uid,
    )


def validate_terminal_error_recoverability(
    actor, scenario, candidate: TerminalSpawnCandidate
) -> None:
    validate_scenario_recoverability(
        actor,
        scenario_name=scenario.name,
        spawn_clearance=candidate.start_dy,
        initial_vy_up=candidate.initial_vy_up,
    )


def _sample_from_fraction(value: float | SampleRange, fraction: float) -> float:
    if not isinstance(value, SampleRange):
        return float(value)
    return float(value.low) + ((float(value.high) - float(value.low)) * float(fraction))


def _van_der_corput(index: int, base: int) -> float:
    if index <= 0:
        return 0.0
    value = 0.0
    denom = 1.0
    n = int(index)
    while n > 0:
        n, remainder = divmod(n, base)
        denom *= base
        value += remainder / denom
    return value
