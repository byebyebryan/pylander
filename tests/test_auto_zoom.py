from __future__ import annotations

from ui.auto_zoom import AutoZoomController


class _Camera:
    def __init__(self):
        self.x = 0.0
        self.y = 100.0
        self.zoom = 1.0
        self.min_zoom = 0.02
        self.max_zoom = 2.0


def test_auto_zoom_update_accepts_strict_vector_sensor_path() -> None:
    controller = AutoZoomController(delay_seconds=0.0, response_rate=1.0)
    camera = _Camera()

    def _height_at(_x: float) -> float:
        return 0.0

    controller.update(1.0 / 60.0, _height_at, camera, screen_height=720)

    assert camera.min_zoom <= camera.zoom <= camera.max_zoom
