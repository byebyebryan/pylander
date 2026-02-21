"""Visual data generation for Landers."""

from __future__ import annotations

import math
from dataclasses import dataclass
from core.maths import RigidTransform2, Vector2


@dataclass
class Thrust:
    """Thrust flame descriptor for rendering."""
    x: float
    y: float
    angle: float
    width: float
    length: float
    power: float


class LanderVisuals:
    """Mixin for generating lander visual artifacts (polygons, flames).
    
    Requires the host class to have:
    - x, y: float (world coordinates)
    - rotation: float (radians)
    - width, height: float
    - thrust_level: float (0..1)
    """

    def get_body_polygon(self) -> list[Vector2]:
        """Return the lander body polygon vertices in world space."""
        half_w = self.width / 2.0
        half_h = self.height / 2.0
        
        # Local-space triangle points (nose up in y-up)
        local_pts = [
            Vector2(0.0, half_h),  # top (nose)
            Vector2(-half_w, -half_h),  # bottom-left
            Vector2(half_w, -half_h),  # bottom-right
        ]
        
        # Use simple x,y property access for compatibility if pos not available
        # But since we know we are usually on Lander which has pos:
        pos = getattr(self, "pos", Vector2(self.x, self.y))
        tf = RigidTransform2(pos, self.rotation)
        
        world_pts = []
        for pt in local_pts:
            w = tf.apply(pt)
            world_pts.append(w)
            
        return world_pts

    def get_thrusts(self) -> list[Thrust]:
        """Return a list of simple thrust descriptors for renderer."""
        # Geometry in local space (y-up): base sits below body
        half_h = self.height / 2.0
        base_offset_local = half_h * 1.5  # distance from center to base along -y
        
        # Base point in local space: (0, -base_offset)
        local_base = Vector2(0.0, -base_offset_local)
        
        pos = getattr(self, "pos", Vector2(self.x, self.y))
        tf = RigidTransform2(pos, self.rotation)
        
        world_base = tf.apply(local_base)
        
        # Direction of flame (local -y) mapped to world angle
        # This matches the legacy logic: atan2(-cos, -sin)
        # cos(r), sin(r) are cacheable but Transform computes them internally
        # Let's just recompute or rely on legacy math for angle since Transform doesn't expose it publically yet
        cos_r = math.cos(self.rotation)
        sin_r = math.sin(self.rotation)
        world_angle = math.atan2(-cos_r, -sin_r)

        return [
            Thrust(
                x=world_base.x,
                y=world_base.y,
                angle=world_angle,
                width=self.width / 2.0,
                length=20.0,
                power=self.thrust_level,
            )
        ]
