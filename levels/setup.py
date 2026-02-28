from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Any

from core.components import FuelTank, PhysicsState, Transform
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
        self.scenario = _make_spec(
            name=self._eval_scenario_name,
            start_dx=0.0,
            start_dy=800.0,
            cargo_mass=0.0,
        )
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

    @staticmethod
    def _to_optional_float(value: Any) -> float | None:
        if value is None:
            return None
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(numeric):
            return None
        return numeric

    @staticmethod
    def _resolve_zem_snapshot(game) -> dict[str, Any] | None:
        actor_bots = getattr(game, "actor_bots", {})
        if not isinstance(actor_bots, dict):
            return None
        for bot in actor_bots.values():
            get_snapshot = getattr(bot, "get_evaluation_snapshot", None)
            if not callable(get_snapshot):
                continue
            try:
                snapshot = get_snapshot()
            except Exception:
                continue
            if not isinstance(snapshot, dict):
                continue
            if str(snapshot.get("kind") or "") == "zem_zev":
                return snapshot
        return None

    def _mode_for_run(self) -> str:
        if self._eval_mode_name == "auto":
            return _SETUP_DEFAULT_EVAL_MODE
        return self._eval_mode_name

    def _reset_phase_eval_metrics(self) -> None:
        self._setup_phase_done = False
        self._setup_phase_time = None
        self._setup_phase_altitude = None
        self._setup_phase_projected_dx = None
        self._setup_phase_distance = 0.0
        self._setup_phase_fuel_consumed = 0.0
        self._setup_prev_pos: Vector2 | None = None
        self._setup_prev_fuel: float | None = None
        self._zem_setup_gate_done = False
        self._zem_setup_gate_time = None
        self._zem_setup_gate_altitude = None
        self._zem_setup_gate_projected_dx = None
        self._zem_terminal_gate_done = False
        self._zem_terminal_gate_time = None
        self._zem_terminal_gate_altitude = None
        self._zem_terminal_gate_projected_dx = None
        self._zem_solve_count = None
        self._zem_solve_ms_mean = None
        self._zem_solve_ms_p90 = None
        self._zem_fallback_frames = None

    def _update_phase_metrics(self) -> None:
        if self._setup_phase_done:
            return
        actor = self.world.actors[0]
        trans = require_component(actor, Transform)
        tank = require_component(actor, FuelTank)
        cur_pos = Vector2(trans.pos)
        cur_fuel = float(tank.fuel)
        if self._setup_prev_pos is not None:
            self._setup_phase_distance += math.hypot(
                cur_pos.x - self._setup_prev_pos.x,
                cur_pos.y - self._setup_prev_pos.y,
            )
        if self._setup_prev_fuel is not None:
            self._setup_phase_fuel_consumed += max(0.0, self._setup_prev_fuel - cur_fuel)
        self._setup_prev_pos = cur_pos
        self._setup_prev_fuel = cur_fuel

    def _capture_zem_setup_gate(self, game, snapshot: dict[str, Any]) -> None:
        self._zem_setup_gate_done = bool(snapshot.get("setup_gate_done"))
        self._zem_setup_gate_time = self._to_optional_float(snapshot.get("setup_gate_time"))
        self._zem_setup_gate_altitude = self._to_optional_float(snapshot.get("setup_gate_altitude"))
        self._zem_setup_gate_projected_dx = self._to_optional_float(
            snapshot.get("setup_gate_projected_dx")
        )
        self._zem_terminal_gate_done = bool(snapshot.get("terminal_gate_done"))
        self._zem_terminal_gate_time = self._to_optional_float(snapshot.get("terminal_gate_time"))
        self._zem_terminal_gate_altitude = self._to_optional_float(
            snapshot.get("terminal_gate_altitude")
        )
        self._zem_terminal_gate_projected_dx = self._to_optional_float(
            snapshot.get("terminal_gate_projected_dx")
        )
        self._zem_solve_count = self._to_optional_float(snapshot.get("solve_count"))
        self._zem_solve_ms_mean = self._to_optional_float(snapshot.get("solve_ms_mean"))
        self._zem_solve_ms_p90 = self._to_optional_float(snapshot.get("solve_ms_p90"))
        self._zem_fallback_frames = self._to_optional_float(snapshot.get("fallback_frames"))

        if self._setup_phase_done or (not self._zem_setup_gate_done):
            return

        actor = self.world.actors[0]
        trans = require_component(actor, Transform)
        self._setup_phase_done = True
        self._setup_phase_time = (
            self._zem_setup_gate_time
            if self._zem_setup_gate_time is not None
            else float(getattr(game, "_elapsed_time", 0.0))
        )
        self._setup_phase_altitude = (
            self._zem_setup_gate_altitude
            if self._zem_setup_gate_altitude is not None
            else max(
                0.0,
                float(trans.pos.y)
                - float(getattr(self, "eval_target_pos", Vector2(0.0, 0.0)).y),
            )
        )
        self._setup_phase_projected_dx = self._zem_setup_gate_projected_dx

    def setup(self, game, seed: int) -> None:
        self._resolved_eval_mode = self._mode_for_run()
        self._reset_phase_eval_metrics()

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

        self._setup_prev_pos = Vector2(trans.pos)
        tank = require_component(actor, FuelTank)
        self._setup_prev_fuel = float(tank.fuel)
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
        self._update_phase_metrics()
        if self._setup_phase_done:
            return
        snapshot = self._resolve_zem_snapshot(game)
        if isinstance(snapshot, dict):
            self._capture_zem_setup_gate(game, snapshot)

    def should_end(self, game) -> bool:
        if self._resolved_eval_mode == "focused" and self._setup_phase_done:
            return True
        return super().should_end(game)

    def end(self, game):
        result = super().end(game)

        setup_distance = self._setup_phase_distance
        setup_fuel = self._setup_phase_fuel_consumed
        setup_fuel_per_distance = (setup_fuel / setup_distance) if setup_distance > 1e-9 else 0.0
        setup_path_efficiency = None
        actor = self.world.actors[0]
        start_pos = getattr(actor, "start_pos", None)
        target_pos = getattr(self, "eval_target_pos", None)
        if isinstance(start_pos, Vector2) and isinstance(target_pos, Vector2) and setup_distance > 1e-9:
            straight_line = math.hypot(target_pos.x - start_pos.x, target_pos.y - start_pos.y)
            setup_path_efficiency = min(1.0, straight_line / setup_distance)

        result["eval_mode"] = self._resolved_eval_mode
        result["setup_phase_done"] = self._setup_phase_done
        result["setup_phase_time"] = self._setup_phase_time
        result["setup_phase_altitude"] = self._setup_phase_altitude
        result["setup_phase_projected_dx"] = self._setup_phase_projected_dx
        result["setup_phase_distance"] = setup_distance
        result["setup_phase_fuel_consumed"] = setup_fuel
        result["setup_phase_fuel_per_distance"] = setup_fuel_per_distance
        result["setup_phase_path_efficiency"] = setup_path_efficiency

        result["zem_setup_gate_done"] = self._zem_setup_gate_done
        result["zem_setup_gate_time"] = self._zem_setup_gate_time
        result["zem_setup_gate_altitude"] = self._zem_setup_gate_altitude
        result["zem_setup_gate_projected_dx"] = self._zem_setup_gate_projected_dx
        result["zem_terminal_gate_done"] = self._zem_terminal_gate_done
        result["zem_terminal_gate_time"] = self._zem_terminal_gate_time
        result["zem_terminal_gate_altitude"] = self._zem_terminal_gate_altitude
        result["zem_terminal_gate_projected_dx"] = self._zem_terminal_gate_projected_dx
        result["zem_solve_count"] = self._zem_solve_count
        result["zem_solve_ms_mean"] = self._zem_solve_ms_mean
        result["zem_solve_ms_p90"] = self._zem_solve_ms_p90
        result["zem_fallback_frames"] = self._zem_fallback_frames

        if self._resolved_eval_mode == "focused":
            success = bool(self._setup_phase_done)
            result["eval_phase"] = "zem_setup_gate"
            result["success"] = success
            state = str(result.get("state", "unknown"))
            result["failure_mode"] = "none" if success else state
        return result


def create_level() -> Level:
    return SetupLevel()
