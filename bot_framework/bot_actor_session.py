"""Bot/actor session management."""

from __future__ import annotations

from typing import Any, Callable

from core.bot import Bot
from core.ecs import World
from core.ecs import Entity
from core.level import Level


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
    build_vehicle_info: Callable[..., Any] | None = None,
    build_bot_environment: Callable[..., Any] | None = None,
) -> None:
    actor_bots[uid] = bot
    ensure_bot_identity_fields(bot)
    actor = ecs_world.get_entity_by_id(uid)
    if actor is None:
        return
    if hasattr(bot, "set_vehicle_info") and build_vehicle_info is not None:
        bot.set_vehicle_info(build_vehicle_info(actor))
    if hasattr(bot, "set_environment") and build_bot_environment is not None:
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
    find_first_actor_for_role: Callable[[list[Entity], str], str | None] | None = None,
    build_vehicle_info: Callable[..., Any] | None = None,
    build_bot_environment: Callable[..., Any] | None = None,
) -> None:
    bot_uid: str | None = None
    if find_first_actor_for_role is not None:
        bot_uid = find_first_actor_for_role(actors, "bot")
    if bot_uid is None:
        bot_uid = next((a.uid for a in actors if a.uid != active_uid), active_uid)
    install_actor_bot(
        actor_bots=actor_bots,
        ecs_world=ecs_world,
        level=level,
        uid=bot_uid,
        bot=bot,
        build_vehicle_info=build_vehicle_info,
        build_bot_environment=build_bot_environment,
    )


def install_world_actor_bots(
    *,
    actor_bots: dict[str, Bot],
    ecs_world: World,
    level: Level,
    world_bots: Any,
    build_vehicle_info: Callable[..., Any] | None = None,
    build_bot_environment: Callable[..., Any] | None = None,
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
                build_vehicle_info=build_vehicle_info,
                build_bot_environment=build_bot_environment,
            )


__all__ = [
    "active_actor_bot",
    "attach_primary_bot",
    "ensure_bot_identity_fields",
    "install_actor_bot",
    "install_world_actor_bots",
]
