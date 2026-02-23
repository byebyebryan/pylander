from __future__ import annotations

import random
from dataclasses import dataclass, replace

from core.components import CargoHold, Engine, FuelTank, PhysicsState, Transform
from core.level import Level
from core.maths import Vector2
from levels.scenario_common import ScenarioLevel, ScenarioLevelSpec, _require_component


@dataclass(frozen=True)
class DriftScenario:
    name: str
    spawn_clearance: float
    start_x: float
    initial_vx: float = 0.0
    initial_vy_up: float = 0.0
    initial_angle: float = 0.0
    cargo_mass: float = 1800.0


_BASE_SCENARIOS: tuple[DriftScenario, ...] = (
    DriftScenario(name="alt_100_offset", spawn_clearance=100.0, start_x=100.0),
    DriftScenario(name="alt_400_offset", spawn_clearance=400.0, start_x=180.0),
    DriftScenario(name="alt_1600_offset", spawn_clearance=1600.0, start_x=300.0),
    DriftScenario(
        name="alt_400_offset_vx_toward",
        spawn_clearance=400.0,
        start_x=180.0,
        initial_vx=-8.0,
    ),
    DriftScenario(
        name="alt_400_offset_vx_away",
        spawn_clearance=400.0,
        start_x=180.0,
        initial_vx=8.0,
    ),
)
_CARGO_VARIANTS: tuple[tuple[str, float], ...] = (
    ("cargo_low", 0.0),
    ("cargo_high", 4500.0),
)
_CARGO_VARIANT_BASES: tuple[str, ...] = (
    "alt_400_offset",
    "alt_400_offset_vx_away",
)
_SCENARIOS: tuple[DriftScenario, ...] = (
    _BASE_SCENARIOS
    + tuple(
        DriftScenario(
            name=f"{base.name}_{suffix}",
            spawn_clearance=base.spawn_clearance,
            start_x=base.start_x,
            initial_vx=base.initial_vx,
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
_DEFAULT_SCENARIO = "alt_400_offset"

_DRIFT_CONE_OFFSET_MIN = 70.0
_DRIFT_CONE_OFFSET_MAX = 280.0
_DRIFT_CONE_OFFSET_PER_ALT = 0.35
_DRIFT_CONE_SPEED_MIN = 3.5
_DRIFT_CONE_SPEED_MAX = 9.0
_DRIFT_CONE_SPEED_PER_ALT = 0.015


def _clamp_signed(value: float, magnitude_limit: float) -> float:
    limit = max(0.0, float(magnitude_limit))
    return max(-limit, min(limit, float(value)))


def _apply_drift_envelope(scenario: DriftScenario) -> DriftScenario:
    alt = max(0.0, float(scenario.spawn_clearance))
    offset_limit = min(
        _DRIFT_CONE_OFFSET_MAX,
        max(_DRIFT_CONE_OFFSET_MIN, _DRIFT_CONE_OFFSET_PER_ALT * alt),
    )
    speed_limit = min(
        _DRIFT_CONE_SPEED_MAX,
        max(_DRIFT_CONE_SPEED_MIN, _DRIFT_CONE_SPEED_PER_ALT * alt),
    )
    return replace(
        scenario,
        start_x=_clamp_signed(scenario.start_x, offset_limit),
        initial_vx=_clamp_signed(scenario.initial_vx, speed_limit),
    )


def _make_spec(scenario: DriftScenario) -> ScenarioLevelSpec:
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


def _validate_recoverability(actor, scenario: DriftScenario) -> None:
    phys = _require_component(actor, PhysicsState)
    tank = _require_component(actor, FuelTank)
    engine = _require_component(actor, Engine)
    cargo = actor.get_component(CargoHold)

    cargo_mass = 0.0
    if cargo is not None:
        cargo_mass = max(0.0, min(float(cargo.cargo_mass), float(cargo.max_cargo_mass)))
    total_mass = max(
        0.5,
        float(phys.mass) + float(tank.fuel) * float(tank.density) + cargo_mass,
    )
    max_up_acc = (float(engine.max_power) * float(engine.max_thrust) / total_mass) - 9.8
    if max_up_acc <= 1e-6:
        raise ValueError(f"Scenario '{scenario.name}' is unrecoverable: no upward acceleration")

    downward_speed = max(0.0, -float(scenario.initial_vy_up))
    stop_distance = (downward_speed * downward_speed) / (2.0 * max_up_acc)
    safety_margin = max(8.0, scenario.spawn_clearance * 0.18)
    usable_altitude = max(0.0, scenario.spawn_clearance - safety_margin)

    if stop_distance > usable_altitude:
        raise ValueError(
            f"Scenario '{scenario.name}' is unrecoverable: "
            f"stop_distance={stop_distance:.2f} usable_altitude={usable_altitude:.2f}"
        )


class DriftLevel(ScenarioLevel):
    default_bot_name = "drift"

    def __init__(self) -> None:
        super().__init__()
        self._eval_scenario_name = _DEFAULT_SCENARIO
        self.scenario = _make_spec(_SCENARIO_BY_NAME[self._eval_scenario_name])

    @staticmethod
    def list_batch_scenarios() -> list[str]:
        return [item.name for item in _SCENARIOS]

    def set_eval_scenario(self, name: str) -> None:
        key = str(name).strip().lower()
        if key not in _SCENARIO_BY_NAME:
            known = ", ".join(sorted(_SCENARIO_BY_NAME))
            raise ValueError(f"Unknown drift scenario '{name}'. Expected one of: {known}")
        self._eval_scenario_name = key

    def setup(self, game, seed: int) -> None:
        scenario_base = _apply_drift_envelope(_SCENARIO_BY_NAME[self._eval_scenario_name])
        dir_rng = random.Random(seed ^ (sum(ord(ch) for ch in scenario_base.name) << 1))
        direction = -1.0 if dir_rng.random() < 0.5 else 1.0
        scenario = replace(
            scenario_base,
            start_x=float(scenario_base.start_x) * direction,
            initial_vx=float(scenario_base.initial_vx) * direction,
        )
        self.scenario = _make_spec(scenario)
        super().setup(game, seed)

        actor = self.world.actors[0]
        _validate_recoverability(actor, scenario)

        trans = _require_component(actor, Transform)
        phys = _require_component(actor, PhysicsState)
        trans.rotation = float(scenario.initial_angle)
        phys.vel = Vector2(float(scenario.initial_vx), float(scenario.initial_vy_up))

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
                    Vector2(float(scenario.initial_vx), float(scenario.initial_vy_up)),
                    uid=actor.uid,
                )

        setattr(self, "scenario_name", scenario_base.name)


def create_level() -> Level:
    return DriftLevel()
