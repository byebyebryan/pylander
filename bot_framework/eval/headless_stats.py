from __future__ import annotations

import math
from typing import Any

from game.core.components import Engine, FuelTank, PhysicsState, Transform
from game.core.ecs import require_component


def build_headless_stats(entity, terrain) -> str:
    trans = require_component(entity, Transform)
    phys = require_component(entity, PhysicsState)
    eng = require_component(entity, Engine)
    tank = require_component(entity, FuelTank)
    _ = terrain
    angle_deg = math.degrees(trans.rotation)
    thrust_pct = eng.thrust_level * 100.0
    fuel_pct = 100.0 * tank.fuel / max(1e-6, tank.max_fuel)
    return (
        "ship "
        f"x={trans.pos.x:6.1f} "
        f"y={trans.pos.y:6.1f} "
        f"vx={phys.vel.x:6.2f} "
        f"vy={phys.vel.y:6.2f} "
        f"ang={angle_deg:5.1f} "
        f"thr={thrust_pct:3.0f}% "
        f"fuel={fuel_pct:5.1f}%"
    )


def print_headless_stats(
    *,
    elapsed_time: float,
    active_actor: Any,
    terrain: Any,
    actor_bots: dict[str, Any],
) -> None:
    parts = [f"t={elapsed_time:6.2f}"]
    parts.append(build_headless_stats(active_actor, terrain))
    for bot in actor_bots.values():
        if hasattr(bot, "get_headless_stats"):
            bot_str = bot.get_headless_stats()
            if bot_str:
                parts.append(bot_str)
    print(" | ".join(parts))
