"""Auto-zoom controller driven by predicted ballistic impact point."""

from __future__ import annotations

import math
from typing import Callable
from game.core.maths import Vector2

# Impact point target fraction of screen half-extent from center.
# 0.8 means the impact sits at 80% of the way to the edge (20% margin).
_FILL = 0.8


class AutoZoomController:
    """Keeps the predicted ballistic impact point in view.

    Zoom-out is fast; zoom-in is deliberately slow to prevent thrashing
    when the trajectory shortens momentarily.

    Falls back to terrain-distance framing when no impact point is provided.

    Usage per frame:
        controller.update(dt, camera, screen_width, screen_height,
                          impact_point=vec2_or_None,
                          get_height_at=callable_or_None)
    """

    def __init__(self, response_rate: float = 1.0):
        self.response_rate = response_rate
        # Zoom-out tracks the target quickly; zoom-in eases back very slowly.
        self._zoom_out_rate = response_rate * 3.0
        self._zoom_in_rate = response_rate * 0.4

    def reset(self):
        pass

    def update(
        self,
        frame_dt: float,
        camera,
        screen_width: int,
        screen_height: int,
        *,
        impact_point: Vector2 | None = None,
        get_height_at: Callable[[float], float] | None = None,
    ) -> None:
        target_zoom = self._compute_target_zoom(
            camera, screen_width, screen_height, impact_point, get_height_at
        )
        target_zoom = max(camera.min_zoom, min(camera.max_zoom, target_zoom))

        # Pick rate: fast out, slow in.
        rate = self._zoom_out_rate if target_zoom < camera.zoom else self._zoom_in_rate
        alpha = 1.0 - math.exp(-rate * frame_dt)
        camera.zoom += (target_zoom - camera.zoom) * alpha
        camera.zoom = max(camera.min_zoom, min(camera.max_zoom, camera.zoom))

    # ------------------------------------------------------------------
    def _compute_target_zoom(
        self,
        camera,
        screen_width: int,
        screen_height: int,
        impact_point: Vector2 | None,
        get_height_at: Callable[[float], float] | None,
    ) -> float:
        if impact_point is not None:
            dx = abs(impact_point.x - camera.x)
            dy = abs(impact_point.y - camera.y)
            # Zoom required to fit the impact at _FILL fraction of each half-extent.
            zoom_x = (_FILL * screen_width * 0.5) / max(dx, 1.0)
            zoom_y = (_FILL * screen_height * 0.5) / max(dy, 1.0)
            return min(zoom_x, zoom_y)

        # Fallback: keep closest terrain distance in a screen-height band.
        if get_height_at is not None:
            from game.core.sensor import closest_point_on_terrain

            search_radius = (screen_height / max(camera.zoom, 1e-6)) * 1.0
            _, _, dist_world = closest_point_on_terrain(
                get_height_at, Vector2(camera.x, camera.y), search_radius=search_radius
            )
            target_px = float(screen_height) * 0.40
            return target_px / max(dist_world, 1e-3)

        return camera.zoom  # nothing to go on — hold current
