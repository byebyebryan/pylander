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
_TARGET_PAD_BACKSTOP_CLEARANCE = 75.0


@dataclass(frozen=True)
class _ResolvedObstacle:
    kind: str
    placement: str
    center_x: float
    support_x0: float
    support_x1: float
    top_x0: float
    top_x1: float
    left_shoulder_width: float
    right_shoulder_width: float
    height_offset: float
    profile_points: tuple[tuple[float, float], ...] = ()


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
    points: tuple[tuple[float, float], ...], *, max_points: int = 8
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
    """Execution-guardrail terrain scenarios for reactive v1 work."""

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

    def _resolve_backstop(self, scenario, *, dest_x: float) -> _ResolvedObstacle:  # noqa: ANN001
        obstacle = scenario.obstacle
        route_dx = max(1e-6, float(dest_x) - float(SOURCE_PAD_X))
        route_dy = float(scenario.route_dy)
        ramp_start = route_dx + max(
            _TARGET_PAD_BACKSTOP_CLEARANCE, float(obstacle.target_offset)
        )
        top_x0 = ramp_start + max(20.0, float(obstacle.shoulder_width))
        top_x1 = top_x0 + float(obstacle.top_width)
        center_x = 0.5 * (top_x0 + top_x1)
        plateau_y = route_dy + abs(float(obstacle.height_offset))
        profile_points = (
            (0.0, 0.0),
            (route_dx, route_dy),
            (ramp_start, route_dy),
            (top_x0, plateau_y),
            (top_x1, plateau_y),
            (top_x1 + 1.0, plateau_y),
        )
        return _ResolvedObstacle(
            kind=str(obstacle.kind),
            placement=str(obstacle.placement),
            center_x=float(center_x),
            support_x0=float(ramp_start),
            support_x1=float(top_x1 + 1.0),
            top_x0=float(top_x0),
            top_x1=float(top_x1),
            left_shoulder_width=float(top_x0 - ramp_start),
            right_shoulder_width=0.0,
            height_offset=float(plateau_y - route_dy),
            profile_points=profile_points,
        )

    def _resolve_clip(
        self, scenario, *, dest_x: float
    ) -> _ResolvedObstacle:  # noqa: ANN001
        obstacle = scenario.obstacle
        if scenario.family != "downhill":
            raise ValueError("Reactive v1 clip terrain is only defined for downhill cases")
        route_dx = max(1e-6, float(dest_x) - float(SOURCE_PAD_X))
        route_dy = float(scenario.route_dy)
        top_width = float(obstacle.top_width)
        support_x1 = route_dx - max(_PAD_CLEARANCE, float(obstacle.target_offset))
        support_x0 = support_x1 - top_width
        min_support_x0 = _PAD_CLEARANCE
        if support_x0 < min_support_x0:
            shift = min_support_x0 - support_x0
            support_x0 += shift
            support_x1 += shift
        max_support_x1 = route_dx - _PAD_CLEARANCE
        if support_x1 > max_support_x1:
            shift = support_x1 - max_support_x1
            support_x0 -= shift
            support_x1 -= shift
        if support_x0 >= support_x1:
            center_x = 0.5 * route_dx
            support_x0 = center_x - 0.5 * top_width
            support_x1 = center_x + 0.5 * top_width
        top_x0 = support_x0
        top_x1 = support_x1
        center_x = 0.5 * (top_x0 + top_x1)
        plateau_y = route_dy + abs(float(obstacle.height_offset))
        profile_points = (
            (0.0, 0.0),
            (top_x0, plateau_y),
            (top_x1, plateau_y),
            (route_dx, route_dy),
        )
        return _ResolvedObstacle(
            kind=str(obstacle.kind),
            placement=str(obstacle.placement),
            center_x=float(center_x),
            support_x0=float(top_x0),
            support_x1=float(top_x1),
            top_x0=float(top_x0),
            top_x1=float(top_x1),
            left_shoulder_width=0.0,
            right_shoulder_width=0.0,
            height_offset=float(
                plateau_y
                - (self._scenario_slope(scenario, dest_x=dest_x) * center_x)
            ),
            profile_points=profile_points,
        )

    def _resolve_follow(
        self, scenario, *, dest_x: float
    ) -> _ResolvedObstacle:  # noqa: ANN001
        obstacle = scenario.obstacle
        route_dx = max(1e-6, float(dest_x) - float(SOURCE_PAD_X))
        route_dy = float(scenario.route_dy)
        if scenario.family != "flat":
            raise ValueError("Reactive v1 follow terrain is only defined for flat cases")
        amplitude = max(1.0, abs(float(obstacle.height_offset)))
        scaled_points: list[tuple[float, float]] = [(0.0, 0.0)]
        last_x = 0.0
        for x_frac, y_frac in obstacle.anchor_points:
            px = min(
                max(float(x_frac) * route_dx, _PAD_CLEARANCE),
                route_dx - _PAD_CLEARANCE,
            )
            px = max(px, last_x + 1.0)
            py = max(0.0, float(y_frac) * amplitude)
            scaled_points.append((float(px), float(py)))
            last_x = px
        scaled_points.append((route_dx, route_dy))
        support_start_idx = 1
        support_end_idx = len(scaled_points) - 2
        if support_end_idx < support_start_idx:
            raise ValueError("Reactive follow terrain requires at least one interior anchor point")
        top_idx = max(
            range(support_start_idx, support_end_idx + 1),
            key=lambda idx: scaled_points[idx][1]
            - (route_dy / route_dx) * scaled_points[idx][0],
        )
        center_x, center_y = scaled_points[top_idx]
        top_left_idx = max(support_start_idx, top_idx - 1)
        top_right_idx = min(support_end_idx, top_idx + 1)
        return _ResolvedObstacle(
            kind=str(obstacle.kind),
            placement=str(obstacle.placement),
            center_x=float(center_x),
            support_x0=float(scaled_points[support_start_idx][0]),
            support_x1=float(scaled_points[support_end_idx][0]),
            top_x0=float(scaled_points[top_left_idx][0]),
            top_x1=float(scaled_points[top_right_idx][0]),
            left_shoulder_width=float(center_x - scaled_points[top_left_idx][0]),
            right_shoulder_width=float(
                scaled_points[top_right_idx][0] - center_x
            ),
            height_offset=float(
                center_y - (self._scenario_slope(scenario, dest_x=dest_x) * center_x)
            ),
            profile_points=tuple(scaled_points),
        )

    def _resolve_obstacle(self, scenario, *, dest_x: float) -> _ResolvedObstacle:  # noqa: ANN001
        obstacle = scenario.obstacle
        if obstacle.kind == "backstop":
            return self._resolve_backstop(scenario, dest_x=dest_x)
        if obstacle.kind == "shoulder" and obstacle.placement == "terminal":
            return self._resolve_clip(scenario, dest_x=dest_x)
        if obstacle.kind == "follow" and obstacle.placement == "route":
            return self._resolve_follow(scenario, dest_x=dest_x)
        raise ValueError(
            f"Unsupported terrain obstacle '{obstacle.kind}:{obstacle.placement}' for reactive v1"
        )

    def _build_base_terrain(self, seed: int):
        _ = seed
        scenario = self._active_scenario()
        dest_x = getattr(self, "_sampled_dest_x", None)
        if dest_x is None:
            raise RuntimeError("TerrainLevel dest_x was not resolved before terrain build")
        resolved = self._resolve_obstacle(scenario, dest_x=float(dest_x))

        def height_fn(x: float) -> float:
            xx = float(x)
            return _piecewise_linear_height(xx, resolved.profile_points)

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
            "obstacle_profile_mode": "piecewise",
            "avoidance_band": scenario.avoidance_band,
            "reactive_contract": scenario.reactive_contract,
            "hazard_driver": scenario.hazard_driver,
            "reactive_trigger": scenario.reactive_trigger,
            "resume_without_replan": scenario.resume_without_replan,
            "primary_navigation_owner": scenario.primary_navigation_owner,
            "nominal_route_must_clear": scenario.nominal_route_must_clear,
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
