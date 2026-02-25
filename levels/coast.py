from __future__ import annotations

import math
import random
from dataclasses import dataclass, replace
from typing import Any

from core.components import FuelTank, PhysicsState, Transform
from core.level import Level
from core.maths import Vector2
from core.ecs import require_component
from core.terrain import ballistic_fall_time
from levels.scenario_common import (
    ScenarioLevel,
    ScenarioLevelSpec,
    validate_scenario_recoverability,
)


@dataclass(frozen=True)
class CoastScenario:
    name: str
    spawn_clearance: float
    start_x: float
    trajectory_error: float = 0.0
    initial_vx_toward_target: float | None = None
    initial_vy_up: float = 0.0
    initial_angle: float = 0.0
    cargo_mass: float = 1800.0


@dataclass(frozen=True)
class _BallisticProfile:
    name: str
    spawn_clearance: float
    start_x: float
    initial_vy_up: float = 0.0


@dataclass(frozen=True)
class _TrajectoryErrorTier:
    key: str
    trajectory_error: float


@dataclass(frozen=True)
class _ScenarioCell:
    profile: str
    error_tier: str
    scenario: CoastScenario


_BALLISTIC_PROFILES: tuple[_BallisticProfile, ...] = (
    _BallisticProfile(name="glide_short", spawn_clearance=220.0, start_x=120.0),
    _BallisticProfile(name="glide_mid", spawn_clearance=420.0, start_x=320.0),
    _BallisticProfile(name="glide_long", spawn_clearance=900.0, start_x=900.0),
    _BallisticProfile(
        name="flat",
        spawn_clearance=650.0,
        start_x=760.0,
        initial_vy_up=10.0,
    ),
)
_ERROR_TIERS: tuple[_TrajectoryErrorTier, ...] = (
    _TrajectoryErrorTier(key="none", trajectory_error=0.0),
    _TrajectoryErrorTier(key="normal", trajectory_error=20.0),
    _TrajectoryErrorTier(key="stress", trajectory_error=28.0),
)
_PROFILE_ERROR_TIERS: dict[str, tuple[str, ...]] = {
    "glide_short": ("none", "normal"),
    "glide_mid": ("none", "normal"),
    "glide_long": ("none", "normal", "stress"),
    "flat": ("none", "normal", "stress"),
}
_ERROR_TIER_BY_KEY = {tier.key: tier for tier in _ERROR_TIERS}


def _scenario_name(profile: str, error_tier: str) -> str:
    if error_tier == "none":
        return profile
    if error_tier == "normal":
        return f"{profile}_correction"
    if error_tier == "stress":
        return f"{profile}_stress_correction"
    raise ValueError(f"Unknown coast error tier '{error_tier}'")


_BASE_CELLS: tuple[_ScenarioCell, ...] = tuple(
    _ScenarioCell(
        profile=profile.name,
        error_tier=tier_key,
        scenario=CoastScenario(
            name=_scenario_name(profile.name, tier_key),
            spawn_clearance=profile.spawn_clearance,
            start_x=profile.start_x,
            trajectory_error=_ERROR_TIER_BY_KEY[tier_key].trajectory_error,
            initial_vy_up=profile.initial_vy_up,
        ),
    )
    for profile in _BALLISTIC_PROFILES
    for tier_key in _PROFILE_ERROR_TIERS[profile.name]
)
_BASE_SCENARIOS: tuple[CoastScenario, ...] = tuple(cell.scenario for cell in _BASE_CELLS)
_HANDOFF_SCENARIOS: tuple[CoastScenario, ...] = (
    # Ferry high-energy setup mirrors (pre-handoff): very large offset and high |vx|.
    CoastScenario(
        name="handoff_extreme",
        spawn_clearance=260.0,
        start_x=1200.0,
        initial_vx_toward_target=108.0,
        initial_vy_up=34.0,
        cargo_mass=0.0,
    ),
    CoastScenario(
        name="handoff_extreme_fast",
        spawn_clearance=240.0,
        start_x=1320.0,
        initial_vx_toward_target=116.0,
        initial_vy_up=30.0,
        cargo_mass=0.0,
    ),
)
_CARGO_VARIANTS: tuple[tuple[str, float], ...] = (
    ("cargo_high", 4500.0),
)
_CARGO_VARIANT_BASES: tuple[str, ...] = (
    tuple(
        cell.scenario.name
        for cell in _BASE_CELLS
        if cell.profile in {"glide_mid", "glide_long"} and cell.error_tier in {"normal", "stress"}
    )
)
_SCENARIOS: tuple[CoastScenario, ...] = (
    _BASE_SCENARIOS
    + _HANDOFF_SCENARIOS
    + tuple(
        CoastScenario(
            name=f"{base.name}_{suffix}",
            spawn_clearance=base.spawn_clearance,
            start_x=base.start_x,
            trajectory_error=base.trajectory_error,
            initial_vx_toward_target=base.initial_vx_toward_target,
            initial_vy_up=base.initial_vy_up,
            initial_angle=base.initial_angle,
            cargo_mass=cargo_mass,
        )
        for base in _BASE_SCENARIOS
        if base.name in _CARGO_VARIANT_BASES
        for suffix, cargo_mass in _CARGO_VARIANTS
    )
)

_SCENARIO_BY_NAME = {item.name: item for item in _SCENARIOS}
_DEFAULT_SCENARIO = "glide_mid"
_QUICK_BENCHMARK_SCENARIOS: tuple[str, ...] = (
    "glide_mid",
    "glide_long_stress_correction",
    "handoff_extreme",
)
_COAST_EVAL_MODES: tuple[str, ...] = ("auto", "focused", "full")
_COAST_DEFAULT_EVAL_MODE = "full"

_COAST_SPAWN_OFFSET_MIN = 70.0
_COAST_SPAWN_OFFSET_MAX = 900.0
_COAST_SPAWN_OFFSET_PER_ALT = 1.0
_COAST_TRAJECTORY_ERROR_MIN = 0.0
_COAST_TRAJECTORY_ERROR_MAX = 36.0
_COAST_TRAJECTORY_ERROR_PER_ALT = 0.1


def _clamp_signed(value: float, magnitude_limit: float) -> float:
    limit = max(0.0, float(magnitude_limit))
    return max(-limit, min(limit, float(value)))


def _apply_coast_envelope(scenario: CoastScenario) -> CoastScenario:
    if scenario.initial_vx_toward_target is not None:
        # Hand-off mirror scenarios intentionally preserve extreme offsets/speeds.
        return scenario
    alt = max(0.0, float(scenario.spawn_clearance))
    offset_limit = min(
        _COAST_SPAWN_OFFSET_MAX,
        max(_COAST_SPAWN_OFFSET_MIN, _COAST_SPAWN_OFFSET_PER_ALT * alt),
    )
    error_limit = min(
        _COAST_TRAJECTORY_ERROR_MAX,
        max(_COAST_TRAJECTORY_ERROR_MIN, _COAST_TRAJECTORY_ERROR_PER_ALT * alt),
    )
    return replace(
        scenario,
        start_x=_clamp_signed(scenario.start_x, offset_limit),
        trajectory_error=_clamp_signed(scenario.trajectory_error, error_limit),
    )


def _make_spec(scenario: CoastScenario) -> ScenarioLevelSpec:
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


class CoastLevel(ScenarioLevel):
    default_bot_name = "coast"

    def __init__(self) -> None:
        super().__init__()
        self._eval_scenario_name = _DEFAULT_SCENARIO
        self._eval_mode_name = "auto"
        self._resolved_eval_mode = _COAST_DEFAULT_EVAL_MODE
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
            raise ValueError(f"Unknown coast scenario '{name}'. Expected one of: {known}")
        self._eval_scenario_name = key

    def set_eval_mode(self, name: str) -> None:
        key = str(name).strip().lower()
        if key not in _COAST_EVAL_MODES:
            known = ", ".join(_COAST_EVAL_MODES)
            raise ValueError(f"Unknown coast eval mode '{name}'. Expected one of: {known}")
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
        scenario_base = _apply_coast_envelope(_SCENARIO_BY_NAME[self._eval_scenario_name])
        scenario_name_hash = sum(ord(ch) for ch in scenario_base.name)
        dir_rng = random.Random(seed ^ (scenario_name_hash << 1))
        err_rng = random.Random(seed ^ (scenario_name_hash << 2))
        direction = -1.0 if dir_rng.random() < 0.5 else 1.0
        trajectory_error_sign = -1.0 if err_rng.random() < 0.5 else 1.0
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
        if scenario.initial_vx_toward_target is not None:
            initial_vx = -direction * abs(float(scenario.initial_vx_toward_target))
        else:
            vx_ballistic = dx / t_fall
            error_distance = trajectory_error_sign * abs(float(scenario.trajectory_error))
            vx_error = error_distance / t_fall
            initial_vx = vx_ballistic + vx_error
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
            success = bool(self._phase1_handoff_done)
            result["eval_phase"] = "coast_setup"
            result["success"] = success
            result["failure_mode"] = "none" if success else state
        return result


def create_level() -> Level:
    return CoastLevel()
