from __future__ import annotations

import pytest

import core.maths as maths
from core.maths import Range1D, RigidTransform2, Size2, Vector2
from ui.camera import Camera


def test_math_transform_symbol_removed() -> None:
    assert hasattr(maths, "RigidTransform2")
    assert not hasattr(maths, "Transform")


def test_camera_visible_world_rect() -> None:
    cam = Camera(100, 50)
    cam.x = 10.0
    cam.y = 20.0
    cam.zoom = 2.0

    rect = cam.get_visible_world_rect()

    assert rect.min_x == pytest.approx(-15.0)
    assert rect.max_x == pytest.approx(35.0)
    assert rect.min_y == pytest.approx(7.5)
    assert rect.max_y == pytest.approx(32.5)
    assert rect.width == pytest.approx(50.0)
    assert rect.height == pytest.approx(25.0)


def test_camera_world_to_screen_requires_vector2() -> None:
    cam = Camera(100, 50)
    screen = cam.world_to_screen(Vector2(0.0, 0.0))
    assert isinstance(screen, Vector2)

    with pytest.raises(TypeError):
        cam.world_to_screen(0.0, 0.0)  # type: ignore[call-arg]


def test_rigid_transform2_requires_vector2() -> None:
    tf = RigidTransform2(Vector2(1.0, 2.0), 0.0)
    out = tf.apply(Vector2(3.0, 4.0))
    assert out == Vector2(4.0, 6.0)

    with pytest.raises(AttributeError):
        tf.apply((1.0, 2.0))  # type: ignore[arg-type]


def test_range_and_size_helpers() -> None:
    span = Range1D.from_center(10.0, 3.0)
    assert span.min == pytest.approx(7.0)
    assert span.max == pytest.approx(13.0)
    assert span.span == pytest.approx(6.0)
    assert span.contains(9.0)
    assert span.clamp(20.0) == pytest.approx(13.0)

    size = Size2.from_tuple((640.0, 480.0))
    assert size.to_tuple() == (640.0, 480.0)
