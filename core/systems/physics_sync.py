from core.ecs import System, Entity
from core.components import PhysicsState, Transform, Engine
from core.maths import Vector2
import math

class PhysicsSyncSystem(System):
    """Synchronizes PhysicsState components with the external physics engine.
    
    Also applies forces from Engines to the physics body.
    """
    
    def __init__(self, engine_adapter):
        super().__init__()
        self.engine_adapter = engine_adapter

    def update(self, dt: float) -> None:
        if not self.world:
            return

        # 1. Apply Forces (Engine -> Physics Engine)
        entities = self.world.get_entities_with(Engine, Transform)
        for entity in entities:
            self._apply_forces(entity)

        # 2. Sync State (Physics Engine -> PhysicsState/Transform)
        # Assuming the physics engine has stepped externally (or we step it here? Game loop currently steps it)
        # We'll assume Game loop steps physics, then we sync back.
        entities = self.world.get_entities_with(PhysicsState, Transform)
        for entity in entities:
            self._sync_from_physics(entity)

    def _apply_forces(self, entity: Entity) -> None:
        """Calculate and apply engine forces to the physics body."""
        engine = entity.get_component(Engine)
        trans = entity.get_component(Transform)
        
        if engine.thrust_level <= 0.0:
            return

        thrust = engine.thrust_level * engine.max_power
        # Force direction is typically 'up' in local space, which is (sin(r), cos(r)) in world?
        # Legacy Lander math:
        # fx = math.sin(rotation) * thrust
        # fy = math.cos(rotation) * thrust
        
        fx = math.sin(trans.rotation) * thrust
        fy = math.cos(trans.rotation) * thrust
        
        # Apply to physics engine
        # Note: In a real ECS we might have a BodyID component. 
        # Here we assume the engine_adapter knows about 'the lander' (single entity for now).
        # To support multiple entities, we'd need a BodyComponent mapping to Pymunk bodies.
        # functional approximation:
        self.engine_adapter.apply_force(Vector2(fx, fy))

    def _sync_from_physics(self, entity: Entity) -> None:
        """Read pose/velocity from physics engine and update components."""
        # Again, assuming single-body engine adapter for now
        pose, _angle = self.engine_adapter.get_pose()
        vel, _ang_vel = self.engine_adapter.get_velocity()
        
        trans = entity.get_component(Transform)
        phys = entity.get_component(PhysicsState)
        
        if trans:
            trans.pos = pose # Vector2 copy/assign
            # Rotation is currently authoritative in Transform for the 'SimpleLander' style,
            # but for physics-based rotation it should come from body.
            # Legacy Pymunk usage (in `core.physics.pymunk_impl`) might update rotation.
            # But `core/physics.py` `get_pose` only returns position (Vector2). 
            # Wait, `get_pose` in `EngineProtocol` return Vector2. 
            # Where does rotation come from?
            # In `game.py`: `lander.pos = vector_pose`, `lander.vel = vector_vel`.
            # Rotation seems to be managed by `lander.apply_controls` directly updating `rotation` attribute!
            # So rotation is KINEMATIC (controlled by user) not DYNAMIC (physics), at least in the main mode.
            pass

        if phys:
            phys.vel = vel
