from __future__ import annotations

import math
import random
from dataclasses import dataclass, replace
from typing import Any

from core.components import FuelTank, PhysicsState, Transform
from core.ecs import require_component
from core.level import Level
from core.maths import Vector2
from levels.scenario_common import (
    ScenarioLevel,
    ScenarioLevelSpec,
    validate_scenario_recoverability,
)


@dataclass(frozen=True)
class LaunchScenario:
    name: str
    angle_deg: float
    start_dx: float
    start_dy: float
    initial_angle: float = 0.0
    cargo_mass: float = 0.0


_SPAWN_RADIUS = 800.0
_ANGLE_PROFILES: tuple[tuple[str, float], ...] = (
    ("air_shallow", 15.0),
    ("air_mid", 45.0),
    ("air_steep", 75.0),
)


def _build_angle_scenario(name: str, angle_deg: float) -> LaunchScenario:
    angle_rad = math.radians(float(angle_deg))
    start_dx = _SPAWN_RADIUS * math.cos(angle_rad)
    start_dy = _SPAWN_RADIUS * math.sin(angle_rad)
    return LaunchScenario(
        name=name,
        angle_deg=float(angle_deg),
        start_dx=float(start_dx),
        start_dy=float(start_dy),
    )


_SCENARIOS: tuple[LaunchScenario, ...] = tuple(
    _build_angle_scenario(name, angle_deg) for name, angle_deg in _ANGLE_PROFILES
)
_SCENARIO_BY_NAME = {item.name: item for item in _SCENARIOS}
_DEFAULT_SCENARIO = "air_mid"
_QUICK_BENCHMARK_SCENARIOS: tuple[str, ...] = (
    "air_mid",
    "air_steep",
)
_LAUNCH_EVAL_MODES: tuple[str, ...] = ("auto", "focused", "full")
_LAUNCH_DEFAULT_EVAL_MODE = "full"


def _make_spec(scenario: LaunchScenario) -> ScenarioLevelSpec:
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


class LaunchLevel(ScenarioLevel):
    default_bot_name = "launch"

    def __init__(self) -> None:
        super().__init__()
        self._eval_scenario_name = _DEFAULT_SCENARIO
        self._eval_mode_name = "auto"
        self._resolved_eval_mode = _LAUNCH_DEFAULT_EVAL_MODE
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
            raise ValueError(f"Unknown launch scenario '{name}'. Expected one of: {known}")
        self._eval_scenario_name = key

    def set_eval_mode(self, name: str) -> None:
        key = str(name).strip().lower()
        if key not in _LAUNCH_EVAL_MODES:
            known = ", ".join(_LAUNCH_EVAL_MODES)
            raise ValueError(f"Unknown launch eval mode '{name}'. Expected one of: {known}")
        self._eval_mode_name = key

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
    def _resolve_launch_snapshot(game) -> dict[str, Any] | None:
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
            if snapshot.get("kind") == "launch" or "handoff_done" in snapshot:
                return snapshot
        return None

    def _mode_for_run(self) -> str:
        if self._eval_mode_name == "auto":
            return _LAUNCH_DEFAULT_EVAL_MODE
        return self._eval_mode_name

    def _reset_phase_eval_metrics(self) -> None:
        self._phase1_handoff_done = False
        self._phase1_handoff_time = None
        self._phase1_setup_distance = 0.0
        self._phase1_setup_fuel_consumed = 0.0
        self._phase1_prev_pos: Vector2 | None = None
        self._phase1_prev_fuel: float | None = None
        self._phase1_handoff_projected_dx = None
        self._phase1_handoff_impact_x = None
        self._phase1_handoff_target_x = None
        self._phase1_handoff_impact_error = None
        self._phase1_handoff_current_impact_x = None
        self._phase1_handoff_current_target_x = None
        self._phase1_handoff_current_impact_error = None
        self._phase1_handoff_abs_angle_deg = None
        self._phase1_handoff_x = None
        self._phase1_handoff_y = None
        self._phase1_handoff_dx = None
        self._phase1_handoff_altitude = None
        self._phase1_handoff_vx = None
        self._phase1_handoff_vy_up = None
        self._phase1_handoff_speed = None
        self._phase1_handoff_horizontal_speed = None
        self._phase1_handoff_on_track = None
        self._phase1_handoff_speed_ready = None
        self._phase1_handoff_not_falling_short = None
        self._phase1_handoff_centered = None
        self._phase1_handoff_inside_target = None

    def _update_phase_metrics(self) -> None:
        if self._phase1_handoff_done:
            return
        actor = self.world.actors[0]
        trans = require_component(actor, Transform)
        tank = require_component(actor, FuelTank)
        cur_pos = Vector2(trans.pos)
        cur_fuel = float(tank.fuel)
        if self._phase1_prev_pos is not None:
            self._phase1_setup_distance += math.hypot(
                cur_pos.x - self._phase1_prev_pos.x,
                cur_pos.y - self._phase1_prev_pos.y,
            )
        if self._phase1_prev_fuel is not None:
            self._phase1_setup_fuel_consumed += max(0.0, self._phase1_prev_fuel - cur_fuel)
        self._phase1_prev_pos = cur_pos
        self._phase1_prev_fuel = cur_fuel

    def _capture_handoff(self, game, snapshot: dict[str, Any]) -> None:
        if self._phase1_handoff_done:
            return
        actor = self.world.actors[0]
        trans = require_component(actor, Transform)
        self._phase1_handoff_done = True
        self._phase1_handoff_time = float(getattr(game, "_elapsed_time", 0.0))
        self._phase1_handoff_projected_dx = self._to_optional_float(snapshot.get("projected_dx"))
        self._phase1_handoff_impact_x = self._to_optional_float(snapshot.get("impact_x"))
        self._phase1_handoff_target_x = self._to_optional_float(snapshot.get("target_x"))
        self._phase1_handoff_impact_error = self._to_optional_float(snapshot.get("impact_error"))
        self._phase1_handoff_current_impact_x = self._to_optional_float(
            snapshot.get("current_impact_x")
        )
        self._phase1_handoff_current_target_x = self._to_optional_float(
            snapshot.get("current_target_x")
        )
        self._phase1_handoff_current_impact_error = self._to_optional_float(
            snapshot.get("current_impact_error")
        )
        if (
            self._phase1_handoff_impact_error is None
            and self._phase1_handoff_impact_x is not None
            and self._phase1_handoff_target_x is not None
        ):
            self._phase1_handoff_impact_error = abs(
                self._phase1_handoff_impact_x - self._phase1_handoff_target_x
            )
        if (
            self._phase1_handoff_current_impact_error is None
            and self._phase1_handoff_current_impact_x is not None
            and self._phase1_handoff_current_target_x is not None
        ):
            self._phase1_handoff_current_impact_error = abs(
                self._phase1_handoff_current_impact_x - self._phase1_handoff_current_target_x
            )
        angle_rad = self._to_optional_float(snapshot.get("angle_rad"))
        if angle_rad is None:
            angle_rad = float(trans.rotation)
        self._phase1_handoff_abs_angle_deg = abs(math.degrees(angle_rad))
        self._phase1_handoff_x = self._to_optional_float(snapshot.get("x"))
        self._phase1_handoff_y = self._to_optional_float(snapshot.get("y"))
        self._phase1_handoff_dx = self._to_optional_float(snapshot.get("dx"))
        self._phase1_handoff_altitude = self._to_optional_float(snapshot.get("altitude"))
        self._phase1_handoff_vx = self._to_optional_float(snapshot.get("vx"))
        self._phase1_handoff_vy_up = self._to_optional_float(snapshot.get("vy_up"))
        self._phase1_handoff_speed = self._to_optional_float(snapshot.get("speed"))
        self._phase1_handoff_horizontal_speed = self._to_optional_float(
            snapshot.get("horizontal_speed")
        )
        if (
            self._phase1_handoff_speed is None
            and self._phase1_handoff_vx is not None
            and self._phase1_handoff_vy_up is not None
        ):
            self._phase1_handoff_speed = math.hypot(
                self._phase1_handoff_vx,
                self._phase1_handoff_vy_up,
            )
        if (
            self._phase1_handoff_horizontal_speed is None
            and self._phase1_handoff_vx is not None
        ):
            self._phase1_handoff_horizontal_speed = abs(self._phase1_handoff_vx)
        self._phase1_handoff_on_track = bool(snapshot.get("on_track"))
        self._phase1_handoff_speed_ready = bool(snapshot.get("speed_ready"))
        self._phase1_handoff_not_falling_short = bool(snapshot.get("not_falling_short"))
        self._phase1_handoff_centered = bool(snapshot.get("centered"))
        self._phase1_handoff_inside_target = bool(snapshot.get("inside_target"))

    def setup(self, game, seed: int) -> None:
        self._resolved_eval_mode = self._mode_for_run()
        self._reset_phase_eval_metrics()
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
        target_pos = getattr(self, "eval_target_pos", Vector2(0.0, 0.0))
        trans = require_component(actor, Transform)
        phys = require_component(actor, PhysicsState)
        start_pos = Vector2(
            float(target_pos.x) + float(scenario.start_dx),
            float(target_pos.y) + float(scenario.start_dy),
        )
        trans.pos = Vector2(start_pos)
        actor.start_pos = Vector2(start_pos)

        validate_scenario_recoverability(
            actor,
            scenario_name=scenario.name,
            spawn_clearance=scenario.start_dy,
            initial_vy_up=0.0,
        )
        trans.rotation = float(scenario.initial_angle)
        initial_vx = 0.0
        initial_vy_up = 0.0
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

        self._phase1_prev_pos = Vector2(trans.pos)
        tank = require_component(actor, FuelTank)
        self._phase1_prev_fuel = float(tank.fuel)
        setattr(self, "scenario_name", scenario_base.name)

    def update(self, game, dt: float) -> None:
        _ = dt
        self._update_phase_metrics()
        if self._phase1_handoff_done:
            return
        snapshot = self._resolve_launch_snapshot(game)
        if not isinstance(snapshot, dict):
            return
        if bool(snapshot.get("handoff_done")):
            self._capture_handoff(game, snapshot)

    def should_end(self, game) -> bool:
        if self._resolved_eval_mode == "focused" and self._phase1_handoff_done:
            return True
        return super().should_end(game)

    def end(self, game):
        result = super().end(game)
        setup_distance = self._phase1_setup_distance
        setup_fuel = self._phase1_setup_fuel_consumed
        fuel_per_distance = (setup_fuel / setup_distance) if setup_distance > 1e-9 else 0.0
        setup_path_efficiency = None
        actor = self.world.actors[0]
        trans = require_component(actor, Transform)
        start_pos = getattr(actor, "start_pos", None)
        target_pos = getattr(self, "eval_target_pos", None)
        if isinstance(start_pos, Vector2) and isinstance(target_pos, Vector2) and setup_distance > 1e-9:
            straight_line = math.hypot(target_pos.x - start_pos.x, target_pos.y - start_pos.y)
            setup_path_efficiency = min(1.0, straight_line / setup_distance)
        if self._phase1_handoff_done and self._phase1_handoff_abs_angle_deg is None:
            self._phase1_handoff_abs_angle_deg = abs(math.degrees(float(trans.rotation)))

        result["eval_mode"] = self._resolved_eval_mode
        result["launch_handoff_done"] = self._phase1_handoff_done
        result["launch_handoff_time"] = self._phase1_handoff_time
        result["launch_handoff_projected_dx"] = self._phase1_handoff_projected_dx
        result["launch_handoff_impact_x"] = self._phase1_handoff_impact_x
        result["launch_handoff_target_x"] = self._phase1_handoff_target_x
        result["launch_handoff_impact_error"] = (
            self._phase1_handoff_current_impact_error
            if self._phase1_handoff_current_impact_error is not None
            else self._phase1_handoff_impact_error
        )
        result["launch_handoff_planned_impact_error"] = self._phase1_handoff_impact_error
        result["launch_handoff_current_impact_x"] = self._phase1_handoff_current_impact_x
        result["launch_handoff_current_target_x"] = self._phase1_handoff_current_target_x
        result["launch_handoff_abs_angle_deg"] = self._phase1_handoff_abs_angle_deg
        result["launch_handoff_x"] = self._phase1_handoff_x
        result["launch_handoff_y"] = self._phase1_handoff_y
        result["launch_handoff_dx"] = self._phase1_handoff_dx
        result["launch_handoff_abs_dx"] = (
            abs(self._phase1_handoff_dx)
            if self._phase1_handoff_dx is not None
            else None
        )
        result["launch_handoff_altitude"] = self._phase1_handoff_altitude
        result["launch_handoff_vx"] = self._phase1_handoff_vx
        result["launch_handoff_vy_up"] = self._phase1_handoff_vy_up
        result["launch_handoff_speed"] = self._phase1_handoff_speed
        result["launch_handoff_horizontal_speed"] = self._phase1_handoff_horizontal_speed
        result["launch_handoff_on_track"] = self._phase1_handoff_on_track
        result["launch_handoff_speed_ready"] = self._phase1_handoff_speed_ready
        result["launch_handoff_not_falling_short"] = self._phase1_handoff_not_falling_short
        result["launch_handoff_centered"] = self._phase1_handoff_centered
        result["launch_handoff_inside_target"] = self._phase1_handoff_inside_target
        result["launch_setup_distance"] = setup_distance
        result["launch_setup_fuel_consumed"] = setup_fuel
        result["launch_setup_fuel_per_distance"] = fuel_per_distance
        result["launch_setup_path_efficiency"] = setup_path_efficiency

        if self._resolved_eval_mode == "focused":
            state = str(result.get("state", "unknown"))
            success = bool(self._phase1_handoff_done)
            result["eval_phase"] = "launch_setup"
            result["success"] = success
            result["failure_mode"] = "none" if success else state
        return result


def create_level() -> Level:
    return LaunchLevel()
