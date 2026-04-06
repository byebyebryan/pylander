"""Terrain query and boundary detection for bot environment setup."""

from __future__ import annotations

from dataclasses import dataclass
from math import fabs
from typing import Any

from core.bot import BotEnvironment, BotTerrainSummary, TerrainBoundary
from core.config import GRAVITY
from core.ecs import Entity, require_component
from core.level_capabilities import level_name_tag, level_scenario_tag
from core.maths import Vector2
from core.terrain import (
    anchored_profile,
    estimate_terrain_slope,
    sample_terrain_height,
    terrain_resolution,
)
from runtime.sensors import resolve_eval_target

_BOT_TERRAIN_SUMMARY_HEIGHT_THRESHOLD = 30.0
_BOT_TERRAIN_SUMMARY_MIN_DISTANCE = 4096.0
_BOT_TERRAIN_SUMMARY_STEEPNESS_WINDOW = 40.0


@dataclass(frozen=True)
class _TerrainQueryAdapter:
    terrain: Any

    def sample_height(self, x: float, lod: int = 0) -> float:
        return sample_terrain_height(self.terrain, x, lod=lod)

    def sample_slope(self, x: float, lod: int = 0) -> float:
        return estimate_terrain_slope(self.terrain, x, lod=lod)

    def profile(
        self,
        x0: float,
        x1: float,
        *,
        step: float,
        lod: int = 0,
    ) -> list[tuple[float, float]]:
        return anchored_profile(self.terrain, x0, x1, step=step, lod=lod)

    def resolution(self, lod: int = 0) -> float:
        return terrain_resolution(self.terrain, lod=lod)


def _find_elevated_boundary(
    terrain: Any,
    *,
    target_x: float,
    target_ground_y: float,
    direction: int,
    height_threshold: float,
    search_distance: float,
) -> TerrainBoundary | None:
    resolution = max(0.5, terrain_resolution(terrain, lod=0))
    threshold_y = target_ground_y + height_threshold
    sample_count = max(1, int(search_distance / resolution))
    for sample_idx in range(1, sample_count + 1):
        sample_x = target_x + (direction * resolution * sample_idx)
        sample_y = float(sample_terrain_height(terrain, sample_x, lod=0))
        if sample_y > threshold_y:
            steepness = 0.0
            window = max(_BOT_TERRAIN_SUMMARY_STEEPNESS_WINDOW, resolution)
            edge_x = sample_x + (direction * window)
            edge_y = float(sample_terrain_height(terrain, edge_x, lod=0))
            rise = max(0.0, edge_y - sample_y)
            steepness = rise / max(window, 1e-6)
            tail_edge_x = edge_x + (direction * window)
            tail_edge_y = float(sample_terrain_height(terrain, tail_edge_x, lod=0))
            tail_rise = max(0.0, tail_edge_y - edge_y)
            tail_steepness = tail_rise / max(window, 1e-6)
            return TerrainBoundary(
                direction=direction,
                x=sample_x,
                height=sample_y,
                steepness=float(steepness),
                tail_steepness=float(tail_steepness),
            )
    return None


def _build_terrain_summary(
    *,
    terrain: Any,
    start_pos: Vector2,
    target: Any,
) -> BotTerrainSummary:
    target_x = float(target.x)
    search_distance = max(
        _BOT_TERRAIN_SUMMARY_MIN_DISTANCE,
        abs(float(start_pos.x) - target_x) + 2048.0,
    )
    target_ground_y = float(sample_terrain_height(terrain, target_x, lod=0))
    height_threshold = _BOT_TERRAIN_SUMMARY_HEIGHT_THRESHOLD
    return BotTerrainSummary(
        target_ground_y=target_ground_y,
        height_threshold=height_threshold,
        left_boundary=_find_elevated_boundary(
            terrain,
            target_x=target_x,
            target_ground_y=target_ground_y,
            direction=-1,
            height_threshold=height_threshold,
            search_distance=search_distance,
        ),
        right_boundary=_find_elevated_boundary(
            terrain,
            target_x=target_x,
            target_ground_y=target_ground_y,
            direction=1,
            height_threshold=height_threshold,
            search_distance=search_distance,
        ),
    )


def build_bot_environment(*, level: Any, actor: Entity) -> BotEnvironment | None:
    terrain = getattr(level, "terrain", None)
    if terrain is None:
        return None
    from core.components import Transform

    trans = require_component(actor, Transform)
    start_pos = Vector2(getattr(actor, "start_pos", trans.pos))
    target = resolve_eval_target(level, level.sites, start_pos)
    terrain_summary = (
        _build_terrain_summary(terrain=terrain, start_pos=start_pos, target=target)
        if target is not None
        else None
    )
    scenario_params = getattr(level, "_scenario_params", None)
    env_params: dict[str, float | int | str | bool] | None = None
    if isinstance(scenario_params, dict):
        env_params = {
            str(key): value
            for key, value in scenario_params.items()
            if isinstance(value, (float, int, str, bool))
        }
    return BotEnvironment(
        terrain=_TerrainQueryAdapter(terrain),
        gravity_mag=fabs(float(GRAVITY)),
        target=target,
        terrain_summary=terrain_summary,
        level_name=level_name_tag(level),
        scenario_name=level_scenario_tag(level) or None,
        scenario_params=env_params,
    )
