from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from runtime.loop_timing import LoopTimers


def sync_actor_masses_to_engine(
    *,
    actors: list[Any],
    engine_adapter: Any,
    mass_resolver: Callable[[Any], float],
) -> None:
    for actor in actors:
        engine_adapter.set_actor_mass(actor.uid, mass_resolver(actor))


@dataclass
class PhysicsStepContext:
    actors: list[Any]
    engine_adapter: Any
    scripted_control_system: Any
    landing_site_motion_system: Any
    landing_site_projection_system: Any
    propulsion_system: Any
    force_application_system: Any
    physics_sync_system: Any
    contact_system: Any
    mass_resolver: Callable[[Any], float]


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
