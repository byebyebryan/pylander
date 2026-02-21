from __future__ import annotations

import math

from core.components import KinematicMotion, LandingSite, PhysicsState, SiteAttachment, Transform
from core.ecs import System
from core.maths import Vector2


class LandingSiteMotionSystem(System):
    """Update kinematic/attached landing-site transforms."""

    def update(self, dt: float) -> None:
        if not self.world:
            return
        for entity in self.world.get_entities_with(LandingSite, Transform):
            trans = entity.get_component(Transform)
            attach = entity.get_component(SiteAttachment)
            motion = entity.get_component(KinematicMotion)
            if trans is None:
                continue

            if attach is not None and attach.parent_uid:
                parent = self.world.get_entity_by_id(attach.parent_uid)
                if parent is not None:
                    ptrans = parent.get_component(Transform)
                    if ptrans is not None:
                        ox, oy = attach.local_offset.x, attach.local_offset.y
                        cos_r = math.cos(ptrans.rotation)
                        sin_r = math.sin(ptrans.rotation)
                        world_off = Vector2(
                            ox * cos_r + oy * sin_r,
                            -ox * sin_r + oy * cos_r,
                        )
                        trans.pos = ptrans.pos + world_off

            if motion is not None:
                trans.pos += motion.velocity * dt

