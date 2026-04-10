from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable

from game.runtime.loop_timing import LoopTimers

if TYPE_CHECKING:
    from game.core.ecs import Entity, System
    from game.core.physics import PhysicsEngine


def sync_actor_masses_to_engine(
    *,
    actors: list[Entity],
    engine: PhysicsEngine,
    mass_resolver: Callable[[Entity], float],
    last_synced_mass_by_uid: dict[str, float],
) -> None:
    for actor in actors:
        current_mass = mass_resolver(actor)
        last_mass = last_synced_mass_by_uid.get(actor.uid)
        if last_mass is not None and abs(current_mass - last_mass) < 1e-9:
            continue
        engine.set_mass(current_mass, uid=actor.uid)
        last_synced_mass_by_uid[actor.uid] = current_mass


@dataclass
class PhysicsStepContext:
    actors: list[Entity]
    engine: PhysicsEngine
    scripted_control_system: System
    landing_site_motion_system: System
    landing_site_projection_system: System
    propulsion_system: System
    force_application_system: System
    physics_sync_system: System
    contact_system: System
    mass_resolver: Callable[[Entity], float]
    last_synced_mass_by_uid: dict[str, float] = field(default_factory=dict)


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
        sync_actor_masses_to_engine(
            actors=context.actors,
            engine=context.engine,
            mass_resolver=context.mass_resolver,
            last_synced_mass_by_uid=context.last_synced_mass_by_uid,
        )
        context.engine.step(physics_dt)
        context.physics_sync_system.update(physics_dt)
        context.contact_system.update(physics_dt)
