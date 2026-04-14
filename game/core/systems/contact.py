import math

from game.core.ecs import System, Entity
from game.core.components import (
    ContactReport,
    Engine,
    FlightState,
    FuelTank,
    LanderGeometry,
    LanderState,
    LandingSiteEconomy,
    PhysicsState,
    Transform,
    Wallet,
)
from game.core.maths import Range1D, Vector2


class ContactSystem(System):
    """Post-physics: resolve contacts → landing or crash state transitions.

    Replaces Lander.resolve_contact() / _apply_landing() / _apply_crash().
    """

    _LANDING_NORMAL_MIN_Y = 0.65

    def __init__(self, engine, sites):
        super().__init__()
        self.engine = engine
        self.sites = sites

    def update(self, dt: float) -> None:
        if not self.world:
            return

        for entity in self.world.get_entities_with(
            LanderState, PhysicsState, Transform, FuelTank
        ):
            report = self.engine.get_contact_report(uid=entity.uid)
            self._resolve(entity, report, dt)

    def _resolve(self, entity: Entity, report: ContactReport, dt: float) -> None:
        ls = entity.get_component(LanderState)
        phys = entity.get_component(PhysicsState)
        trans = entity.get_component(Transform)
        if ls is None or phys is None or trans is None:
            return
        if ls.state != FlightState.FLYING:
            return

        geo = entity.get_component(LanderGeometry)
        half_w = (geo.width / 2.0) if geo is not None else 4.0
        half_h = (geo.height / 2.0) if geo is not None else 4.0

        site = None
        if self.sites is not None:
            nearby_sites = self.sites.get_sites(
                Range1D.from_center(trans.pos.x, half_w)
            )
            site = nearby_sites[0] if nearby_sites else None

        if site is not None and self._can_land_on_site(
            entity, site, half_w, half_h, dt, report=report
        ):
            self._apply_landing(entity, site, half_h)
            return

        if report.colliding and not self._is_landing_surface_contact(report):
            self._apply_crash(entity)
            return

        if self._is_unsafe_colliding_impact(report, ls.safe_landing_velocity):
            self._apply_crash(entity)
            return

        if site is not None and self._crossed_site_plane(
            entity, site, half_w, half_h, dt
        ):
            self._apply_crash(entity)
            return

        self._resolve_terrain_contact(
            entity, report, phys, trans, site, half_w, half_h, dt
        )

    @staticmethod
    def _impact_speed(report: ContactReport) -> float:
        speed = report.rel_speed
        if not math.isfinite(speed):
            return 0.0
        return speed

    def _is_unsafe_colliding_impact(
        self, report: ContactReport, safe_speed: float
    ) -> bool:
        # Use solver-reported impact speed so hard impacts cannot "escape" crash
        # classification due to an immediate upward rebound in the same frame.
        if not report.colliding:
            return False
        return self._impact_speed(report) >= safe_speed

    def _resolve_terrain_contact(
        self,
        entity: Entity,
        report: ContactReport,
        phys: PhysicsState,
        trans: Transform,
        site,
        half_w: float,
        half_h: float,
        dt: float,
    ) -> None:
        # Terrain contact path: colliding while descending resolves as terrain landing/crash.
        if not report.colliding or phys.vel.y > 0.0:
            return
        speed = phys.vel.length()
        ls = entity.get_component(LanderState)
        if ls is None:
            return
        angle_ok = self._upright_angle_error(trans.rotation) < ls.safe_landing_angle
        speed_ok = speed < ls.safe_landing_velocity

        if (
            angle_ok
            and speed_ok
            and site is not None
            and self._can_land_on_site(entity, site, half_w, half_h, dt, report=report)
        ):
            self._apply_landing(entity, site, half_h)
        else:
            self._apply_crash(entity)

    def _can_land_on_site(
        self,
        entity: Entity,
        site,
        half_w: float,
        half_h: float,
        dt: float,
        *,
        report: ContactReport | None = None,
    ) -> bool:
        ls = entity.get_component(LanderState)
        phys = entity.get_component(PhysicsState)
        trans = entity.get_component(Transform)
        if ls is None or phys is None or trans is None:
            return False

        if (
            report is not None
            and report.colliding
            and not self._is_landing_surface_contact(report)
        ):
            return False

        if abs(trans.pos.x - site.x) > (site.size * 0.5 + half_w):
            return False

        rel_vel = phys.vel - site.vel
        if rel_vel.y > 0.0:
            return False
        if self._upright_angle_error(trans.rotation) >= ls.safe_landing_angle:
            return False
        if rel_vel.length() >= ls.safe_landing_velocity:
            return False

        lander_bottom_y = trans.pos.y - half_h
        landing_band = max(2.0, abs(rel_vel.y) * max(dt, 1e-3) * 1.5 + 1.0)
        return abs(lander_bottom_y - site.y) <= landing_band

    def _is_landing_surface_contact(self, report: ContactReport) -> bool:
        normal = report.normal
        if not isinstance(normal, (tuple, list)) or len(normal) < 2:
            return False
        try:
            normal_y = float(normal[1])
        except (TypeError, ValueError):
            return False
        if not math.isfinite(normal_y):
            return False
        return abs(normal_y) >= self._LANDING_NORMAL_MIN_Y

    def _crossed_site_plane(
        self, entity: Entity, site, half_w: float, half_h: float, dt: float
    ) -> bool:
        """Detect downward crossing through a site plane between fixed updates."""
        phys = entity.get_component(PhysicsState)
        trans = entity.get_component(Transform)
        if phys is None or trans is None:
            return False
        if abs(trans.pos.x - site.x) > (site.size * 0.5 + half_w):
            return False

        rel_vel = phys.vel - site.vel
        if rel_vel.y >= 0.0:
            return False

        dt_safe = max(1e-3, float(dt))
        current_bottom = trans.pos.y - half_h
        prev_bottom = current_bottom - rel_vel.y * dt_safe
        # A small tolerance avoids edge jitter around the exact plane.
        tol = 0.5
        return prev_bottom >= site.y - tol and current_bottom <= site.y + tol

    @staticmethod
    def _upright_angle_error(angle: float) -> float:
        wrapped = (float(angle) + math.pi) % (2.0 * math.pi) - math.pi
        return abs(wrapped)

    def _freeze_entity(self, entity: Entity) -> None:
        freeze_fn = getattr(self.engine, "freeze", None)
        if callable(freeze_fn):
            freeze_fn(uid=entity.uid)

    def _apply_landing(self, entity: Entity, site, half_h: float) -> None:
        ls = entity.get_component(LanderState)
        phys = entity.get_component(PhysicsState)
        trans = entity.get_component(Transform)
        wallet = entity.get_component(Wallet)
        if ls is None or phys is None or trans is None:
            return

        ls.state = FlightState.LANDED
        phys.vel.update(0.0, 0.0)
        trans.rotation = 0.0

        trans.pos.y = site.y + half_h

        eng = entity.get_component(Engine)
        if eng is not None:
            eng.thrust_level = 0.0
            eng.target_thrust = 0.0
            eng.target_angle = 0.0

        award = 0.0
        if self.world is not None:
            site_entity = self.world.get_entity_by_id(site.uid)
            if site_entity is not None:
                econ = site_entity.get_component(LandingSiteEconomy)
                if econ is not None and not econ.visited:
                    award = econ.award
                    econ.visited = True
        if wallet is not None and award != 0.0:
            wallet.credits += award

        self._teleport_entity(entity, trans)
        self._freeze_entity(entity)

    def _apply_crash(self, entity: Entity) -> None:
        ls = entity.get_component(LanderState)
        if ls is None:
            return

        ls.state = FlightState.CRASHED

        eng = entity.get_component(Engine)
        if eng is not None:
            eng.thrust_level = 0.0
            eng.target_thrust = 0.0

        # Do NOT freeze or zero velocity here. The physics body keeps its
        # post-collision velocity (tangential slide + angular spin) and
        # EulerBackend continues to handle terrain collisions naturally
        # during the crash animation window. The entity is only frozen once
        # the pause menu appears (or when reset_actor() clears the state).

    def _teleport_entity(self, entity: Entity, trans: Transform, *, clear_angular: bool = True) -> None:
        self.engine.teleport(
            Vector2(trans.pos.x, trans.pos.y),
            angle=trans.rotation,
            clear_velocity=True,
            clear_angular=clear_angular,
            uid=entity.uid,
        )
