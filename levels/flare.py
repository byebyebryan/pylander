from __future__ import annotations

import math
import random
from dataclasses import dataclass, replace

from core.config import GRAVITY
from core.components import PhysicsState, Transform
from core.ecs import require_component
from core.level import Level
from core.maths import Vector2
from levels.scenario_common import (
    ScenarioLevel,
    ScenarioLevelSpec,
    validate_scenario_recoverability,
)


@dataclass(frozen=True)
class FlareScenario:
    name: str
    angle_deg: float
    start_dx: float
    start_dy: float
    initial_vx_toward_target: float
    initial_vy_up: float
    initial_angle: float = 0.0
    cargo_mass: float = 2250.0


_SPAWN_RADIUS = 800.0
_TARGET_FLIGHT_TIME_S = 12.0
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


def _build_angle_scenario(name: str, angle_deg: float) -> FlareScenario:
    angle_rad = math.radians(float(angle_deg))
    start_dx = _SPAWN_RADIUS * math.cos(angle_rad)
    start_dy = _SPAWN_RADIUS * math.sin(angle_rad)
    gravity = abs(float(GRAVITY))
    time_to_target = _TARGET_FLIGHT_TIME_S
    vx_toward_target = start_dx / max(1e-6, time_to_target)
    vy_up = (
        (0.5 * gravity * time_to_target * time_to_target) - start_dy
    ) / max(1e-6, time_to_target)
    return FlareScenario(
        name=name,
        angle_deg=float(angle_deg),
        start_dx=float(start_dx),
        start_dy=float(start_dy),
        initial_vx_toward_target=float(vx_toward_target),
        initial_vy_up=float(vy_up),
    )


_SCENARIOS: tuple[FlareScenario, ...] = tuple(
    _build_angle_scenario(name, angle_deg) for name, angle_deg in _ANGLE_PROFILES
)
_SCENARIO_BY_NAME = {item.name: item for item in _SCENARIOS}
_DEFAULT_SCENARIO = "mid"
_QUICK_BENCHMARK_SCENARIOS: tuple[str, ...] = (
    "shallower",
    "mid",
    "steeper",
)


def _make_spec(scenario: FlareScenario) -> ScenarioLevelSpec:
    return ScenarioLevelSpec(
        name=scenario.name,
        start_x=scenario.start_dx,
        target_x=0.0,
        spawn_clearance=scenario.start_dy,
        terrain_kind="flat",
        target_mode="flush_flatten",
        target_offset_y=0.0,
        target_size=110.0,
        cargo_mass=scenario.cargo_mass,
    )


class FlareLevel(ScenarioLevel):
    default_bot_name = "flare"

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
            raise ValueError(f"Unknown flare scenario '{name}'. Expected one of: {known}")
        self._eval_scenario_name = key

    def setup(self, game, seed: int) -> None:
        scenario_base = _SCENARIO_BY_NAME[self._eval_scenario_name]
        scenario_name_hash = sum(ord(ch) for ch in scenario_base.name)
        dir_rng = random.Random(seed ^ (scenario_name_hash << 1))
        direction = -1.0 if dir_rng.random() < 0.5 else 1.0
        scenario = replace(
            scenario_base,
            start_dx=float(scenario_base.start_dx) * direction,
        )
        self.scenario = _make_spec(scenario)
        super().setup(game, seed)

        actor = self.world.actors[0]
        trans = require_component(actor, Transform)
        phys = require_component(actor, PhysicsState)

        target_pos = getattr(self, "eval_target_pos", Vector2(0.0, 0.0))
        start_pos = Vector2(
            float(target_pos.x) + (direction * float(scenario_base.start_dx)),
            float(target_pos.y) + float(scenario_base.start_dy),
        )
        trans.pos = Vector2(start_pos)
        actor.start_pos = Vector2(start_pos)
        toward_speed = abs(float(scenario.initial_vx_toward_target))
        initial_vx = -direction * toward_speed
        initial_vy_up = float(scenario.initial_vy_up)
        trans.rotation = _angle_from_velocity(initial_vx, initial_vy_up, opposite=True)
        validate_scenario_recoverability(
            actor,
            scenario_name=scenario.name,
            spawn_clearance=scenario.start_dy,
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
                engine.set_lander_velocity(
                    Vector2(initial_vx, initial_vy_up),
                    uid=actor.uid,
                )

        setattr(self, "scenario_name", scenario_base.name)


def create_level() -> Level:
    return FlareLevel()
