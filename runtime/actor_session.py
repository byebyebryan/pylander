from __future__ import annotations

from dataclasses import dataclass
from math import fabs
from typing import Any, cast

from core.bot import Bot, BotEnvironment
from core.components import (
    ActorControlRole,
    PlayerControlled,
    PlayerSelectable,
    Transform,
)
from core.config import GRAVITY
from core.ecs import Entity, World, require_component
from core.engine_adapter import EngineAdapter
from core.level import Level
from core.level_capabilities import level_name_tag, level_scenario_tag
from core.maths import Vector2
from core.terrain import (
    anchored_profile,
    estimate_terrain_slope,
    sample_terrain_height,
    terrain_resolution,
)
from runtime.sensors import build_vehicle_info, resolve_eval_target


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


def build_bot_environment(*, level: Level, actor: Entity) -> BotEnvironment | None:
    terrain = getattr(level, "terrain", None)
    if terrain is None:
        return None
    trans = require_component(actor, Transform)
    start_pos = Vector2(getattr(actor, "start_pos", trans.pos))
    target = resolve_eval_target(level, level.sites, start_pos)
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
        level_name=level_name_tag(level),
        scenario_name=level_scenario_tag(level) or None,
        scenario_params=env_params,
    )


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


def find_initial_player_actor_uid(actors: list[Entity]) -> str:
    for actor in actors:
        selected = actor.get_component(PlayerControlled)
        if selected is not None and selected.active:
            return actor.uid

    selectable: list[tuple[int, str]] = []
    for actor in actors:
        marker = actor.get_component(PlayerSelectable)
        if marker is not None:
            selectable.append((marker.order, actor.uid))
    if selectable:
        selectable.sort(key=lambda item: item[0])
        return selectable[0][1]

    return actors[0].uid


def set_active_actor(
    *,
    actors: list[Entity],
    ecs_world: World,
    level: Level,
    engine_adapter: EngineAdapter,
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
        cast(Any, level.world).lander = actor
    engine_adapter.set_primary_actor(uid)
    return actor


def switch_active_actor(
    *,
    actors: list[Entity],
    ecs_world: World,
    level: Level,
    engine_adapter: EngineAdapter,
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
        engine_adapter=engine_adapter,
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
