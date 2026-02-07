import math
from core.ecs import System, Entity
from core.components import Engine, FuelTank, Transform

class PropulsionSystem(System):
    """Handles thrust and rotation mechanics based on Engine state."""

    def update(self, dt: float) -> None:
        if not self.world:
            return

        # Operate on entities with Engine, FuelTank, and Transform
        entities = self.world.get_entities_with(Engine, FuelTank, Transform)
        for entity in entities:
            self._update_entity(dt, entity)

    def _update_entity(self, dt: float, entity: Entity) -> None:
        engine = entity.get_component(Engine)
        tank = entity.get_component(FuelTank)
        trans = entity.get_component(Transform)

        if not engine or not tank or not trans:
            return

        if tank.fuel <= 0.0:
            engine.thrust_level = 0.0
            return

        # 1. Thrust Slew (Smoothly approach target thrust)
        delta_thrust = engine.target_thrust - engine.thrust_level
        if delta_thrust > 0:
            step = engine.increase_rate * dt
            engine.thrust_level = min(1.0, engine.thrust_level + min(step, delta_thrust))
        elif delta_thrust < 0:
            step = engine.decrease_rate * dt
            engine.thrust_level = max(0.0, engine.thrust_level - min(step, -delta_thrust))

        # 2. Rotation Slew
        def _angle_diff(a: float, b: float) -> float:
            d = (b - a + math.pi) % (2 * math.pi) - math.pi
            return d

        d_ang = _angle_diff(trans.rotation, engine.target_angle)
        max_step = engine.max_rotation_rate * dt
        ease_band = math.radians(15.0)
        
        # Simple proportional control inside ease band
        step_mag = (
            max_step
            if abs(d_ang) >= ease_band
            else max_step * (abs(d_ang) / max(ease_band, 1e-6))
        )

        if abs(d_ang) <= step_mag:
            trans.rotation = engine.target_angle
        else:
            trans.rotation += math.copysign(step_mag, d_ang)

        # 3. Fuel Consumption
        # Burn is proportional to thrust level
        burn = tank.burn_rate * engine.thrust_level * dt
        tank.fuel = max(0.0, tank.fuel - burn)
