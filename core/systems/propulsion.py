import math

from core.components import Engine, FuelTank, LanderState, Transform
from core.ecs import Entity, System


class PropulsionSystem(System):
    """Handles thrust, rotation slew, and fuel burn from engine targets."""

    def update(self, dt: float) -> None:
        if not self.world:
            return
        for entity in self.world.get_entities_with(Engine, FuelTank, Transform):
            self._update_entity(dt, entity)

    def _update_entity(self, dt: float, entity: Entity) -> None:
        engine = entity.get_component(Engine)
        tank = entity.get_component(FuelTank)
        trans = entity.get_component(Transform)
        state = entity.get_component(LanderState)
        if not engine or not tank or not trans:
            return

        if self._should_disable_thrust(state, tank):
            self._disable_engine(engine)
            return

        throttle_min, throttle_max, target = self._resolve_target_thrust(engine)
        self._slew_thrust(engine, target, throttle_min, throttle_max, dt)
        self._slew_rotation(engine, trans, dt)
        self._burn_fuel(engine, tank, dt)

    @staticmethod
    def _should_disable_thrust(state: LanderState | None, tank: FuelTank) -> bool:
        if state is not None and state.state in ("crashed", "out_of_fuel"):
            return True
        return tank.fuel <= 0.0

    @staticmethod
    def _disable_engine(engine: Engine) -> None:
        engine.thrust_level = 0.0
        engine.target_thrust = 0.0

    @staticmethod
    def _resolve_target_thrust(engine: Engine) -> tuple[float, float, float]:
        throttle_max = max(0.0, float(engine.max_thrust))
        throttle_min = max(0.0, min(float(engine.min_thrust), throttle_max))

        target = max(0.0, min(throttle_max, float(engine.target_thrust)))
        if target > 0.0:
            target = max(throttle_min, target)
            if engine.thrust_level <= 0.0 and throttle_min > 0.0:
                engine.thrust_level = throttle_min
        engine.target_thrust = target
        return throttle_min, throttle_max, target

    @staticmethod
    def _slew_thrust(
        engine: Engine,
        target: float,
        throttle_min: float,
        throttle_max: float,
        dt: float,
    ) -> None:
        _ = throttle_min
        delta_thrust = target - engine.thrust_level
        if delta_thrust > 0:
            step = engine.increase_rate * dt
            engine.thrust_level = min(
                throttle_max,
                engine.thrust_level + min(step, delta_thrust),
            )
            return
        if delta_thrust < 0:
            step = engine.decrease_rate * dt
            engine.thrust_level = max(0.0, engine.thrust_level - min(step, -delta_thrust))

    @staticmethod
    def _angle_diff(a: float, b: float) -> float:
        return (b - a + math.pi) % (2 * math.pi) - math.pi

    @classmethod
    def _slew_rotation(cls, engine: Engine, trans: Transform, dt: float) -> None:
        d_ang = cls._angle_diff(trans.rotation, engine.target_angle)
        max_step = engine.max_rotation_rate * dt
        ease_band = math.radians(15.0)

        step_mag = (
            max_step
            if abs(d_ang) >= ease_band
            else max_step * (abs(d_ang) / max(ease_band, 1e-6))
        )

        if abs(d_ang) <= step_mag:
            trans.rotation = engine.target_angle
            return
        trans.rotation += math.copysign(step_mag, d_ang)

    @staticmethod
    def _burn_fuel(engine: Engine, tank: FuelTank, dt: float) -> None:
        thrust = max(0.0, float(engine.thrust_level))
        if thrust <= 1.0:
            burn_multiplier = thrust
        else:
            over = thrust - 1.0
            burn_multiplier = thrust * (
                1.0 + over * max(0.0, float(engine.overdrive_burn_multiplier))
            )

        burn = max(0.0, float(engine.base_burn_rate)) * burn_multiplier * dt
        tank.fuel = max(0.0, tank.fuel - burn)
