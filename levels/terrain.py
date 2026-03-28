from __future__ import annotations

from dataclasses import dataclass

import core.terrain as _terrain
from core.level import Level
from levels.boost_transfer import SOURCE_PAD_X, BoostTransferLevel, build_boost_weight_params
from levels.common_scenarios import (
    has_randomized_values,
    is_ranged_value,
    resolve_sample_value,
)
from levels.terrain_catalog import (
    TERRAIN_DEFAULT_SCENARIO,
    TERRAIN_QUICK_SCENARIOS,
    TERRAIN_SCENARIO_BY_NAME,
    TERRAIN_SMOKE_SCENARIOS,
)


_PAD_CLEARANCE = 85.0


@dataclass(frozen=True)
class _ResolvedObstacle:
    kind: str
    placement: str
    profile_mode: str
    center_x: float
    support_x0: float
    support_x1: float
    top_x0: float
    top_x1: float
    left_shoulder_width: float
    right_shoulder_width: float
    height_offset: float
    profile_points: tuple[tuple[float, float], ...] = ()


def _trapezoid_height(x: float, obstacle: _ResolvedObstacle) -> float:
    if x <= obstacle.support_x0 or x >= obstacle.support_x1:
        return 0.0
    if x < obstacle.top_x0:
        span = max(1e-6, obstacle.left_shoulder_width)
        t = (x - obstacle.support_x0) / span
        return obstacle.height_offset * t
    if x <= obstacle.top_x1:
        return obstacle.height_offset
    span = max(1e-6, obstacle.right_shoulder_width)
    t = (obstacle.support_x1 - x) / span
    return obstacle.height_offset * t


def _lerp(x0: float, y0: float, x1: float, y1: float, x: float) -> float:
    if abs(x1 - x0) <= 1e-9:
        return y0
    t = (x - x0) / (x1 - x0)
    return (y0 * (1.0 - t)) + (y1 * t)


def _piecewise_linear_height(
    x: float, points: tuple[tuple[float, float], ...]
) -> float:
    if not points:
        return 0.0
    if len(points) == 1:
        return points[0][1]
    if x <= points[0][0]:
        (x0, y0), (x1, y1) = points[0], points[1]
        return _lerp(x0, y0, x1, y1, x)
    for (x0, y0), (x1, y1) in zip(points, points[1:], strict=False):
        if x <= x1:
            return _lerp(x0, y0, x1, y1, x)
    (x0, y0), (x1, y1) = points[-2], points[-1]
    return _lerp(x0, y0, x1, y1, x)


def _profile_param_items(
    points: tuple[tuple[float, float], ...], *, max_points: int = 6
) -> dict[str, float]:
    out: dict[str, float] = {
        "obstacle_profile_point_count": float(len(points)),
    }
    for idx in range(max_points):
        if idx < len(points):
            px, py = points[idx]
            out[f"obstacle_profile_p{idx}_x"] = float(px)
            out[f"obstacle_profile_p{idx}_y"] = float(py)
        else:
            out[f"obstacle_profile_p{idx}_x"] = 0.0
            out[f"obstacle_profile_p{idx}_y"] = 0.0
    return out


def _sample_profile_points(
    terrain, points: tuple[tuple[float, float], ...]
) -> tuple[tuple[float, float], ...]:
    if terrain is None or not points:
        return points
    sampled: list[tuple[float, float]] = []
    for px, _py in points:
        sampled.append((float(px), float(terrain(float(px), lod=0))))
    return tuple(sampled)


class TerrainLevel(BoostTransferLevel):
    """Reactive terrain-transfer scenario root for manual plotting and setup work."""

    _scenario_by_name = TERRAIN_SCENARIO_BY_NAME
    _default_scenario_name = TERRAIN_DEFAULT_SCENARIO
    _smoke_benchmark_scenarios = TERRAIN_SMOKE_SCENARIOS
    _quick_benchmark_scenarios = TERRAIN_QUICK_SCENARIOS
    _benchmark_policy = "observe_only"

    def scenario_has_randomized_fields(self, _name: str | None = None) -> bool:
        scenario = self._active_scenario()
        return has_randomized_values((scenario.route_dx,))

    @staticmethod
    def _scenario_dx(scenario, *, dest_x: float | None = None) -> float:  # noqa: ANN001
        if dest_x is not None:
            return max(1e-6, float(dest_x) - float(SOURCE_PAD_X))
        route_dx = scenario.route_dx
        if is_ranged_value(route_dx):
            return max(1e-6, route_dx.median())
        return max(1e-6, float(route_dx))

    @classmethod
    def _scenario_slope(cls, scenario, *, dest_x: float | None = None) -> float:  # noqa: ANN001
        if scenario.family == "flat":
            return 0.0
        return float(scenario.route_dy) / cls._scenario_dx(scenario, dest_x=dest_x)

    def _resolve_obstacle(self, scenario, *, dest_x: float) -> _ResolvedObstacle:  # noqa: ANN001
        obstacle = scenario.obstacle
        route_dx = max(1e-6, float(dest_x) - float(SOURCE_PAD_X))
        route_dy = float(scenario.route_dy)
        slope = self._scenario_slope(scenario, dest_x=dest_x)
        left_shoulder_width = float(
            obstacle.left_shoulder_width
            if obstacle.left_shoulder_width is not None
            else obstacle.shoulder_width
        )
        right_shoulder_width = float(
            obstacle.right_shoulder_width
            if obstacle.right_shoulder_width is not None
            else obstacle.shoulder_width
        )
        if obstacle.kind == "shoulder":
            if obstacle.placement == "boost":
                if scenario.family == "climb":
                    plateau_start = min(
                        max(float(obstacle.x_fraction) * route_dx, _PAD_CLEARANCE),
                        route_dx - _PAD_CLEARANCE - float(obstacle.top_width),
                    )
                    plateau_end = min(
                        route_dx - _PAD_CLEARANCE,
                        plateau_start + float(obstacle.top_width),
                    )
                    ramp_start = max(
                        _PAD_CLEARANCE,
                        plateau_start - max(20.0, float(obstacle.shoulder_width)),
                    )
                    center_x = 0.5 * (plateau_start + plateau_end)
                    plateau_y = (slope * center_x) + abs(float(obstacle.height_offset))
                    profile_points = (
                        (0.0, 0.0),
                        (ramp_start, slope * ramp_start),
                        (plateau_start, plateau_y),
                        (plateau_end, plateau_y),
                        (route_dx, route_dy),
                    )
                    return _ResolvedObstacle(
                        kind=str(obstacle.kind),
                        placement=str(obstacle.placement),
                        profile_mode="piecewise",
                        center_x=float(center_x),
                        support_x0=float(ramp_start),
                        support_x1=float(plateau_end),
                        top_x0=float(plateau_start),
                        top_x1=float(plateau_end),
                        left_shoulder_width=float(plateau_start - ramp_start),
                        right_shoulder_width=float(route_dx - plateau_end),
                        height_offset=float(plateau_y - (slope * center_x)),
                        profile_points=profile_points,
                    )
                anchor_x = min(
                    max(float(obstacle.x_fraction) * route_dx, _PAD_CLEARANCE),
                    route_dx - _PAD_CLEARANCE - float(obstacle.top_width),
                )
                flat_end_x = min(
                    route_dx - _PAD_CLEARANCE,
                    anchor_x + float(obstacle.top_width),
                )
                profile_points = (
                    (0.0, 0.0),
                    (anchor_x, 0.0),
                    (flat_end_x, 0.0),
                    (route_dx, route_dy),
                )
                center_x = 0.5 * (anchor_x + flat_end_x)
                return _ResolvedObstacle(
                    kind=str(obstacle.kind),
                    placement=str(obstacle.placement),
                    profile_mode="piecewise",
                    center_x=float(center_x),
                    support_x0=0.0,
                    support_x1=float(flat_end_x),
                    top_x0=float(anchor_x),
                    top_x1=float(flat_end_x),
                    left_shoulder_width=0.0,
                    right_shoulder_width=0.0,
                    height_offset=float(-(slope * center_x)),
                    profile_points=profile_points,
                )
            if scenario.family == "climb":
                top_half = 0.5 * float(obstacle.top_width)
                min_center = _PAD_CLEARANCE + top_half
                max_center = route_dx - _PAD_CLEARANCE - top_half
                desired_center = float(obstacle.x_fraction) * route_dx
                if max_center < min_center:
                    center_x = 0.5 * route_dx
                else:
                    center_x = min(max(desired_center, min_center), max_center)
                plateau_start = center_x - top_half
                plateau_end = center_x + top_half
                ramp_start = max(
                    _PAD_CLEARANCE,
                    plateau_start - max(20.0, float(obstacle.shoulder_width)),
                )
                plateau_y = (slope * center_x) + abs(float(obstacle.height_offset))
                profile_points = (
                    (0.0, 0.0),
                    (ramp_start, slope * ramp_start),
                    (plateau_start, plateau_y),
                    (plateau_end, plateau_y),
                    (route_dx, route_dy),
                )
                return _ResolvedObstacle(
                    kind=str(obstacle.kind),
                    placement=str(obstacle.placement),
                    profile_mode="piecewise",
                    center_x=float(center_x),
                    support_x0=float(ramp_start),
                    support_x1=float(plateau_end),
                    top_x0=float(plateau_start),
                    top_x1=float(plateau_end),
                    left_shoulder_width=float(plateau_start - ramp_start),
                    right_shoulder_width=float(route_dx - plateau_end),
                    height_offset=float(plateau_y - (slope * center_x)),
                    profile_points=profile_points,
                )
            top_half = 0.5 * float(obstacle.top_width)
            min_center = _PAD_CLEARANCE + top_half
            max_center = route_dx - _PAD_CLEARANCE - top_half
            desired_center = float(obstacle.x_fraction) * route_dx
            if max_center < min_center:
                center_x = 0.5 * route_dx
            else:
                center_x = min(max(desired_center, min_center), max_center)
            top_x0 = center_x - top_half
            top_x1 = center_x + top_half
            target_y = route_dy
            shoulder_delta = abs(float(obstacle.height_offset))
            plateau_y = (
                target_y + shoulder_delta
                if scenario.family == "downhill"
                else target_y - shoulder_delta
            )
            profile_points = (
                (0.0, 0.0),
                (top_x0, plateau_y),
                (top_x1, plateau_y),
                (route_dx, route_dy),
            )
            return _ResolvedObstacle(
                kind=str(obstacle.kind),
                placement=str(obstacle.placement),
                profile_mode="piecewise",
                center_x=float(center_x),
                support_x0=float(top_x0),
                support_x1=float(top_x1),
                top_x0=float(top_x0),
                top_x1=float(top_x1),
                left_shoulder_width=0.0,
                right_shoulder_width=0.0,
                height_offset=float(plateau_y - (slope * center_x)),
                profile_points=profile_points,
            )
        top_half = 0.5 * float(obstacle.top_width)
        min_center = _PAD_CLEARANCE + left_shoulder_width + top_half
        max_center = route_dx - _PAD_CLEARANCE - right_shoulder_width - top_half
        desired_center = float(obstacle.x_fraction) * route_dx
        if max_center < min_center:
            center_x = 0.5 * route_dx
        else:
            center_x = min(max(desired_center, min_center), max_center)
        top_x0 = center_x - top_half
        top_x1 = center_x + top_half
        support_x0 = top_x0 - left_shoulder_width
        support_x1 = top_x1 + right_shoulder_width
        return _ResolvedObstacle(
            kind=str(obstacle.kind),
            placement=str(obstacle.placement),
            profile_mode="trapezoid",
            center_x=float(center_x),
            support_x0=float(support_x0),
            support_x1=float(support_x1),
            top_x0=float(top_x0),
            top_x1=float(top_x1),
            left_shoulder_width=float(left_shoulder_width),
            right_shoulder_width=float(right_shoulder_width),
            height_offset=float(obstacle.height_offset),
        )

    def _build_base_terrain(self, seed: int):
        _ = seed
        scenario = self._active_scenario()
        dest_x = getattr(self, "_sampled_dest_x", None)
        if dest_x is None:
            raise RuntimeError("TerrainLevel dest_x was not resolved before terrain build")
        slope = self._scenario_slope(scenario, dest_x=dest_x)
        resolved = self._resolve_obstacle(scenario, dest_x=float(dest_x))

        def height_fn(x: float) -> float:
            xx = float(x)
            if resolved.profile_mode == "piecewise":
                return _piecewise_linear_height(xx, resolved.profile_points)
            base_y = slope * xx
            return base_y + _trapezoid_height(xx, resolved)

        return _terrain.LodGridGenerator(height_fn)

    def _resolve_dest_x(self, scenario, rng) -> float:  # noqa: ANN001
        dest_dx = resolve_sample_value(
            scenario.route_dx,
            mode="median" if self._benchmark_random_mode == "median" else "sample",
            rng=rng,
        )
        return SOURCE_PAD_X + dest_dx

    def _build_scenario_params(self, scenario, dest_x: float) -> dict:  # noqa: ANN001
        slope = self._scenario_slope(scenario, dest_x=dest_x)
        resolved = self._resolve_obstacle(scenario, dest_x=dest_x)
        terrain = None
        if self.world is not None:
            terrain = getattr(self.world, "terrain", None)
        sampled_profile_points = _sample_profile_points(terrain, resolved.profile_points)
        height_offset = float(resolved.height_offset)
        if terrain is not None:
            center_y = float(terrain(float(resolved.center_x), lod=0))
            height_offset = center_y - (slope * float(resolved.center_x))
        return {
            "family": scenario.family,
            "route_tier": scenario.route_tier,
            "terrain_kind": "terrain",
            "obstacle_case": scenario.obstacle_case,
            "obstacle_kind": resolved.kind,
            "obstacle_placement": resolved.placement,
            "obstacle_profile_mode": resolved.profile_mode,
            "avoidance_band": scenario.avoidance_band,
            "slope": slope,
            "dx": float(dest_x) - float(SOURCE_PAD_X),
            "dy": float(scenario.route_dy),
            "obstacle_center_x": resolved.center_x,
            "obstacle_support_x0": resolved.support_x0,
            "obstacle_support_x1": resolved.support_x1,
            "obstacle_top_x0": resolved.top_x0,
            "obstacle_top_x1": resolved.top_x1,
            "obstacle_left_shoulder_width": resolved.left_shoulder_width,
            "obstacle_right_shoulder_width": resolved.right_shoulder_width,
            "obstacle_height_offset": height_offset,
            **_profile_param_items(sampled_profile_points),
            **build_boost_weight_params(scenario),
        }


def create_level() -> Level:
    return TerrainLevel()
