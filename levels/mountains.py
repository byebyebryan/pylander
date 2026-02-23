from __future__ import annotations

import math

import core.terrain as _terrain
from core.level import Level
from levels.common import PresetLevel, SiteSpec


def _build_mountain_terrain(seed: int):
    layered = _terrain.LayeredTerrainGenerator(
        seed=seed,
        base_height=0.0,
        macro_amplitude=850.0,
        macro_frequency=0.00007,
        structure_amplitude=2600.0,
        structure_frequency=0.00022,
        structure_octaves=5,
        structure_persistence=0.44,
        structure_lacunarity=2.15,
        ridge_mix=0.62,
        warp_amplitude=520.0,
        warp_frequency=0.00014,
        feature_cell_size=1050.0,
        feature_density=0.42,
    )

    def height_fn(x: float) -> float:
        center_valley = -500.0 * math.exp(-((x / 2200.0) ** 2))
        long_wave = 380.0 * math.sin(x * 0.00035)
        return layered(x) + center_valley + long_wave

    return _terrain.LodGridGenerator(height_fn, base_resolution=8.0)


class MountainsLevel(PresetLevel):
    """Steeper terrain with elevated pads for harder routes."""

    site_specs = (
        SiteSpec(
            uid="mtn_site_left_valley",
            x=-1700.0,
            size=92.0,
            award=220.0,
            fuel_price=10.5,
            y_offset=10.0,
        ),
        SiteSpec(
            uid="mtn_site_central_tower",
            x=-300.0,
            size=85.0,
            award=260.0,
            fuel_price=11.0,
            terrain_mode="elevated_supports",
            terrain_bound=False,
            y_offset=130.0,
            support_height=120.0,
        ),
        SiteSpec(
            uid="mtn_site_right_ridge",
            x=980.0,
            size=84.0,
            award=300.0,
            fuel_price=11.5,
            y_offset=20.0,
        ),
        SiteSpec(
            uid="mtn_site_far_peak",
            x=2150.0,
            size=74.0,
            award=420.0,
            fuel_price=12.5,
            terrain_mode="elevated_supports",
            terrain_bound=False,
            y_offset=190.0,
            support_height=160.0,
        ),
    )
    spawn_x = -950.0
    spawn_clearance = 150.0
    spawn_x_jitter = 70.0
    site_x_jitter = 90.0

    def _build_base_terrain(self, seed: int):
        return _build_mountain_terrain(seed)


def create_level() -> Level:
    return MountainsLevel()
