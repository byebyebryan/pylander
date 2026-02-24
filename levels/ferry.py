from __future__ import annotations

import random
from dataclasses import replace

from core.components import FuelTank, PhysicsState, Transform
from core.ecs import require_component
from core.level import Level
from core.maths import Vector2
from core.terrain import ballistic_fall_time
from levels.scenario_common import (
    ScenarioLevel,
    ScenarioLevelSpec,
    validate_scenario_recoverability,
)
from levels.transfer import TransferLevel, TransferScenario


_SCENARIOS: tuple[TransferScenario, ...] = (
    TransferScenario(
        name="air_low_long_climb",
        spawn_clearance=100.0,
        start_x=1600.0,
        vx_factor=0.0,
        initial_vy_up=0.0,
        cargo_mass=0.0,
    ),
)
_SCENARIO_BY_NAME = {item.name: item for item in _SCENARIOS}
_DEFAULT_SCENARIO = "air_low_long_climb"
_QUICK_BENCHMARK_SCENARIOS: tuple[str, ...] = (
    "air_low_long_climb",
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


class FerryLevel(TransferLevel):
    default_bot_name = "ferry"

    def __init__(self) -> None:
        super().__init__()
        self._eval_scenario_name = _DEFAULT_SCENARIO
        self.scenario = _make_spec(_SCENARIO_BY_NAME[self._eval_scenario_name])
        self._reset_phase_eval_metrics()

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
            raise ValueError(f"Unknown ferry scenario '{name}'. Expected one of: {known}")
        self._eval_scenario_name = key

    def setup(self, game, seed: int) -> None:
        self._resolved_eval_mode = self._mode_for_run()
        self._reset_phase_eval_metrics()
        scenario_base = _SCENARIO_BY_NAME[self._eval_scenario_name]
        scenario_name_hash = sum(ord(ch) for ch in scenario_base.name)
        dir_rng = random.Random(seed ^ (scenario_name_hash << 1))
        direction = -1.0 if dir_rng.random() < 0.5 else 1.0
        scenario = replace(
            scenario_base,
            start_x=float(scenario_base.start_x) * direction,
        )
        self.scenario = _make_spec(scenario)
        ScenarioLevel.setup(self, game, seed)

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

        self._phase1_prev_pos = Vector2(trans.pos)
        tank = require_component(actor, FuelTank)
        self._phase1_prev_fuel = float(tank.fuel)
        setattr(self, "scenario_name", scenario_base.name)


def create_level() -> Level:
    return FerryLevel()
