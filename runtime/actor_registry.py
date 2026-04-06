"""Actor enumeration and role queries."""

from __future__ import annotations

from typing import cast

from core.components import ActorControlRole
from core.ecs import Entity
from core.level import Level


def collect_actor_entities(level: Level) -> list[Entity]:
    world = level.world
    if world is None:
        return []
    actors = cast(list[Entity], list(getattr(world, "actors", []) or []))
    if not actors and getattr(world, "lander", None) is not None:
        actors = [cast(Entity, world.lander)]
    return actors


def get_actor_control_role(entity: Entity) -> str:
    role = entity.get_component(ActorControlRole)
    if role is None:
        return "none"
    return role.role


def find_first_actor_for_role(actors: list[Entity], role: str) -> str | None:
    for actor in actors:
        if get_actor_control_role(actor) == role:
            return actor.uid
    return None
