from __future__ import annotations

import math
import random
from dataclasses import dataclass

from core.components import PhysicsState, Transform
from core.ecs import require_component
from core.eval_goals import EVAL_GOAL_LANDING, EVAL_GOAL_SETUP
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
class SetupScenario:
    name: str
    base_angle_deg: float
    radius: SampleRange
    angle_deviation_deg: SampleRange = SampleRange(-5.0, 5.0)
    initial_angle: float = 0.0
    cargo_mass: float = 0.0


_ANGLE_PROFILES: tuple[tuple[str, float], ...] = (
    ("shallower", 15.0),
    ("shallow", 30.0),
    ("mid", 45.0),
    ("steep", 60.0),
    ("steeper", 75.0),
)

_RADIUS_TIERS: tuple[tuple[str, SampleRange], ...] = (
    ("near", SampleRange(620.0, 780.0)),
    ("far", SampleRange(860.0, 1050.0)),
)


def _scenario_name(angle_key: str, radius_key: str) -> str:
    return f"{angle_key}_{radius_key}"


def _build_scenario(angle_key: str, angle_deg: float, radius_key: str, radius: SampleRange) -> SetupScenario:
    return SetupScenario(
        name=_scenario_name(angle_key, radius_key),
        base_angle_deg=angle_deg,
        radius=radius,
    )


_SCENARIOS: tuple[SetupScenario, ...] = tuple(
    _build_scenario(angle_key, angle_deg, radius_key, radius)
    for angle_key, angle_deg in _ANGLE_PROFILES
    for radius_key, radius in _RADIUS_TIERS
)
_SCENARIO_BY_NAME = {item.name: item for item in _SCENARIOS}
_DEFAULT_SCENARIO = "mid_near"
_SMOKE_BENCHMARK_SCENARIOS: tuple[str, ...] = ("mid_far",)
_QUICK_BENCHMARK_SCENARIOS: tuple[str, ...] = (
    "shallow_near",
    "mid_far",
    "steep_far",
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


class SetupLevel(ScenarioCatalogMixin, ScenarioLevel):
    default_bot_name = "zem_zev"
    _scenario_by_name = _SCENARIO_BY_NAME
    _default_scenario_name = _DEFAULT_SCENARIO
    _smoke_benchmark_scenarios = _SMOKE_BENCHMARK_SCENARIOS
    _quick_benchmark_scenarios = _QUICK_BENCHMARK_SCENARIOS
    _supported_eval_goals = (EVAL_GOAL_LANDING, EVAL_GOAL_SETUP)

    def __init__(self) -> None:
        super().__init__()
        self._init_scenario_catalog()
        self.scenario = _make_spec(
            name=self._eval_scenario_name,
            start_dx=0.0,
            start_dy=800.0,
            cargo_mass=0.0,
        )

    def scenario_has_randomized_fields(self, _name: str | None = None) -> bool:
        scenario = self._active_scenario()
        return has_randomized_values((scenario.radius, scenario.angle_deviation_deg))

    def setup(self, game, seed: int) -> None:
        scenario_base = self._active_scenario()
        scenario_name_hash = sum(ord(ch) for ch in scenario_base.name)
        rng = random.Random(seed ^ (scenario_name_hash << 1))

        direction = -1.0 if rng.random() < 0.5 else 1.0
        radius = self._resolve_sample_value(scenario_base.radius, rng)
        angle_deviation_deg = self._resolve_sample_value(scenario_base.angle_deviation_deg, rng)
        entry_angle_deg = float(scenario_base.base_angle_deg) + angle_deviation_deg
        entry_angle_rad = math.radians(entry_angle_deg)
        start_dx = direction * radius * math.cos(entry_angle_rad)
        start_dy = radius * math.sin(entry_angle_rad)

        self.scenario = _make_spec(
            name=scenario_base.name,
            start_dx=start_dx,
            start_dy=start_dy,
            cargo_mass=float(scenario_base.cargo_mass),
        )
        super().setup(game, seed)

        actor = self.world.actors[0]
        target_pos = getattr(self, "eval_target_pos", Vector2(0.0, 0.0))
        trans = require_component(actor, Transform)
        phys = require_component(actor, PhysicsState)
        start_pos = Vector2(
            float(target_pos.x) + start_dx,
            float(target_pos.y) + start_dy,
        )
        trans.pos = Vector2(start_pos)
        actor.start_pos = Vector2(start_pos)

        validate_scenario_recoverability(
            actor,
            scenario_name=scenario_base.name,
            spawn_clearance=start_dy,
            initial_vy_up=0.0,
        )

        trans.rotation = float(scenario_base.initial_angle)
        phys.vel = Vector2(0.0, 0.0)

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
                engine.set_lander_velocity(Vector2(0.0, 0.0), uid=actor.uid)

        self._set_scenario_params(
            {
                "radius": radius,
                "entry_angle_deg": entry_angle_deg,
                "angle_deviation_deg": angle_deviation_deg,
                "direction": direction,
            }
        )
        setattr(self, "scenario_name", scenario_base.name)

    def update(self, game, dt: float) -> None:
        _ = game, dt

    def end(self, game):
        return super().end(game)


def create_level() -> Level:
    return SetupLevel()
