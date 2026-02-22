from __future__ import annotations

from dataclasses import dataclass

from core.components import Engine, FuelTank, PhysicsState, Transform
from core.level import Level
from core.maths import Vector2
from levels.scenario_common import ScenarioLevel, ScenarioLevelSpec, _require_component


@dataclass(frozen=True)
class DescentAttitude:
    name: str
    spawn_clearance: float
    initial_vx: float = 0.0
    initial_vy_up: float = 0.0
    initial_angle: float = 0.0


_ATTITUDES: tuple[DescentAttitude, ...] = (
    DescentAttitude(name="vertical_low", spawn_clearance=70.0),
    DescentAttitude(name="vertical_mid_a", spawn_clearance=105.0),
    DescentAttitude(name="vertical_mid_b", spawn_clearance=155.0),
    DescentAttitude(name="vertical_high", spawn_clearance=220.0),
    DescentAttitude(name="vertical_speed", spawn_clearance=105.0, initial_vy_up=-16.0),
)

_ATTITUDE_BY_NAME = {item.name: item for item in _ATTITUDES}
_DEFAULT_ATTITUDE = "vertical_mid_a"


def _make_spec(attitude: DescentAttitude) -> ScenarioLevelSpec:
    return ScenarioLevelSpec(
        name=attitude.name,
        start_x=0.0,
        target_x=0.0,
        spawn_clearance=attitude.spawn_clearance,
        terrain_kind="flat",
        target_mode="flush_flatten",
        target_offset_y=0.0,
        target_size=110.0,
    )


def _validate_recoverability(actor, attitude: DescentAttitude) -> None:
    phys = _require_component(actor, PhysicsState)
    tank = _require_component(actor, FuelTank)
    engine = _require_component(actor, Engine)

    total_mass = max(0.5, float(phys.mass) + float(tank.fuel) * float(tank.density))
    max_up_acc = (float(engine.max_power) / total_mass) - 9.8
    if max_up_acc <= 1e-6:
        raise ValueError(f"Attitude '{attitude.name}' is unrecoverable: no upward acceleration")

    downward_speed = max(0.0, -float(attitude.initial_vy_up))
    stop_distance = (downward_speed * downward_speed) / (2.0 * max_up_acc)
    safety_margin = max(8.0, attitude.spawn_clearance * 0.18)
    usable_altitude = max(0.0, attitude.spawn_clearance - safety_margin)

    if stop_distance > usable_altitude:
        raise ValueError(
            f"Attitude '{attitude.name}' is unrecoverable: "
            f"stop_distance={stop_distance:.2f} usable_altitude={usable_altitude:.2f}"
        )


class DescentLevel(ScenarioLevel):
    default_bot_name = "descent"

    def __init__(self) -> None:
        super().__init__()
        self._eval_attitude_name = _DEFAULT_ATTITUDE
        self.scenario = _make_spec(_ATTITUDE_BY_NAME[self._eval_attitude_name])

    @staticmethod
    def list_batch_attitudes() -> list[str]:
        return [item.name for item in _ATTITUDES]

    def set_eval_attitude(self, name: str) -> None:
        key = str(name).strip().lower()
        if key not in _ATTITUDE_BY_NAME:
            known = ", ".join(sorted(_ATTITUDE_BY_NAME))
            raise ValueError(f"Unknown descent attitude '{name}'. Expected one of: {known}")
        self._eval_attitude_name = key

    def setup(self, game, seed: int) -> None:
        attitude = _ATTITUDE_BY_NAME[self._eval_attitude_name]
        self.scenario = _make_spec(attitude)
        super().setup(game, seed)

        actor = self.world.actors[0]
        _validate_recoverability(actor, attitude)

        trans = _require_component(actor, Transform)
        phys = _require_component(actor, PhysicsState)
        trans.rotation = float(attitude.initial_angle)
        phys.vel = Vector2(float(attitude.initial_vx), float(attitude.initial_vy_up))

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
                    Vector2(float(attitude.initial_vx), float(attitude.initial_vy_up)),
                    uid=actor.uid,
                )

        setattr(self, "scenario_name", attitude.name)


def create_level() -> Level:
    return DescentLevel()

