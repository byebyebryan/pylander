from __future__ import annotations

from core.level import Level
from levels.scenario_common import ScenarioLevel, ScenarioLevelSpec


class DropLevel(ScenarioLevel):
    scenario = ScenarioLevelSpec(
        name="spawn_above_target",
        start_x=0.0,
        target_x=0.0,
        spawn_clearance=70.0,
        terrain_kind="flat",
        target_mode="flush_flatten",
        target_offset_y=0.0,
        target_size=110.0,
    )
    default_bot_name = "drop"


def create_level() -> Level:
    return DropLevel()
