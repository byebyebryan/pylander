"""Procedural terrain generation using simplex noise."""

from opensimplex import OpenSimplex
from typing import Protocol
import numpy as np
from core.maths import Vector2


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

class Terrain(Protocol):
    def __call__(self, x: float, lod: int = 0) -> float: ...

