from __future__ import annotations

import math
import random

import core.terrain as _terrain
from core.level import Level
from levels.common import PresetLevel, SiteSpec


def _build_flat_terrain(seed: int):
    rng = random.Random(seed)
    base_height = rng.uniform(-60.0, 40.0)
    gentle_slope = rng.uniform(-0.003, 0.003)
    wave_phase = rng.uniform(0.0, math.tau)

    def height_fn(x: float) -> float:
        return (
            base_height
            + gentle_slope * x
            + 14.0 * math.sin(x * 0.0012 + wave_phase)
            + 6.0 * math.sin(x * 0.0028 + wave_phase * 0.5)
        )

    return _terrain.LodGridGenerator(height_fn, base_resolution=8.0)


class FlatLevel(PresetLevel):
    """Beginner-friendly terrain with clear progression targets."""

    site_specs = (
        SiteSpec(
            uid="flat_site_home",
            x=-280.0,
            size=120.0,
            award=80.0,
            fuel_price=8.5,
        ),
        SiteSpec(
            uid="flat_site_mid",
            x=950.0,
            size=100.0,
            award=180.0,
            fuel_price=10.0,
        ),
        SiteSpec(
            uid="flat_site_far",
            x=2300.0,
            size=90.0,
            award=320.0,
            fuel_price=11.0,
            terrain_mode="elevated_supports",
            terrain_bound=False,
            y_offset=100.0,
            support_height=100.0,
        ),
        SiteSpec(
            uid="flat_site_left",
            x=-1650.0,
            size=95.0,
            award=220.0,
            fuel_price=10.5,
        ),
    )
    spawn_x = 0.0
    spawn_clearance = 110.0
    spawn_x_jitter = 40.0
    site_x_jitter = 60.0

    def _build_base_terrain(self, seed: int):
        return _build_flat_terrain(seed)


def create_level() -> Level:
    return FlatLevel()
