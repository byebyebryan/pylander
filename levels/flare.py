from __future__ import annotations

import math
import random
from dataclasses import dataclass

from core.config import GRAVITY
from core.components import PhysicsState, Transform
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
    "shallower",
    "mid",
    "steeper",
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


class FlareLevel(ScenarioLevel):
    default_bot_name = "flare"

    def __init__(self) -> None:
        super().__init__()
        self._eval_scenario_name = _DEFAULT_SCENARIO
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

    def scenario_has_randomized_fields(self, _name: str | None = None) -> bool:
        scenario = _SCENARIO_BY_NAME[self._eval_scenario_name]
        return has_randomized_values(
            (
                scenario.radius,
                scenario.angle_deviation_deg,
                scenario.target_flight_time_s,
            )
        )

    def setup(self, game, seed: int) -> None:
        scenario_base = _SCENARIO_BY_NAME[self._eval_scenario_name]
        scenario_name_hash = sum(ord(ch) for ch in scenario_base.name)
        rng = random.Random(seed ^ (scenario_name_hash << 1))
        direction = -1.0 if rng.random() < 0.5 else 1.0
        radius = self._resolve_sample_value(scenario_base.radius, rng)
        angle_deviation_deg = self._resolve_sample_value(scenario_base.angle_deviation_deg, rng)
        target_flight_time_s = max(
            1e-6,
            self._resolve_sample_value(scenario_base.target_flight_time_s, rng),
        )
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
        start_pos = Vector2(
            float(target_pos.x) + start_dx,
            float(target_pos.y) + start_dy,
        )
        trans.pos = Vector2(start_pos)
        actor.start_pos = Vector2(start_pos)
        initial_vx = (float(target_pos.x) - float(start_pos.x)) / target_flight_time_s
        initial_vy_up = (
            (float(target_pos.y) - float(start_pos.y))
            + (0.5 * abs(float(GRAVITY)) * target_flight_time_s * target_flight_time_s)
        ) / target_flight_time_s
        trans.rotation = _angle_from_velocity(initial_vx, initial_vy_up, opposite=True)
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
                engine.set_lander_velocity(
                    Vector2(initial_vx, initial_vy_up),
                    uid=actor.uid,
                )

        self._set_scenario_params(
            {
                "radius": radius,
                "entry_angle_deg": entry_angle_deg,
                "angle_deviation_deg": angle_deviation_deg,
                "target_flight_time_s": target_flight_time_s,
                "direction": direction,
            }
        )
        setattr(self, "scenario_name", scenario_base.name)


def create_level() -> Level:
    return FlareLevel()
