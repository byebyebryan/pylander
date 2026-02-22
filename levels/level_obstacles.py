from __future__ import annotations

from core.level import Level
from levels.scenario_common import ScenarioLevel, ScenarioLevelSpec


class ObstaclesLevel(ScenarioLevel):
    scenario = ScenarioLevelSpec(
        name="complex_terrain_vertical_features",
        start_x=-150.0,
        target_x=1300.0,
        spawn_clearance=120.0,
        terrain_kind="complex",
        terrain_amplitude=5400.0,
        terrain_frequency=0.00016,
        terrain_octaves=6,
        target_mode="elevated_supports",
        target_offset_y=100.0,
        target_size=85.0,
    )
    default_bot_name = "ferry"


def create_level() -> Level:
    return ObstaclesLevel()

