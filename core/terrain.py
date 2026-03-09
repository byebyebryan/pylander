"""Procedural terrain generation and sampling helpers."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Protocol

import numpy as np
from opensimplex import OpenSimplex

from core.config import GRAVITY
from core.maths import Vector2


def sample_terrain_height(height_func: Any, x: float, lod: int = 0) -> float:
    """Sample a terrain-like callable with optional lod support."""
    return float(height_func(x, lod))


def terrain_resolution(height_func: Any, lod: int = 0, minimum: float = 0.5) -> float:
    """Resolve terrain sampling resolution, with safe fallback."""
    get_resolution = getattr(height_func, "get_resolution", None)
    if callable(get_resolution):
        try:
            return max(float(minimum), float(get_resolution(lod)))
        except Exception:
            return 2.0
    return 2.0


def estimate_terrain_slope(height_func: Any, x: float, lod: int = 0) -> float:
    """Estimate local terrain slope around x using central difference."""
    step = terrain_resolution(height_func, lod=lod)
    y0 = sample_terrain_height(height_func, x - step, lod=lod)
    y1 = sample_terrain_height(height_func, x + step, lod=lod)
    return (y1 - y0) / (2.0 * step)


def pick_lod_for_world_step(
    height_func: Any, world_step: float, max_lod: int = 8
) -> int:
    """Pick LOD whose terrain resolution best matches desired world-step."""
    target = max(1e-6, float(world_step))
    best_lod = 0
    best_score = float("inf")
    for lod in range(max(0, int(max_lod)) + 1):
        res = terrain_resolution(height_func, lod=lod, minimum=1e-6)
        score = abs(math.log2(res / target))
        if score < best_score:
            best_lod = lod
            best_score = score
    return best_lod


def anchored_profile(
    height_func: Any,
    x0: float,
    x1: float,
    *,
    step: float,
    lod: int = 0,
) -> list[tuple[float, float]]:
    """Sample a stable x/y profile aligned to a world-space step grid."""
    step = max(1e-6, float(step))
    min_x = min(x0, x1)
    max_x = max(x0, x1)
    start_x = math.floor(min_x / step) * step
    end_x = math.ceil(max_x / step) * step

    out: list[tuple[float, float]] = []
    xx = start_x
    while xx <= end_x + 1e-9:
        out.append((xx, sample_terrain_height(height_func, xx, lod=lod)))
        xx += step
    return out


@dataclass(frozen=True)
class BallisticTrajectory:
    """Engine-off ballistic trajectory sampled against terrain."""

    points: list[tuple[float, float]]
    hit: bool
    hit_x: float | None
    hit_y: float | None
    hit_time: float | None
    hit_vx: float | None
    hit_vy_up: float | None
    hit_speed: float | None
    distance: float
    duration: float
    termination: str


def _ballistic_position(
    x0: float,
    y0: float,
    vx: float,
    vy_up: float,
    g: float,
    t: float,
) -> tuple[float, float]:
    return (
        x0 + (vx * t),
        y0 + (vy_up * t) - (0.5 * g * t * t),
    )


def ballistic_velocity(
    vx: float,
    vy_up: float,
    g: float,
    t: float,
) -> tuple[float, float]:
    """Return ballistic velocity (vx, vy_up) at time t."""
    return (vx, vy_up - (g * t))


def ballistic_state(
    x0: float,
    y0: float,
    vx: float,
    vy_up: float,
    g: float,
    t: float,
) -> tuple[float, float, float, float]:
    """Return ballistic position + velocity at time t."""
    px, py = _ballistic_position(x0, y0, vx, vy_up, g, t)
    vv_x, vv_y = ballistic_velocity(vx, vy_up, g, t)
    return px, py, vv_x, vv_y


def ballistic_fall_time(
    altitude: float,
    vy_up: float,
    g: float = 9.8,
    *,
    min_time: float = 0.5,
) -> float:
    """Return analytic engine-off time-to-ground for local altitude."""
    gravity = abs(float(g))
    if gravity <= 1e-9:
        gravity = 9.8
    disc = max(0.0, (vy_up * vy_up) + (2.0 * gravity * max(0.0, altitude)))
    t = (vy_up + math.sqrt(disc)) / gravity
    return max(float(min_time), t)


def sample_ballistic_trajectory(
    height_func: Any,
    *,
    x: float,
    y: float,
    vx: float,
    vy_up: float,
    max_distance: float = 3000.0,
    segment_length: float = 24.0,
    max_points: int = 256,
    lod: int = 0,
    clearance: float = 0.0,
    gravity: float | None = None,
) -> BallisticTrajectory:
    """Sample engine-off trajectory until terrain hit or max distance.

    Uses analytic kinematics with constant gravity and a distance-guided timestep,
    then refines terrain impact time with short bisection for stable hit points.
    """
    start_x = float(x)
    start_y = float(y)
    vx = float(vx)
    vy_up = float(vy_up)
    max_distance = max(0.0, float(max_distance))
    segment_length = max(0.5, float(segment_length))
    max_points = max(2, int(max_points))
    clearance = max(0.0, float(clearance))
    g = abs(float(GRAVITY if gravity is None else gravity))
    if g <= 1e-9:
        g = abs(float(GRAVITY))

    points: list[tuple[float, float]] = [(start_x, start_y)]
    terrain_start = sample_terrain_height(height_func, start_x, lod=lod)
    if start_y <= (terrain_start + clearance):
        return BallisticTrajectory(
            points=points,
            hit=True,
            hit_x=start_x,
            hit_y=start_y,
            hit_time=0.0,
            hit_vx=vx,
            hit_vy_up=vy_up,
            hit_speed=math.hypot(vx, vy_up),
            distance=0.0,
            duration=0.0,
            termination="terrain_hit",
        )
    if max_distance <= 0.0:
        return BallisticTrajectory(
            points=points,
            hit=False,
            hit_x=None,
            hit_y=None,
            hit_time=None,
            hit_vx=None,
            hit_vy_up=None,
            hit_speed=None,
            distance=0.0,
            duration=0.0,
            termination="max_distance",
        )

    t_prev = 0.0
    x_prev = start_x
    y_prev = start_y
    distance = 0.0

    while len(points) < max_points:
        vy_now = vy_up - (g * t_prev)
        speed_now = max(1.0, math.hypot(vx, vy_now))
        dt = segment_length / speed_now
        t_next = t_prev + dt
        x_next, y_next = _ballistic_position(start_x, start_y, vx, vy_up, g, t_next)

        seg_dist = math.hypot(x_next - x_prev, y_next - y_prev)
        if seg_dist <= 1e-9:
            break

        remaining = max_distance - distance
        if remaining <= 1e-9:
            break

        if seg_dist > remaining:
            ratio = remaining / seg_dist
            t_end = t_prev + (dt * ratio)
            x_end = x_prev + ((x_next - x_prev) * ratio)
            y_end = y_prev + ((y_next - y_prev) * ratio)
            points.append((x_end, y_end))
            return BallisticTrajectory(
                points=points,
                hit=False,
                hit_x=None,
                hit_y=None,
                hit_time=None,
                hit_vx=None,
                hit_vy_up=None,
                hit_speed=None,
                distance=max_distance,
                duration=t_end,
                termination="max_distance",
            )

        terrain_y = sample_terrain_height(height_func, x_next, lod=lod)
        if y_next <= (terrain_y + clearance):
            # Refine impact point to avoid large penetration when using coarse steps.
            t_lo = t_prev
            t_hi = t_next
            for _ in range(12):
                t_mid = 0.5 * (t_lo + t_hi)
                x_mid, y_mid = _ballistic_position(start_x, start_y, vx, vy_up, g, t_mid)
                terrain_mid = sample_terrain_height(height_func, x_mid, lod=lod)
                if y_mid > (terrain_mid + clearance):
                    t_lo = t_mid
                else:
                    t_hi = t_mid
            t_hit = t_hi
            x_hit, y_hit, v_hit_x, v_hit_y = ballistic_state(
                start_x,
                start_y,
                vx,
                vy_up,
                g,
                t_hit,
            )
            distance += math.hypot(x_hit - x_prev, y_hit - y_prev)
            points.append((x_hit, y_hit))
            return BallisticTrajectory(
                points=points,
                hit=True,
                hit_x=x_hit,
                hit_y=y_hit,
                hit_time=t_hit,
                hit_vx=v_hit_x,
                hit_vy_up=v_hit_y,
                hit_speed=math.hypot(v_hit_x, v_hit_y),
                distance=distance,
                duration=t_hit,
                termination="terrain_hit",
            )

        distance += seg_dist
        points.append((x_next, y_next))
        t_prev = t_next
        x_prev = x_next
        y_prev = y_next

        if distance >= max_distance:
            return BallisticTrajectory(
                points=points,
                hit=False,
                hit_x=None,
                hit_y=None,
                hit_time=None,
                hit_vx=None,
                hit_vy_up=None,
                hit_speed=None,
                distance=max_distance,
                duration=t_prev,
                termination="max_distance",
            )

    return BallisticTrajectory(
        points=points,
        hit=False,
        hit_x=None,
        hit_y=None,
        hit_time=None,
        hit_vx=None,
        hit_vy_up=None,
        hit_speed=None,
        distance=distance,
        duration=t_prev,
        termination="point_budget",
    )


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

    def __call__(self, x: float, lod: int = 0) -> float:
        """Sample terrain height at x."""
        _ = lod
        value = 0.0
        amplitude = self.amplitude
        frequency = self.frequency

        for _ in range(self.octaves):
            value += self.noise.noise2(x * frequency, 0) * amplitude
            amplitude *= self.persistence
            frequency *= self.lacunarity

        return value


class LayeredTerrainGenerator:
    """Composable terrain generator with macro, structure, and sparse local features."""

    def __init__(
        self,
        seed: int = 0,
        *,
        base_height: float = 0.0,
        macro_amplitude: float = 900.0,
        macro_frequency: float = 0.00008,
        structure_amplitude: float = 1800.0,
        structure_frequency: float = 0.00023,
        structure_octaves: int = 4,
        structure_persistence: float = 0.45,
        structure_lacunarity: float = 2.1,
        ridge_mix: float = 0.55,
        warp_amplitude: float = 450.0,
        warp_frequency: float = 0.00015,
        feature_cell_size: float = 900.0,
        feature_density: float = 0.38,
    ):
        self.seed = int(seed)
        self.base_height = float(base_height)
        self.macro_amplitude = float(macro_amplitude)
        self.macro_frequency = float(macro_frequency)
        self.structure_amplitude = float(structure_amplitude)
        self.structure_frequency = float(structure_frequency)
        self.structure_octaves = max(1, int(structure_octaves))
        self.structure_persistence = float(structure_persistence)
        self.structure_lacunarity = float(structure_lacunarity)
        self.ridge_mix = max(0.0, min(1.0, float(ridge_mix)))
        self.warp_amplitude = float(warp_amplitude)
        self.warp_frequency = float(warp_frequency)
        self.feature_cell_size = max(200.0, float(feature_cell_size))
        self.feature_density = max(0.0, min(1.0, float(feature_density)))

        self._macro_noise = OpenSimplex(self.seed + 101)
        self._structure_noise = OpenSimplex(self.seed + 211)
        self._ridge_noise = OpenSimplex(self.seed + 307)
        self._warp_noise = OpenSimplex(self.seed + 401)

    @staticmethod
    def _smoothstep(t: float) -> float:
        t = max(0.0, min(1.0, t))
        return t * t * (3.0 - 2.0 * t)

    def _rand01(self, index: int, salt: int) -> float:
        value = (index * 1619) ^ (self.seed * 31337) ^ (salt * 6971)
        value = (value << 13) ^ value
        hashed = (
            value * (value * value * 15731 + 789221) + 1376312589
        ) & 0x7FFFFFFF
        return hashed / 2147483647.0

    def _macro(self, x: float) -> float:
        return (
            self._macro_noise.noise2(x * self.macro_frequency, 0.0)
            * self.macro_amplitude
        )

    def _warped_x(self, x: float) -> float:
        warp = self._warp_noise.noise2(x * self.warp_frequency, 91.0) * self.warp_amplitude
        return x + warp

    def _structure(self, x: float) -> float:
        xx = self._warped_x(x)
        amp = self.structure_amplitude
        freq = self.structure_frequency
        regular_sum = 0.0
        ridged_sum = 0.0
        amp_sum = 0.0
        for _ in range(self.structure_octaves):
            n = self._structure_noise.noise2(xx * freq, 23.0)
            regular_sum += n * amp

            r = 1.0 - abs(self._ridge_noise.noise2(xx * freq, 67.0))
            r = r * r
            ridged_sum += (r * 2.0 - 1.0) * amp

            amp_sum += amp
            amp *= self.structure_persistence
            freq *= self.structure_lacunarity

        if amp_sum <= 1e-9:
            return 0.0
        regular = regular_sum / amp_sum
        ridged = ridged_sum / amp_sum
        mix = self.ridge_mix
        return (regular * (1.0 - mix) + ridged * mix) * self.structure_amplitude

    def _feature_from_cell(self, x: float, cell: int) -> float:
        if self._rand01(cell, 0) >= self.feature_density:
            return 0.0

        jitter = (self._rand01(cell, 1) - 0.5) * self.feature_cell_size * 0.7
        center = (cell + 0.5) * self.feature_cell_size + jitter
        dx = x - center

        radius = self.feature_cell_size * (0.18 + 0.30 * self._rand01(cell, 2))
        if abs(dx) >= radius:
            return 0.0

        t = abs(dx) / radius
        feature_kind = int(self._rand01(cell, 3) * 3.0)

        if feature_kind == 0:
            depth = self.structure_amplitude * (0.08 + 0.10 * self._rand01(cell, 4))
            k = 1.0 - t * t
            return -depth * k * k

        if feature_kind == 1:
            height = self.structure_amplitude * (0.06 + 0.10 * self._rand01(cell, 5))
            core = 0.45
            if t <= core:
                return height
            edge_t = (t - core) / max(1e-6, 1.0 - core)
            return height * (1.0 - self._smoothstep(edge_t))

        depth = self.structure_amplitude * (0.05 + 0.08 * self._rand01(cell, 6))
        return -depth * (1.0 - self._smoothstep(t))

    def _features(self, x: float) -> float:
        center_cell = math.floor(x / self.feature_cell_size)
        # Check adjacent cells only; feature radii are bounded by cell size.
        return (
            self._feature_from_cell(x, center_cell - 1)
            + self._feature_from_cell(x, center_cell)
            + self._feature_from_cell(x, center_cell + 1)
        )

    def __call__(self, x: float, lod: int = 0) -> float:
        _ = lod
        return self.base_height + self._macro(x) + self._structure(x) + self._features(x)


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

    def profile(
        self, x0: float, x1: float, *, step: float | None = None
    ) -> list[tuple[float, float]]:
        use_step = self.resolution if step is None else max(self.resolution, float(step))
        return anchored_profile(self.height_func, x0, x1, step=use_step, lod=0)


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

    def profile(
        self,
        x0: float,
        x1: float,
        *,
        lod: int = 0,
        step: float | None = None,
    ) -> list[tuple[float, float]]:
        base_step = self.get_resolution(lod)
        use_step = base_step if step is None else max(base_step, float(step))
        return anchored_profile(self, x0, x1, step=use_step, lod=lod)


class AddHeightModifier:
    def __init__(self, height_func, modifier_func):
        self.height_func = height_func
        self.modifier_func = modifier_func

    def __call__(self, x: float, lod: int = 0) -> float:
        base_y = sample_terrain_height(self.height_func, x, lod=lod)
        return self.modifier_func(Vector2(x, base_y), base_y, lod)

    def profile(
        self,
        x0: float,
        x1: float,
        *,
        lod: int = 0,
        step: float | None = None,
    ) -> list[tuple[float, float]]:
        if step is None:
            get_resolution = getattr(self.height_func, "get_resolution", None)
            if callable(get_resolution):
                try:
                    step = float(get_resolution(lod))
                except Exception:
                    step = 2.0
            else:
                step = 2.0
        return anchored_profile(self, x0, x1, step=max(1e-6, float(step)), lod=lod)

    def __getattr__(self, name: str):
        return getattr(self.height_func, name)


class Terrain(Protocol):
    def __call__(self, x: float, lod: int = 0) -> float: ...

