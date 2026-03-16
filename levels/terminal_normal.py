from __future__ import annotations

import math
import random
from dataclasses import dataclass

from core.config import GRAVITY
from core.components import Engine, PhysicsState, Transform
from core.ecs import require_component
from core.level import Level
from core.maths import Vector2
from levels.common import get_mass
from levels.scenario_common import (
    FLARE_ANGLE_PROFILES,
    SampleRange,
    ScenarioCatalogMixin,
    ScenarioLevel,
    angle_from_velocity,
    prime_boost_cutoff_for_primary_bot,
    has_randomized_values,
    make_flat_scenario_spec,
    scenario_seed,
    sync_engine_pose_velocity,
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


_ANGLE_PROFILES = FLARE_ANGLE_PROFILES


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
_SMOKE_BENCHMARK_SCENARIOS: tuple[str, ...] = ("mid",)
_QUICK_BENCHMARK_SCENARIOS: tuple[str, ...] = (
    "shallow",
    "mid",
    "steep",
)

_GRAVITY_MAG = abs(float(GRAVITY))
_MAX_SETUP_ATTEMPTS = 64
_FULL_MARGIN_T_MIN = 1.0
_FULL_MARGIN_H_MIN = 30.0


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


class FlareNormalLevel(ScenarioCatalogMixin, ScenarioLevel):
    default_bot_name = "pdg"
    _scenario_by_name = _SCENARIO_BY_NAME
    _default_scenario_name = _DEFAULT_SCENARIO
    _smoke_benchmark_scenarios = _SMOKE_BENCHMARK_SCENARIOS
    _quick_benchmark_scenarios = _QUICK_BENCHMARK_SCENARIOS

    def __init__(self) -> None:
        super().__init__()
        self._init_scenario_catalog()
        self.scenario = make_flat_scenario_spec(
            name=self._eval_scenario_name,
            start_dx=0.0,
            start_dy=800.0,
            cargo_mass=2250.0,
        )

    def scenario_has_randomized_fields(self, _name: str | None = None) -> bool:
        scenario = self._active_scenario()
        return has_randomized_values(
            (
                scenario.radius,
                scenario.angle_deviation_deg,
                scenario.target_flight_time_s,
            )
        )

    def start(self, game) -> None:
        prime_boost_cutoff_for_primary_bot(self, game)

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
            rng = random.Random(scenario_seed(seed, scenario.name))
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
        return max(0.5, get_mass(actor))

    @staticmethod
    def _compute_accel_limits(actor) -> tuple[float, float]:
        engine = require_component(actor, Engine)
        total_mass = FlareNormalLevel._compute_total_mass(actor)
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

    @staticmethod
    def _validate_flare_start_state(
        *,
        candidate: _FlareCandidate,
        target_pos: Vector2,
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

    def setup(self, game, seed: int) -> None:
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
        self.scenario = make_flat_scenario_spec(
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
            )
            if ok:
                selected = candidate
                break

        if selected is None:
            raise ValueError(
                f"Scenario '{scenario_base.name}' failed terminal validity generation "
                f"(seed={seed}, attempts={_MAX_SETUP_ATTEMPTS})"
            )

        trans.pos = Vector2(selected.start_pos)
        actor.start_pos = Vector2(selected.start_pos)
        trans.rotation = angle_from_velocity(selected.initial_vx, selected.initial_vy_up, opposite=True)
        phys.vel = Vector2(selected.initial_vx, selected.initial_vy_up)

        sync_engine_pose_velocity(
            getattr(self, "engine", None),
            trans.pos,
            trans.rotation,
            selected.initial_vx,
            selected.initial_vy_up,
            actor.uid,
        )

        self._set_scenario_params(
            {
                "radius": selected.radius,
                "entry_angle_deg": selected.entry_angle_deg,
                "angle_deviation_deg": selected.angle_deviation_deg,
                "target_flight_time_s": selected.target_flight_time_s,
                "direction": selected.direction,
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
    return FlareNormalLevel()
