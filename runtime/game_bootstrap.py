from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from core.bot import Bot
from core.controllers import PlayerController
from core.ecs import World
from runtime.actor_session import attach_primary_bot, install_world_actor_bots
from runtime.bootstrap import SystemsBundle, create_systems
from runtime.bot_loop import BotLoopContext
from runtime.metrics import BotLoopProfiler
from runtime.physics_steps import PhysicsStepContext
from ui.renderer import Renderer
from utils.input import InputHandler
from utils.tracepack import TraceRecorder
from core.level_capabilities import (
    level_name_tag,
    level_trace_detail,
    level_trace_enabled,
    level_trace_sample_period_s,
    level_scenario_tag,
)
from levels.common_world import get_mass

if TYPE_CHECKING:
    from core.physics import PhysicsEngine


@dataclass(frozen=True)
class CoreRuntimeBootstrap:
    sites: Any
    engine: PhysicsEngine
    ecs_world: World
    systems: Any


def bootstrap_core_runtime(
    *,
    level: Any,
    actors: list[Any],
    active_uid: str,
) -> CoreRuntimeBootstrap:
    sites = level.world.sites
    engine = level.engine
    if engine is None:
        raise RuntimeError(
            "Level setup did not initialize the physics engine (level.engine is None)"
        )
    engine.set_primary_actor(active_uid)

    ecs_world = World()
    for actor in actors:
        ecs_world.add_entity(actor)
    for site_entity in getattr(level.world, "site_entities", []):
        ecs_world.add_entity(site_entity)
    for extra_entity in getattr(level.world, "extra_entities", []):
        ecs_world.add_entity(extra_entity)

    systems = create_systems(
        ecs_world,
        terrain=level.world.terrain,
        sites=sites,
        engine=engine,
    )
    return CoreRuntimeBootstrap(
        sites=sites,
        engine=engine,
        ecs_world=ecs_world,
        systems=systems,
    )


@dataclass(frozen=True)
class InteractiveRuntimeBootstrap:
    input_handler: Any
    renderer: Any
    player_controller: Any


def bootstrap_interactive_runtime(
    *,
    headless: bool,
    level: Any,
    width: int,
    height: int,
    bot: Bot | None,
) -> InteractiveRuntimeBootstrap:
    if not headless and InputHandler is not None and Renderer is not None:
        return InteractiveRuntimeBootstrap(
            input_handler=InputHandler(),
            renderer=Renderer(level, width, height, bot=bot),
            player_controller=PlayerController(),
        )
    return InteractiveRuntimeBootstrap(
        input_handler=None,
        renderer=None,
        player_controller=None,
    )


@dataclass(frozen=True)
class BotRuntimeBootstrap:
    actor_bots: dict[str, Bot]
    bot_loop_context: BotLoopContext
    physics_step_context: PhysicsStepContext


def bootstrap_bot_runtime(
    *,
    level: Any,
    actors: list[Any],
    ecs_world: World,
    world_bots: Any,
    primary_bot: Bot | None,
    active_uid: str,
    systems: SystemsBundle,
    profiler: BotLoopProfiler,
    terrain: Any,
    engine: PhysicsEngine,
) -> BotRuntimeBootstrap:
    actor_bots: dict[str, Bot] = {}
    install_world_actor_bots(
        actor_bots=actor_bots,
        ecs_world=ecs_world,
        level=level,
        world_bots=world_bots,
    )
    if primary_bot is not None:
        attach_primary_bot(
            actors=actors,
            actor_bots=actor_bots,
            ecs_world=ecs_world,
            level=level,
            active_uid=active_uid,
            bot=primary_bot,
        )
    return BotRuntimeBootstrap(
        actor_bots=actor_bots,
        bot_loop_context=BotLoopContext(
            ecs_world=ecs_world,
            actor_bots=actor_bots,
            sensor_update_system=systems.sensor_update,
            profiler=profiler,
            terrain=terrain,
            trace_recorder=None,
        ),
        physics_step_context=PhysicsStepContext(
            actors=actors,
            engine=engine,
            scripted_control_system=systems.scripted_control,
            landing_site_motion_system=systems.landing_site_motion,
            landing_site_projection_system=systems.landing_site_projection,
            propulsion_system=systems.propulsion,
            force_application_system=systems.force_application,
            physics_sync_system=systems.physics_sync,
            contact_system=systems.contact,
            mass_resolver=get_mass,
        ),
    )


@dataclass(frozen=True)
class TraceRuntimeBootstrap:
    trace_recorder: TraceRecorder
    events_seen: set[tuple[str, str]]


def bootstrap_trace_runtime(
    *,
    terrain: Any,
    ecs_world: World,
    actor_bots: dict[str, Bot],
    active_uid_getter: Any,
    headless: bool,
    level: Any,
    seed: int,
) -> TraceRuntimeBootstrap:
    trace_recorder = TraceRecorder(
        terrain,
        ecs_world,
        actor_bots,
        active_uid_getter,
        enabled=(headless and level_trace_enabled(level)),
        sample_period_s=level_trace_sample_period_s(level),
        detail=level_trace_detail(level),
    )
    runtime_context = level.ensure_runtime_context()
    explicit_tag = (
        runtime_context.trace_selector_tag
        if runtime_context.trace_selector_tag
        else None
    )
    if isinstance(explicit_tag, str) and explicit_tag.strip():
        trace_recorder.set_selector_tag(explicit_tag)
    else:
        level_name = level_name_tag(level)
        scenario_name = level_scenario_tag(level)
        tag_parts = [level_name] if level_name else ["level"]
        if scenario_name and scenario_name != level_name:
            tag_parts.append(scenario_name)
        tag_parts.append(str(seed))
        trace_recorder.set_selector_tag("_".join(tag_parts))
    return TraceRuntimeBootstrap(
        trace_recorder=trace_recorder,
        events_seen=set(),
    )
