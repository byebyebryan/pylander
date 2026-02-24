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
class _TransferProfile:
    key: str
    offset: float
    vx_factor: float


_MID_OFFSET = 520.0
_LONG_OFFSET = 760.0
_MID_SPAWN_CLEARANCE = 760.0
_MID_VX_FACTOR = 0.14
_LONG_VX_FACTOR = 0.05

_TRANSFER_PROFILES: tuple[_TransferProfile, ...] = (
    _TransferProfile(key="mid", offset=_MID_OFFSET, vx_factor=_MID_VX_FACTOR),
    _TransferProfile(key="long", offset=_LONG_OFFSET, vx_factor=_LONG_VX_FACTOR),
)


def _proportional_clearance(offset: float) -> float:
    return round((_MID_SPAWN_CLEARANCE * float(offset)) / _MID_OFFSET, 1)


_BASE_SCENARIOS: tuple[TransferScenario, ...] = tuple(
    TransferScenario(
        name=f"air_{profile.key}",
        spawn_clearance=_proportional_clearance(profile.offset),
        start_x=profile.offset,
        vx_factor=profile.vx_factor,
    )
    for profile in _TRANSFER_PROFILES
)
_STRESS_SCENARIOS: tuple[TransferScenario, ...] = (
    TransferScenario(
        name="air_mid_reverse",
        # Keep extra room for away-velocity correction before drift handoff.
        spawn_clearance=max(900.0, _proportional_clearance(_MID_OFFSET) + 120.0),
        start_x=_MID_OFFSET,
        vx_factor=-0.52,
        initial_vy_up=0.0,
    ),
)
_CARGO_VARIANTS: tuple[tuple[str, float], ...] = (
    ("heavy", 3200.0),
)
_CARGO_VARIANT_BASES: tuple[str, ...] = (
    "air_long",
    "air_mid_reverse",
)
_CORE_SCENARIOS: tuple[TransferScenario, ...] = _BASE_SCENARIOS + _STRESS_SCENARIOS
_SCENARIOS: tuple[TransferScenario, ...] = (
    _CORE_SCENARIOS
    + tuple(
        TransferScenario(
            name=f"{base.name}_{suffix}",
            spawn_clearance=base.spawn_clearance,
            start_x=base.start_x,
            vx_factor=base.vx_factor,
            initial_vy_up=base.initial_vy_up,
            initial_angle=base.initial_angle,
            cargo_mass=cargo_mass,
        )
        for base in _CORE_SCENARIOS
        if base.name in _CARGO_VARIANT_BASES
        for suffix, cargo_mass in _CARGO_VARIANTS
    )
)
_SCENARIO_BY_NAME = {item.name: item for item in _SCENARIOS}
_DEFAULT_SCENARIO = "air_mid"
_QUICK_BENCHMARK_SCENARIOS: tuple[str, ...] = (
    "air_mid",
    "air_long",
    "air_mid_reverse",
    "air_long_heavy",
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
