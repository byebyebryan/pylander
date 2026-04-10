"""Math utilities for 2D vectors, transforms, and bounds."""

from __future__ import annotations

import math
from dataclasses import dataclass
from pygame.math import Vector2 as _Vector2

# Export Vector2 alias
Vector2 = _Vector2


def lander_half_height(height: float) -> float:
    return max(1.0, float(height) * 0.5)


def clearance_above_terrain(
    center_y: float,
    terrain_y: float,
    *,
    body_height: float,
) -> float:
    return float(center_y) - float(terrain_y) - lander_half_height(body_height)


@dataclass(frozen=True)
class Size2:
    w: float
    h: float

    @classmethod
    def from_tuple(cls, value: tuple[float, float]) -> "Size2":
        return cls(w=float(value[0]), h=float(value[1]))

    def to_tuple(self) -> tuple[float, float]:
        return (self.w, self.h)


@dataclass(frozen=True)
class Range1D:
    min: float
    max: float

    @classmethod
    def from_center(cls, center: float, radius: float) -> "Range1D":
        return cls(center - radius, center + radius)

    @property
    def span(self) -> float:
        return self.max - self.min

    def contains(self, x: float) -> bool:
        return self.min <= x <= self.max

    def clamp(self, x: float) -> float:
        return max(self.min, min(self.max, x))


@dataclass(frozen=True)
class Rect:
    x: float
    y: float
    w: float
    h: float

    @classmethod
    def from_bounds(
        cls, min_x: float, max_x: float, min_y: float, max_y: float
    ) -> "Rect":
        return cls(min_x, min_y, max_x - min_x, max_y - min_y)

    @classmethod
    def from_center(cls, center: Vector2, size: Size2) -> "Rect":
        return cls(center.x - size.w / 2.0, center.y - size.h / 2.0, size.w, size.h)

    @property
    def min_x(self) -> float:
        return self.x

    @property
    def max_x(self) -> float:
        return self.x + self.w

    @property
    def min_y(self) -> float:
        return self.y

    @property
    def max_y(self) -> float:
        return self.y + self.h

    @property
    def width(self) -> float:
        return self.w

    @property
    def height(self) -> float:
        return self.h

    @property
    def center(self) -> Vector2:
        return Vector2(self.x + self.w / 2.0, self.y + self.h / 2.0)

    @property
    def size(self) -> Size2:
        return Size2(self.w, self.h)

    def to_bounds(self) -> tuple[float, float, float, float]:
        return (self.min_x, self.max_x, self.min_y, self.max_y)

    def contains(self, point: Vector2) -> bool:
        return self.min_x <= point.x <= self.max_x and self.min_y <= point.y <= self.max_y

    def clamp_point(self, point: Vector2) -> Vector2:
        return Vector2(
            max(self.min_x, min(self.max_x, point.x)),
            max(self.min_y, min(self.max_y, point.y)),
        )

    def to_pygame_rect(self):
        import pygame

        return pygame.Rect(int(self.x), int(self.y), int(self.w), int(self.h))


class RigidTransform2:
    """2D rigid transform (position + rotation) with y-up convention."""

    def __init__(self, pos: Vector2, angle: float):
        self.pos = pos
        self.angle = angle
        self._cos = math.cos(angle)
        self._sin = math.sin(angle)

    def apply(self, local_point: Vector2) -> Vector2:
        wx = self.pos.x + local_point.x * self._cos + local_point.y * self._sin
        wy = self.pos.y - local_point.x * self._sin + local_point.y * self._cos
        return Vector2(wx, wy)

    def apply_inverse(self, world_point: Vector2) -> Vector2:
        dx = world_point.x - self.pos.x
        dy = world_point.y - self.pos.y
        lx = dx * self._cos - dy * self._sin
        ly = dx * self._sin + dy * self._cos
        return Vector2(lx, ly)
