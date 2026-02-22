from __future__ import annotations

from core.level import Level
from levels.scenario_common import ScenarioLevel, ScenarioLevelSpec


class FerryLevel(ScenarioLevel):
    scenario = ScenarioLevelSpec(
        name="increase_horizontal_distance",
        start_x=0.0,
        target_x=1800.0,
        spawn_clearance=120.0,
        terrain_kind="flat",
        target_mode="flush_flatten",
        target_offset_y=0.0,
        target_size=105.0,
    )
    default_bot_name = "ferry"


def create_level() -> Level:
    return FerryLevel()
