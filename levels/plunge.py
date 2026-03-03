from __future__ import annotations

from dataclasses import dataclass

from core.components import PhysicsState, Transform
from core.level import Level
from core.level_capabilities import BenchmarkScenarioSets, LevelBenchmarkProfile
from core.maths import Vector2
from core.ecs import require_component
from levels.scenario_common import (
    ScenarioLevel,
    ScenarioLevelSpec,
    validate_scenario_recoverability,
)


@dataclass(frozen=True)
class PlungeScenario:
    name: str
    spawn_clearance: float
    initial_vx: float = 0.0
    initial_vy_up: float = 0.0
    initial_angle: float = 0.0
    cargo_mass: float = 2250.0


_ALTITUDE_TIERS: tuple[tuple[str, float], ...] = (
    ("low", 100.0),
    ("mid", 400.0),
    ("high", 1600.0),
)
_WEIGHT_TIERS: tuple[tuple[str, float], ...] = (
    ("light", 0.0),
    ("normal", 2250.0),
    ("heavy", 4500.0),
)


def _scenario_name(alt_tier: str, weight_tier: str) -> str:
    return f"{alt_tier}_{weight_tier}"


_SCENARIOS: tuple[PlungeScenario, ...] = (
    tuple(
        PlungeScenario(
            name=_scenario_name(alt_tier, weight_tier),
            spawn_clearance=spawn_clearance,
            cargo_mass=cargo_mass,
        )
        for alt_tier, spawn_clearance in _ALTITUDE_TIERS
        for weight_tier, cargo_mass in _WEIGHT_TIERS
    )
)

_SCENARIO_BY_NAME = {item.name: item for item in _SCENARIOS}
_DEFAULT_SCENARIO = _scenario_name("mid", "normal")
_SMOKE_BENCHMARK_SCENARIOS: tuple[str, ...] = (_scenario_name("mid", "normal"),)
_QUICK_BENCHMARK_SCENARIOS: tuple[str, ...] = (
    _scenario_name("low", "normal"),
    _scenario_name("mid", "normal"),
    _scenario_name("high", "normal"),
)


def _make_spec(scenario: PlungeScenario) -> ScenarioLevelSpec:
    return ScenarioLevelSpec(
        name=scenario.name,
        start_x=0.0,
        target_x=0.0,
        spawn_clearance=scenario.spawn_clearance,
        terrain_kind="flat",
        target_mode="flush_flatten",
        target_offset_y=0.0,
        target_size=110.0,
        cargo_mass=scenario.cargo_mass,
    )


class PlungeLevel(ScenarioLevel):
    default_bot_name = "zem_zev"

    def __init__(self) -> None:
        super().__init__()
        self._eval_scenario_name = _DEFAULT_SCENARIO
        self.scenario = _make_spec(_SCENARIO_BY_NAME[self._eval_scenario_name])

    @staticmethod
    def list_batch_scenarios() -> list[str]:
        return [item.name for item in _SCENARIOS]

    @staticmethod
    def list_quick_benchmark_scenarios() -> list[str]:
        return [name for name in _QUICK_BENCHMARK_SCENARIOS if name in _SCENARIO_BY_NAME]

    @staticmethod
    def benchmark_profile() -> LevelBenchmarkProfile:
        full = tuple(item.name for item in _SCENARIOS)
        quick = tuple(name for name in _QUICK_BENCHMARK_SCENARIOS if name in _SCENARIO_BY_NAME)
        smoke = tuple(name for name in _SMOKE_BENCHMARK_SCENARIOS if name in _SCENARIO_BY_NAME)
        return LevelBenchmarkProfile(
            policy="normal",
            scenarios=BenchmarkScenarioSets(smoke=smoke, quick=quick, full=full),
        )

    def set_eval_scenario(self, name: str) -> None:
        key = str(name).strip().lower()
        if key not in _SCENARIO_BY_NAME:
            known = ", ".join(sorted(_SCENARIO_BY_NAME))
            raise ValueError(f"Unknown plunge scenario '{name}'. Expected one of: {known}")
        self._eval_scenario_name = key

    def setup(self, game, seed: int) -> None:
        _ = seed
        scenario = _SCENARIO_BY_NAME[self._eval_scenario_name]
        self.scenario = _make_spec(scenario)
        super().setup(game, seed)

        actor = self.world.actors[0]
        validate_scenario_recoverability(
            actor,
            scenario_name=scenario.name,
            spawn_clearance=scenario.spawn_clearance,
            initial_vy_up=scenario.initial_vy_up,
        )

        trans = require_component(actor, Transform)
        phys = require_component(actor, PhysicsState)
        trans.rotation = float(scenario.initial_angle)
        phys.vel = Vector2(float(scenario.initial_vx), float(scenario.initial_vy_up))

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
                    Vector2(float(scenario.initial_vx), float(scenario.initial_vy_up)),
                    uid=actor.uid,
                )

        setattr(self, "scenario_name", scenario.name)


def create_level() -> Level:
    return PlungeLevel()
