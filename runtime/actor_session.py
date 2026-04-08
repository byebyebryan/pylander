"""Actor session management."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from core.bot import Bot
from core.components import PlayerControlled, PlayerSelectable
from core.ecs import Entity, World
from core.level import Level

if TYPE_CHECKING:
    from core.physics import PhysicsEngine

from runtime.actor_registry import find_first_actor_for_role
from runtime.sensors import build_vehicle_info
from runtime.terrain_intel import build_bot_environment


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


def active_actor_bot(
    *,
    actor_bots: dict[str, Bot],
    active_uid: str,
    primary_bot: Bot | None,
) -> Bot | None:
    if active_uid in actor_bots:
        return actor_bots[active_uid]
    return primary_bot


def ensure_bot_identity_fields(bot: Bot) -> None:
    if bot.get_identity_name():
        return
    bot.set_identity_name(bot.__class__.__module__.split(".")[-1])


def install_actor_bot(
    *,
    actor_bots: dict[str, Bot],
    ecs_world: World,
    level: Level,
    uid: str,
    bot: Bot,
) -> None:
    actor_bots[uid] = bot
    ensure_bot_identity_fields(bot)
    actor = ecs_world.get_entity_by_id(uid)
    if actor is None:
        return
    if hasattr(bot, "set_vehicle_info"):
        bot.set_vehicle_info(build_vehicle_info(actor))
    if hasattr(bot, "set_environment"):
        environment = build_bot_environment(level=level, actor=actor)
        if environment is not None:
            bot.set_environment(environment)


def attach_primary_bot(
    *,
    actors: list[Entity],
    actor_bots: dict[str, Bot],
    ecs_world: World,
    level: Level,
    active_uid: str,
    bot: Bot,
) -> None:
    bot_uid = find_first_actor_for_role(actors, "bot")
    if bot_uid is None:
        bot_uid = next((a.uid for a in actors if a.uid != active_uid), active_uid)
    install_actor_bot(
        actor_bots=actor_bots,
        ecs_world=ecs_world,
        level=level,
        uid=bot_uid,
        bot=bot,
    )


def install_world_actor_bots(
    *,
    actor_bots: dict[str, Bot],
    ecs_world: World,
    level: Level,
    world_bots: Any,
) -> None:
    if not isinstance(world_bots, dict):
        return
    for uid, actor_bot in world_bots.items():
        if isinstance(actor_bot, Bot):
            install_actor_bot(
                actor_bots=actor_bots,
                ecs_world=ecs_world,
                level=level,
                uid=uid,
                bot=actor_bot,
            )


__all__ = [
    "active_actor_bot",
    "attach_primary_bot",
    "ensure_bot_identity_fields",
    "install_actor_bot",
    "install_world_actor_bots",
    "set_active_actor",
    "switch_active_actor",
]
