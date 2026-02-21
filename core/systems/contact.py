from core.ecs import System, Entity
from core.components import LanderState, PhysicsState, Transform, FuelTank, Wallet


class ContactSystem(System):
    """Post-physics: resolve contacts → landing or crash state transitions.

    Replaces Lander.resolve_contact() / _apply_landing() / _apply_crash().
    """

    def __init__(self, engine_adapter, targets):
        super().__init__()
        self.engine_adapter = engine_adapter
        self.targets = targets

    def update(self, dt: float) -> None:
        if not self.world:
            return

        report = self.engine_adapter.get_contact_report()
        for entity in self.world.get_entities_with(LanderState, PhysicsState, Transform, FuelTank):
            self._resolve(entity, report)

    def _resolve(self, entity: Entity, report: dict) -> None:
        ls = entity.get_component(LanderState)
        phys = entity.get_component(PhysicsState)
        trans = entity.get_component(Transform)

        # Only resolve when flying, actively colliding, and moving downward
        if ls.state != "flying" or not report.get("colliding") or phys.vel.y > 0.0:
            return

        speed = phys.vel.length()
        angle_ok = abs(trans.rotation) < ls.safe_landing_angle
        speed_ok = speed < ls.safe_landing_velocity

        target = None
        if self.targets is not None:
            from core.components import LanderGeometry
            geo = entity.get_component(LanderGeometry)
            half_w = (geo.width / 2.0) if geo is not None else 4.0
            nearby = self.targets.get_targets(trans.pos.x, half_w)
            target = nearby[0] if nearby else None

        if angle_ok and speed_ok and target is not None:
            self._apply_landing(entity, target)
        else:
            self._apply_crash(entity)

    def _apply_landing(self, entity: Entity, target) -> None:
        ls = entity.get_component(LanderState)
        phys = entity.get_component(PhysicsState)
        trans = entity.get_component(Transform)
        tank = entity.get_component(FuelTank)
        wallet = entity.get_component(Wallet)

        ls.state = "landed"
        phys.vel.update(0.0, 0.0)
        trans.rotation = 0.0

        # Snap position to platform surface
        # Height is stored in LanderGeometry; read it from the entity if available
        from core.components import LanderGeometry
        geo = entity.get_component(LanderGeometry)
        half_h = geo.height / 2.0 if geo is not None else 4.0
        trans.pos.y = target.y + half_h

        # Zero out engine intent
        from core.components import Engine
        eng = entity.get_component(Engine)
        if eng is not None:
            eng.thrust_level = 0.0
            eng.target_thrust = 0.0
            eng.target_angle = 0.0

        # Award credits
        award = target.info.get("award", 0) if getattr(target, "info", None) else 0
        if wallet is not None and award != 0:
            wallet.credits += award
        if getattr(target, "info", None) is not None:
            target.info["award"] = 0

        if self.engine_adapter.enabled:
            self.engine_adapter.teleport_lander(
                (trans.pos.x, trans.pos.y),
                angle=trans.rotation,
                clear_velocity=True,
            )

    def _apply_crash(self, entity: Entity) -> None:
        ls = entity.get_component(LanderState)
        phys = entity.get_component(PhysicsState)

        ls.state = "crashed"
        phys.vel.update(0.0, 0.0)

        from core.components import Engine
        eng = entity.get_component(Engine)
        if eng is not None:
            eng.thrust_level = 0.0
            eng.target_thrust = 0.0

        if self.engine_adapter.enabled:
            trans = entity.get_component(Transform)
            if trans is not None:
                self.engine_adapter.teleport_lander(
                    (trans.pos.x, trans.pos.y),
                    angle=trans.rotation,
                    clear_velocity=True,
                )
