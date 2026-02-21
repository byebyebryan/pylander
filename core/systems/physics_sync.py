from core.ecs import System, Entity
from core.components import PhysicsState, Transform


class PhysicsSyncSystem(System):
    """Post-physics: sync position and velocity FROM the physics engine into components.

    Called after engine_adapter.step() so it always reads the freshly integrated state.
    Rotation is intentionally NOT synced here: rotation is kinematic, driven by
    PropulsionSystem (authoritative) and pushed to the physics body by ForceApplicationSystem.
    """

    def __init__(self, engine_adapter):
        super().__init__()
        self.engine_adapter = engine_adapter

    def update(self, dt: float) -> None:
        if not self.world:
            return

        for entity in self.world.get_entities_with(PhysicsState, Transform):
            self._sync_from_physics(entity)

    def _sync_from_physics(self, entity: Entity) -> None:
        """Read pose/velocity from physics engine and update components."""
        pose, _angle = self.engine_adapter.get_pose()
        vel, _ang_vel = self.engine_adapter.get_velocity()

        trans = entity.get_component(Transform)
        phys = entity.get_component(PhysicsState)

        if trans:
            trans.pos = pose

        if phys:
            phys.vel = vel
