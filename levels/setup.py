from __future__ import annotations

import math
import random
from dataclasses import dataclass

from core.components import PhysicsState, Transform
from core.ecs import require_component
from core.level_capabilities import BenchmarkScenarioSets, LevelBenchmarkProfile
from core.level import Level
from core.maths import Vector2
from levels.scenario_common import (
    SampleRange,
    ScenarioLevel,
    ScenarioLevelSpec,
    has_randomized_values,
    validate_scenario_recoverability,
)
from levels.staged_eval import ZemStageEvalTracker


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
_SETUP_EVAL_MODES: tuple[str, ...] = ("auto", "focused", "full")
_SETUP_DEFAULT_EVAL_MODE = "full"


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


class SetupLevel(ScenarioLevel):
    default_bot_name = "zem_zev"

    def __init__(self) -> None:
        super().__init__()
        self._eval_scenario_name = _DEFAULT_SCENARIO
        self._eval_mode_name = "auto"
        self._resolved_eval_mode = _SETUP_DEFAULT_EVAL_MODE
        self._stage_eval = ZemStageEvalTracker(
            stage_prefix="setup",
            completion_gate_prefix="setup_gate",
        )
        self.scenario = _make_spec(
            name=self._eval_scenario_name,
            start_dx=0.0,
            start_dy=800.0,
            cargo_mass=0.0,
        )

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
            raise ValueError(f"Unknown setup scenario '{name}'. Expected one of: {known}")
        self._eval_scenario_name = key

    def set_eval_mode(self, name: str) -> None:
        key = str(name).strip().lower()
        if key not in _SETUP_EVAL_MODES:
            known = ", ".join(_SETUP_EVAL_MODES)
            raise ValueError(f"Unknown setup eval mode '{name}'. Expected one of: {known}")
        self._eval_mode_name = key

    def scenario_has_randomized_fields(self, _name: str | None = None) -> bool:
        scenario = _SCENARIO_BY_NAME[self._eval_scenario_name]
        return has_randomized_values((scenario.radius, scenario.angle_deviation_deg))

    def _mode_for_run(self) -> str:
        if self._eval_mode_name == "auto":
            return _SETUP_DEFAULT_EVAL_MODE
        return self._eval_mode_name

    def _resolve_zem_snapshot(self, game):
        return self._stage_eval.resolve_zem_snapshot(game)

    def setup(self, game, seed: int) -> None:
        self._resolved_eval_mode = self._mode_for_run()
        self._stage_eval.reset()

        scenario_base = _SCENARIO_BY_NAME[self._eval_scenario_name]
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

        self._stage_eval.seed_motion_state(actor)
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
        _ = dt
        actor = self.world.actors[0]
        self._stage_eval.update_motion(actor)
        if self._stage_eval.phase_done:
            return
        snapshot = self._resolve_zem_snapshot(game)
        if isinstance(snapshot, dict):
            target_pos = getattr(self, "eval_target_pos", Vector2(0.0, 0.0))
            self._stage_eval.capture_snapshot(game, actor, target_pos, snapshot)

    def should_end(self, game) -> bool:
        if self._stage_eval.should_end_focused(self._resolved_eval_mode):
            return True
        return super().should_end(game)

    def end(self, game):
        result = super().end(game)
        result["eval_mode"] = self._resolved_eval_mode
        actor = self.world.actors[0]
        target_pos = getattr(self, "eval_target_pos", Vector2(0.0, 0.0))
        self._stage_eval.apply_result(
            result,
            eval_mode=self._resolved_eval_mode,
            eval_phase_name="zem_setup_gate",
            actor=actor,
            target_pos=target_pos,
        )
        return result


def create_level() -> Level:
    return SetupLevel()
