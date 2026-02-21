"""Procedural terrain generation using simplex noise."""

import random
from opensimplex import OpenSimplex
from dataclasses import dataclass
from typing import Protocol
import numpy as np
from core.maths import Range1D, Vector2


class SimplexNoiseGenerator:
    """Generates terrain heightmaps using layered simplex noise."""

    def __init__(
        self,
        seed: int = 0,
        octaves: int = 5,
        amplitude: float = 5000.0,
        frequency: float = 0.0001,
        persistence: float = 0.25,
        lacunarity: float = 4.0,
    ):
        self.seed = seed
        self.noise = OpenSimplex(seed)
        self.octaves = octaves
        self.persistence = persistence
        self.lacunarity = lacunarity
        self.frequency = frequency
        self.amplitude = amplitude

    def __call__(self, x: float) -> float:
        """Sample terrain height at x."""
        value = 0.0
        amplitude = self.amplitude
        frequency = self.frequency

        for _ in range(self.octaves):
            value += self.noise.noise2(x * frequency, 0) * amplitude
            amplitude *= self.persistence
            frequency *= self.lacunarity

        return value


class UniformGridChunk:
    # assume uniform grid of points
    def __init__(self, height_func, start_x: float, end_x: float, resolution: float):
        self.points = []
        self.start_x = start_x
        self.end_x = end_x
        self.resolution = resolution

        for x in np.arange(self.start_x, self.end_x + 1.0, self.resolution):
            self.points.append((x, height_func(x)))

    def _interpolate(
        self, x0: float, y0: float, x1: float, y1: float, x: float
    ) -> float:
        if x1 == x0:
            return y0
        t = (x - x0) / (x1 - x0)
        return y0 * (1 - t) + y1 * t

    def __call__(self, x: float) -> float | None:
        if x < self.start_x or x > self.end_x:
            return None

        if x == self.start_x:
            return self.points[0][1]
        if x == self.end_x:
            return self.points[-1][1]

        i = int((x - self.start_x) / self.resolution)
        if i == len(self.points) - 1:
            return self.points[-1][1]
        j = i + 1

        pi = self.points[i]
        pj = self.points[j]
        return self._interpolate(pi[0], pi[1], pj[0], pj[1], x)


class UniformGridGenerator:
    def __init__(
        self, height_func, chunk_size: float = 1000.0, resolution: float = 10.0
    ):
        self.chunks: dict[int, UniformGridChunk] = {}
        self.height_func = height_func
        self.chunk_size = chunk_size
        self.resolution = resolution

    def _get_chunk(self, x: float) -> UniformGridChunk:
        chunk_index = round(x / self.chunk_size)
        if chunk_index not in self.chunks:
            start_x = chunk_index * self.chunk_size - self.chunk_size / 2
            end_x = start_x + self.chunk_size
            self.chunks[chunk_index] = UniformGridChunk(
                self.height_func, start_x, end_x, self.resolution
            )
        return self.chunks[chunk_index]

    def __call__(self, x: float) -> float:
        chunk = self._get_chunk(x)
        return chunk(x)


class LodGridGenerator:
    def __init__(
        self, height_func, chunk_elements: int = 100, base_resolution: float = 10.0
    ):
        self.lod_generators: dict[int, UniformGridGenerator] = {}
        self.chunk_elements = chunk_elements
        self.base_resolution = base_resolution
        self.height_func = height_func

    def get_resolution(self, lod: int) -> float:
        return self.base_resolution * (2**lod)

    def _get_lod(self, lod: int) -> UniformGridGenerator:
        if lod not in self.lod_generators:
            resolution = self.get_resolution(lod)
            chunk_size = self.chunk_elements * resolution
            self.lod_generators[lod] = UniformGridGenerator(
                self.height_func, chunk_size, resolution
            )
        return self.lod_generators[lod]

    def __call__(self, x: float, lod: int = 0) -> float:
        generator = self._get_lod(lod)
        return generator(x)


class AddHeightModifier:
    def __init__(self, height_func, modifier_func):
        self.height_func = height_func
        self.modifier_func = modifier_func

    def __call__(self, x: float, lod: int = 0) -> float:
        base_y = self.height_func(x, lod)
        return self.modifier_func(Vector2(x, base_y), base_y, lod)

    def __getattr__(self, name: str):
        return getattr(self.height_func, name)


@dataclass
class Target:
    x: float
    y: float
    size: float
    info: dict


class RandomDistanceTargetGenerator:
    def __init__(
        self, seed: int = 0, min_distance: float = 1000.0, max_distance: float = 3000.0
    ):
        self.rng = random.Random(seed)
        self.min_distance = min_distance
        self.max_distance = max_distance

    def __call__(self, prev_target: Target, direction: int) -> Target:
        if direction == 0:
            x = self.rng.uniform(-self.min_distance, +self.min_distance)
        else:
            x = prev_target.x + direction * self.rng.uniform(
                self.min_distance, self.max_distance
            )
        return Target(x, prev_target.y, prev_target.size, prev_target.info)


class TargetHeightModifier:
    def __init__(
        self,
        height_func,
        seed: int = 0,
        min_height_variation: float = -100.0,
        max_height_variation: float = 100.0,
    ):
        self.height_func = height_func
        self.rng = random.Random(seed)
        self.min_height_variation = min_height_variation
        self.max_height_variation = max_height_variation

    def __call__(self, target: Target, _direction: int) -> Target:
        y = self.height_func(target.x) + self.rng.uniform(
            self.min_height_variation, self.max_height_variation
        )
        return Target(target.x, y, target.size, target.info)


class TargetSizeModifier:
    def __init__(self, seed: int = 0, min_size: float = 50.0, max_size: float = 100.0):
        self.rng = random.Random(seed)
        self.min_size = min_size
        self.max_size = max_size

    def __call__(self, target: Target, _direction: int) -> Target:
        size = self.rng.uniform(self.min_size, self.max_size)
        return Target(target.x, target.y, size, target.info)


class TargetAwardsModifier:
    def __init__(
        self, seed: int = 0, min_award: float = 100.0, max_award: float = 500.0
    ):
        self.rng = random.Random(seed)
        self.min_award = min_award
        self.max_award = max_award

    def __call__(self, target: Target, _direction: int) -> Target:
        award = self.rng.uniform(self.min_award, self.max_award)
        return Target(target.x, target.y, target.size, {**target.info, "award": award})


class TargetFuelPriceModifier:
    def __init__(
        self, seed: int = 0, min_price: float = 5.0, max_price: float = 15.0
    ):
        self.rng = random.Random(seed)
        self.min_price = min_price
        self.max_price = max_price

    def __call__(self, target: Target, _direction: int) -> Target:
        price = self.rng.uniform(self.min_price, self.max_price)
        # Round to nearest 0.5 for nice numbers
        price = round(price * 2) / 2
        return Target(target.x, target.y, target.size, {**target.info, "fuel_price": price})


class CompositeTargetGenerator:
    def __init__(self, target_generators):
        self.target_generators = target_generators

    def __call__(self, target: Target, direction: int) -> Target:
        for target_generator in self.target_generators:
            target = target_generator(target, direction)
        return target


class TargetManager:
    def __init__(self, target_func):
        # target_func: target, dir -> target
        self.target_func = target_func
        # target: x, y, size, info
        self.targets = [self.target_func(Target(0, 0, 0, {}), 0)]

    def _ensure_target(self, x: float):
        # try to generate targets towards right
        while self.targets[-1].x < x:
            self.targets.append(self.target_func(self.targets[-1], 1))

        # try to generate targets towards left
        while self.targets[0].x > x:
            self.targets.insert(0, self.target_func(self.targets[0], -1))

    def get_targets(self, span: Range1D):
        self._ensure_target(span.min)
        self._ensure_target(span.max)
        targets = []
        center_x = (span.min + span.max) * 0.5
        half_span = span.span * 0.5
        for target in self.targets:
            if (
                target.x - target.size / 2 - half_span
                <= center_x
                <= target.x + target.size / 2 + half_span
            ):
                targets.append(target)
        return targets

    def height_modifier(self, pos: Vector2, y: float, lod: int = 0) -> float:
        margin = 20.0 * (2**lod)
        targets = self.get_targets(Range1D.from_center(pos.x, margin))
        if targets:
            return targets[0].y
        return y

class Terrain(Protocol):
    def __call__(self, x: float, lod: int = 0) -> float: ...

