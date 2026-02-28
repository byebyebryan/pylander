from __future__ import annotations

import math
import random
from dataclasses import dataclass, replace

from core.config import GRAVITY
from core.components import CargoHold, Engine, FuelTank, PhysicsState, Transform
from core.ecs import require_component
from core.level import Level
from core.maths import Vector2
from levels.scenario_common import (
    SampleRange,
    ScenarioLevel,
    ScenarioLevelSpec,
    has_randomized_values,
    validate_scenario_recoverability,
)


@dataclass(frozen=True)
class FlareScenario:
    name: str
    base_angle_deg: float
    radius: float | SampleRange
    angle_deviation_deg: float | SampleRange
    target_flight_time_s: float | SampleRange
    cargo_mass: float = 2250.0


_ANGLE_PROFILES: tuple[tuple[str, float], ...] = (
    ("shallower", 15.0),
    ("shallow", 30.0),
    ("mid", 45.0),
    ("steep", 60.0),
    ("steeper", 75.0),
)


def _angle_from_velocity(vx: float, vy_up: float, *, opposite: bool = False) -> float:
    vel_x = -float(vx) if opposite else float(vx)
    vel_y = -float(vy_up) if opposite else float(vy_up)
    if abs(vel_x) <= 1e-6 and abs(vel_y) <= 1e-6:
        return 0.0
    return math.atan2(vel_x, vel_y)


def _build_angle_scenario(name: str, base_angle_deg: float) -> FlareScenario:
    return FlareScenario(
        name=name,
        base_angle_deg=float(base_angle_deg),
        radius=SampleRange(700.0, 900.0),
        angle_deviation_deg=SampleRange(-5.0, 5.0),
        target_flight_time_s=SampleRange(10.0, 12.0),
    )


_SCENARIOS: tuple[FlareScenario, ...] = tuple(
    _build_angle_scenario(name, angle_deg) for name, angle_deg in _ANGLE_PROFILES
)
_SCENARIO_BY_NAME = {item.name: item for item in _SCENARIOS}
_DEFAULT_SCENARIO = "mid"
_QUICK_BENCHMARK_SCENARIOS: tuple[str, ...] = (
    "shallow",
    "mid",
    "steep",
)
_FLARE_EVAL_MODES: tuple[str, ...] = ("auto", "focused", "full")
_FLARE_DEFAULT_EVAL_MODE = "full"

_GRAVITY_MAG = abs(float(GRAVITY))
_MAX_SETUP_ATTEMPTS = 64
_FOCUSED_MIN_DOWNSPEED = 8.0
_FOCUSED_TGO_TARGET_S = 4.5
_FOCUSED_MARGIN_TARGET_M = 120.0
_FULL_MARGIN_T_MIN = 1.0
_FULL_MARGIN_H_MIN = 30.0
_FOCUSED_MARGIN_T_MIN = 0.35
_FOCUSED_MARGIN_H_MIN = 10.0


@dataclass(frozen=True)
class _FlareCandidate:
    radius: float
    angle_deviation_deg: float
    target_flight_time_s: float
    direction: float
    entry_angle_deg: float
    start_dx: float
    start_dy: float
    start_pos: Vector2
    initial_vx: float
    initial_vy_up: float
    trim_time_s: float
    t_go_start_s: float
    focus_margin_m: float


def _make_spec(*, name: str, start_dx: float, start_dy: float, cargo_mass: float) -> ScenarioLevelSpec:
    return ScenarioLevelSpec(
        name=name,
        start_x=start_dx,
        target_x=0.0,
        spawn_clearance=start_dy,
        terrain_kind="flat",
        target_mode="flush_flatten",
        target_offset_y=0.0,
        target_size=110.0,
        cargo_mass=cargo_mass,
    )


class FlareLevel(ScenarioLevel):
    default_bot_name = "zem_zev"

    def __init__(self) -> None:
        super().__init__()
        self._eval_scenario_name = _DEFAULT_SCENARIO
        self._eval_mode_name = "auto"
        self._resolved_eval_mode = _FLARE_DEFAULT_EVAL_MODE
        self.scenario = _make_spec(
            name=self._eval_scenario_name,
            start_dx=0.0,
            start_dy=800.0,
            cargo_mass=2250.0,
        )

    @staticmethod
    def list_batch_scenarios() -> list[str]:
        return [item.name for item in _SCENARIOS]

    @staticmethod
    def list_quick_benchmark_scenarios() -> list[str]:
        return [name for name in _QUICK_BENCHMARK_SCENARIOS if name in _SCENARIO_BY_NAME]

    def set_eval_scenario(self, name: str) -> None:
        key = str(name).strip().lower()
        if key not in _SCENARIO_BY_NAME:
            known = ", ".join(sorted(_SCENARIO_BY_NAME))
            raise ValueError(f"Unknown flare scenario '{name}'. Expected one of: {known}")
        self._eval_scenario_name = key

    def set_eval_mode(self, name: str) -> None:
        key = str(name).strip().lower()
        if key not in _FLARE_EVAL_MODES:
            known = ", ".join(_FLARE_EVAL_MODES)
            raise ValueError(f"Unknown flare eval mode '{name}'. Expected one of: {known}")
        self._eval_mode_name = key

    def scenario_has_randomized_fields(self, _name: str | None = None) -> bool:
        scenario = _SCENARIO_BY_NAME[self._eval_scenario_name]
        return has_randomized_values(
            (
                scenario.radius,
                scenario.angle_deviation_deg,
                scenario.target_flight_time_s,
            )
        )

    def _mode_for_run(self) -> str:
        if self._eval_mode_name == "auto":
            return _FLARE_DEFAULT_EVAL_MODE
        return self._eval_mode_name

    @staticmethod
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

    def _sample_candidate(
        self,
        *,
        scenario: FlareScenario,
        scenario_hash: int,
        seed: int,
        attempt: int,
        target_pos: Vector2,
    ) -> _FlareCandidate:
        if self._benchmark_random_mode == "median":
            rng = random.Random(seed ^ (scenario_hash << 1))
            radius = self._resolve_sample_value(scenario.radius, rng)
            angle_deviation_deg = self._resolve_sample_value(scenario.angle_deviation_deg, rng)
            target_flight_time_s = max(
                1e-6,
                self._resolve_sample_value(scenario.target_flight_time_s, rng),
            )
        else:
            seed_index = abs(int(seed)) + 1 + (attempt * 37)
            radius_frac = self._van_der_corput(seed_index + (scenario_hash * 3), 2)
            angle_frac = self._van_der_corput(seed_index + (scenario_hash * 5), 3)
            time_frac = self._van_der_corput(seed_index + (scenario_hash * 7), 5)

            radius = scenario.radius.median()
            if isinstance(scenario.radius, SampleRange):
                radius = scenario.radius.low + ((scenario.radius.high - scenario.radius.low) * radius_frac)

            angle_deviation_deg = 0.0
            if isinstance(scenario.angle_deviation_deg, SampleRange):
                angle_deviation_deg = scenario.angle_deviation_deg.low + (
                    (scenario.angle_deviation_deg.high - scenario.angle_deviation_deg.low) * angle_frac
                )
            else:
                angle_deviation_deg = float(scenario.angle_deviation_deg)

            target_flight_time_s = 10.0
            if isinstance(scenario.target_flight_time_s, SampleRange):
                target_flight_time_s = scenario.target_flight_time_s.low + (
                    (scenario.target_flight_time_s.high - scenario.target_flight_time_s.low) * time_frac
                )
            else:
                target_flight_time_s = float(scenario.target_flight_time_s)
            target_flight_time_s = max(1e-6, target_flight_time_s)

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
            + (0.5 * _GRAVITY_MAG * target_flight_time_s * target_flight_time_s)
        ) / target_flight_time_s

        return _FlareCandidate(
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

    @staticmethod
    def _compute_total_mass(actor) -> float:
        phys = require_component(actor, PhysicsState)
        tank = require_component(actor, FuelTank)
        cargo = actor.get_component(CargoHold)
        cargo_mass = 0.0
        if cargo is not None:
            cargo_mass = max(0.0, min(float(cargo.cargo_mass), float(cargo.max_cargo_mass)))
        return max(
            0.5,
            float(phys.mass) + (float(tank.fuel) * float(tank.density)) + cargo_mass,
        )

    @staticmethod
    def _compute_accel_limits(actor) -> tuple[float, float]:
        engine = require_component(actor, Engine)
        total_mass = FlareLevel._compute_total_mass(actor)
        max_force = float(engine.max_power) * float(engine.max_thrust)
        a_total = max(0.1, max_force / total_mass)
        a_up_max = max(0.1, a_total - _GRAVITY_MAG)
        # Slightly conservative lateral authority estimate.
        a_lat_eff = max(0.5, 0.90 * a_total)
        return a_up_max, a_lat_eff

    @staticmethod
    def _ballistic_state_at_time(
        *,
        start_pos: Vector2,
        initial_vx: float,
        initial_vy_up: float,
        elapsed_s: float,
    ) -> tuple[Vector2, float, float]:
        t = max(0.0, float(elapsed_s))
        pos = Vector2(
            float(start_pos.x) + (float(initial_vx) * t),
            float(start_pos.y) + (float(initial_vy_up) * t) - (0.5 * _GRAVITY_MAG * t * t),
        )
        vx = float(initial_vx)
        vy_up = float(initial_vy_up) - (_GRAVITY_MAG * t)
        return pos, vx, vy_up

    def _focused_trim_candidate(
        self,
        *,
        candidate: _FlareCandidate,
        target_pos: Vector2,
        a_up_max: float,
        a_lat_eff: float,
    ) -> _FlareCandidate:
        total_time = max(1e-3, float(candidate.target_flight_time_s))
        max_trim = max(0.0, total_time - 0.2)
        if max_trim <= 0.0:
            return candidate

        best_tau = -1.0
        best_score = float("inf")
        best_margin = 0.0

        for idx in range(1, 97):
            tau = (idx / 96.0) * max_trim
            pos, vx, vy_up = self._ballistic_state_at_time(
                start_pos=candidate.start_pos,
                initial_vx=candidate.initial_vx,
                initial_vy_up=candidate.initial_vy_up,
                elapsed_s=tau,
            )
            altitude = float(pos.y) - float(target_pos.y)
            if altitude <= 5.0:
                continue
            downspeed = max(0.0, -vy_up)
            if downspeed < _FOCUSED_MIN_DOWNSPEED:
                continue
            stop_distance = (downspeed * downspeed) / (2.0 * max(0.1, a_up_max))
            focus_margin = altitude - stop_distance
            t_go = total_time - tau
            t_brake_v = downspeed / max(0.1, a_up_max)
            t_brake_h = abs(vx) / max(0.5, a_lat_eff)
            margin_t = t_go - max(t_brake_v, t_brake_h)
            margin_h = focus_margin
            if margin_t < _FOCUSED_MARGIN_T_MIN or margin_h < _FOCUSED_MARGIN_H_MIN:
                continue
            score = abs(focus_margin - _FOCUSED_MARGIN_TARGET_M) + (0.2 * abs(t_go - 6.0))
            if score < best_score:
                best_score = score
                best_tau = tau
                best_margin = focus_margin

        if best_tau < 0.0:
            fallback_tau = min(max_trim, max(0.0, total_time - _FOCUSED_TGO_TARGET_S))
            best_tau = fallback_tau
            best_margin = 0.0
            best_margin_t = -1e9
            for idx in range(1, 97):
                tau = (idx / 96.0) * max_trim
                pos, vx, vy_up = self._ballistic_state_at_time(
                    start_pos=candidate.start_pos,
                    initial_vx=candidate.initial_vx,
                    initial_vy_up=candidate.initial_vy_up,
                    elapsed_s=tau,
                )
                altitude = float(pos.y) - float(target_pos.y)
                if altitude <= 5.0:
                    continue
                downspeed = max(0.0, -vy_up)
                if downspeed < _FOCUSED_MIN_DOWNSPEED:
                    continue
                stop_distance = (downspeed * downspeed) / (2.0 * max(0.1, a_up_max))
                focus_margin = altitude - stop_distance
                t_go = total_time - tau
                t_brake_v = downspeed / max(0.1, a_up_max)
                t_brake_h = abs(vx) / max(0.5, a_lat_eff)
                margin_t = t_go - max(t_brake_v, t_brake_h)
                margin_h = focus_margin
                if margin_h < _FOCUSED_MARGIN_H_MIN:
                    continue
                if margin_t > best_margin_t:
                    best_margin_t = margin_t
                    best_tau = tau
                    best_margin = focus_margin

            if best_margin_t <= -1e8:
                pos, _, vy_up = self._ballistic_state_at_time(
                    start_pos=candidate.start_pos,
                    initial_vx=candidate.initial_vx,
                    initial_vy_up=candidate.initial_vy_up,
                    elapsed_s=best_tau,
                )
                altitude = float(pos.y) - float(target_pos.y)
                downspeed = max(0.0, -vy_up)
                stop_distance = (downspeed * downspeed) / (2.0 * max(0.1, a_up_max))
                best_margin = altitude - stop_distance

        trim_start_pos, trim_vx, trim_vy = self._ballistic_state_at_time(
            start_pos=candidate.start_pos,
            initial_vx=candidate.initial_vx,
            initial_vy_up=candidate.initial_vy_up,
            elapsed_s=best_tau,
        )
        return replace(
            candidate,
            start_pos=Vector2(trim_start_pos),
            start_dx=float(trim_start_pos.x) - float(target_pos.x),
            start_dy=max(0.0, float(trim_start_pos.y) - float(target_pos.y)),
            initial_vx=float(trim_vx),
            initial_vy_up=float(trim_vy),
            trim_time_s=float(best_tau),
            t_go_start_s=max(1e-3, total_time - float(best_tau)),
            focus_margin_m=float(best_margin),
        )

    @staticmethod
    def _validate_flare_start_state(
        *,
        candidate: _FlareCandidate,
        target_pos: Vector2,
        a_up_max: float,
        a_lat_eff: float,
        mode: str,
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

        if mode == "focused":
            ok = (
                margin_t >= _FOCUSED_MARGIN_T_MIN
                and margin_h >= _FOCUSED_MARGIN_H_MIN
                and downspeed >= _FOCUSED_MIN_DOWNSPEED
            )
            return ok, margin_t, margin_h, downspeed

        ok = margin_t >= _FULL_MARGIN_T_MIN and margin_h >= _FULL_MARGIN_H_MIN
        return ok, margin_t, margin_h, downspeed

    def setup(self, game, seed: int) -> None:
        self._resolved_eval_mode = self._mode_for_run()
        scenario_base = _SCENARIO_BY_NAME[self._eval_scenario_name]
        scenario_name_hash = sum(ord(ch) for ch in scenario_base.name)
        pre_target = Vector2(0.0, 0.0)
        spec_candidate = self._sample_candidate(
            scenario=scenario_base,
            scenario_hash=scenario_name_hash,
            seed=seed,
            attempt=0,
            target_pos=pre_target,
        )
        self.scenario = _make_spec(
            name=scenario_base.name,
            start_dx=spec_candidate.start_dx,
            start_dy=max(0.0, spec_candidate.start_dy),
            cargo_mass=float(scenario_base.cargo_mass),
        )
        super().setup(game, seed)

        actor = self.world.actors[0]
        trans = require_component(actor, Transform)
        phys = require_component(actor, PhysicsState)
        target_pos = getattr(self, "eval_target_pos", Vector2(0.0, 0.0))
        a_up_max, a_lat_eff = self._compute_accel_limits(actor)

        selected: _FlareCandidate | None = None
        margin_t = 0.0
        margin_h = 0.0
        downspeed = 0.0
        for attempt in range(_MAX_SETUP_ATTEMPTS):
            candidate = self._sample_candidate(
                scenario=scenario_base,
                scenario_hash=scenario_name_hash,
                seed=seed,
                attempt=attempt,
                target_pos=target_pos,
            )
            if self._resolved_eval_mode == "focused":
                candidate = self._focused_trim_candidate(
                    candidate=candidate,
                    target_pos=target_pos,
                    a_up_max=a_up_max,
                    a_lat_eff=a_lat_eff,
                )

            try:
                validate_scenario_recoverability(
                    actor,
                    scenario_name=scenario_base.name,
                    spawn_clearance=max(0.0, float(candidate.start_pos.y) - float(target_pos.y)),
                    initial_vy_up=float(candidate.initial_vy_up),
                )
            except ValueError:
                continue

            ok, margin_t, margin_h, downspeed = self._validate_flare_start_state(
                candidate=candidate,
                target_pos=target_pos,
                a_up_max=a_up_max,
                a_lat_eff=a_lat_eff,
                mode=self._resolved_eval_mode,
            )
            if ok:
                selected = candidate
                break

        if selected is None:
            raise ValueError(
                f"Scenario '{scenario_base.name}' failed flare validity generation "
                f"(mode={self._resolved_eval_mode}, seed={seed}, attempts={_MAX_SETUP_ATTEMPTS})"
            )

        trans.pos = Vector2(selected.start_pos)
        actor.start_pos = Vector2(selected.start_pos)
        trans.rotation = _angle_from_velocity(selected.initial_vx, selected.initial_vy_up, opposite=True)
        phys.vel = Vector2(selected.initial_vx, selected.initial_vy_up)

        engine = getattr(self, "engine", None)
        if engine is not None:
            if hasattr(engine, "teleport_lander"):
                engine.teleport_lander(
                    Vector2(trans.pos),
                    angle=trans.rotation,
                    clear_velocity=False,
                    uid=actor.uid,
                )
            if hasattr(engine, "set_lander_velocity"):
                engine.set_lander_velocity(
                    Vector2(selected.initial_vx, selected.initial_vy_up),
                    uid=actor.uid,
                )

        self._set_scenario_params(
            {
                "radius": selected.radius,
                "entry_angle_deg": selected.entry_angle_deg,
                "angle_deviation_deg": selected.angle_deviation_deg,
                "target_flight_time_s": selected.target_flight_time_s,
                "direction": selected.direction,
                "eval_mode": self._resolved_eval_mode,
                "trim_time_s": selected.trim_time_s,
                "tgo_start_s": selected.t_go_start_s,
                "focus_margin_m": selected.focus_margin_m,
                "validity_margin_time_s": margin_t,
                "validity_margin_altitude_m": margin_h,
                "validity_downspeed_mps": downspeed,
            }
        )
        setattr(self, "scenario_name", scenario_base.name)


def create_level() -> Level:
    return FlareLevel()
