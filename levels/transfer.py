from __future__ import annotations

import random
from dataclasses import dataclass, replace

from core.components import PhysicsState, Transform
from core.ecs import require_component
from core.level import Level
from core.maths import Vector2
from core.terrain import ballistic_fall_time
from levels.scenario_common import (
    ScenarioLevel,
    ScenarioLevelSpec,
    validate_scenario_recoverability,
)


@dataclass(frozen=True)
class TransferScenario:
    name: str
    spawn_clearance: float
    start_x: float
    vx_factor: float = 0.0
    initial_vy_up: float = 0.0
    initial_angle: float = 0.0
    cargo_mass: float = 1800.0


@dataclass(frozen=True)
class _AltitudeTier:
    key: str
    clearance: float


@dataclass(frozen=True)
class _RangeTier:
    key: str
    offset: float
    vx_factor: float


_ALTITUDE_TIERS: tuple[_AltitudeTier, ...] = (
    _AltitudeTier(key="low", clearance=300.0),
    _AltitudeTier(key="high", clearance=900.0),
)
_RANGE_TIERS: tuple[_RangeTier, ...] = (
    _RangeTier(key="short", offset=220.0, vx_factor=0.35),
    _RangeTier(key="mid", offset=520.0, vx_factor=0.16),
    _RangeTier(key="long", offset=920.0, vx_factor=0.02),
)

_BASE_SCENARIOS: tuple[TransferScenario, ...] = tuple(
    TransferScenario(
        name=f"air_{alt_tier.key}_{range_tier.key}",
        spawn_clearance=alt_tier.clearance,
        start_x=range_tier.offset,
        vx_factor=range_tier.vx_factor,
    )
    for alt_tier in _ALTITUDE_TIERS
    for range_tier in _RANGE_TIERS
)
_STRESS_SCENARIOS: tuple[TransferScenario, ...] = (
    TransferScenario(
        name="air_low_mid_reverse",
        spawn_clearance=300.0,
        start_x=560.0,
        vx_factor=-0.75,
        initial_vy_up=0.0,
    ),
    TransferScenario(
        name="air_high_long_reverse",
        spawn_clearance=900.0,
        start_x=1080.0,
        vx_factor=-0.70,
        initial_vy_up=0.0,
    ),
)
_SCENARIOS: tuple[TransferScenario, ...] = _BASE_SCENARIOS + _STRESS_SCENARIOS
_SCENARIO_BY_NAME = {item.name: item for item in _SCENARIOS}
_DEFAULT_SCENARIO = "air_high_mid"
_QUICK_BENCHMARK_SCENARIOS: tuple[str, ...] = (
    "air_low_mid",
    "air_high_long",
    "air_low_long",
    "air_low_mid_reverse",
    "air_high_long_reverse",
)


def _make_spec(scenario: TransferScenario) -> ScenarioLevelSpec:
    return ScenarioLevelSpec(
        name=scenario.name,
        start_x=scenario.start_x,
        target_x=0.0,
        spawn_clearance=scenario.spawn_clearance,
        terrain_kind="flat",
        target_mode="flush_flatten",
        target_offset_y=0.0,
        target_size=110.0,
        cargo_mass=scenario.cargo_mass,
    )


class TransferLevel(ScenarioLevel):
    default_bot_name = "transfer"

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
            raise ValueError(f"Unknown transfer scenario '{name}'. Expected one of: {known}")
        self._eval_scenario_name = key

    def setup(self, game, seed: int) -> None:
        scenario_base = _SCENARIO_BY_NAME[self._eval_scenario_name]
        scenario_name_hash = sum(ord(ch) for ch in scenario_base.name)
        dir_rng = random.Random(seed ^ (scenario_name_hash << 1))
        direction = -1.0 if dir_rng.random() < 0.5 else 1.0
        scenario = replace(
            scenario_base,
            start_x=float(scenario_base.start_x) * direction,
        )
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

        target_pos = getattr(self, "eval_target_pos", Vector2(0.0, 0.0))
        dx = float(target_pos.x - trans.pos.x)
        alt = max(0.0, float(trans.pos.y - target_pos.y))
        t_fall = ballistic_fall_time(altitude=alt, vy_up=float(scenario.initial_vy_up))
        vx_ballistic = dx / t_fall
        initial_vx = vx_ballistic * float(scenario.vx_factor)
        phys.vel = Vector2(initial_vx, float(scenario.initial_vy_up))

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
                    Vector2(initial_vx, float(scenario.initial_vy_up)),
                    uid=actor.uid,
                )

        setattr(self, "scenario_name", scenario_base.name)


def create_level() -> Level:
    return TransferLevel()
