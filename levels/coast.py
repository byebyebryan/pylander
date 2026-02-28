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
    ScenarioLevel,
    ScenarioLevelSpec,
    has_randomized_values,
    validate_scenario_recoverability,
)
from levels.staged_eval import ZemStageEvalTracker


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
_QUICK_BENCHMARK_SCENARIOS: tuple[str, ...] = (
    "shallow_tight",
    "mid_wide",
    "steep_wide",
)
_COAST_EVAL_MODES: tuple[str, ...] = ("auto", "focused", "full")
_COAST_DEFAULT_EVAL_MODE = "full"


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


class CoastLevel(ScenarioLevel):
    default_bot_name = "zem_zev"

    def __init__(self) -> None:
        super().__init__()
        self._eval_scenario_name = _DEFAULT_SCENARIO
        self._eval_mode_name = "auto"
        self._resolved_eval_mode = _COAST_DEFAULT_EVAL_MODE
        self._stage_eval = ZemStageEvalTracker(
            stage_prefix="coast",
            completion_gate_prefix="terminal_gate",
        )
        self.scenario = _make_spec(
            name=self._eval_scenario_name,
            start_dx=0.0,
            start_dy=800.0,
            cargo_mass=1800.0,
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
            raise ValueError(f"Unknown coast scenario '{name}'. Expected one of: {known}")
        self._eval_scenario_name = key

    def set_eval_mode(self, name: str) -> None:
        key = str(name).strip().lower()
        if key not in _COAST_EVAL_MODES:
            known = ", ".join(_COAST_EVAL_MODES)
            raise ValueError(f"Unknown coast eval mode '{name}'. Expected one of: {known}")
        self._eval_mode_name = key

    def scenario_has_randomized_fields(self, _name: str | None = None) -> bool:
        scenario = _SCENARIO_BY_NAME[self._eval_scenario_name]
        return has_randomized_values(
            (
                scenario.radius,
                scenario.angle_deviation_deg,
                scenario.target_flight_time_s,
                scenario.projected_dx_error,
            )
        )

    def _mode_for_run(self) -> str:
        if self._eval_mode_name == "auto":
            return _COAST_DEFAULT_EVAL_MODE
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

        self._stage_eval.seed_motion_state(actor)
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
            eval_phase_name="zem_terminal_gate",
            actor=actor,
            target_pos=target_pos,
        )
        return result


def create_level() -> Level:
    return CoastLevel()
