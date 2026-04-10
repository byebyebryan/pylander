from __future__ import annotations

import math
from typing import Any

from game.core.bot import BoostCutoffMetrics
from game.core.components import PhysicsState, Transform
from game.core.config import GRAVITY_MAG
from game.core.ecs import require_component
from game.core.level_capabilities import level_name_tag
from game.core.maths import Vector2


def build_boost_cutoff_metrics_from_state(
    *,
    x: float,
    y: float,
    vx: float,
    vy_up: float,
    altitude: float,
    target_x: float,
    target_y: float,
) -> BoostCutoffMetrics:
    dx = float(target_x) - float(x)
    dy = float(target_y) - float(y)
    vy_pos = max(0.0, float(vy_up))
    apex_y = float(y)
    if GRAVITY_MAG > 1e-6:
        apex_y += (vy_pos * vy_pos) / (2.0 * GRAVITY_MAG)
    projected_apex_over_target = apex_y - float(target_y)

    has_target_y_solution = True
    projected_impact_dx: float | None = None
    projected_impact_angle_deg: float | None = None
    t_cross: float | None = None

    if GRAVITY_MAG <= 1e-6:
        if abs(float(vy_up)) > 1e-6:
            t_cross = dy / float(vy_up)
        elif abs(dy) <= 1e-6:
            t_cross = 0.0
        else:
            has_target_y_solution = False
    else:
        disc = (float(vy_up) * float(vy_up)) - (2.0 * GRAVITY_MAG * dy)
        if disc < 0.0:
            has_target_y_solution = False
        else:
            sqrt_disc = math.sqrt(max(0.0, disc))
            roots = sorted(
                (
                    (float(vy_up) - sqrt_disc) / GRAVITY_MAG,
                    (float(vy_up) + sqrt_disc) / GRAVITY_MAG,
                )
            )
            positive = [value for value in roots if value >= 0.0]
            if positive:
                if dy >= 0.0 and len(positive) >= 2:
                    t_cross = positive[-1]
                else:
                    future = [value for value in positive if value > 1e-4]
                    t_cross = future[0] if future else positive[0]
            else:
                has_target_y_solution = False

    if has_target_y_solution and t_cross is not None:
        projected_impact_dx = dx - (float(vx) * float(t_cross))
        vy_down = abs(float(vy_up) - (GRAVITY_MAG * max(0.0, float(t_cross))))
        projected_impact_angle_deg = math.degrees(math.atan2(vy_down, abs(float(vx))))

    return BoostCutoffMetrics(
        time_s=0.0,
        altitude=max(0.0, float(altitude)),
        x=float(x),
        y=float(y),
        vx=float(vx),
        vy_up=float(vy_up),
        projected_apex_y=apex_y,
        projected_apex_over_target=projected_apex_over_target,
        has_target_y_solution=has_target_y_solution,
        projected_dx=projected_impact_dx,
        projected_impact_dx=projected_impact_dx,
        projected_impact_angle_deg=projected_impact_angle_deg,
        burn_duration_s=0.0,
        burn_fuel_used=0.0,
        burn_avg_thrust_level=0.0,
    )


def prime_boost_cutoff_for_primary_bot(level, actor_bots: dict[str, Any]) -> None:
    if level_name_tag(level) != "terminal":
        return
    world = getattr(level, "world", None)
    if world is None or not getattr(world, "actors", None):
        return
    actor = world.actors[0]
    bot = actor_bots.get(actor.uid)
    if bot is None:
        return

    target_pos = level.ensure_runtime_context().eval_target_pos
    if not isinstance(target_pos, Vector2):
        return

    trans = require_component(actor, Transform)
    phys = require_component(actor, PhysicsState)
    altitude = float(trans.pos.y) - float(level.terrain(float(trans.pos.x), lod=0))
    bot.prime_boost_cutoff(
        build_boost_cutoff_metrics_from_state(
            x=float(trans.pos.x),
            y=float(trans.pos.y),
            vx=float(phys.vel.x),
            vy_up=float(phys.vel.y),
            altitude=altitude,
            target_x=float(target_pos.x),
            target_y=float(target_pos.y),
        )
    )
