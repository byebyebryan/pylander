from __future__ import annotations

from game.ui.auto_zoom import AutoZoomController
from game.core.maths import Vector2


class _Camera:
    def __init__(self):
        self.x = 0.0
        self.y = 100.0
        self.zoom = 1.0
        self.min_zoom = 0.02
        self.max_zoom = 2.0


def test_auto_zoom_zooms_out_to_fit_impact_point() -> None:
    """When the impact point is far away, zoom should decrease."""
    controller = AutoZoomController(response_rate=1.0)
    camera = _Camera()
    camera.zoom = 2.0  # start zoomed in

    # Impact is 500 world units ahead and 100 below — should trigger zoom-out.
    impact = Vector2(500.0, 0.0)
    controller.update(1.0 / 60.0, camera, 640, 480, impact_point=impact)

    assert camera.min_zoom <= camera.zoom <= camera.max_zoom
    assert camera.zoom < 2.0  # zoomed out


def test_auto_zoom_zooms_in_slowly_when_impact_is_close() -> None:
    """When impact is nearby, zoom should increase but very slowly (no thrashing)."""
    controller = AutoZoomController(response_rate=1.0)
    camera = _Camera()
    camera.zoom = 0.5  # start zoomed out

    # Impact very close — target zoom will be max_zoom.
    impact = Vector2(1.0, 99.0)
    controller.update(1.0 / 60.0, camera, 640, 480, impact_point=impact)

    assert camera.min_zoom <= camera.zoom <= camera.max_zoom
    assert camera.zoom > 0.5  # moving toward max, but slowly


def test_auto_zoom_fallback_terrain_distance() -> None:
    """Fallback to terrain-distance framing when no impact point provided."""
    controller = AutoZoomController(response_rate=1.0)
    camera = _Camera()

    def _height_at(_x: float) -> float:
        return 0.0

    controller.update(1.0 / 60.0, camera, 640, 480, get_height_at=_height_at)

    assert camera.min_zoom <= camera.zoom <= camera.max_zoom


def test_auto_zoom_holds_when_no_input() -> None:
    """With neither impact point nor terrain function, zoom should not change."""
    controller = AutoZoomController(response_rate=1.0)
    camera = _Camera()
    original_zoom = camera.zoom

    controller.update(1.0 / 60.0, camera, 640, 480)

    assert camera.zoom == original_zoom
