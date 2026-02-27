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
class CoastScenario:
    name: str
    base_angle_deg: float
    projected_dx_error: float | SampleRange
    radius: float | SampleRange = SampleRange(700.0, 900.0)
    angle_deviation_deg: float | SampleRange = SampleRange(-5.0, 5.0)
    target_flight_time_s: float | SampleRange = SampleRange(10.0, 12.0)
    initial_angle: float = 0.0
    cargo_mass: float = 1800.0


@dataclass(frozen=True)
class _DeviationTier:
    key: str
    projected_dx_error: SampleRange


_ANGLE_PROFILES: tuple[tuple[str, float], ...] = (
    ("shallow", 15.0),
    ("mid", 45.0),
    ("steep", 75.0),
)
_DEVIATION_TIERS: tuple[_DeviationTier, ...] = (
    _DeviationTier(key="low", projected_dx_error=SampleRange(40.0, 60.0)),
    _DeviationTier(key="high", projected_dx_error=SampleRange(80.0, 100.0)),
)


def _angle_from_velocity(vx: float, vy_up: float, *, opposite: bool = False) -> float:
    vel_x = -float(vx) if opposite else float(vx)
    vel_y = -float(vy_up) if opposite else float(vy_up)
    if abs(vel_x) <= 1e-6 and abs(vel_y) <= 1e-6:
        return 0.0
    return math.atan2(vel_x, vel_y)


def _scenario_name(profile: str, tier: str) -> str:
    return f"entry_{profile}_{tier}"


def _build_entry(profile_name: str, angle_deg: float, tier: _DeviationTier) -> CoastScenario:
    return CoastScenario(
        name=_scenario_name(profile_name, tier.key),
        base_angle_deg=float(angle_deg),
        projected_dx_error=tier.projected_dx_error,
    )


_SCENARIOS: tuple[CoastScenario, ...] = tuple(
    _build_entry(profile_name, angle_deg, tier)
    for profile_name, angle_deg in _ANGLE_PROFILES
    for tier in _DEVIATION_TIERS
)

_SCENARIO_BY_NAME = {item.name: item for item in _SCENARIOS}
_DEFAULT_SCENARIO = "entry_mid_low"
_QUICK_BENCHMARK_SCENARIOS: tuple[str, ...] = (
    "entry_mid_low",
    "entry_mid_high",
    "entry_steep_high",
)
_COAST_EVAL_MODES: tuple[str, ...] = ("auto", "focused", "full")
_COAST_DEFAULT_EVAL_MODE = "full"
_FOCUSED_SUCCESS_PROJECTED_DX_MAX = 30.0

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
    default_bot_name = "coast"

    def __init__(self) -> None:
        super().__init__()
        self._eval_scenario_name = _DEFAULT_SCENARIO
        self._eval_mode_name = "auto"
        self._resolved_eval_mode = _COAST_DEFAULT_EVAL_MODE
        self.scenario = _make_spec(
            name=self._eval_scenario_name,
            start_dx=0.0,
            start_dy=800.0,
            cargo_mass=1800.0,
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
    def _resolve_coast_snapshot(game) -> dict[str, Any] | None:
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
            kind = snapshot.get("kind")
            if kind == "coast" or (kind is None and "handoff_done" in snapshot):
                return snapshot
        return None

    def _mode_for_run(self) -> str:
        if self._eval_mode_name == "auto":
            return _COAST_DEFAULT_EVAL_MODE
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
        self._phase1_handoff_x = None
        self._phase1_handoff_y = None
        self._phase1_handoff_dx = None
        self._phase1_handoff_altitude = None
        self._phase1_handoff_vx = None
        self._phase1_handoff_vy_up = None
        self._phase1_handoff_speed = None
        self._phase1_handoff_horizontal_speed = None
        self._phase1_handoff_abs_angle_deg = None
        self._phase1_handoff_on_track = None
        self._phase1_handoff_inside_target = None
        self._phase1_handoff_speed_ready = None
        self._phase1_handoff_descending = None
        self._phase1_handoff_t_fall_ready = None
        self._phase1_handoff_sensor_used = None
        self._phase1_handoff_vx_err = None
        self._phase1_handoff_t_fall = None

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
        angle_rad = self._to_optional_float(snapshot.get("angle_rad"))
        if angle_rad is None:
            angle_rad = float(trans.rotation)
        self._phase1_handoff_abs_angle_deg = abs(math.degrees(angle_rad))
        self._phase1_handoff_on_track = bool(snapshot.get("on_track"))
        self._phase1_handoff_inside_target = bool(snapshot.get("inside_target"))
        self._phase1_handoff_speed_ready = bool(snapshot.get("speed_ready"))
        self._phase1_handoff_descending = bool(snapshot.get("descending"))
        self._phase1_handoff_t_fall_ready = bool(snapshot.get("t_fall_ready"))
        self._phase1_handoff_sensor_used = bool(snapshot.get("sensor_used"))
        self._phase1_handoff_vx_err = self._to_optional_float(snapshot.get("vx_err"))
        self._phase1_handoff_t_fall = self._to_optional_float(snapshot.get("t_fall"))

    def setup(self, game, seed: int) -> None:
        self._resolved_eval_mode = self._mode_for_run()
        self._reset_phase_eval_metrics()
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
                engine.set_lander_velocity(
                    Vector2(initial_vx, initial_vy_up),
                    uid=actor.uid,
                )

        self._phase1_prev_pos = Vector2(trans.pos)
        tank = require_component(actor, FuelTank)
        self._phase1_prev_fuel = float(tank.fuel)
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
        self._update_phase_metrics()
        if self._phase1_handoff_done:
            return
        snapshot = self._resolve_coast_snapshot(game)
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
        start_pos = getattr(actor, "start_pos", None)
        target_pos = getattr(self, "eval_target_pos", None)
        if isinstance(start_pos, Vector2) and isinstance(target_pos, Vector2) and setup_distance > 1e-9:
            straight_line = math.hypot(target_pos.x - start_pos.x, target_pos.y - start_pos.y)
            setup_path_efficiency = min(1.0, straight_line / setup_distance)
        result["eval_mode"] = self._resolved_eval_mode
        result["coast_handoff_done"] = self._phase1_handoff_done
        result["coast_handoff_time"] = self._phase1_handoff_time
        result["coast_handoff_projected_dx"] = self._phase1_handoff_projected_dx
        result["coast_handoff_abs_projected_dx"] = (
            abs(self._phase1_handoff_projected_dx)
            if self._phase1_handoff_projected_dx is not None
            else None
        )
        result["coast_handoff_impact_x"] = self._phase1_handoff_impact_x
        result["coast_handoff_target_x"] = self._phase1_handoff_target_x
        result["coast_handoff_x"] = self._phase1_handoff_x
        result["coast_handoff_y"] = self._phase1_handoff_y
        result["coast_handoff_dx"] = self._phase1_handoff_dx
        result["coast_handoff_abs_dx"] = (
            abs(self._phase1_handoff_dx)
            if self._phase1_handoff_dx is not None
            else None
        )
        result["coast_handoff_altitude"] = self._phase1_handoff_altitude
        result["coast_handoff_vx"] = self._phase1_handoff_vx
        result["coast_handoff_vy_up"] = self._phase1_handoff_vy_up
        result["coast_handoff_speed"] = self._phase1_handoff_speed
        result["coast_handoff_horizontal_speed"] = self._phase1_handoff_horizontal_speed
        result["coast_handoff_abs_angle_deg"] = self._phase1_handoff_abs_angle_deg
        result["coast_handoff_on_track"] = self._phase1_handoff_on_track
        result["coast_handoff_inside_target"] = self._phase1_handoff_inside_target
        result["coast_handoff_speed_ready"] = self._phase1_handoff_speed_ready
        result["coast_handoff_descending"] = self._phase1_handoff_descending
        result["coast_handoff_t_fall_ready"] = self._phase1_handoff_t_fall_ready
        result["coast_handoff_sensor_used"] = self._phase1_handoff_sensor_used
        result["coast_handoff_vx_err"] = self._phase1_handoff_vx_err
        result["coast_handoff_t_fall"] = self._phase1_handoff_t_fall
        result["coast_setup_distance"] = setup_distance
        result["coast_setup_fuel_consumed"] = setup_fuel
        result["coast_setup_fuel_per_distance"] = fuel_per_distance
        result["coast_setup_path_efficiency"] = setup_path_efficiency
        if self._resolved_eval_mode == "focused":
            state = str(result.get("state", "unknown"))
            projected_dx_ok = (
                self._phase1_handoff_projected_dx is not None
                and abs(self._phase1_handoff_projected_dx) <= _FOCUSED_SUCCESS_PROJECTED_DX_MAX
            )
            success = bool(self._phase1_handoff_done) and bool(projected_dx_ok)
            result["eval_phase"] = "coast_setup"
            result["success"] = success
            result["coast_success_projected_dx_max"] = _FOCUSED_SUCCESS_PROJECTED_DX_MAX
            result["failure_mode"] = (
                "none"
                if success
                else ("projection_out_of_bounds" if self._phase1_handoff_done else state)
            )
        return result


def create_level() -> Level:
    return CoastLevel()
