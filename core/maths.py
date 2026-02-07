"""Math utilities for 2D vectors and coordinate transforms."""

import math
from pygame.math import Vector2 as _Vector2

# Export Vector2 alias
Vector2 = _Vector2


class Transform:
    """Represents a 2D coordinate transform (position + rotation).
    
    Coordinate system assumptions match the game's logic:
    - Position (x, y)
    - Rotation (angle) in radians.
    - Rotation logic mirrors the legacy Lander implementation:
        wx = x + px * cos(r) + py * sin(r)
        wy = y - px * sin(r) + py * cos(r)
      This corresponds to a rotation matrix R = [[cos, sin], [-sin, cos]].
    """

    def __init__(self, pos: Vector2 | tuple[float, float], angle: float):
        if isinstance(pos, Vector2):
            self.pos = pos
        else:
            self.pos = Vector2(pos[0], pos[1])
        self.angle = angle
        
        # Cache trig values
        self._cos = math.cos(angle)
        self._sin = math.sin(angle)

    def apply(self, local_point: Vector2 | tuple[float, float]) -> Vector2:
        """Transform a local point to world space."""
        if isinstance(local_point, Vector2):
            px, py = local_point.x, local_point.y
        else:
            px, py = local_point[0], local_point[1]
            
        wx = self.pos.x + px * self._cos + py * self._sin
        wy = self.pos.y - px * self._sin + py * self._cos
        return Vector2(wx, wy)

    def apply_inverse(self, world_point: Vector2 | tuple[float, float]) -> Vector2:
        """Transform a world point to local space (inverse transform)."""
        if isinstance(world_point, Vector2):
            wx, wy = world_point.x, world_point.y
        else:
            wx, wy = world_point[0], world_point[1]

        dx = wx - self.pos.x
        dy = wy - self.pos.y
        
        # Inverse rotation (transpose of the matrix):
        # [ cos -sin ]
        # [ sin  cos ]
        lx = dx * self._cos - dy * self._sin
        ly = dx * self._sin + dy * self._cos
        return Vector2(lx, ly)
