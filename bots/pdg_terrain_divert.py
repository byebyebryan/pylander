from __future__ import annotations

import math
from dataclasses import dataclass

from core.bot import Sensors, TerrainBoundary
from core.config import GRAVITY

_GRAVITY_MAG = abs(float(GRAVITY))


@dataclass(frozen=True)
class TerrainDivertProbe:
    active: bool
    mode: str | None = None
    min_margin: float | None = None
    first_limit_t: float | None = None
    worst_x: float | None = None
    worst_y: float | None = None
    horizon_s: float = 0.0
    sample_count: int = 0


@dataclass(frozen=True)
class TerrainDivertPrefilter:
    should_probe: bool = False
    overshoot: float = 0.0
    outward_vx: float = 0.0
    worst_x: float | None = None
    worst_y: float | None = None
    first_limit_t: float | None = None


def _terrain_probe_enabled(bot) -> bool:
    cfg = getattr(bot, "_cfg", None)
    if cfg is None or not bool(getattr(cfg, "terrain_divert_enable", False)):
        return False
    environment = getattr(bot, "environment", None)
    if environment is None:
        return False
    return (
        getattr(environment, "terrain", None) is not None
        and getattr(environment, "target", None) is not None
        and getattr(environment, "terrain_summary", None) is not None
    )


def _body_clearance(bot) -> float:
    vehicle_info = getattr(bot, "vehicle_info", None)
    if vehicle_info is None:
        return 0.0
    cfg = bot._cfg
    body_margin = max(0.0, float(getattr(cfg, "terrain_divert_body_margin", 0.0)))
    return max(0.0, (0.5 * float(vehicle_info.height)) + body_margin)


def _projected_landing_x(bot, projected_dx: float | None) -> float | None:
    if projected_dx is None:
        return None
    target = getattr(getattr(bot, "environment", None), "target", None)
    if target is None:
        return None
    return float(target.x) - float(projected_dx)


def _boundary_for_direction(bot, direction: int) -> TerrainBoundary | None:
    summary = getattr(getattr(bot, "environment", None), "terrain_summary", None)
    if summary is None:
        return None
    return summary.right_boundary if direction > 0 else summary.left_boundary


def _boundary_supports_containment(bot, boundary: TerrainBoundary | None) -> bool:
    if boundary is None:
        return False
    cfg = getattr(bot, "_cfg", None)
    if cfg is None:
        return False
    return (
        float(boundary.steepness)
        >= float(getattr(cfg, "terrain_divert_min_boundary_steepness", 0.0))
        and float(boundary.tail_steepness)
        <= float(getattr(cfg, "terrain_divert_max_boundary_tail_steepness", 0.0))
    )


@dataclass(frozen=True)
class _ContainmentState:
    direction: int
    boundary: TerrainBoundary
    corridor_x: float
    projected_landing_x: float
    overshoot: float
    outward_vx: float
    first_limit_t: float | None


def _containment_state(
    bot,
    *,
    passive: Sensors,
    projected_dx: float | None,
) -> _ContainmentState | None:
    if not _terrain_probe_enabled(bot):
        return None
    target = bot.environment.target
    if target is None:
        return None
    projected_landing_x = _projected_landing_x(bot, projected_dx)
    if projected_landing_x is None:
        return None
    landing_delta = float(projected_landing_x) - float(target.x)
    if abs(landing_delta) <= 1e-6:
        vx = float(passive.vx)
        if abs(vx) <= 1e-6:
            return None
        direction = 1 if vx > 0.0 else -1
    else:
        direction = 1 if landing_delta > 0.0 else -1
    boundary = _boundary_for_direction(bot, direction)
    if not _boundary_supports_containment(bot, boundary):
        return None

    body_clearance = _body_clearance(bot)
    corridor_x = float(boundary.x) - (direction * body_clearance)
    overshoot = max(
        0.0,
        direction * (float(projected_landing_x) - float(corridor_x)),
    )
    outward_vx = max(0.0, direction * float(passive.vx))
    if overshoot <= 0.0 and outward_vx <= 0.0:
        return None

    first_limit_t: float | None = None
    if outward_vx > 1e-6:
        boundary_distance = max(0.0, direction * (float(corridor_x) - float(passive.x)))
        first_limit_t = boundary_distance / outward_vx

    return _ContainmentState(
        direction=direction,
        boundary=boundary,
        corridor_x=float(corridor_x),
        projected_landing_x=float(projected_landing_x),
        overshoot=float(overshoot),
        outward_vx=float(outward_vx),
        first_limit_t=first_limit_t,
    )


def prefilter_terrain_divert(
    bot,
    *,
    passive: Sensors,
    projected_dx: float | None,
) -> TerrainDivertPrefilter:
    if not _terrain_probe_enabled(bot):
        return TerrainDivertPrefilter()
    summary = getattr(getattr(bot, "environment", None), "terrain_summary", None)
    if summary is None:
        return TerrainDivertPrefilter()
    if not (
        _boundary_supports_containment(bot, summary.left_boundary)
        or _boundary_supports_containment(bot, summary.right_boundary)
    ):
        return TerrainDivertPrefilter()
    target = bot.environment.target
    if target is None or projected_dx is None:
        return TerrainDivertPrefilter()
    arm_overshoot = float(bot._cfg.terrain_divert_arm_overshoot)
    target_half = max(0.0, 0.5 * float(getattr(target, "size", 0.0) or 0.0))
    projected_abs_dx = abs(float(projected_dx))
    outward_speed = abs(float(passive.vx))
    if projected_abs_dx <= (target_half + arm_overshoot) and outward_speed < float(
        bot._cfg.terrain_divert_arm_vx
    ):
        return TerrainDivertPrefilter()

    state = _containment_state(bot, passive=passive, projected_dx=projected_dx)
    if state is None:
        return TerrainDivertPrefilter()
    cfg = bot._cfg
    arm_overshoot = float(cfg.terrain_divert_arm_overshoot)
    arm_vx = float(cfg.terrain_divert_arm_vx)
    should_probe = state.overshoot >= arm_overshoot or state.outward_vx >= arm_vx
    worst_x = (
        max(state.corridor_x, state.projected_landing_x)
        if state.direction > 0
        else min(state.corridor_x, state.projected_landing_x)
    )
    return TerrainDivertPrefilter(
        should_probe=should_probe,
        overshoot=float(state.overshoot),
        outward_vx=float(state.outward_vx),
        worst_x=float(worst_x),
        worst_y=float(state.boundary.height),
        first_limit_t=state.first_limit_t,
    )


def evaluate_terrain_divert_probe(
    bot,
    *,
    passive: Sensors,
    projected_dx: float | None,
    max_thrust_accel: float,
) -> TerrainDivertProbe:
    del max_thrust_accel
    prefilter = prefilter_terrain_divert(bot, passive=passive, projected_dx=projected_dx)
    if not prefilter.should_probe:
        return TerrainDivertProbe(active=False)
    cfg = bot._cfg
    min_margin = float(cfg.terrain_divert_arm_overshoot) - prefilter.overshoot
    return TerrainDivertProbe(
        active=True,
        mode="lateral_containment",
        min_margin=float(min_margin),
        first_limit_t=prefilter.first_limit_t,
        worst_x=prefilter.worst_x,
        worst_y=prefilter.worst_y,
        horizon_s=max(0.0, float(prefilter.first_limit_t or 0.0)),
        sample_count=1,
    )


def backstop_containment_override(
    bot,
    *,
    passive: Sensors,
    projected_dx: float | None,
    max_thrust_accel: float,
) -> tuple[float, float] | None:
    state = _containment_state(bot, passive=passive, projected_dx=projected_dx)
    if state is None:
        return None
    if state.outward_vx <= 0.0 or state.overshoot <= 0.0:
        return None

    cfg = bot._cfg
    if (
        state.overshoot <= float(cfg.terrain_divert_release_overshoot)
        and state.outward_vx <= float(cfg.terrain_divert_release_vx)
    ):
        return None

    inward_mag = min(
        float(cfg.terrain_divert_bias_max),
        (float(cfg.terrain_divert_bias_per_meter) * state.overshoot)
        + (float(cfg.terrain_divert_containment_vx_gain) * state.outward_vx),
    )
    desired_ay = min(
        float(max_thrust_accel),
        _GRAVITY_MAG + float(cfg.terrain_divert_containment_net_up),
    )
    lateral_sq = max(0.0, (float(max_thrust_accel) ** 2) - (desired_ay**2))
    inward_mag = min(inward_mag, math.sqrt(lateral_sq))
    if inward_mag < 1e-3:
        return None

    return (-state.direction * inward_mag, desired_ay)


__all__ = [
    "TerrainDivertPrefilter",
    "TerrainDivertProbe",
    "backstop_containment_override",
    "evaluate_terrain_divert_probe",
    "prefilter_terrain_divert",
]
