from __future__ import annotations

import math
import random
from dataclasses import dataclass

from core.components import PhysicsState, Transform
from core.ecs import require_component
from core.level import Level
from core.maths import Vector2
from levels.scenario_common import (
    SampleRange,
    ScenarioCatalogMixin,
    ScenarioLevel,
    ScenarioLevelSpec,
    has_randomized_values,
    validate_scenario_recoverability,
)


@dataclass(frozen=True)
class CoastScenario:
    name: str
    base_angle_deg: float
    projected_dx_error: SampleRange
    radius: SampleRange = SampleRange(700.0, 900.0)
    angle_deviation_deg: SampleRange = SampleRange(-5.0, 5.0)
    target_flight_time_s: SampleRange = SampleRange(9.5, 12.5)
    initial_angle: float = 0.0
    cargo_mass: float = 1800.0


@dataclass(frozen=True)
class _ErrorTier:
    key: str
    projected_dx_error: SampleRange


_ANGLE_PROFILES: tuple[tuple[str, float], ...] = (
    ("shallower", 15.0),
    ("shallow", 30.0),
    ("mid", 45.0),
    ("steep", 60.0),
    ("steeper", 75.0),
)

_ERROR_TIERS: tuple[_ErrorTier, ...] = (
    _ErrorTier(key="tight", projected_dx_error=SampleRange(30.0, 55.0)),
    _ErrorTier(key="wide", projected_dx_error=SampleRange(75.0, 110.0)),
)


def _angle_from_velocity(vx: float, vy_up: float) -> float:
    vel_x = float(vx)
    vel_y = float(vy_up)
    if abs(vel_x) <= 1e-6 and abs(vel_y) <= 1e-6:
        return 0.0
    return math.atan2(vel_x, vel_y)


def _scenario_name(profile: str, tier: str) -> str:
    return f"{profile}_{tier}"


def _build_entry(profile_name: str, angle_deg: float, tier: _ErrorTier) -> CoastScenario:
    return CoastScenario(
        name=_scenario_name(profile_name, tier.key),
        base_angle_deg=float(angle_deg),
        projected_dx_error=tier.projected_dx_error,
    )


_SCENARIOS: tuple[CoastScenario, ...] = tuple(
    _build_entry(profile_name, angle_deg, tier)
    for profile_name, angle_deg in _ANGLE_PROFILES
    for tier in _ERROR_TIERS
)

_SCENARIO_BY_NAME = {item.name: item for item in _SCENARIOS}
_DEFAULT_SCENARIO = "mid_tight"
_SMOKE_BENCHMARK_SCENARIOS: tuple[str, ...] = ("mid_wide",)
_QUICK_BENCHMARK_SCENARIOS: tuple[str, ...] = (
    "shallow_tight",
    "mid_wide",
    "steep_wide",
)
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


class FlareErrorLevel(ScenarioCatalogMixin, ScenarioLevel):
    default_bot_name = "zem_zev"
    _scenario_by_name = _SCENARIO_BY_NAME
    _default_scenario_name = _DEFAULT_SCENARIO
    _smoke_benchmark_scenarios = _SMOKE_BENCHMARK_SCENARIOS
    _quick_benchmark_scenarios = _QUICK_BENCHMARK_SCENARIOS

    def __init__(self) -> None:
        super().__init__()
        self._init_scenario_catalog()
        self.scenario = _make_spec(
            name=self._eval_scenario_name,
            start_dx=0.0,
            start_dy=800.0,
            cargo_mass=1800.0,
        )

    def scenario_has_randomized_fields(self, _name: str | None = None) -> bool:
        scenario = self._active_scenario()
        return has_randomized_values(
            (
                scenario.radius,
                scenario.angle_deviation_deg,
                scenario.target_flight_time_s,
                scenario.projected_dx_error,
            )
        )

    def setup(self, game, seed: int) -> None:
        scenario_base = self._active_scenario()
        scenario_name_hash = sum(ord(ch) for ch in scenario_base.name)
        rng = random.Random(seed ^ (scenario_name_hash << 1))

        direction = -1.0 if rng.random() < 0.5 else 1.0
        radius = self._resolve_sample_value(scenario_base.radius, rng)
        angle_deviation_deg = self._resolve_sample_value(scenario_base.angle_deviation_deg, rng)
        target_flight_time_s = max(
            1e-6,
            self._resolve_sample_value(scenario_base.target_flight_time_s, rng),
        )
        projected_dx_error_mag = abs(self._resolve_sample_value(scenario_base.projected_dx_error, rng))
        if self._benchmark_random_mode == "median":
            projected_dx_error_sign = 1.0
        else:
            projected_dx_error_sign = -1.0 if rng.random() < 0.5 else 1.0
        projected_dx_error = projected_dx_error_sign * projected_dx_error_mag

        entry_angle_deg = float(scenario_base.base_angle_deg) + angle_deviation_deg
        entry_angle_rad = math.radians(entry_angle_deg)
        start_dx_mag = radius * math.cos(entry_angle_rad)
        start_dy = radius * math.sin(entry_angle_rad)
        start_dx = direction * start_dx_mag

        self.scenario = _make_spec(
            name=scenario_base.name,
            start_dx=start_dx,
            start_dy=start_dy,
            cargo_mass=float(scenario_base.cargo_mass),
        )
        super().setup(game, seed)

        actor = self.world.actors[0]
        trans = require_component(actor, Transform)
        phys = require_component(actor, PhysicsState)
        target_pos = getattr(self, "eval_target_pos", Vector2(0.0, 0.0))
        trans.pos = Vector2(
            float(target_pos.x) + start_dx,
            float(target_pos.y) + start_dy,
        )
        actor.start_pos = Vector2(trans.pos)

        impact_target_x = float(target_pos.x) + projected_dx_error
        initial_vx = (impact_target_x - float(trans.pos.x)) / target_flight_time_s
        initial_vy_up = (
            (float(target_pos.y) - float(trans.pos.y))
            + (0.5 * 9.8 * target_flight_time_s * target_flight_time_s)
        ) / target_flight_time_s
        trans.rotation = _angle_from_velocity(initial_vx, initial_vy_up)

        validate_scenario_recoverability(
            actor,
            scenario_name=scenario_base.name,
            spawn_clearance=start_dy,
            initial_vy_up=initial_vy_up,
        )

        phys.vel = Vector2(initial_vx, initial_vy_up)

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
                engine.set_lander_velocity(Vector2(initial_vx, initial_vy_up), uid=actor.uid)

        self._set_scenario_params(
            {
                "radius": radius,
                "entry_angle_deg": entry_angle_deg,
                "angle_deviation_deg": angle_deviation_deg,
                "target_flight_time_s": target_flight_time_s,
                "projected_dx_error": projected_dx_error,
                "projected_dx_error_mag": projected_dx_error_mag,
                "projected_dx_error_sign": projected_dx_error_sign,
                "direction": direction,
            }
        )
        setattr(self, "scenario_name", scenario_base.name)

    def update(self, game, dt: float) -> None:
        _ = game, dt

    def end(self, game):
        return super().end(game)


def create_level() -> Level:
    return FlareErrorLevel()
