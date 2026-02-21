from core.ecs import System, Entity
from core.components import LanderState, PhysicsState, Transform, FuelTank, Wallet
from core.maths import Range1D, Vector2


class ContactSystem(System):
    """Post-physics: resolve contacts → landing or crash state transitions.

    Replaces Lander.resolve_contact() / _apply_landing() / _apply_crash().
    """

    def __init__(self, engine_adapter, sites):
        super().__init__()
        self.engine_adapter = engine_adapter
        self.sites = sites

    def update(self, dt: float) -> None:
        if not self.world:
            return

        report = self.engine_adapter.get_contact_report()
        for entity in self.world.get_entities_with(LanderState, PhysicsState, Transform, FuelTank):
            self._resolve(entity, report, dt)

    def _resolve(self, entity: Entity, report: dict, dt: float) -> None:
        ls = entity.get_component(LanderState)
        phys = entity.get_component(PhysicsState)
        trans = entity.get_component(Transform)
        if ls is None or phys is None or trans is None:
            return
        if ls.state != "flying":
            return

        from core.components import LanderGeometry
        geo = entity.get_component(LanderGeometry)
        half_w = (geo.width / 2.0) if geo is not None else 4.0
        half_h = (geo.height / 2.0) if geo is not None else 4.0

        site = None
        if self.sites is not None:
            nearby_sites = self.sites.get_sites(Range1D.from_center(trans.pos.x, half_w))
            site = nearby_sites[0] if nearby_sites else None

        if site is not None and self._can_land_on_site(entity, site, half_w, half_h, dt):
            self._apply_landing(entity, site, half_h)
            return

        # Terrain contact path: colliding while descending resolves as terrain landing/crash.
        if not report.get("colliding") or phys.vel.y > 0.0:
            return

        speed = phys.vel.length()
        angle_ok = abs(trans.rotation) < ls.safe_landing_angle
        speed_ok = speed < ls.safe_landing_velocity

        if angle_ok and speed_ok and site is not None:
            self._apply_landing(entity, site, half_h)
        else:
            self._apply_crash(entity)

    def _can_land_on_site(
        self, entity: Entity, site, half_w: float, half_h: float, dt: float
    ) -> bool:
        ls = entity.get_component(LanderState)
        phys = entity.get_component(PhysicsState)
        trans = entity.get_component(Transform)
        if ls is None or phys is None or trans is None:
            return False

        if abs(trans.pos.x - site.x) > (site.size * 0.5 + half_w):
            return False

        rel_vel = phys.vel - site.vel
        if rel_vel.y > 0.0:
            return False
        if abs(trans.rotation) >= ls.safe_landing_angle:
            return False
        if rel_vel.length() >= ls.safe_landing_velocity:
            return False

        lander_bottom_y = trans.pos.y - half_h
        landing_band = max(2.0, abs(rel_vel.y) * max(dt, 1e-3) * 1.5 + 1.0)
        return abs(lander_bottom_y - site.y) <= landing_band

    def _apply_landing(self, entity: Entity, site, half_h: float) -> None:
        ls = entity.get_component(LanderState)
        phys = entity.get_component(PhysicsState)
        trans = entity.get_component(Transform)
        wallet = entity.get_component(Wallet)
        if ls is None or phys is None or trans is None:
            return

        ls.state = "landed"
        phys.vel.update(0.0, 0.0)
        trans.rotation = 0.0

        # Snap position to the site plane.
        trans.pos.y = site.y + half_h

        # Zero out engine intent
        from core.components import Engine
        eng = entity.get_component(Engine)
        if eng is not None:
            eng.thrust_level = 0.0
            eng.target_thrust = 0.0
            eng.target_angle = 0.0

        # Award credits and mark site visited.
        award = 0.0
        if self.world is not None:
            from core.components import LandingSiteEconomy
            site_entity = self.world.get_entity_by_id(site.uid)
            if site_entity is not None:
                econ = site_entity.get_component(LandingSiteEconomy)
                if econ is not None and not econ.visited and econ.award != 0.0:
                    award = econ.award
                    econ.visited = True
        if wallet is not None and award != 0.0:
            wallet.credits += award

        if self.engine_adapter.enabled:
            self.engine_adapter.teleport_lander(
                Vector2(trans.pos.x, trans.pos.y),
                angle=trans.rotation,
                clear_velocity=True,
            )

    def _apply_crash(self, entity: Entity) -> None:
        ls = entity.get_component(LanderState)
        phys = entity.get_component(PhysicsState)
        if ls is None or phys is None:
            return

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
                    Vector2(trans.pos.x, trans.pos.y),
                    angle=trans.rotation,
                    clear_velocity=True,
                )
