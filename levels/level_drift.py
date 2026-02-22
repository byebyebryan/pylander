from __future__ import annotations

from core.level import Level
from levels.scenario_common import ScenarioLevel, ScenarioLevelSpec


class DriftLevel(ScenarioLevel):
    scenario = ScenarioLevelSpec(
        name="horizontal_travel_flat_descend",
        start_x=0.0,
        target_x=900.0,
        spawn_clearance=100.0,
        terrain_kind="flat",
        terrain_base=0.0,
        target_mode="flush_flatten",
        target_offset_y=0.0,
        target_size=100.0,
    )
    default_bot_name = "drift"


def create_level() -> Level:
    return DriftLevel()
