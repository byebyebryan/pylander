from __future__ import annotations

from core.level import Level
from levels.scenario_common import ScenarioLevel, ScenarioLevelSpec


class ClimbLevel(ScenarioLevel):
    scenario = ScenarioLevelSpec(
        name="climb_to_target",
        start_x=0.0,
        target_x=900.0,
        spawn_clearance=70.0,
        terrain_kind="slope",
        slope=0.04,
        terrain_base=-80.0,
        target_mode="elevated_supports",
        target_offset_y=90.0,
        target_size=90.0,
    )
    default_bot_name = "drift"


def create_level() -> Level:
    return ClimbLevel()

