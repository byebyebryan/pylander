"""Auto-zoom controller for maintaining terrain distance within a screen-space band."""

from __future__ import annotations

import math
from typing import Callable


class AutoZoomController:
    """Maintains camera zoom so nearest terrain distance stays within a pixel band.

    Usage per frame:
        controller.update(frame_dt, get_height_at, camera, screen_height)
    """

    def __init__(self, delay_seconds: float = 3.0, response_rate: float = 1.0):
        self.delay_seconds = delay_seconds
        self.response_rate = response_rate
        self._timer = 0.0

    def reset(self):
        self._timer = 0.0

    def update(
        self,
        frame_dt: float,
        get_height_at: Callable[[float], float],
        camera,
        screen_height: int,
    ):
        """Update camera zoom to keep closest terrain distance within a band.

        Args:
            frame_dt: Seconds since last frame
            get_height_at: function x->height for terrain sampling
            camera: object with x, y, zoom, min_zoom, max_zoom
            screen_height: height in pixels
        """
        # Lazy import to avoid module cycles
        from sensor import closest_point_on_terrain

        # Search radius in world units based on screen height and current zoom
        search_radius = (screen_height / max(camera.zoom, 1e-6)) * 1.0
        _, _, dist_world = closest_point_on_terrain(
            get_height_at, camera.x, camera.y, search_radius=search_radius
        )

        # Desired on-screen distance band (diameter ~80% of screen height)
        h = float(screen_height)
        target_px = h * 0.40  # center of band (40% of height)
        min_px = h * 0.35  # lower bound of band
        max_px = h * 0.45  # upper bound of band

        dist_px = dist_world * camera.zoom
        need_zoom_in = dist_px < min_px  # too close -> increase zoom immediately
        need_zoom_out = dist_px > max_px  # too far  -> decrease zoom after delay

        # Update dwell timer only for zoom-out; decay otherwise
        if need_zoom_out:
            self._timer = min(self.delay_seconds * 2.0, self._timer + frame_dt)
        else:
            # need_zoom_in case: no dwell accumulation; gentle decay
            self._timer = max(0.0, self._timer - frame_dt)

        if need_zoom_in or (need_zoom_out and self._timer >= self.delay_seconds):
            # Compute target zoom and ease toward it
            target_zoom = target_px / max(dist_world, 1e-3)
            target_zoom = max(camera.min_zoom, min(camera.max_zoom, target_zoom))
            # Time-based smoothing to avoid abrupt changes
            alpha = 1.0 - math.exp(-self.response_rate * frame_dt)
            camera.zoom = camera.zoom + (target_zoom - camera.zoom) * alpha
            # Final clamp
            camera.zoom = max(camera.min_zoom, min(camera.max_zoom, camera.zoom))
