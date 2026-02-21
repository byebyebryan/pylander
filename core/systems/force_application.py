import math
from core.ecs import System, Entity
from core.components import Engine, Transform
from core.maths import Vector2


class ForceApplicationSystem(System):
    """Pre-physics: push Engine forces and rotation override to the physics body."""

    def __init__(self, engine_adapter):
        super().__init__()
        self.engine_adapter = engine_adapter

    def update(self, dt: float) -> None:
        if not self.world:
            return

        for entity in self.world.get_entities_with(Engine, Transform):
            self._apply_forces(entity)
            self._apply_rotation_override(entity)

    def _apply_forces(self, entity: Entity) -> None:
        """Calculate and apply engine thrust force to the physics body."""
        engine = entity.get_component(Engine)
        trans = entity.get_component(Transform)

        if engine.thrust_level <= 0.0:
            return

        thrust = engine.thrust_level * engine.max_power
        fx = math.sin(trans.rotation) * thrust
        fy = math.cos(trans.rotation) * thrust
        force = Vector2(fx, fy)
        if hasattr(self.engine_adapter, "apply_force_for"):
            self.engine_adapter.apply_force_for(entity.uid, force)
        else:
            self.engine_adapter.apply_force(force)

    def _apply_rotation_override(self, entity: Entity) -> None:
        """Push current rotation to the physics body (kinematic override)."""
        trans = entity.get_component(Transform)
        # Rotation is kinematically driven by PropulsionSystem; we tell the
        # physics engine the current angle so the collision shape stays in sync.
        if hasattr(self.engine_adapter, "override_for"):
            self.engine_adapter.override_for(entity.uid, trans.rotation)
        else:
            self.engine_adapter.override(trans.rotation)
