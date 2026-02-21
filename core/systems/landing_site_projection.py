from __future__ import annotations

from core.components import (
    KinematicMotion,
    LandingSite,
    LandingSiteEconomy,
    PhysicsState,
    SiteAttachment,
    Transform,
)
from core.ecs import System
from core.landing_sites import LandingSiteSurfaceModel, to_view
from core.maths import Vector2


class LandingSiteProjectionSystem(System):
    """Build landing-site read projections from ECS state."""

    def __init__(self, surface_model: LandingSiteSurfaceModel):
        super().__init__()
        self.surface_model = surface_model

    def update(self, dt: float) -> None:
        _ = dt
        if not self.world:
            return

        views = []
        for entity in self.world.get_entities_with(LandingSite, Transform):
            site = entity.get_component(LandingSite)
            trans = entity.get_component(Transform)
            econ = entity.get_component(LandingSiteEconomy)
            motion = entity.get_component(KinematicMotion)
            attach = entity.get_component(SiteAttachment)
            if site is None or trans is None:
                continue

            vel = Vector2(0.0, 0.0)
            if motion is not None:
                vel = Vector2(motion.velocity)
            if attach is not None and attach.parent_uid:
                parent = self.world.get_entity_by_id(attach.parent_uid)
                if parent is not None:
                    pphys = parent.get_component(PhysicsState)
                    pmotion = parent.get_component(KinematicMotion)
                    if pphys is not None:
                        vel += pphys.vel
                    elif pmotion is not None:
                        vel += pmotion.velocity

            award = 0.0
            fuel_price = 10.0
            visited = False
            if econ is not None:
                award = econ.award
                fuel_price = econ.fuel_price
                visited = econ.visited

            views.append(
                to_view(
                    uid=entity.uid,
                    x=trans.pos.x,
                    y=trans.pos.y,
                    size=site.size,
                    vel=vel,
                    award=award,
                    fuel_price=fuel_price,
                    terrain_mode=site.terrain_mode,
                    terrain_bound=site.terrain_bound,
                    blend_margin=site.blend_margin,
                    cut_depth=site.cut_depth,
                    support_height=site.support_height,
                    visited=visited,
                )
            )

        self.surface_model.update_from_views(views)

