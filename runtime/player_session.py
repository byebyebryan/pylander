"""Player/actor session management."""

from __future__ import annotations

from typing import TYPE_CHECKING

from core.components import PlayerControlled, PlayerSelectable
from core.ecs import Entity, World
from core.level import Level

if TYPE_CHECKING:
    from core.physics import PhysicsEngine


def set_active_actor(
    *,
    actors: list[Entity],
    ecs_world: World,
    level: Level,
    engine: PhysicsEngine,
    uid: str,
) -> Entity | None:
    actor = ecs_world.get_entity_by_id(uid)
    if actor is None:
        return None
    for item in actors:
        marker = item.get_component(PlayerControlled)
        is_active = item.uid == uid
        if marker is None and is_active:
            item.add_component(PlayerControlled(active=True))
        elif marker is not None:
            marker.active = is_active
    if level.world is not None:
        level.world.primary_actor_uid = uid
        level.world.lander = actor
    engine.set_primary_actor(uid)
    return actor


def switch_active_actor(
    *,
    actors: list[Entity],
    ecs_world: World,
    level: Level,
    engine: PhysicsEngine,
    active_uid: str,
    delta: int = 1,
) -> tuple[str, Entity] | None:
    selectable: list[tuple[int, str]] = []
    for actor in actors:
        marker = actor.get_component(PlayerSelectable)
        if marker is not None:
            selectable.append((marker.order, actor.uid))
    if not selectable:
        return None
    selectable.sort(key=lambda item: item[0])
    ordered_ids = [uid for _, uid in selectable]
    if active_uid not in ordered_ids:
        next_uid = ordered_ids[0]
    else:
        idx = ordered_ids.index(active_uid)
        next_uid = ordered_ids[(idx + delta) % len(ordered_ids)]
    actor = set_active_actor(
        actors=actors,
        ecs_world=ecs_world,
        level=level,
        engine=engine,
        uid=next_uid,
    )
    if actor is None:
        return None
    return next_uid, actor


__all__ = [
    "set_active_actor",
    "switch_active_actor",
]
