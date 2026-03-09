from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable

from core.components import FuelTank
from runtime.loop_timing import LoopTimers

if TYPE_CHECKING:
    from core.ecs import Entity, System
    from core.engine_adapter import EngineAdapter


def sync_actor_masses_to_engine(
    *,
    actors: list[Entity],
    engine_adapter: EngineAdapter,
    mass_resolver: Callable[[Entity], float],
) -> None:
    for actor in actors:
        tank: FuelTank | None = getattr(actor, "get_component", lambda _: None)(FuelTank)
        if tank is not None and not tank._mass_dirty:
            continue
        engine_adapter.set_actor_mass(actor.uid, mass_resolver(actor))
        if tank is not None:
            tank._mass_dirty = False


@dataclass
class PhysicsStepContext:
    actors: list[Entity]
    engine_adapter: EngineAdapter
    scripted_control_system: System
    landing_site_motion_system: System
    landing_site_projection_system: System
    propulsion_system: System
    force_application_system: System
    physics_sync_system: System
    contact_system: System
    mass_resolver: Callable[[Entity], float]


def update_physics_steps(
    timers: LoopTimers,
    *,
    context: PhysicsStepContext,
) -> None:
    physics_dt = timers.physics_dt
    while timers.should_step_physics():
        timers.consume_physics()
        context.scripted_control_system.update(physics_dt)
        context.landing_site_motion_system.update(physics_dt)
        context.landing_site_projection_system.update(physics_dt)
        context.propulsion_system.update(physics_dt)
        context.force_application_system.update(physics_dt)
        if getattr(context.engine_adapter, "enabled", False):
            sync_actor_masses_to_engine(
                actors=context.actors,
                engine_adapter=context.engine_adapter,
                mass_resolver=context.mass_resolver,
            )
            context.engine_adapter.step(physics_dt)
            context.physics_sync_system.update(physics_dt)
            context.contact_system.update(physics_dt)
