from __future__ import annotations

from dataclasses import dataclass

from core.components import PhysicsState, Transform
from core.level import Level
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
    cargo_mass: float = 1800.0


_BASE_SCENARIOS: tuple[PlungeScenario, ...] = (
    PlungeScenario(name="alt_100", spawn_clearance=100.0),
    PlungeScenario(name="alt_400", spawn_clearance=400.0),
    PlungeScenario(name="alt_1600", spawn_clearance=1600.0),
    PlungeScenario(name="speed_low", spawn_clearance=220.0, initial_vy_up=-12.0),
    PlungeScenario(name="speed_high", spawn_clearance=320.0, initial_vy_up=-24.0),
    PlungeScenario(name="upward_low", spawn_clearance=260.0, initial_vy_up=8.0),
)
_CARGO_VARIANTS: tuple[tuple[str, float], ...] = (
    ("cargo_low", 0.0),
    ("cargo_high", 4500.0),
)
_CARGO_VARIANT_BASES: tuple[str, ...] = (
    "alt_400",
    "speed_high",
    "upward_low",
)
_SCENARIOS: tuple[PlungeScenario, ...] = (
    _BASE_SCENARIOS
    + tuple(
        PlungeScenario(
            name=f"{base.name}_{suffix}",
            spawn_clearance=base.spawn_clearance,
            initial_vx=base.initial_vx,
            initial_vy_up=base.initial_vy_up,
            initial_angle=base.initial_angle,
            cargo_mass=cargo_mass,
        )
        for base in _BASE_SCENARIOS
        if base.name in _CARGO_VARIANT_BASES
        for suffix, cargo_mass in _CARGO_VARIANTS
    )
)

_SCENARIO_BY_NAME = {item.name: item for item in _SCENARIOS}
_DEFAULT_SCENARIO = "alt_400"
_QUICK_BENCHMARK_SCENARIOS: tuple[str, ...] = (
    "alt_400",
    "speed_high",
    "upward_low",
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
    default_bot_name = "plunge"

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
